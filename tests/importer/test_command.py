"""``python -m haynes_studio.importer`` on the real public records, with a fake Wan
volume. The real hashes name private files no test can make, so here every read finds
nothing (or other bytes); the twin tests prove the verified path."""

from __future__ import annotations

import io
import json
import os
import stat
import subprocess
import sys

import pytest

from haynes_studio.adapters.fakes import FailingRunner, FakeRunner, FakeWanVolume
from haynes_studio.importer.command import LIBRARY_FILE, REPORT_FILE, main
from haynes_studio.library.library import Library
from tests.importer.test_import import snapshot
from tests.library.fixtures import OPERATOR, imported
from tests.motion.fixtures import still_version
from tests.support.policy import REPO_ROOT

URL = "https://work.haynesnetwork.com/work_packages/428"


@pytest.fixture
def inputs(tmp_path):
    result = imported(4)
    folder = tmp_path / "r4"
    folder.mkdir()
    (folder / "story.json").write_text(json.dumps(result.story))
    (folder / "legacy-import.json").write_text(json.dumps(result.import_map))
    (tmp_path / "store").mkdir()
    return folder


def argv(tmp_path, inputs, *extra, operator_flags=None):
    flags = (["--operator-iss", OPERATOR["iss"], "--operator-sub", OPERATOR["sub"]]
             if operator_flags is None else operator_flags)
    return ["--repo", str(REPO_ROOT), "--story", str(inputs / "story.json"),
            "--map", str(inputs / "legacy-import.json"), *flags,
            "--store", str(tmp_path / "store"), *extra]


class Factory:
    def __init__(self, runner=None):
        self.runner, self.made = runner, 0

    def __call__(self):
        self.made += 1
        if self.runner is None:
            raise AssertionError("no runner may be made here")
        return self.runner


def call(args, factory=None):
    out, err = io.StringIO(), io.StringIO()
    code = main(args, stdout=out, stderr=err, runner_factory=factory or Factory(),
                now=lambda: "2026-11-13T23:50:00Z")
    return code, out.getvalue(), err.getvalue()


def test_the_dry_run_lists_every_row_and_writes_nothing(tmp_path, inputs):
    before = snapshot(tmp_path)
    factory = Factory()
    code, out, err = call(argv(tmp_path, inputs, "--dry-run", "--out", str(tmp_path / "new")), factory)
    assert (code, err) == (0, "") and factory.made == 0
    assert out.startswith("dry run: 156 rows, 101 distinct hashes; to_read 132, not_read 24;")
    assert "nothing read or written" in out
    assert snapshot(tmp_path) == before and not (tmp_path / "new").exists()
    code, out, _ = call(argv(tmp_path, inputs, "--dry-run", "--json"), factory)
    report = json.loads(out)
    assert code == 0 and report["dry_run"] and len(report["rows"]) == 156 and factory.made == 0
    assert report["library"]["versions"] == 46


@pytest.mark.parametrize("extra,message", [
    (("--out", "NEW"), "--authorized-by"),
    (("--out", "NEW", "--authorized-by", "428"), "--authorized-by"),
    (("--out", "NEW", "--authorized-by", "https://work.haynesnetwork.com/work_packages/428/x"),
     "--authorized-by"),
    (("--authorized-by", URL), "--out is required"),
    (("--out", "EXISTS", "--authorized-by", URL), "already exists"),
])
def test_a_run_needs_its_authority_and_a_new_folder(tmp_path, inputs, extra, message):
    (tmp_path / "EXISTS").mkdir()
    extra = tuple(str(tmp_path / e) if e in ("NEW", "EXISTS") else e for e in extra)
    factory = Factory()
    code, _, err = call(argv(tmp_path, inputs, *extra), factory)
    assert code == 2 and message in err and factory.made == 0
    assert not (tmp_path / "NEW").exists()


@pytest.mark.parametrize("flag,value", [("--operator-sub", "tom@example.invalid"),
                                        ("--operator-sub", "two words"),
                                        ("--operator-iss", "not-a-url")])
def test_the_operator_must_be_an_oidc_identity(tmp_path, inputs, flag, value):
    args = argv(tmp_path, inputs, "--dry-run")
    args[args.index(flag) + 1] = value
    code, _, err = call(args)
    assert code == 2 and flag in err


@pytest.mark.parametrize("agent_session", [False, True], ids=["human", "agent-session"])
def test_a_run_against_an_empty_volume_reports_every_row_absent_and_exits_1(tmp_path, inputs, agent_session):
    vol = FakeWanVolume(tmp_path / "pod" / "workspace")
    factory = Factory(FakeRunner(vol))
    from tests.cli.test_operators import AGENT_FLAGS, SESSION
    flags = AGENT_FLAGS if agent_session else None
    out_dir = tmp_path / "run-1"
    code, out, err = call(argv(tmp_path, inputs, "--out", str(out_dir), "--authorized-by", URL,
                               operator_flags=flags), factory)
    assert code == 1 and "no read found its file" in err and factory.made == 1
    assert out.startswith("156 rows: 0 verified, 156 absent, 0 mismatch;")
    report = json.loads((out_dir / REPORT_FILE).read_text())
    assert report["authorized_by"] == URL and report["stopped"] is None
    assert {r["status"] for r in report["rows"]} == {"absent"} and len(report["rows"]) == 156
    assert len(vol.runs) == 129  # every source of every readable hash, each once
    for name in (REPORT_FILE, LIBRARY_FILE):
        assert stat.S_IMODE(os.stat(out_dir / name).st_mode) == 0o444  # create-only, read-only
    library = Library.from_version_documents(json.loads((out_dir / LIBRARY_FILE).read_text()))
    assert len(library.versions) == 46 and report["library"]["created_now"]["e0_motion"] == 22
    actor = {"kind": "cli", "command": "studio private import",
             "operator": SESSION if agent_session else OPERATOR}
    assert all(v.provenance["created_by"] == actor for v in library.versions.values())
    # A second run on the first run's library creates nothing.
    code, _, _ = call(argv(tmp_path, inputs, "--library", str(out_dir / LIBRARY_FILE), "--out",
                           str(tmp_path / "run-2"), "--authorized-by", URL, operator_flags=flags),
                       Factory(FakeRunner(vol)))
    second = json.loads((tmp_path / "run-2" / REPORT_FILE).read_text())
    assert code == 1 and second["library"]["created_now"] == {"winter_menu": 0, "e0_motion": 0}
    again = Library.from_version_documents(json.loads((tmp_path / "run-2" / LIBRARY_FILE).read_text()))
    assert set(again.versions) == set(library.versions)


def test_other_bytes_are_a_mismatch_and_exit_1(tmp_path, inputs):
    vol = FakeWanVolume(tmp_path / "pod" / "workspace")
    ledger = json.loads((REPO_ROOT / "titles/the-winter-menu/evidence-r4/production.json").read_text())
    asset = next(a for a in ledger["assets"] if a["path"].endswith("/cutouts/a-proud.png"))
    vol.add_ledger(ledger, {asset["sha256"]: b"not the delivered bytes"})
    code, out, _ = call(argv(tmp_path, inputs, "--out", str(tmp_path / "run"), "--authorized-by", URL),
                        Factory(FakeRunner(vol)))
    report = json.loads((tmp_path / "run" / REPORT_FILE).read_text())
    item = next(i for i in report["hashes"] if i["sha256"] == asset["sha256"])
    assert code == 1 and item["status"] == "mismatch" and " 4 mismatch;" in out  # its 4 rows
    assert not list((tmp_path / "store").rglob("*.png")) and not list((tmp_path / "store").rglob("*.wav"))


def test_a_stop_exits_1_and_still_writes_the_report(tmp_path, inputs):
    runner = FailingRunner(1, b"error: You must be logged in to the server (Unauthorized)\n")
    code, out, _ = call(argv(tmp_path, inputs, "--out", str(tmp_path / "run"), "--authorized-by", URL),
                        Factory(runner))
    report = json.loads((tmp_path / "run" / REPORT_FILE).read_text())
    assert code == 1 and report["stopped"]["code"] == "adapter.command_failed"
    assert len(runner.calls) == 1 and "stopped: adapter.command_failed" in out


def test_the_module_runs_as_a_command():
    result = subprocess.run([sys.executable, "-m", "haynes_studio.importer", "--help"],
                            capture_output=True, timeout=60, check=False, cwd=REPO_ROOT)
    assert result.returncode == 0 and b"--dry-run" in result.stdout


@pytest.mark.parametrize("agent_session", [False, True], ids=["person", "agent-session"])
def test_main_and_module_refuse_library_opt_in_before_creating_outputs(tmp_path, inputs, agent_session):
    from tests.cli.test_operators import AGENT_FLAGS
    plate = still_version(200, "b" * 64, kind="set")
    plate["occlusion"] = {
        "foreground": [{"key": "shelf", "label": None, "layer_order": 10}], "focal_props": [],
    }
    versions = tmp_path / "versions.json"
    versions.write_text(json.dumps([plate]))
    flags = AGENT_FLAGS if agent_session else None
    args = argv(tmp_path, inputs, "--library", str(versions), "--out", str(tmp_path / "new"),
                "--authorized-by", URL, operator_flags=flags)
    before = snapshot(tmp_path)
    factory = Factory()
    code, out, err = call(args, factory)
    assert code != 0 and not out and factory.made == 0
    result = subprocess.run([sys.executable, "-m", "haynes_studio.importer", *args],
                            text=True, capture_output=True, timeout=60, check=False, cwd=REPO_ROOT)
    assert result.returncode == code and result.stdout == out and result.stderr == err
    assert "occlusion.check_unavailable at /occlusion" in err
    assert "The visibility check is not installed" in err and snapshot(tmp_path) == before
