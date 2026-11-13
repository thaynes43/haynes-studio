"""``studio legacy import``: summary, JSON, create-only output, ID reuse from a map, and
no legacy file written."""

from __future__ import annotations

import hashlib
import io
import json

import pytest

from haynes_studio import cli
from haynes_studio.canonical import validate_legacy_import, validate_story
from haynes_studio.cli import main
from tests.canonical.fixtures import IMPORT_MAP, NOW, OPERATOR, manifest_path, speech_path
from tests.support.policy import REPO_ROOT

OPERATOR_ARGS = ["--operator-iss", OPERATOR["iss"], "--operator-sub", OPERATOR["sub"]]


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def import_args(revision=4, *extra):
    return ["legacy", "import", str(manifest_path(revision)), "--speech",
            str(speech_path(revision)), *OPERATOR_ARGS, *extra]


@pytest.fixture(autouse=True)
def fixed_time_and_folder(monkeypatch):
    monkeypatch.setattr(cli, "_now", lambda: NOW)
    monkeypatch.chdir(REPO_ROOT)


def _titles_digest() -> dict[str, str]:
    return {str(path.relative_to(REPO_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((REPO_ROOT / "titles").rglob("*")) if path.is_file()}


def test_import_with_the_contract_map_prints_a_summary():
    code, out, err = run(*import_args(4, "--map", str(IMPORT_MAP)))
    assert (code, err) == (0, "")
    first = out.splitlines()[0]
    assert "imported revision 4 as story sty_01M79V9FC00000000000000001" in first
    assert "9 boards, 13 lines, 17 cues, 3 notes, 1 bed; 1087 frames (45.292 s)" in first
    assert "IDs: 24 from the map, 45 minted" in first
    assert "B08 brd_01M79V9FC00000000000000008 shot 8: 251 frames from film frame 728" in out


def test_json_output_is_a_valid_story_and_map():
    code, out, _ = run(*import_args(2, "--json"))
    assert code == 0
    result = json.loads(out)
    assert result["story"]["derived"]["frames"] == 823
    assert result["story"]["origin"]["manifest"] == "titles/the-winter-menu/manifest-r2.json"
    assert result["story"]["created_by"]["operator"] == OPERATOR
    assert validate_story(result["story"], context="read") == []  # derived as read
    assert validate_legacy_import(result["legacy_import"]) == []


def test_out_is_create_only_and_its_map_returns_the_same_ids(tmp_path):
    before = _titles_digest()
    first = tmp_path / "first"
    code, out, _ = run(*import_args(4, "--out", str(first)))
    assert code == 0 and "wrote" in out
    story = json.loads((first / "story.json").read_text())
    import_map = json.loads((first / "legacy-import.json").read_text())

    code, _, err = run(*import_args(4, "--out", str(first)))
    assert code == 2 and "will not overwrite" in err
    assert json.loads((first / "story.json").read_text()) == story

    second = tmp_path / "second"
    code, out, _ = run(*import_args(4, "--map", str(first / "legacy-import.json"),
                                    "--out", str(second)))
    assert code == 0 and "IDs: 69 from the map, 0 minted" in out
    assert json.loads((second / "story.json").read_text()) == story
    assert json.loads((second / "legacy-import.json").read_text()) == import_map
    assert _titles_digest() == before  # no legacy file written


def test_a_map_from_another_draft_revision_is_a_rule_failure():
    code, out, err = run(*import_args(1, "--map", str(IMPORT_MAP)))
    assert (code, out) == (1, "")
    assert err.strip() == (f"{IMPORT_MAP}: rule legacy.import_map_mismatch at "
                           "/draft_from_revision: the map has 4; this import needs 1")


@pytest.mark.parametrize("extra,message", [
    (["--production", "sty_01M79V9FC00000000000000001"], "is not a prd_ ID"),
    (["--map", "missing-map.json"], "cannot read missing-map.json"),
])
def test_usage_errors(extra, message):
    code, _, err = run(*import_args(4, *extra))
    assert code == 2 and message in err


def test_a_map_that_is_not_json_is_a_usage_error(tmp_path):
    bad = tmp_path / "map.json"
    bad.write_text("{", encoding="utf-8")
    code, _, err = run(*import_args(4, "--map", str(bad)))
    assert code == 2 and "not JSON" in err


def test_operator_is_required(capsys):
    args = ["legacy", "import", str(manifest_path(4)), "--speech", str(speech_path(4))]
    assert main(args) == 2
    assert "--operator-iss" in capsys.readouterr().err
