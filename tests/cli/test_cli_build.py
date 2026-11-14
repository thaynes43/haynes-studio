"""``studio voice``, ``studio build`` and ``studio run show`` (story 406), with fake
clients passed in at the edge. The live clip-source hook is left unfilled: the service
phase (and a full build) stop with its message and make no run; an offline build needs
nothing from it."""

from __future__ import annotations

import io
import json

import pytest

import haynes_studio.build as studio_build
from haynes_studio.cli import Clients, main
from haynes_studio.store import StoreError
from haynes_studio.store.errors import COLLISION
from tests.build_story import fixtures as f

OPERATOR = ["--operator-iss", "https://authentik.example.invalid/application/o/haynes-studio/",
            "--operator-sub", "example-subject-build"]


def run_cli(*argv: str, clients: Clients | None = None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=out, stderr=err, clients=clients)
    return code, out.getvalue(), err.getvalue()


class Fakes:
    def __init__(self, heard: str = f.HEARD):
        self.speech_runs = []
        self.heard = heard

    def clients(self) -> Clients:
        def speech():
            client, runner = f.kokoro()
            self.speech_runs.append(runner)
            return client
        return Clients(speech=speech, transcriber=lambda: f.transcriber(self.heard)[0])


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    root = tmp_path_factory.mktemp("cli-build")
    world = f.make_world(root / "store")
    files = root / "files"
    files.mkdir()
    (files / "story.json").write_text(json.dumps(f.story_document()))
    (files / "library.json").write_text(json.dumps(world.library().documents()))
    (files / "toolchain.json").write_text(json.dumps(
        {"s2v_profile": f.S2V_PROFILE, "i2v_clip_frames": 25,
         "i2v_profile": {**dict(f.toolchain().i2v_profile)}}))
    return world, files


def args(world, story, library, *extra):
    return ["--store", str(world.root), "--story", str(story), "--library", str(library),
            *OPERATOR, *extra]


def test_voice_makes_the_board_voices_and_writes_new_files(setup):
    world, files = setup
    fakes = Fakes()
    code, out, err = run_cli("voice", *args(world, files / "story.json", files / "library.json",
                                            "--out", str(files / "voiced"), "--register",
                                            str(f.REGISTER)), clients=fakes.clients())
    assert code == 0, err
    assert f"{f.B1}: made" in out
    story = json.loads((files / "voiced" / "story.json").read_text())
    assert f.board_of(story, f.B1)["voice"]["current_version_id"] is not None
    assert len(fakes.speech_runs[0].calls) == 1  # one line, one speech call
    again = run_cli("voice", *args(world, files / "voiced" / "story.json",
                                   files / "voiced" / "library.json", "--out", str(files / "again"),
                                   "--register", str(f.REGISTER)), clients=fakes.clients())
    assert again[0] == 0 and f"{f.B1}: current" in again[1]
    assert len(fakes.speech_runs[1].calls) == 0
    refused = run_cli("voice", *args(world, files / "story.json", files / "library.json",
                                     "--out", str(files / "voiced")), clients=fakes.clients())
    assert refused[0] == 2 and "will not overwrite" in refused[2]


def test_the_unfilled_hook_stops_the_service_phase_and_a_full_build_with_no_run(setup):
    world, files = setup
    before = studio_build.local_run_ids(world.store, f.PRODUCTION)
    for extra in (("--phase", "service"), ()):
        code, _, err = run_cli("build", *args(world, files / "story.json", files / "library.json",
                                              *extra), clients=Fakes().clients())
        assert code == 1
        assert "build.clip_sources_unwired" in err and "--offline" in err
    assert studio_build.local_run_ids(world.store, f.PRODUCTION) == before


def test_service_then_offline_builds_and_run_show_reads_the_run(setup, monkeypatch):
    world, files = setup
    voiced = files / "voiced"
    sources = f.sources()
    monkeypatch.setattr(studio_build, "live_clip_sources", lambda: sources)
    base = args(world, voiced / "story.json", voiced / "library.json", "--toolchain",
                str(files / "toolchain.json"), "--register", str(f.REGISTER), "--studio-commit", "abc123")
    code, out, err = run_cli("build", *base, "--phase", "service", clients=Fakes().clients())
    assert code == 0, err
    assert "(service phase): cancelled" in out
    assert len(sources.s2v.calls) == 1 and len(sources.i2v.calls) == 1
    monkeypatch.setattr(studio_build, "live_clip_sources", lambda: pytest.fail("offline asks no hook"))
    # Offline renders the picture and master, then stops at the transcript check (a
    # service call); the service phase checks the cached master; offline then delivers.
    code, out, err = run_cli("build", *base, "--offline", clients=Fakes().clients())
    assert code == 1 and "rule build.offline_missing" in err and "(stage check_result)" in err
    monkeypatch.setattr(studio_build, "live_clip_sources", lambda: sources)
    code, out, err = run_cli("build", *base, "--phase", "service", clients=Fakes().clients())
    assert code == 0, err
    monkeypatch.setattr(studio_build, "live_clip_sources", lambda: pytest.fail("offline asks no hook"))
    code, out, err = run_cli("build", *base, "--offline", "--json", clients=Fakes().clients())
    assert code == 0, err
    run = json.loads(out)
    assert run["status"] == "succeeded" and run["phase"] == "offline"
    assert run["provenance"]["toolchain"]["studio"] == "git:abc123"
    code, shown, err = run_cli("run", "show", run["id"], "--store", str(world.root),
                               "--production", f.PRODUCTION, "--json")
    assert code == 0 and json.loads(shown) == run
    code, text, _ = run_cli("run", "show", run["id"], "--store", str(world.root),
                            "--production", f.PRODUCTION)
    assert f"run {run['id']} (offline phase): succeeded" in text and "delivery dlv_" in text
    code, history, _ = run_cli("run", "show", run["id"], "--store", str(world.root),
                               "--production", f.PRODUCTION, "--history")
    assert code == 0 and history.splitlines()[-1].startswith("3: succeeded")


def test_a_failed_transcript_in_the_service_phase_exits_1(setup, monkeypatch):
    # After the test above, the voiced story's master is cached; new tolerances key a
    # new transcript check of it, which the service phase makes (review finding 3).
    world, files = setup
    voiced = files / "voiced"
    story = json.loads((voiced / "story.json").read_text())
    story["checks"]["asr_tolerances"] = {"2": "two", "3": "three"}
    (files / "retolerated.json").write_text(json.dumps(story))
    monkeypatch.setattr(studio_build, "live_clip_sources", lambda: f.sources())
    code, out, err = run_cli("build", *args(world, files / "retolerated.json", voiced / "library.json",
                                            "--phase", "service", "--toolchain",
                                            str(files / "toolchain.json"), "--register", str(f.REGISTER)),
                             clients=Fakes(heard="stop team two").clients())
    assert code == 1 and "(service phase): failed" in out
    assert "rule build.check_failed" in err and "(stage checks)" in err and "master.transcript" in err


def test_a_failure_the_store_cannot_record_exits_1_naming_the_run(setup, monkeypatch):
    world, files = setup
    voiced = files / "voiced"
    story = json.loads((voiced / "story.json").read_text())
    f.board_of(story, f.B3)["seeds"]["i2v:frame"] = 78  # a clip no run made
    (files / "reseeded-78.json").write_text(json.dumps(story))
    real = studio_build.RunRecords.write

    def write(self, run):
        if run["status"] == "failed":
            raise StoreError(COLLISION, "another record holds that version")
        return real(self, run)
    monkeypatch.setattr(studio_build.RunRecords, "write", write)
    code, _, err = run_cli("build", *args(world, files / "reseeded-78.json", voiced / "library.json",
                                          "--offline", "--toolchain", str(files / "toolchain.json"),
                                          "--register", str(f.REGISTER)), clients=Fakes().clients())
    assert code == 1
    assert "rule build.run_unrecorded" in err and "`running`" in err and "no delivery" in err
    assert "build.offline_missing" in err and " run_" in err


def test_a_failed_offline_build_exits_1_with_its_code_and_board(setup):
    world, files = setup
    voiced = files / "voiced"
    story = json.loads((voiced / "story.json").read_text())
    f.board_of(story, f.B3)["seeds"]["i2v:frame"] = 77  # a clip no run made
    (files / "reseeded.json").write_text(json.dumps(story))
    code, out, err = run_cli("build", *args(world, files / "reseeded.json", voiced / "library.json",
                                            "--offline", "--toolchain", str(files / "toolchain.json"),
                                            "--register", str(f.REGISTER)), clients=Fakes().clients())
    assert code == 1
    assert "rule build.offline_missing" in err and f"at board {f.B3}" in err
    assert ": failed" in out


def test_run_show_refuses_an_unknown_run(setup):
    world, _ = setup
    code, _, err = run_cli("run", "show", f.ident("run", 999), "--store", str(world.root),
                           "--production", f.PRODUCTION)
    assert code == 1 and "no run" in err
