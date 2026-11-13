"""The ``studio`` command: help, version, ``legacy validate`` and ``legacy timeline``."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from importlib.metadata import entry_points
from pathlib import Path

import pytest

import haynes_studio
from haynes_studio.cli import main
from tests.support.policy import REPO_ROOT

TITLE = REPO_ROOT / "titles" / "the-winter-menu"
FIXTURES = {1: ("manifest.json", "evidence", 662), 2: ("manifest-r2.json", "evidence-r2", 823),
            3: ("manifest-r3.json", "evidence-r3", 1094), 4: ("manifest-r4.json", "evidence-r4", 1087)}


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def rel(path: Path) -> str:
    """The path as the command is given it; absolute, so the tests run from any folder."""
    return str(path)


def test_version(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out == f"studio {haynes_studio.__version__}\n"


def test_help_lists_the_legacy_commands(capsys):
    assert main(["--help"]) == 0
    assert "legacy" in capsys.readouterr().out
    assert main(["legacy", "--help"]) == 0
    text = capsys.readouterr().out
    assert "validate" in text and "timeline" in text


@pytest.mark.parametrize("argv", [[], ["legacy"], ["legacy", "timeline", "m.json"], ["nope"]])
def test_usage_errors_exit_2(argv, capsys):
    assert main(argv) == 2
    assert "usage:" in capsys.readouterr().err


def test_console_script_is_installed():
    (script,) = entry_points(group="console_scripts", name="studio")
    assert script.value == "haynes_studio.cli:main"
    installed = Path(sys.executable).parent / "studio"
    assert installed.is_file(), "uv sync installs the studio script beside the interpreter"
    result = subprocess.run([str(installed), "--help"], capture_output=True, text=True,
                            timeout=60, check=False)
    assert result.returncode == 0 and "legacy" in result.stdout


def test_python_dash_m_runs_the_cli():
    result = subprocess.run([sys.executable, "-m", "haynes_studio", "--version"],
                            capture_output=True, text=True, timeout=60, check=False)
    assert (result.returncode, result.stdout) == (0, f"studio {haynes_studio.__version__}\n")


@pytest.mark.parametrize("revision", FIXTURES)
def test_validate_each_revision(revision):
    path = rel(TITLE / FIXTURES[revision][0])
    code, out, err = run("legacy", "validate", path)
    assert (code, err) == (0, "")
    assert out.startswith(f"{path}: valid legacy.manifest/v1, revision {revision}")


def test_validate_json():
    code, out, _ = run("legacy", "validate", rel(TITLE / "manifest-r4.json"), "--json")
    summary = json.loads(out)
    assert code == 0
    assert {k: summary[k] for k in ("schema", "valid", "revision", "shots", "lines",
                                    "sound_cues", "beds", "gaps_defaulted")} == {
        "schema": "legacy.manifest/v1", "valid": True, "revision": 4, "shots": 9, "lines": 13,
        "sound_cues": 4, "beds": 1, "gaps_defaulted": 0}


def test_validate_reports_file_rule_and_path(tmp_path):
    case = json.loads((REPO_ROOT / "docs/contracts/examples/invalid/"
                       "legacy-duration-with-lines.json").read_text(encoding="utf-8"))
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(case["document"]), encoding="utf-8")
    code, out, err = run("legacy", "validate", str(path))
    assert (code, out) == (1, "")
    assert err.splitlines() == [
        f"{path}: rule legacy.duration_with_lines at /shots/0: a shot with lines has no "
        "duration; the legacy editor silently let duration win"]


def test_validate_a_missing_file_exits_2(tmp_path):
    code, out, err = run("legacy", "validate", str(tmp_path / "absent.json"))
    assert (code, out) == (2, "")
    assert err.startswith("studio: cannot read ") and "absent.json" in err


@pytest.mark.parametrize("revision", FIXTURES)
def test_timeline_compare_matches(revision):
    name, evidence, frames = FIXTURES[revision]
    code, out, err = run("legacy", "timeline", rel(TITLE / name),
                         "--speech", rel(TITLE / evidence / "speech.json"),
                         "--compare", rel(TITLE / evidence / "timeline.json"))
    assert (code, err) == (0, "")
    assert f"total {frames} frames at 24 fps" in out
    assert f"compared with {rel(TITLE / evidence / 'timeline.json')}: match;" in out


def test_timeline_json():
    code, out, _ = run("legacy", "timeline", rel(TITLE / "manifest-r4.json"),
                       "--speech", rel(TITLE / "evidence-r4/speech.json"),
                       "--compare", rel(TITLE / "evidence-r4/timeline.json"), "--json")
    result = json.loads(out)
    assert code == 0
    assert result["frames"] == 1087 and result["samples"] == 2_174_000
    assert result["display_seconds"] == "45.292"
    assert result["shots"][7]["sfx"][1] == {"cue": "gavel", "start_ms": 7625,
                                            "start_sample": 1_822_000, "end_sample": 1_853_200,
                                            "cut_at_film_end": False}
    assert result["comparison"]["match"] is True and result["comparison"]["mismatches"] == []


def test_timeline_without_compare_computes_only():
    code, out, _ = run("legacy", "timeline", rel(TITLE / "manifest-r4.json"),
                       "--speech", rel(TITLE / "evidence-r4/speech.json"))
    assert code == 0 and "compared with" not in out


def test_timeline_mismatch_exits_1(tmp_path):
    recorded = json.loads((TITLE / "evidence-r4/timeline.json").read_text(encoding="utf-8"))
    recorded["shots"][0]["frames"] = 152
    path = tmp_path / "timeline.json"
    path.write_text(json.dumps(recorded), encoding="utf-8")
    code, out, err = run("legacy", "timeline", rel(TITLE / "manifest-r4.json"),
                         "--speech", rel(TITLE / "evidence-r4/speech.json"), "--compare", str(path))
    assert code == 1
    assert f"compared with {path}: 2 mismatch(es);" in out
    assert err.splitlines() == [
        f"{path}: rule legacy.timeline_mismatch at /shots/0/frames: shot 1 frames: "
        "computed 153, recorded 152 (exact)",
        f"{path}: rule legacy.timeline_mismatch at /shots: film frames: computed 1087, "
        "recorded 1086 (exact)",
    ]


def test_timeline_json_mismatches_carry_paths(tmp_path):
    recorded = json.loads((TITLE / "evidence-r4/timeline.json").read_text(encoding="utf-8"))
    recorded["total_s"] = 45.3
    path = tmp_path / "timeline.json"
    path.write_text(json.dumps(recorded), encoding="utf-8")
    code, out, _ = run("legacy", "timeline", rel(TITLE / "manifest-r4.json"),
                       "--speech", rel(TITLE / "evidence-r4/speech.json"), "--compare", str(path),
                       "--json")
    assert code == 1
    assert json.loads(out)["comparison"]["mismatches"] == [
        "rule legacy.timeline_mismatch at /total_s: film total: computed 45.2917, recorded "
        "45.3 (4 decimals, diff -8.333 ms)"]


def test_a_malformed_record_exits_1_without_a_traceback(tmp_path):
    recorded = json.loads((TITLE / "evidence-r4/timeline.json").read_text(encoding="utf-8"))
    recorded["audio"][0]["shot"] = [1]
    path = tmp_path / "timeline.json"
    path.write_text(json.dumps(recorded).replace('"start_s": 0.5,', '"start_s": 1e400,', 1),
                    encoding="utf-8")
    code, _, err = run("legacy", "timeline", rel(TITLE / "manifest-r4.json"),
                       "--speech", rel(TITLE / "evidence-r4/speech.json"), "--compare", str(path))
    assert code == 1
    assert err.splitlines() == [f"{path}: rule legacy.invalid at (root): not JSON: 1e400 is too "
                                "large for a number"]


def test_timeline_with_the_wrong_speech_exits_1():
    code, out, err = run("legacy", "timeline", rel(TITLE / "manifest-r4.json"),
                         "--speech", rel(TITLE / "evidence/speech.json"))
    assert (code, out) == (1, "")
    assert "rule legacy.speech_mismatch" in err
