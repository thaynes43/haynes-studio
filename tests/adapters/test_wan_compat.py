"""The Wan clip client sends what the PoC sent (story 842).

``poc/wan.py`` and ``poc/s2v.py`` are read with ``ast`` (tests/adapters/poc_source.py),
never imported; where a test needs the PoC's own result, it compiles only the PoC's graph
and job statements (pure code) and runs them on the recorded inputs. The recorded inputs
are the public E0 clip records in ``titles/the-winter-menu/video-e0/``: 15 whole-frame
and layer image-to-video clips, 9 layer clips and 11 lightning speech-to-video clips.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import types

import pytest

from haynes_studio.adapters import pinned, wan
from haynes_studio.adapters.fakes import s2v_frames_delivered, synthetic_png
from haynes_studio.adapters.runner import WAN_API
from haynes_studio.adapters.wan import ImageToVideo, SpeechToVideo, WanClipClient
from tests.adapters import poc_source as poc
from tests.support.policy import REPO_ROOT

E0 = REPO_ROOT / "titles" / "the-winter-menu" / "video-e0"
REGISTER = REPO_ROOT / "docs" / "reference" / "model-licences.json"


def records(name):
    return [json.loads(line) for line in (E0 / name).read_text(encoding="utf-8").splitlines() if line.strip()]


I2V_RECORDS = [r for r in records("clip-records.jsonl") + records("clip-records-layers.jsonl")
               if "method" not in r]
S2V_RECORDS = [r for r in records("clip-records-s2v.jsonl")]
WHOLE_FRAME_S2V = [r for r in records("clip-records.jsonl") if r.get("method") == "s2v"]


class _NoRunner:
    def run(self, command):
        raise AssertionError("this test only builds commands")


def client():
    return WanClipClient(_NoRunner())


def test_the_records_are_the_ones_this_file_describes():
    assert len(I2V_RECORDS) == 24 and len(S2V_RECORDS) == 11 and len(WHOLE_FRAME_S2V) == 1
    assert {r["method"] for r in S2V_RECORDS} == {"s2v-lightning"}


# Snippets and template: byte for byte ----------------------------------------------------------

@pytest.mark.parametrize("pin,constant", [("wan_probe.py", "PROBE"), ("wan_upload.py", "UPLOAD"),
                                          ("wan_run.py", "RUN")])
def test_ported_snippet_is_the_poc_text(pin, constant):
    assert pinned.load(pin).data == poc.constants("wan")[constant].encode()


def test_s2v_uses_the_same_snippets_and_negative_as_wan():
    imports = [n for n in poc.module("s2v").body if isinstance(n, ast.ImportFrom) and n.module == "wan"]
    assert [a.name for a in imports[0].names] == ["REMOTE", "UPLOAD", "RUN", "NEGATIVE", "remote", "wait_cool"]


def test_the_template_is_the_one_every_layer_record_names():
    template = pinned.load("wan_ti2v_workflow.json")
    layer = records("clip-records-layers.jsonl")
    assert {r["template_sha256"] for r in layer} == {template.sha256}
    assert pinned.HAYNES_OPS_WAN_COMMIT.startswith("3a3571c4")
    render = ast.unparse(poc.function("wan", "render"))
    assert f"expected = {wan.I2V_NODES!r}" in render


def test_the_fetch_reads_the_same_route_with_the_same_timeouts():
    render = ast.unparse(poc.function("wan", "render"))
    assert "'/file\",timeout=60).read())'" in render and "remote(fetch, timeout=90)" in render
    assert "'http://127.0.0.1:8080/videos/' + job['id'] + '/file" in render.replace('"', "'")
    text = pinned.load("wan_clip_fetch.py").text
    assert "urllib.request.urlopen('http://127.0.0.1:8080/videos/'+sys.argv[1]+'/file',timeout=60).read()" in text
    command = client().fetch_command("a" * 32)
    assert command.timeout_s == 90 and command.argv[-1] == "a" * 32


# Command lines and timeouts ----------------------------------------------------------------------

def _remote_calls(script, func):
    return [ast.unparse(n) for n in ast.walk(poc.function(script, func))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "remote"]


def test_remote_is_kubectl_exec_into_the_api_container():
    call, = poc.subprocess_runs(poc.function("wan", "remote"))
    assert ast.unparse(call.args[0]) == "REMOTE + [code] + list(args)"
    assert poc.constants("wan")["REMOTE"] == list(WAN_API.argv("x"))[:-1]


def test_probe_command_line_and_timeout_match_poc():
    assert _remote_calls("wan", "wait_cool") == ["remote(PROBE, timeout=30)"]
    command = client().probe_command()
    assert list(command.argv) == poc.constants("wan")["REMOTE"] + [poc.constants("wan")["PROBE"]]
    assert command.timeout_s == 30 and command.stdin == b""


@pytest.mark.parametrize("script,func,name", [("wan", "render", "up_name"), ("s2v", "upload", "name")])
def test_upload_command_line_and_timeout_match_poc(script, func, name):
    call, = poc.subprocess_runs(poc.function(script, func))
    data = synthetic_png(seed=4)
    digest = hashlib.sha256(data).hexdigest()
    command = client().upload_command(data, ".png")
    assert list(command.argv) == poc.argv("wan", call, {name: f"{digest[:16]}.png", "digest": digest})
    assert command.timeout_s == ast.literal_eval(poc.keyword(call, "timeout")) == 30
    assert ast.unparse(poc.keyword(call, "input")) == "data"
    assert command.stdin == data


def test_run_command_line_payload_and_timeout_match_poc():
    assert "remote(RUN, {'job': job, 'graph': graph, 'prompt': prompt}, timeout=1500)" in \
        _remote_calls("wan", "render")
    assert "remote(RUN, {'job': job, 'graph': g, 'prompt': prompt}, timeout=1500)" in _remote_calls("s2v", "main")
    call, = poc.subprocess_runs(poc.function("wan", "remote"))
    assert ast.unparse(poc.keyword(call, "input")) == "None if payload is None else json.dumps(payload).encode()"
    request = ImageToVideo(image_png=synthetic_png(seed=5), prompt="p", seed=1,
                           story=wan.I2V_STORY)
    job_id, created = "c" * 32, 1_762_000_000.5
    command = client().command(request, job_id, created)
    assert list(command.argv) == poc.constants("wan")["REMOTE"] + [poc.constants("wan")["RUN"]]
    assert command.timeout_s == 1500
    graph, job = _poc_i2v(request.prompt, request.negative, request.width, request.height, request.length,
                          request.seed, wan.upload_name(request.image_png, ".png"), request.image_sha256,
                          job_id, created)
    assert command.stdin == json.dumps({'job': job, 'graph': graph, 'prompt': request.prompt}).encode()


# The cool-idle wait ----------------------------------------------------------------------------

def test_cool_idle_rule_is_the_pocs():
    poc_text = ast.unparse(poc.function("wan", "wait_cool"))
    assert poc_text.startswith("def wait_cool(max_s=1800):")
    for line in ("h.get('accepting_jobs') is not True or h.get('active_job') is not None",
                 "q.get('queue_running') or q.get('queue_pending')",
                 "g['temperature_c'] < 62 and g['utilization_percent'] <= 5",
                 "time.monotonic() - t0 > max_s", "time.sleep(10)"):
        assert line in poc_text, line
    package = ast.unparse(next(n for n in ast.walk(ast.parse(
        (REPO_ROOT / "src/haynes_studio/adapters/wan.py").read_text())) if isinstance(n, ast.ClassDef)
        and n.name == "WanClipClient"))
    for line in ("h.get('accepting_jobs') is not True or h.get('active_job') is not None",
                 "q.get('queue_running') or q.get('queue_pending')",
                 "self.clock() - t0 > COOL_MAX_S", "self.sleep(COOL_POLL_S)"):
        assert line in package, line
    assert (wan.COOL_MAX_S, wan.COOL_POLL_S, wan.COOL_TEMP_C, wan.COOL_UTIL_PERCENT) == (1800, 10, 62, 5)


# Image to video: the same graph and job for every recorded clip --------------------------------

def _poc_statements(script, func, first, last):
    body = poc.function(script, func).body
    start = next(i for i, s in enumerate(body) if ast.unparse(s).startswith(first))
    end = next(i for i, s in enumerate(body) if ast.unparse(s).startswith(last))
    return ast.Module(body=body[start:end + 1], type_ignores=[])


def _poc_i2v(prompt, negative, width, height, length, seed, up_name, digest, job_id, created_at):
    """The graph and job ``poc/wan.py render()`` builds, by running its own statements."""
    code = compile(_poc_statements("wan", "render", "template = TEMPLATE.read_bytes()", "graph['13'] ="),
                   "poc/wan.py", "exec")
    template = pinned.load("wan_ti2v_workflow.json").data
    space = {"TEMPLATE": types.SimpleNamespace(read_bytes=lambda: template), "json": json,
             "uuid": types.SimpleNamespace(uuid4=lambda: types.SimpleNamespace(hex=job_id)),
             "time": types.SimpleNamespace(time=lambda: created_at), "prompt": prompt, "negative": negative,
             "width": width, "height": height, "length": length, "seed": seed, "steps": 20,
             "up_name": up_name, "digest": digest}
    exec(code, space)
    return space["graph"], space["job"]


def test_i2v_fills_the_same_graph_fields_as_poc():
    poc_lines = [ast.unparse(s) for s in poc.function("wan", "render").body]
    tree = ast.parse((REPO_ROOT / "src/haynes_studio/adapters/wan.py").read_text())
    package = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "i2v_graph")
    package_lines = [ast.unparse(s) for s in package.body]
    assert [x for x in package_lines if x.startswith("graph[")] == [x for x in poc_lines if x.startswith("graph[")]


@pytest.mark.parametrize("record", I2V_RECORDS, ids=lambda r: r["name"])
def test_i2v_rebuilds_every_recorded_graph_and_job(record):
    up_name = record["image_sha256"][:16] + ".png"
    created = 1_762_000_000.0
    expected_graph, expected_job = _poc_i2v(record["prompt"], record["negative"], record["width"],
                                            record["height"], record["length"], record["seed"], up_name,
                                            record["image_sha256"], record["job_id"], created)
    graph = wan.i2v_graph(pinned.load("wan_ti2v_workflow.json").data, prompt=record["prompt"],
                          negative=record["negative"], width=record["width"], height=record["height"],
                          length=record["length"], seed=record["seed"], steps=wan.I2V_STEPS,
                          job_id=record["job_id"], up_name=up_name)
    job = wan.i2v_job(job_id=record["job_id"], width=record["width"], height=record["height"],
                      length=record["length"], seed=record["seed"], created_at=created, up_name=up_name,
                      digest=record["image_sha256"], story=wan.I2V_STORY)
    assert graph == expected_graph
    assert json.dumps(job) == json.dumps(expected_job)  # same keys, same order
    assert record["negative"] == wan.NEGATIVE
    assert record["frames"] >= record["length"]  # E0 never delivered a short clip


def test_i2v_client_passes_the_request_to_the_poc_builder():
    request = ImageToVideo(image_png=synthetic_png(seed=6), prompt="p", seed=3, story=wan.I2V_STORY,
                           width=576, height=1024, length=121)
    expected, _ = _poc_i2v("p", wan.NEGATIVE, 576, 1024, 121, 3, wan.upload_name(request.image_png, ".png"),
                           request.image_sha256, "d" * 32, 0.0)
    assert client().graph(request, "d" * 32) == expected


# Speech to video: the same graph and job for every recorded clip --------------------------------

def _poc_s2v_graph():
    func = poc.function("s2v", "graph")
    known = poc.constants("s2v")
    space = {"math": math, "CHUNK": known["CHUNK"], "LORA": known["LORA"], "FPS": known["FPS"]}
    exec(compile(ast.Module(body=[func], type_ignores=[]), "poc/s2v.py", "exec"), space)
    return space["graph"]


def test_s2v_graph_function_is_the_pocs():
    func = poc.function("s2v", "graph")
    tree = ast.parse((REPO_ROOT / "src/haynes_studio/adapters/wan.py").read_text())
    package = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "s2v_graph")
    assert ast.dump(package.args) == ast.dump(func.args)
    assert [ast.dump(s) for s in package.body] == [ast.dump(s) for s in func.body]
    known = poc.constants("s2v")
    assert (wan.FPS, wan.CHUNK, wan.LORA) == (known["FPS"], known["CHUNK"], known["LORA"])


def test_time9_is_the_poc_length_rule_with_pad_zero():
    main = ast.unparse(poc.function("s2v", "main"))
    assert "length = 4 * math.ceil((dur + a.pad_s) * FPS / 4) + 1" in main
    assert "length = CHUNK * math.ceil(length / CHUNK)" in main
    for frames in range(1, 343):
        dur = frames / 24
        legacy = 4 * math.ceil((dur + 0) * 16 / 4) + 1
        if legacy > 77:
            legacy = 77 * math.ceil(legacy / 77)
        assert wan.s2v_length(frames) == legacy, frames


def _poc_s2v_job(prompt, image, audio, image_sha, audio_sha, width, height, length, seed, job_id, created_at):
    code = compile(_poc_statements("s2v", "main", "jid = uuid.uuid4().hex", "job = "), "poc/s2v.py", "exec")
    space = {"uuid": types.SimpleNamespace(uuid4=lambda: types.SimpleNamespace(hex=job_id)),
             "time": types.SimpleNamespace(time=lambda: created_at), "graph": _poc_s2v_graph(),
             "NEGATIVE": wan.NEGATIVE, "prompt": prompt, "image": image, "audio": audio,
             "image_sha": image_sha, "audio_sha": audio_sha, "length": length,
             "a": types.SimpleNamespace(width=width, height=height, seed=seed, lightning=True)}
    exec(code, space)
    return space["g"], space["job"]


@pytest.mark.parametrize("record", S2V_RECORDS, ids=lambda r: r["name"])
def test_s2v_rebuilds_every_recorded_graph_and_job(record):
    board_frames = round(record["audio_s"] * 24)
    assert round(board_frames / 24, 3) == record["audio_s"]  # the drive was exactly F / 24 s
    length = wan.s2v_length(board_frames)
    assert length == record["length"]
    assert max(1, math.ceil(length / wan.CHUNK)) == record["chunks"]
    image = "studio-e0/" + record["image_sha256"][:16] + ".png"
    audio = "studio-e0/" + record["audio_sha256"][:16] + ".wav"
    expected_graph, expected_job = _poc_s2v_job(record["prompt"], image, audio, record["image_sha256"],
                                                record["audio_sha256"], record["width"], record["height"],
                                                length, record["seed"], record["job_id"], 1_762_000_000.0)
    graph = wan.s2v_graph(record["prompt"], wan.NEGATIVE, image, audio, record["width"], record["height"],
                          length, record["seed"], "video/" + record["job_id"], True)
    job = wan.s2v_job(job_id=record["job_id"], width=record["width"], height=record["height"], length=length,
                      seed=record["seed"], created_at=1_762_000_000.0, image=image,
                      image_sha=record["image_sha256"], audio=audio, audio_sha=record["audio_sha256"],
                      story=wan.S2V_STORY)
    assert graph == expected_graph
    assert json.dumps(job) == json.dumps(expected_job)
    assert record["frames"] >= length and record["frames"] >= wan.s2v_frames_needed(board_frames)
    chunks = [min(length, wan.CHUNK)] + [wan.CHUNK] * (record["chunks"] - 1)
    assert s2v_frames_delivered(chunks) == record["frames"]  # the fake delivers what E0 did


def test_s2v_client_passes_the_request_to_the_poc_builder():
    from haynes_studio.adapters.fakes import synthetic_wav
    request = SpeechToVideo(image_png=synthetic_png(seed=7), drive_wav=synthetic_wav(94000), board_frames=94,
                            prompt="p", seed=501, story=wan.S2V_STORY)
    image = "studio-e0/" + wan.upload_name(request.image_png, ".png")
    audio = "studio-e0/" + wan.upload_name(request.drive_wav, ".wav")
    expected_graph, expected_job = _poc_s2v_job(
        "p", image, audio, request.image_sha256, hashlib.sha256(request.drive_wav).hexdigest(),
        576, 1024, 65, 501, "e" * 32, 5.0)
    assert client().graph(request, "e" * 32) == expected_graph
    assert json.dumps(client().job(request, "e" * 32, 5.0)) == json.dumps(expected_job)


def test_the_whole_frame_20_step_s2v_record_is_not_a_profile_this_client_builds():
    record, = WHOLE_FRAME_S2V
    assert record["method"] == "s2v" and SpeechToVideo.lightning is True


# Model files ------------------------------------------------------------------------------------

def test_model_files_are_the_registers():
    register = json.loads(REGISTER.read_text(encoding="utf-8"))
    wan_files = {f["name"]: f["sha256"] for f in register["files"] if f["engine"] in ("wan-ti2v", "wan-s2v")}
    assert wan.MODEL_FILES_SHA256 == wan_files
    i2v = wan.model_files(json.loads(pinned.load("wan_ti2v_workflow.json").data))
    s2v = wan.model_files(wan.s2v_graph("p", "n", "i", "a", 576, 1024, 65, 1, "video/x", True))
    engines = {e["key"]: e["files"] for e in register["engines"]}
    keys = {f["name"]: f["key"] for f in register["files"]}
    assert sorted(keys[n] for n in i2v) == sorted(engines["wan-ti2v"])
    # The S2V graph also loads the shared umt5 text encoder, which the register lists once,
    # under wan-ti2v (an observation for the register's owner, story 842).
    assert sorted(keys[n] for n in s2v) == sorted(engines["wan-s2v"] + ["umt5-xxl-fp8"])
