"""``studio legacy import``: summary, JSON, create-only output, ID reuse from a map, and
no legacy file written."""

from __future__ import annotations

import hashlib
import io
import json
import os

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


# Review fixes of story 404 -------------------------------------------------------------


def _deep(depth: int) -> str:
    return "{\"a\":" * depth + "1" + "}" * depth


def test_a_map_that_is_not_an_object_is_a_rule_failure(tmp_path):
    for text, kind in (("null", "null"), ("[]", "list"), ("5", "int")):
        bad = tmp_path / f"map-{kind}.json"
        bad.write_text(text, encoding="utf-8")
        code, out, err = run(*import_args(4, "--map", str(bad)))
        assert (code, out) == (1, "")
        assert err.strip() == (f"{bad}: rule schema.invalid at (root): an import map must be a "
                               f"JSON object, not {kind}")


def test_a_deeply_nested_input_is_a_one_line_usage_error(tmp_path):
    contract = json.loads(IMPORT_MAP.read_text(encoding="utf-8"))
    contract["hidden_candidates"] = ["@@DEEP@@"]
    deep_map = tmp_path / "map.json"
    deep_map.write_text(json.dumps(contract).replace('"@@DEEP@@"', _deep(700)), encoding="utf-8")
    code, out, err = run(*import_args(4, "--map", str(deep_map)))
    assert (code, out) == (2, "")
    assert err == f"studio: {deep_map}: nested deeper than 64 levels\n"

    raw = json.loads(manifest_path(4).read_text(encoding="utf-8"))
    raw["provenance"] = "@@DEEP@@"
    deep_manifest = tmp_path / "manifest-r4.json"
    deep_manifest.write_text(json.dumps(raw).replace('"@@DEEP@@"', _deep(700)), encoding="utf-8")
    code, _, err = run("legacy", "import", str(deep_manifest), "--speech", str(speech_path(4)),
                       *OPERATOR_ARGS)
    assert (code, err) == (2, f"studio: {deep_manifest}: nested deeper than 64 levels\n")
    code, _, err = run("legacy", "validate", str(deep_manifest))  # story 378's commands too
    assert (code, err) == (2, f"studio: {deep_manifest}: nested deeper than 64 levels\n")


@pytest.mark.parametrize("iss,sub,flag", [
    ("", OPERATOR["sub"], "--operator-iss"),
    ("issuer", OPERATOR["sub"], "--operator-iss"),
    ("ftp://issuer.example.invalid/", OPERATOR["sub"], "--operator-iss"),
    ("https:///no-host", OPERATOR["sub"], "--operator-iss"),
    ("https://issuer.example.invalid/ x", OPERATOR["sub"], "--operator-iss"),
    (OPERATOR["iss"], "", "--operator-sub"),
    (OPERATOR["iss"], "tom smith", "--operator-sub"),
    (OPERATOR["iss"], "subject\n", "--operator-sub"),
    (OPERATOR["iss"], "s" * 256, "--operator-sub"),
])
def test_a_malformed_operator_is_a_usage_error(iss, sub, flag):
    args = ["legacy", "import", str(manifest_path(4)), "--speech", str(speech_path(4)),
            "--operator-iss", iss, "--operator-sub", sub]
    code, out, err = run(*args)
    assert (code, out) == (2, "")
    assert err.startswith(f"studio: {flag} ") and len(err.splitlines()) == 1


def test_a_production_with_a_trailing_newline_is_a_usage_error():
    code, _, err = run(*import_args(4, "--production", "prd_01M79V9FC00000000000000009\n"))
    assert code == 2 and "is not a prd_ ID" in err


def test_unparseable_legacy_files_are_rule_failures_and_missing_ones_usage(tmp_path):
    bad = tmp_path / "manifest.json"
    bad.write_text("{", encoding="utf-8")
    code, _, err = run("legacy", "import", str(bad), "--speech", str(speech_path(4)),
                       *OPERATOR_ARGS)
    assert code == 1 and err.startswith(f"{bad}: rule legacy.invalid at (root): not JSON")
    code, _, err = run("legacy", "import", str(manifest_path(4)), "--speech", str(bad),
                       *OPERATOR_ARGS)
    assert code == 1 and err.startswith(f"{bad}: rule legacy.invalid at (root): not JSON")
    missing = tmp_path / "missing.json"
    code, _, err = run("legacy", "import", str(missing), "--speech", str(speech_path(4)),
                       *OPERATOR_ARGS)
    assert code == 2 and err.startswith(f"studio: cannot read {missing}")


def test_out_checks_both_targets_before_writing(tmp_path):
    folder = tmp_path / "out"
    folder.mkdir()
    os.symlink(tmp_path / "nowhere.json", folder / "legacy-import.json")  # a dangling link
    code, _, err = run(*import_args(4, "--out", str(folder)))
    assert code == 2 and "will not overwrite" in err and "legacy-import.json" in err
    assert not (folder / "story.json").exists()


def test_a_failed_write_names_both_files_and_deletes_nothing(tmp_path, monkeypatch):
    real = cli._create

    def create(path, document):
        if path.name == "legacy-import.json":
            raise PermissionError(13, "Permission denied", str(path))
        real(path, document)

    monkeypatch.setattr(cli, "_create", create)
    folder = tmp_path / "out"
    code, out, err = run(*import_args(4, "--out", str(folder)))
    assert (code, out) == (2, "")
    assert err == (f"studio: cannot write {folder / 'legacy-import.json'}: Permission denied; "
                   f"{folder / 'story.json'} was already written and is left as it is "
                   "(choose a new --out folder)\n")
    assert json.loads((folder / "story.json").read_text())["schema"] == "studio.story/v1"


def test_a_given_production_is_reported_as_given():
    code, out, _ = run(*import_args(1, "--production", "prd_01M79V9FC00000000000000009"))
    assert code == 0
    assert "IDs: 0 from the map, " in out and " minted, 1 given" in out


def test_the_manifest_label_is_never_an_absolute_path(tmp_path, monkeypatch):
    outside = tmp_path / "manifest-r4.json"
    outside.write_bytes(manifest_path(4).read_bytes())
    code, out, _ = run("legacy", "import", str(outside), "--speech", str(speech_path(4)),
                       *OPERATOR_ARGS, "--json")
    assert code == 0
    assert json.loads(out)["story"]["origin"]["manifest"] == "manifest-r4.json"
    elsewhere = tmp_path / "work"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # the repository path does not depend on the working folder
    code, out, _ = run(*import_args(4, "--json"))
    assert code == 0
    assert json.loads(out)["story"]["origin"]["manifest"] == "titles/the-winter-menu/manifest-r4.json"
