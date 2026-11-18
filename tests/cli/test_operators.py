"""Operator flags on every writing CLI, before input reads or client construction."""
from __future__ import annotations

import io
import json

import pytest

import haynes_studio.build as studio_build
from haynes_studio.build import RunRecords, validate_run
from haynes_studio.cli import Clients, main
from haynes_studio.importer.command import main as import_main
from tests.build_story import fixtures as f
from tests.canonical.fixtures import manifest_path, speech_path

SESSION = {"kind": "agent_session", "session": "op864-test", "harness": "Codex",
           "model": "gpt-6.1-sol"}
AGENT_FLAGS = ["--operator-session", SESSION["session"], "--operator-harness", SESSION["harness"],
               "--operator-model", SESSION["model"]]
HUMAN = {"kind": "human", "iss": "https://auth.example.invalid", "sub": "subject"}
HUMAN_FLAGS = ["--operator-iss", HUMAN["iss"], "--operator-sub", HUMAN["sub"]]


def call(argv, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    code = main(argv, stdout=out, stderr=err, **kwargs)
    return code, out.getvalue(), err.getvalue()


COMMANDS = [
    ["legacy", "import", "missing", "--speech", "missing"],
    ["voice", "--store", "missing", "--story", "missing", "--library", "missing", "--out", "missing"],
    ["build", "--store", "missing", "--story", "missing", "--library", "missing", "--offline"],
    ["private-view", f.ident("run", 1), "--store", "missing", "--production", f.PRODUCTION,
     "--job", "op864-view", "--out", "missing", "--title", "Test"],
]
BAD_FLAGS = [
    ([], "exactly one operator set"),
    (HUMAN_FLAGS + AGENT_FLAGS, "exactly one operator set"),
    (HUMAN_FLAGS + AGENT_FLAGS[:2], "exactly one operator set"),
    (AGENT_FLAGS + HUMAN_FLAGS[:2], "exactly one operator set"),
    (HUMAN_FLAGS[:2], "--operator-sub"),
    (HUMAN_FLAGS[2:], "--operator-iss"),
    (AGENT_FLAGS[:2], "--operator-harness"),
    (AGENT_FLAGS[2:], "--operator-session"),
    (AGENT_FLAGS[:4], "--operator-model"),
    (["--operator-session", "", *AGENT_FLAGS[2:]], "--operator-session"),
    ([*AGENT_FLAGS[:2], "--operator-harness", " ", *AGENT_FLAGS[4:]], "--operator-harness"),
    ([*AGENT_FLAGS[:4], "--operator-model", ""], "--operator-model"),
]


@pytest.mark.parametrize("command", COMMANDS, ids=["legacy-import", "voice", "build", "private-view"])
@pytest.mark.parametrize("flags, message", BAD_FLAGS)
def test_invalid_operator_flags_stop_before_any_input_or_service(command, flags, message):
    def forbidden():
        pytest.fail("operator refusal must precede client construction")
    code, out, err = call(command + flags, clients=Clients(forbidden, forbidden, forbidden))
    assert code == 2 and not out and message in err


@pytest.mark.parametrize("flags, message", BAD_FLAGS)
def test_private_import_uses_the_same_complete_exclusive_sets(flags, message):
    out, err = io.StringIO(), io.StringIO()
    code = import_main(["--story", "missing", "--map", "missing", "--dry-run", *flags],
                       stdout=out, stderr=err,
                       runner_factory=lambda: pytest.fail("no service"))
    assert code == 2 and not out.getvalue() and message in err.getvalue()


@pytest.mark.parametrize("flags, operator", [(HUMAN_FLAGS, HUMAN), (AGENT_FLAGS, SESSION)],
                         ids=["human", "agent-session"])
def test_legacy_import_records_the_exact_operator_on_story_and_boards(flags, operator):
    code, out, err = call(["legacy", "import", str(manifest_path(4)), "--speech", str(speech_path(4)),
                           *flags, "--json"])
    assert code == 0, err
    story = json.loads(out)["story"]
    actor = {"kind": "cli", "command": "studio legacy import", "operator": operator}
    assert story["created_by"] == actor
    assert all(b["drafted_by"] == actor for b in story["boards"])


@pytest.mark.parametrize("flags, operator", [(HUMAN_FLAGS, HUMAN), (AGENT_FLAGS, SESSION)],
                         ids=["human", "agent-session"])
def test_build_records_operator_on_queued_by_and_every_transition(tmp_path, monkeypatch, flags, operator):
    world = f.make_world(tmp_path / "store")
    story, library = f.voiced(world)
    monkeypatch.setattr(studio_build, "live_clip_sources", lambda *a, **k: f.sources())
    (tmp_path / "toolchain.json").write_text(json.dumps({
        "s2v_profile": f.S2V_PROFILE, "i2v_clip_frames": 25,
        "i2v_profile": dict(f.toolchain().i2v_profile)}))
    (tmp_path / "story.json").write_text(json.dumps(story))
    (tmp_path / "library.json").write_text(json.dumps(library.documents()))
    code, out, err = call([
        "build", "--store", str(world.root), "--story", str(tmp_path / "story.json"),
        "--library", str(tmp_path / "library.json"), "--register", str(f.REGISTER),
        "--toolchain", str(tmp_path / "toolchain.json"),
        "--wan-story",
        "https://work.haynesnetwork.com/work_packages/864", "--json", *flags],
        clients=Clients(lambda: pytest.fail("no voice service"), lambda: f.transcriber()[0],
                        lambda: None))
    assert code == 0, err
    run = json.loads(out)
    actor = {"kind": "cli", "command": "studio build", "operator": operator}
    assert run["status"] == "succeeded" and not validate_run(run)
    assert run["queued_by"] == actor
    assert all(t["by"] == actor for t in run["transitions"])
    records = RunRecords(world.store, f.PRODUCTION)
    for version in records.history(run["id"]):
        assert version["queued_by"] == actor
        assert all(t["by"] == actor for t in version["transitions"])


def test_agent_voice_records_the_operator_on_new_library_versions_and_jobs(tmp_path, monkeypatch):
    world = f.make_world(tmp_path / "store")
    (tmp_path / "story.json").write_text(json.dumps(f.story_document()))
    original = world.library().documents()
    (tmp_path / "library.json").write_text(json.dumps(original))
    jobs = []
    from haynes_studio.build import voice
    real_request = voice.request_voice

    def request(*args, **kwargs):
        result = real_request(*args, **kwargs)
        if result.job is not None:
            jobs.append(result.job.to_document())
        return result
    monkeypatch.setattr(voice, "request_voice", request)
    speech, _ = f.kokoro()
    code, _, err = call([
        "voice", "--store", str(world.root), "--story", str(tmp_path / "story.json"),
        "--library", str(tmp_path / "library.json"), "--register", str(f.REGISTER),
        "--out", str(tmp_path / "voiced"), *AGENT_FLAGS],
        clients=Clients(lambda: speech, lambda: pytest.fail("no ASR")))
    assert code == 0, err
    actor = {"kind": "cli", "command": "studio voice", "operator": SESSION}
    assert jobs and all(j["created_by"] == actor for j in jobs)
    made = json.loads((tmp_path / "voiced/library.json").read_text())
    old_ids = {v["id"] for v in original}
    new = [v for v in made if v["id"] not in old_ids]
    assert new and all(v["provenance"]["created_by"] == actor for v in new)
