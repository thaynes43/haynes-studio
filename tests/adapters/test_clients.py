"""Client behaviour through fakes: requests, frozen answers, refusals and errors."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import threading
import time

import pytest

from haynes_studio.adapters import errors, pinned, runner
from haynes_studio.adapters.comfyui import (
    ImageClient,
    ImageEdit,
    InFlight,
    TextToImage,
    upload_name_for,
)
from haynes_studio.adapters.errors import AdapterError, ImageError, PinMismatch, RequestInvalid
from haynes_studio.adapters.fakes import (
    FailingRunner,
    FakeComfyUI,
    FakeKokoro,
    FakeRunner,
    FakeWhisper,
    UnexpectedCommand,
    synthetic_png,
    synthetic_wav,
)
from haynes_studio.adapters.kokoro import KokoroClient, SpeechRequest
from haynes_studio.adapters.runner import Command, Completed, ExecTarget, SubprocessRunner
from haynes_studio.adapters.whisper import TranscriptRequest, WhisperClient

SECRET_URL = "https://agent:hunter2-not-a-real-password@kube.example:6443/api"
SECRET_TOKEN = "token=abcdef0123456789abcdef"
PROMPT = "0b5d5a1e-1111-4222-8333-944445555666"


def t2i(**changes):
    fields = dict(job="the-winter-menu-r9", name="a-test", prompt="a doll", seed=1)
    fields.update(changes)
    return TextToImage(**fields)


class ScriptedRunner:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run(self, command):
        self.calls.append(command)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


# Three lines with a fake --------------------------------------------------------------

def test_three_line_use_with_fakes():
    kokoro = FakeKokoro()
    runner = FakeRunner(kokoro, FakeWhisper(kokoro.spoken))
    take = KokoroClient(runner).synthesize(SpeechRequest("bf_emma", "Aye."))
    assert WhisperClient(runner).transcribe(TranscriptRequest(take.wav)).text == "Aye."
    assert [c.label for c in runner.calls] == ["kokoro.synthesize", "whisper.transcribe"]


# Requests ----------------------------------------------------------------------------

@pytest.mark.parametrize("voice,text", [("", "x"), ("Emma", "x"), ("bf_emma", "  "),
                                        ("bf_emma", "x" * 1001), ("bf_emma", 3)])
def test_speech_request_validation(voice, text):
    with pytest.raises(RequestInvalid) as caught:
        SpeechRequest(voice, text)
    assert caught.value.code == errors.REQUEST_INVALID


@pytest.mark.parametrize("changes", [dict(job="../x"), dict(name="A"), dict(prompt=""),
                                     dict(seed=-1), dict(seed=True), dict(seed=2 ** 64),
                                     dict(width=1100), dict(height=32)])
def test_image_request_validation(changes):
    with pytest.raises(RequestInvalid):
        t2i(**changes)


def test_edit_request_needs_png_and_names_the_upload_by_its_bytes():
    png = synthetic_png()
    with pytest.raises(RequestInvalid):
        ImageEdit("j", "n", "p", 1, b"not a png")
    edit = ImageEdit("j", "n", "p", 1, png)
    assert edit.upload_name == upload_name_for(png) != upload_name_for(synthetic_png(seed=1))
    with pytest.raises(TypeError):
        ImageEdit("j", "n", "p", 1, png, "studio-000000000000.png")


def test_edit_upload_name_is_the_full_sha256():
    """Finding 2: the name carries all 64 hex digits, not a 12-digit prefix."""
    png = synthetic_png(seed=4)
    name = ImageEdit("j", "n", "p", 1, png).upload_name
    assert name == f"studio-{hashlib.sha256(png).hexdigest()}.png"
    assert re.fullmatch(r"studio-[0-9a-f]{64}\.png", name)


def test_transcript_request_needs_a_wav():
    with pytest.raises(RequestInvalid):
        TranscriptRequest(b"RIFF....nope")
    with pytest.raises(RequestInvalid):
        TranscriptRequest(b"")


def test_command_validation():
    with pytest.raises(ValueError):
        Command("x", (), b"", 1)
    with pytest.raises(ValueError):
        Command("x", ("a",), "text", 1)
    with pytest.raises(ValueError):
        Command("x", ("a",), b"", 0)
    assert ExecTarget("ai", "deploy/kokoro", "app", "python").describe() == \
        "kubectl exec -n ai deploy/kokoro -c app"


def test_command_repr_hides_payload_and_code():
    command = KokoroClient(FakeRunner()).command(SpeechRequest("bf_emma", "a secret-ish line"))
    assert "secret-ish" not in repr(command) and "wyoming" not in repr(command)


# Errors ------------------------------------------------------------------------------

def test_failure_keeps_a_redacted_stderr_tail_and_no_payload():
    stderr = f"error: dial {SECRET_URL}\n{SECRET_TOKEN}\nRuntimeError: TTS error\n".encode()
    client = KokoroClient(FailingRunner(1, stderr))
    with pytest.raises(AdapterError) as caught:
        client.synthesize(SpeechRequest("bf_emma", "Bibs on, ladies."))
    text = str(caught.value)
    assert caught.value.code == errors.COMMAND_FAILED and caught.value.returncode == 1
    assert "hunter2" not in text and "abcdef0123456789" not in text
    assert "<redacted>" in text and "TTS error" in text
    assert "Bibs on" not in text and "wyoming" not in text and "kubectl exec -n ai deploy/kokoro" in text


@pytest.mark.parametrize("raw,secret", [
    ("GH_TOKEN=ghs_aaaabbbbccccdddd1234", "ghs_aaaa"),
    ("DB_PASSWORD=correct-horse-battery", "correct-horse"),
    ("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIK7MDENG", "wJalrXUt"),
    ("refresh_token=rt-0123456789abcdef", "0123456789ab"),
    ("client_secret: cs-0123456789abcdef", "0123456789ab"),
    ("uploaded {'token': 'tk-0123456789abcdef'}", "0123456789ab"),
    ('{"password": "pw-0123456789abcdef"}', "0123456789ab"),
    ("Authorization: Bearer bt-0123456789abcdef", "0123456789ab"),
    ("Authorization: Basic dXNlcjpwYXNzd29yZA==", "dXNlcjpw"),
    ("dial https://u:p/ss0123456789@host:6443", "ss0123456789"),
    ("dial https://u:p@ss0123456789@host:6443", "ss0123456789"),
    ("cookie=session-0123456789abcdef", "0123456789ab"),
])
def test_safe_detail_redacts_credential_forms(raw, secret):
    detail = errors.safe_detail(raw.encode())
    assert secret not in detail and "<redacted>" in detail


def test_safe_detail_redacts_before_cutting():
    long = ("x" * 400 + " password=" + "p" * 40).encode()
    detail = errors.safe_detail(long, limit=30)
    assert "p" * 10 not in detail and detail.endswith("<redacted>")
    assert errors.safe_detail(b"\x1b[31mred\x00") == "?[31mred?"
    assert errors.safe_detail(None) == ""
    spaced = 'x' * 400 + ' password: "correct horse battery staple"'
    assert errors.safe_detail(spaced, limit=40).endswith('password: "<redacted>"')


# Finding 6: each form the review found left in place, as the reviewer wrote it.
@pytest.mark.parametrize("raw,secrets,kept", [
    ('login failed: password: "correct horse battery staple"\nnext',
     ("correct", "horse", "battery", "staple"), ('password: "<redacted>"', "next")),
    ("{'api_key': 'ak 0123 4567'}", ("0123", "4567"), ("{'api_key': '<redacted>'}",)),
    ("token=super secret leftover\nRuntimeError: boom",
     ("super", "leftover"), ("token=<redacted>", "RuntimeError: boom")),
    ("aws_access_key_id=AKIAIOSFODNN7EXAMPLE region us-east-1",
     ("AKIAIOSFODNN7EXAMPLE",), ("region us-east-1",)),
    ("key xASIAY34FZKBOKMUTVV7Ax", ("Y34FZKBOKMUTVV7A",), ("key x",)),
    ("before\n-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0123\nabcdEFGH\n"
     "-----END RSA PRIVATE KEY-----\nafter",
     ("MIIEowIBAAKCAQEA0123", "abcdEFGH", "PRIVATE KEY"), ("before", "after")),
    ("before\n-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEA\ncut off here",
     ("b3BlbnNzaC1rZXktdjEA", "cut off"), ("before",)),
    ("dial https://user:correct horse@kube.example/api: refused",
     ("correct", "horse"), ("https://<redacted>@kube.example/api: refused",)),
])
def test_safe_detail_redacts_the_reviewed_forms(raw, secrets, kept):
    detail = errors.safe_detail(raw.encode())
    for secret in secrets:
        assert secret not in detail, secret
    for text in kept:
        assert text in detail, text


@pytest.mark.parametrize("plain", [
    "Get https://kube.example:8080/path: dial tcp 10.0.0.1:8080: connect: refused",
    "GET http://127.0.0.1:8188/history/abc?x=1 then mail ops@example.com",
    "uploaded {'name': 'studio-0a1b.png', 'subfolder': '', 'type': 'input'}",
    "PROMPT_ID 0b5d5a1e-1111-4222-8333-944445555666",
])
def test_safe_detail_leaves_plain_text_alone(plain):
    assert errors.safe_detail(plain) == plain


@pytest.mark.parametrize("unit", ["a://", "https://" + "x:" * 3, "token", "password=\"\\",
                                  "-----BEGIN", "AKIA", "Bearer ", "x", "a.b", "a:b c@",
                                  "'secret': '", "token_x-"])
def test_safe_detail_stays_linear_on_long_input(unit):
    """Every pattern is bounded or cannot backtrack. 64 KiB of a repeated fragment takes
    a few milliseconds here; the patterns before this fix took minutes on the "x" and
    "token" inputs (4 KiB of "token" alone took 39 s)."""
    raw = unit * (65536 // len(unit))
    start = time.perf_counter()
    errors.redact(raw)
    assert time.perf_counter() - start < 1


def test_timeout_from_the_runner_passes_through():
    timeout = AdapterError(errors.TIMEOUT, "whisper.transcribe", "no answer within 55 s")
    client = WhisperClient(ScriptedRunner(timeout))
    with pytest.raises(AdapterError) as caught:
        client.transcribe(TranscriptRequest(synthetic_wav(2400)))
    assert caught.value.code == errors.TIMEOUT


@pytest.mark.parametrize("stdout", [b"", b"RIFF", b"not audio at all"])
def test_kokoro_refuses_an_answer_that_is_not_a_wav(stdout):
    with pytest.raises(AdapterError) as caught:
        KokoroClient(ScriptedRunner(Completed(0, stdout))).synthesize(SpeechRequest("af_heart", "x"))
    assert caught.value.code == errors.RESPONSE_INVALID


@pytest.mark.parametrize("stdout", [b"", b"[]", b'{"transcript": 3}', b'{"transcript": "a", "x": 1}',
                                    b'{"transcript": "a", "transcript": "b"}', b"\xff"])
def test_whisper_refuses_a_malformed_answer(stdout):
    client = WhisperClient(ScriptedRunner(Completed(0, stdout)))
    with pytest.raises(AdapterError) as caught:
        client.transcribe(TranscriptRequest(synthetic_wav(2400)))
    assert caught.value.code == errors.RESPONSE_INVALID


def test_fake_whisper_without_a_transcript_fails_like_the_snippet():
    with pytest.raises(AdapterError) as caught:
        WhisperClient(FakeRunner(FakeWhisper())).transcribe(TranscriptRequest(synthetic_wav(2400)))
    assert caught.value.code == errors.COMMAND_FAILED and "STT error" in caught.value.detail


# ComfyUI -----------------------------------------------------------------------------

def test_comfyui_failure_after_submission_carries_the_prompt_id():
    stderr = f"PROMPT_ID {PROMPT}\nSystemExit: Timed out waiting\n".encode()
    with pytest.raises(ImageError) as caught:
        ImageClient(FailingRunner(1, stderr)).render(t2i())
    assert caught.value.prompt_id == PROMPT
    assert "do not resubmit" in str(caught.value)
    assert ImageClient.in_flight() == InFlight(PROMPT, errors.COMMAND_FAILED)


def test_comfyui_timeout_keeps_the_prompt_id_from_partial_stderr():
    timeout = AdapterError(errors.TIMEOUT, "comfyui.render", "no answer within 3300 s",
                           detail="uploaded {}\nPROMPT_ID abc-123")
    with pytest.raises(ImageError) as caught:
        ImageClient(ScriptedRunner(timeout)).render(t2i())
    assert (caught.value.code, caught.value.prompt_id) == (errors.TIMEOUT, "abc-123")


def _timeout_run(stderr):
    """A stand-in for ``subprocess.run`` that times out: nothing is started."""
    def run(argv, **kwargs):
        assert argv[:2] == ["kubectl", "exec"]
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output=b"", stderr=stderr)
    return run


def test_subprocess_runner_timeout_keeps_the_whole_redacted_stderr(monkeypatch):
    stderr = (f"uploaded {{}}\nPROMPT_ID {PROMPT}\n" + "polling history\n" * 40
              + f"{SECRET_TOKEN}\n").encode()
    monkeypatch.setattr(runner.subprocess, "run", _timeout_run(stderr))
    with pytest.raises(AdapterError) as caught:
        SubprocessRunner().run(ImageClient(FakeRunner()).command(t2i(prompt="a secret-ish doll")))
    error = caught.value
    assert error.code == errors.TIMEOUT and error.__cause__ is None and error.__context__ is None
    assert f"PROMPT_ID {PROMPT}" in error.redacted_stderr
    assert len(error.detail) <= errors.DETAIL_LIMIT and "PROMPT_ID" not in error.detail
    assert error.redacted_stderr.endswith("token=<redacted>")
    for text in (error.redacted_stderr, error.detail, str(error), repr(error)):
        assert "abcdef0123456789" not in text and "secret-ish" not in text
    assert "PROMPT_ID" not in str(error) and "urlopen" not in str(error)


def test_comfyui_timeout_finds_the_prompt_id_behind_long_stderr(monkeypatch):
    """Finding 1A: over 300 characters of stderr after the PROMPT_ID line."""
    stderr = (f"uploaded {{}}\nPROMPT_ID {PROMPT}\n" + "x" * 1000 + "\n").encode()
    monkeypatch.setattr(runner.subprocess, "run", _timeout_run(stderr))
    with pytest.raises(ImageError) as caught:
        ImageClient(SubprocessRunner()).render(t2i(prompt="a secret-ish doll"))
    error = caught.value
    assert (error.code, error.prompt_id) == (errors.TIMEOUT, PROMPT)
    assert "PROMPT_ID" not in error.detail and "do not resubmit" in str(error)
    assert "secret-ish" not in str(error) and "urlopen" not in str(error)
    assert ImageClient.in_flight() == InFlight(PROMPT, errors.TIMEOUT)


def test_comfyui_busy_queue_message_is_kept():
    stderr = b"SystemExit: ComfyUI stayed busy for 30 min; not submitting\n"
    with pytest.raises(ImageError) as caught:
        ImageClient(FailingRunner(1, stderr)).render(t2i())
    assert caught.value.prompt_id is None and "stayed busy" in caught.value.detail
    assert ImageClient.in_flight() is None  # the snippet gave up before submitting


# Finding 1B: a prompt that may be in flight blocks a second submission ----------------

def _leave_a_prompt_in_flight(prompt_id=PROMPT):
    stderr = f"PROMPT_ID {prompt_id}\n" if prompt_id else ""
    timeout = AdapterError(errors.TIMEOUT, "comfyui.render", "no answer within 3300 s",
                           redacted_stderr=stderr + "x" * 1000)
    with pytest.raises(ImageError):
        ImageClient(ScriptedRunner(timeout)).render(t2i())
    assert ImageClient.in_flight() == InFlight(prompt_id, errors.TIMEOUT)


def test_comfyui_after_a_timeout_render_reads_the_queue_before_submitting():
    _leave_a_prompt_in_flight()
    busy = FakeComfyUI(running=1)
    queue_only = FakeRunner(busy)
    with pytest.raises(ImageError) as caught:
        ImageClient(queue_only).render(t2i(name="b-test"))  # another client, same process
    assert (caught.value.code, caught.value.prompt_id) == (errors.BUSY, PROMPT)
    assert "do not resubmit" in str(caught.value) and "1 running" in str(caught.value)
    assert [c.label for c in queue_only.calls] == ["comfyui.queue"] and busy.payloads == []
    assert ImageClient.in_flight().prompt_id == PROMPT

    idle = FakeComfyUI()
    runner_ = FakeRunner(idle)
    assert ImageClient(runner_).render(t2i(name="c-test")).png
    assert [c.label for c in runner_.calls] == ["comfyui.queue", "comfyui.render"]
    assert ImageClient.in_flight() is None


def test_comfyui_unknown_prompt_after_a_failure_holds_until_the_queue_empties():
    with pytest.raises(ImageError):
        ImageClient(FailingRunner(1, b"error: connection reset by peer\n")).render(t2i())
    assert ImageClient.in_flight() == InFlight(None, errors.COMMAND_FAILED)
    busy = FakeComfyUI(pending=2)
    with pytest.raises(ImageError) as caught:
        ImageClient(FakeRunner(busy)).render(t2i(name="b-test"))
    assert caught.value.code == errors.BUSY and caught.value.prompt_id is None
    assert "do not resubmit" in str(caught.value) and busy.payloads == []


def test_comfyui_clear_in_flight_lets_the_next_render_submit():
    _leave_a_prompt_in_flight()
    assert ImageClient.clear_in_flight() == InFlight(PROMPT, errors.TIMEOUT)
    assert ImageClient.in_flight() is None
    runner_ = FakeRunner(FakeComfyUI(running=1))
    assert ImageClient(runner_).render(t2i(name="b-test")).png
    assert [c.label for c in runner_.calls] == ["comfyui.render"]


def test_comfyui_queue_failure_during_the_check_keeps_the_prompt_in_flight():
    _leave_a_prompt_in_flight()
    broken = ScriptedRunner(Completed(1, b"", b"error: connection refused\n"))
    with pytest.raises(ImageError) as caught:
        ImageClient(broken).render(t2i(name="b-test"))
    assert caught.value.label == "comfyui.queue"
    assert [c.label for c in broken.calls] == ["comfyui.queue"]
    assert ImageClient.in_flight().prompt_id == PROMPT


@pytest.mark.parametrize("outcome", [
    AdapterError(errors.COMMAND_FAILED, "comfyui.render", "could not start kubectl: not found"),
    Completed(0, b"not json", b"PROMPT_ID p\n"),
])
def test_comfyui_nothing_in_flight_when_the_prompt_never_started_or_finished(outcome):
    with pytest.raises(ImageError):
        ImageClient(ScriptedRunner(outcome)).render(t2i())
    assert ImageClient.in_flight() is None


def test_comfyui_unexpected_runner_error_leaves_an_unknown_prompt_in_flight():
    with pytest.raises(RuntimeError):
        ImageClient(ScriptedRunner(RuntimeError("runner broke"))).render(t2i())
    assert ImageClient.in_flight() == InFlight(None, "unknown")


def test_comfyui_in_flight_markers_are_in_the_pinned_snippet():
    text = pinned.load("comfyui_prompt.py").text
    assert "sys.stderr.write('PROMPT_ID %s\\n' % pid); sys.stderr.flush()" in text
    assert "ComfyUI stayed busy for 30 min; not submitting" in text


@pytest.mark.parametrize("body", [
    {"prompt_id": "p", "images": []},
    {"prompt_id": "p", "waited_s": 0, "render_s": 1, "images": [{"filename": "f", "subfolder": "s",
                                                                  "b64": "!!"}]},
    {"prompt_id": "p", "waited_s": 0, "render_s": 1, "images": [{"filename": "f", "subfolder": "s",
                                                                  "b64": base64.b64encode(b"GIF8").decode()}]},
    {"prompt_id": "p", "images": [{"filename": "f", "subfolder": "s",
                                   "b64": base64.b64encode(synthetic_png()).decode()}]},
])
def test_comfyui_refuses_a_malformed_answer(body):
    runner = ScriptedRunner(Completed(0, json.dumps(body).encode(), b"PROMPT_ID p\n"))
    with pytest.raises(ImageError) as caught:
        ImageClient(runner).render(t2i())
    assert caught.value.code == errors.RESPONSE_INVALID and caught.value.prompt_id == "p"


def test_comfyui_one_render_in_flight_per_process():
    entered, release = threading.Event(), threading.Event()
    inner = FakeRunner(FakeComfyUI())

    class Slow:
        def run(self, command):
            entered.set()
            assert release.wait(5)
            return inner.run(command)

    results = []
    worker = threading.Thread(target=lambda: results.append(ImageClient(Slow()).render(t2i())))
    worker.start()
    assert entered.wait(5)
    try:
        with pytest.raises(ImageError) as caught:
            ImageClient(FakeRunner(FakeComfyUI())).render(t2i(name="b-test"))
        assert caught.value.code == errors.BUSY
    finally:
        release.set()
        worker.join(5)
    assert len(results) == 1
    assert ImageClient(FakeRunner(FakeComfyUI())).render(t2i(name="c-test")).png


def test_comfyui_edit_uploads_and_renders():
    fake = FakeComfyUI()
    source = synthetic_png(seed=9)
    request = ImageEdit("the-winter-menu-r9", "a-edit", "make her stare", 301, source)
    result = ImageClient(FakeRunner(fake)).render(request)
    assert fake.payloads[0]["upload"]["name"] == request.upload_name
    assert result.comfy_subfolder == "studio/the-winter-menu-r9"


def test_comfyui_queue_reads_counts_and_submits_nothing():
    fake = FakeComfyUI(running=1, pending=2)
    state = ImageClient(FakeRunner(fake)).queue()
    assert (state.running, state.pending, state.idle) == (1, 2, False)
    assert fake.payloads == []
    with pytest.raises(ImageError):
        ImageClient(ScriptedRunner(Completed(0, b'{"running": -1, "pending": 0}'))).queue()


def test_comfyui_refuses_a_graph_whose_nodes_moved(tmp_path):
    item = pinned.load("qwen_image_2_1_t2i_API.json")
    client = ImageClient(FakeRunner())
    graph = json.loads(item.text)
    graph["8"]["class_type"] = "PreviewImage"
    client.t2i_graph = pinned.PinnedInput(item.name, json.dumps(graph).encode())
    with pytest.raises(PinMismatch):
        client.graph(t2i())


def test_fake_runner_refuses_unpinned_code():
    command = Command("x", ExecTarget("ai", "deploy/kokoro", "app", "python").argv("print(1)"))
    with pytest.raises(UnexpectedCommand):
        FakeRunner(FakeKokoro()).run(command)
    with pytest.raises(UnexpectedCommand):
        FakeRunner().run(Command("x", ("ls",)))
