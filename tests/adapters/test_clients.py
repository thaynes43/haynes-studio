"""Client behaviour through fakes: requests, frozen answers, refusals and errors."""

from __future__ import annotations

import base64
import json
import threading

import pytest

from haynes_studio.adapters import errors, pinned
from haynes_studio.adapters.comfyui import ImageClient, ImageEdit, TextToImage, upload_name_for
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
from haynes_studio.adapters.runner import Command, Completed, ExecTarget
from haynes_studio.adapters.whisper import TranscriptRequest, WhisperClient

SECRET_URL = "https://agent:hunter2-not-a-real-password@kube.example:6443/api"
SECRET_TOKEN = "token=abcdef0123456789abcdef"


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


def test_edit_request_needs_png_and_a_studio_upload_name():
    png = synthetic_png()
    with pytest.raises(RequestInvalid):
        ImageEdit("j", "n", "p", 1, b"not a png", upload_name_for(png))
    with pytest.raises(RequestInvalid):
        ImageEdit("j", "n", "p", 1, png, "../evil.png")
    assert upload_name_for(png) == upload_name_for(png)


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


def test_safe_detail_redacts_before_cutting():
    long = ("x" * 400 + " password=" + "p" * 40).encode()
    detail = errors.safe_detail(long, limit=30)
    assert "p" * 10 not in detail and detail.endswith("<redacted>")
    assert errors.safe_detail(b"\x1b[31mred\x00") == "?[31mred?"
    assert errors.safe_detail(None) == ""


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
    stderr = b"PROMPT_ID 0b5d5a1e-1111-4222-8333-944445555666\nSystemExit: Timed out waiting\n"
    with pytest.raises(ImageError) as caught:
        ImageClient(FailingRunner(1, stderr)).render(t2i())
    assert caught.value.prompt_id == "0b5d5a1e-1111-4222-8333-944445555666"
    assert "do not resubmit" in str(caught.value)


def test_comfyui_timeout_keeps_the_prompt_id_from_partial_stderr():
    timeout = AdapterError(errors.TIMEOUT, "comfyui.render", "no answer within 3300 s",
                           detail="uploaded {}\nPROMPT_ID abc-123")
    with pytest.raises(ImageError) as caught:
        ImageClient(ScriptedRunner(timeout)).render(t2i())
    assert (caught.value.code, caught.value.prompt_id) == (errors.TIMEOUT, "abc-123")


def test_comfyui_busy_queue_message_is_kept():
    stderr = b"SystemExit: ComfyUI stayed busy for 30 min; not submitting\n"
    with pytest.raises(ImageError) as caught:
        ImageClient(FailingRunner(1, stderr)).render(t2i())
    assert caught.value.prompt_id is None and "stayed busy" in caught.value.detail


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
    request = ImageEdit("the-winter-menu-r9", "a-edit", "make her stare", 301, source,
                        upload_name_for(source))
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
