"""The compatibility matrix: for each ported call, the package sends what the PoC sends.

The PoC source is read with ``ast`` (tests/adapters/poc_source.py), never imported.
Recorded Winter Menu inputs come from the committed manifests and evidence. Every
difference from the PoC is listed in docs/reference/legacy-adapters.md and checked
here where it can be.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import json

import pytest

from haynes_studio.adapters import comfyui, kokoro, pinned, wan_ledger, whisper
from haynes_studio.adapters.comfyui import ImageClient, ImageEdit, TextToImage, graph_sha256
from haynes_studio.adapters.fakes import (
    FakeComfyUI,
    FakeKokoro,
    FakeRunner,
    FakeWanLedger,
    FakeWhisper,
    synthetic_png,
)
from haynes_studio.adapters.kokoro import KokoroClient, SpeechRequest
from haynes_studio.adapters.wan_ledger import LedgerReader
from haynes_studio.adapters.whisper import TranscriptRequest, WhisperClient, heard_matches
from tests.adapters import poc_source as poc
from tests.support.policy import REPO_ROOT

TITLE = REPO_ROOT / "titles" / "the-winter-menu"
REVISIONS = {1: ("manifest.json", "evidence"), 2: ("manifest-r2.json", "evidence-r2"),
             3: ("manifest-r3.json", "evidence-r3"), 4: ("manifest-r4.json", "evidence-r4")}
WAV_HEADER = 44  # the wave module's PCM header, which the Kokoro snippet writes


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def revision(n):
    manifest, evidence = REVISIONS[n]
    return (load(TITLE / manifest), load(TITLE / evidence / "speech.json"),
            load(TITLE / evidence / "production.json"))


def nobody_runs(command):
    raise AssertionError("this test only builds commands")


class _NoRunner:
    run = staticmethod(nobody_runs)


# Snippets: byte for byte ---------------------------------------------------------------

@pytest.mark.parametrize("pin,script,constant", [
    ("kokoro_tts.py", "studio", "TTS"),
    ("whisper_asr.py", "studio", "ASR"),
    ("comfyui_prompt.py", "comfy", "REMOTE"),
    ("wan_ledger_read.py", "deliver", "READ"),
])
def test_ported_snippet_is_the_poc_text(pin, script, constant):
    assert pinned.load(pin).data == poc.constants(script)[constant].encode()


def test_t2i_graph_is_the_poc_graph_file():
    assert pinned.load("qwen_image_2_1_t2i_API.json").data == \
        (REPO_ROOT / "poc/graphs/qwen_image_2_1_t2i_API.json").read_bytes()


# Kokoro ------------------------------------------------------------------------------

def test_kokoro_command_line_and_timeout_match_poc():
    call, = poc.subprocess_runs(poc.function("studio", "synthesize"))
    command = KokoroClient(_NoRunner()).command(SpeechRequest("bf_emma", "Aye."))
    assert list(command.argv) == poc.argv("studio", call)
    assert command.timeout_s == ast.literal_eval(poc.keyword(call, "timeout"))
    assert ast.unparse(poc.keyword(call, "input")) == \
        "json.dumps({'voice': voice, 'text': text}).encode()"


@pytest.mark.parametrize("n", sorted(REVISIONS))
def test_kokoro_reproduces_every_recorded_take(n):
    """Each take's request is the PoC's, and a fake WAV of the recorded size parses to
    the recorded duration_s."""
    manifest, speech, ledger = revision(n)
    sizes = {a["path"].rsplit(f"{manifest['job']}/", 1)[1]: a["bytes"] for a in ledger["assets"]}
    frames = {}
    for take in speech["lines"]:
        assert take["voice"] == manifest["cast"][take["doll"]]["voice"]
        frames[(take["voice"], take["text"])] = (sizes[take["file"]] - WAV_HEADER) // 2
    fake = FakeKokoro(frames)
    client = KokoroClient(FakeRunner(fake))
    for take in speech["lines"]:
        request = SpeechRequest(take["voice"], take["text"])
        assert client.command(request).stdin == \
            json.dumps({'voice': take["voice"], 'text': take["text"]}).encode()
        result = client.synthesize(request)
        assert (result.bytes, result.legacy_duration_s) == (sizes[take["file"]], take["duration_s"])
        assert (result.channels, result.sample_width, result.rate) == (1, 2, 24000)


# Whisper -----------------------------------------------------------------------------

def test_whisper_command_line_and_timeout_match_poc():
    call, = poc.subprocess_runs(poc.function("studio", "transcribe"))
    wav = FakeKokoro().answer("kokoro_tts.py", KokoroClient(_NoRunner()).command(
        SpeechRequest("af_heart", "Needs salt.")), ()).stdout
    command = WhisperClient(_NoRunner()).command(TranscriptRequest(wav))
    assert list(command.argv) == poc.argv("studio", call)
    assert command.timeout_s == ast.literal_eval(poc.keyword(call, "timeout"))
    # The PoC passes the open WAV file as stdin; the package passes the same bytes.
    assert ast.unparse(poc.keyword(call, "stdin")) == "f"
    assert command.stdin == wav


@pytest.mark.parametrize("n", sorted(REVISIONS))
def test_whisper_parses_every_recorded_answer(n):
    """Frozen answers: each take's recorded ``heard`` text, as the snippet prints it,
    parses back to that text and gives the recorded ``heard_matches``."""
    manifest, speech, _ = revision(n)
    kokoro_fake = FakeKokoro()
    runner = FakeRunner(kokoro_fake, FakeWhisper(kokoro_fake.spoken))
    speaker, listener = KokoroClient(runner), WhisperClient(runner)
    for take in speech["lines"]:
        wav = speaker.synthesize(SpeechRequest(take["voice"], take["text"])).wav
        kokoro_fake.spoken[hashlib.sha256(wav).hexdigest()] = take["heard"]
        heard = listener.transcribe(TranscriptRequest(wav)).text
        assert heard == take["heard"]
        assert heard_matches(heard, take["text"]) is take["heard_matches"]


def test_whisper_normalization_is_the_poc_norm():
    norm = poc.function("speech", "norm")
    assert poc.statements(norm) == ["return re.sub('[^a-z0-9]', '', s.lower())"]
    assert whisper.normalized("Day 340. I've") == "day340ive"


@pytest.mark.parametrize("n", sorted(REVISIONS))
def test_whisper_parses_the_recorded_film_transcript(n):
    _, evidence = REVISIONS[n]
    recorded = load(TITLE / evidence / "dialogue-transcript.json")
    wav = FakeKokoro().answer("kokoro_tts.py", KokoroClient(_NoRunner()).command(
        SpeechRequest("af_heart", "film")), ()).stdout
    fake = FakeWhisper({hashlib.sha256(wav).hexdigest(): recorded["heard"]})
    assert WhisperClient(FakeRunner(fake)).transcribe(TranscriptRequest(wav)).text == recorded["heard"]


# ComfyUI -----------------------------------------------------------------------------

PROMPTS = load(TITLE / "prompts.json")
T2I_RENDERS = [r for r in PROMPTS["renders"] if r["mode"] == "t2i"]
EDIT_RENDERS = [r for r in PROMPTS["renders"] if r["mode"] == "edit"]


def t2i_request(render):
    prompt = (TITLE / render["prompt_file"]).read_text(encoding="utf-8").strip()  # as poc/comfy.py
    return TextToImage(job=PROMPTS["job"], name=render["name"], prompt=prompt, seed=render["seed"],
                       width=render["width"], height=render["height"])


@pytest.mark.parametrize("render", T2I_RENDERS, ids=lambda r: r["name"])
def test_comfyui_rebuilds_every_recorded_t2i_graph(render):
    """The filled graph hashes to the graph_sha256 prompts.json recorded for the render."""
    client = ImageClient(_NoRunner())
    graph = client.graph(t2i_request(render))
    assert graph_sha256(graph) == render["graph_sha256"]


def test_comfyui_command_line_payload_and_timeout_match_poc():
    run = poc.function("comfy", "run")
    call, = poc.subprocess_runs(run)
    client = ImageClient(_NoRunner())
    request = t2i_request(T2I_RENDERS[0])
    command = client.command(request)
    assert list(command.argv) == poc.argv("comfy", call)
    assert command.timeout_s == ast.literal_eval(poc.keyword(call, "timeout"))
    assert ast.unparse(poc.keyword(call, "input")) == "json.dumps(payload).encode()"
    body = poc.statements(run)
    assert "payload = {'graph': graph, 'client_id': f'studio-{job_dir.name}'}" in body
    assert "if upload:\n    payload['upload'] = upload" in body
    graph = client.graph(request)
    assert command.stdin == json.dumps({'graph': graph, 'client_id': 'studio-the-winter-menu-r1'}).encode()


def _graph_lines(source_lines):
    return [line for line in source_lines if line.startswith("g[")]


def _package_branch(kind):
    tree = ast.parse((REPO_ROOT / "src/haynes_studio/adapters/comfyui.py").read_text())
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "graph")
    branch = next(n for n in method.body if isinstance(n, ast.If) and kind in ast.unparse(n.test))
    return [line.replace("request.upload_name", "image_name").replace("request.", "")
            for line in poc.statements(branch)]


@pytest.mark.parametrize("func,kind", [("t2i_graph", "TextToImage"), ("edit_graph", "ImageEdit")])
def test_comfyui_fills_the_same_graph_fields_as_poc(func, kind):
    assert _graph_lines(_package_branch(kind)) == _graph_lines(poc.statements(poc.function("comfy", func)))


def test_comfyui_edit_payload_matches_poc():
    main = ast.unparse(poc.function("comfy", "main"))
    assert "upload={'name': upload_name, 'b64': base64.b64encode(src).decode()}" in main
    assert "upload_name = f'studio-{uuid.uuid4().hex[:12]}.png'" in main
    source = synthetic_png(seed=3)
    render = EDIT_RENDERS[0]
    request = ImageEdit(job=PROMPTS["job"], name=render["name"], prompt="p", seed=render["seed"],
                        source_png=source)
    assert request.upload_name == comfyui.upload_name_for(source)
    client = ImageClient(_NoRunner())
    graph = client.graph(request)
    assert graph["1"]["inputs"]["image"] == request.upload_name
    assert json.loads(client.command(request).stdin) == {
        'graph': graph, 'client_id': 'studio-the-winter-menu-r1',
        'upload': {'name': request.upload_name, 'b64': base64.b64encode(source).decode()}}


def test_comfyui_edit_template_is_the_recorded_haynes_ops_file():
    assert "7c7b2cf6" in PROMPTS["graph_note"]
    assert pinned.HAYNES_OPS_COMMIT.startswith("7c7b2cf6")
    assert all(r["graph"] == comfyui.EDIT_GRAPH for r in EDIT_RENDERS)
    assert {r["graph"] for r in T2I_RENDERS} == {comfyui.T2I_GRAPH}


@pytest.mark.parametrize("render", T2I_RENDERS[:2], ids=lambda r: r["name"])
def test_comfyui_parses_a_frozen_answer(render):
    fake = FakeComfyUI()
    result = ImageClient(FakeRunner(fake)).render(t2i_request(render))
    assert result.graph_sha256 == render["graph_sha256"]
    assert result.sha256 == hashlib.sha256(result.png).hexdigest()
    assert result.comfy_subfolder == f"studio/{PROMPTS['job']}"
    assert result.comfy_file == f"{render['name']}_00001_.png"


# Wan ledger --------------------------------------------------------------------------

LEDGERS = {n: load(TITLE / evidence / "production.json") for n, (_, evidence) in REVISIONS.items()}


def test_ledger_read_command_line_and_timeout_match_poc():
    call = next(c for c in poc.subprocess_runs(poc.function("deliver", "main"))
                if "READ" in ast.unparse(c.args[0]))
    ledger_id = LEDGERS[4]["id"]
    command = LedgerReader(_NoRunner()).get_command(ledger_id)
    assert list(command.argv) == poc.argv("deliver", call, {"ledger['id']": ledger_id})
    assert command.timeout_s == ast.literal_eval(poc.keyword(call, "timeout"))
    assert poc.keyword(call, "input") is None and command.stdin == b""


@pytest.mark.parametrize("n", sorted(LEDGERS))
def test_ledger_reader_parses_every_recorded_ledger(n):
    """Frozen answers: the committed production.json, as the API serves it."""
    ledger = LEDGERS[n]
    record = LedgerReader(FakeRunner(FakeWanLedger(LEDGERS.values()))).get(ledger["id"])
    assert (record.id, record.output, record.sha256, record.bytes) == \
        (ledger["id"], ledger["output"], ledger["sha256"], ledger["bytes"])
    assert [(a.path, a.sha256) for a in record.assets] == \
        [(a["path"], a["sha256"]) for a in ledger["assets"]]
    assert record.preset == "rigid-doll-dialogue-manifest"
    assert wan_ledger.record_from_document(ledger).id == ledger["id"]


def test_ledger_required_fields_are_the_poc_check():
    check = ast.unparse(poc.function("deliver", "check_ledger"))
    for name in wan_ledger.REQUIRED:
        assert repr(name) in check


def test_kokoro_and_whisper_limits_are_stated():
    assert (kokoro.TIMEOUT_S, whisper.TIMEOUT_S, comfyui.TIMEOUT_S) == (55, 55, 3300)
    assert (wan_ledger.READ_TIMEOUT_S, wan_ledger.LIST_TIMEOUT_S, wan_ledger.FETCH_TIMEOUT_S) == \
        (30, 60, 180)
