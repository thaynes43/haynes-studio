import hashlib
import json
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

from haynes_studio import drafting_benchmark as benchmark
from haynes_studio.db.drafts import _check_board_write
from haynes_studio.db.problems import DraftProtected
from haynes_studio.jsonio import read_json

FIXTURES = Path(__file__).with_name("fixtures")
CASES = ("chorus", "two-sets", "focal-prop", "dense-dialogue", "timed-button")
REVISION_CASES = {"two-sets", "dense-dialogue"}


@pytest.fixture
def corpus():
    return benchmark.Corpus.load(benchmark.CORPUS)


def inputs(case_id, *, draft=None, evidence=None):
    data = (FIXTURES / f"{draft or case_id}.draft.json").read_bytes()
    record = read_json(FIXTURES / f"{evidence or case_id}.evidence.json").document
    if draft:
        # The negative drafts isolate scorer rules with synthetic write evidence.
        record["draft_sha256"] = hashlib.sha256(data).hexdigest()
    return data, record


@pytest.mark.parametrize("case_id", CASES)
def test_handwritten_fixture_passes(corpus, case_id):
    result = benchmark.score(corpus, case_id, *inputs(case_id))
    assert result["verdict"] == "pass"
    expected = dict.fromkeys(benchmark.CHECKS, "pass")
    if case_id not in REVISION_CASES:
        expected["edit_preservation"] = "not_applicable"
    assert {name: check["status"] for name, check in result["checks"].items()} == expected


@pytest.mark.parametrize(("case_id", "draft", "evidence", "family", "code", "path"), [
    ("focal-prop", "fail-board-schema", None, "board_schema", "schema.invalid", "/boards/0/fields/notes/0/text"),
    ("focal-prop", "fail-method", None, "method", "method.unavailable", "/boards/0/fields/method"),
    ("timed-button", "fail-timing", None, "timing", "time.first_line_gap", "/boards/0/fields/lines/0/gap_before_ms"),
    ("focal-prop", "fail-references", None, "references", "asset.scope_mismatch", "/boards/0/fields/cast/0/asset_version_id"),
    ("focal-prop", "fail-brief", None, "brief_invariants", "benchmark.brief_invariant", "/boards/1/fields/photo_inputs"),
    ("focal-prop", None, "fail-scope", "write_scope", "auth.forbidden", "/writes/0/production_id"),
    ("two-sets", None, "fail-preservation", "edit_preservation", "benchmark.protected_board_changed", None),
])
def test_negative_fixtures_fail_one_family(corpus, case_id, draft, evidence, family, code, path):
    data, record = inputs(case_id, draft=draft, evidence=evidence)
    result = benchmark.score(corpus, case_id, data, record)
    assert result["verdict"] == "fail"
    failed = {name: check["violations"] for name, check in result["checks"].items()
              if check["status"] not in {"pass", "not_applicable"}}
    if path is None:
        board_id = corpus.manifest["cases"][case_id]["protected_boards"][0]
        good = inputs(case_id)[1]["protected_boards"][board_id]
        changed = record["protected_boards"][board_id]
        assert changed.encode("utf-8") == good.encode("utf-8") + b" "
        assert json.loads(changed) == json.loads(good)
        path = f"/protected_boards/{board_id}"
    assert failed == {family: [{"code": code, "path": path}]}


@pytest.mark.parametrize("case_id", sorted(REVISION_CASES))
def test_revision_starts_with_person_edited_and_unstamped_boards(corpus, case_id):
    case = corpus.manifest["cases"][case_id]
    boards = corpus.json(case["story"])["boards"]
    agent = {"kind": "agent", "key_id": corpus.manifest["agent_key_id"]}
    for board in boards:
        if board["id"] in case["protected_boards"]:
            with pytest.raises(DraftProtected):
                _check_board_write(board, agent, acknowledgment=None)
        else:
            _check_board_write(board, agent, acknowledgment=None)
    assert any("draft_application" not in board for board in boards)
    assert any(board.get("draft_application", {}).get("person_edit") == "content" for board in boards)


def test_unbound_or_missing_write_evidence_cannot_pass(corpus):
    data, evidence = inputs("focal-prop")
    result = benchmark.score(corpus, "focal-prop", data + b" ", evidence)
    assert result["checks"]["write_scope"]["violations"] == [
        {"code": "benchmark.write_evidence_unbound", "path": "/draft_sha256"},
    ]
    evidence["writes"] = []
    result = benchmark.score(corpus, "focal-prop", data, evidence)
    assert result["checks"]["write_scope"]["violations"] == [
        {"code": "benchmark.write_coverage", "path": "/writes"},
    ]


def test_revision_observation_must_target_the_bound_board(corpus):
    data, evidence = inputs("dense-dialogue")
    evidence["writes"][0]["board_id"] = corpus.manifest["cases"]["dense-dialogue"]["protected_boards"][0]
    result = benchmark.score(corpus, "dense-dialogue", data, evidence)
    assert result["checks"]["write_scope"]["violations"] == [
        {"code": "benchmark.write_target", "path": "/writes/0"},
    ]
    assert result["checks"]["edit_preservation"]["status"] == "pass"


def test_tampered_brief_changes_version_and_score_refuses(corpus, tmp_path, capsys):
    directory = tmp_path / "corpus"
    shutil.copytree(benchmark.CORPUS, directory)
    name = corpus.manifest["cases"]["chorus"]["brief"]
    brief = directory / name
    brief.write_bytes(brief.read_bytes() + b" ")
    hashes = {**corpus.manifest["files"], name: hashlib.sha256(brief.read_bytes()).hexdigest()}
    changed = benchmark.corpus_version(corpus.manifest, hashes)
    assert changed != corpus.manifest["version"]
    with pytest.raises(SystemExit) as stopped:
        benchmark.main(["--corpus", str(directory), "score", str(FIXTURES / "chorus.draft.json"),
                        "--case", "chorus"])
    assert stopped.value.code == 2
    captured = capsys.readouterr()
    assert "Corpus seal mismatch" in captured.err
    assert changed in captured.err
    assert captured.out == ""


def test_cli_scores_and_summarises_offline(corpus, tmp_path, capsys, monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("The offline scorer attempted a network call or spawned a process")

    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(subprocess, "Popen", denied)
    result_files = []
    labels = {"schema": benchmark.LABELS, "reviewer": "Tom",
              "corpus_version": corpus.manifest["version"], "cases": {}}
    synthetic_labels = ["usable_as_is"] * 2 + ["usable_with_light_edits"] * 2 + ["not_usable"]
    for case_id, label in zip(CASES, synthetic_labels, strict=True):
        assert benchmark.main(["score", str(FIXTURES / f"{case_id}.draft.json"), "--case", case_id,
                               "--evidence", str(FIXTURES / f"{case_id}.evidence.json")]) == 0
        output = capsys.readouterr().out
        result_path = tmp_path / f"{case_id}.result.json"
        result_path.write_text(output)
        result_files.append(str(result_path))
        labels["cases"][case_id] = {"label": label, "draft_sha256": json.loads(output)["draft_sha256"]}
    assert benchmark.main(["summarise", *result_files]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["quality"] == {"status": "pending: Tom's labels"}
    assert "usable_with_light_edits" not in output
    assert json.loads(output)["structural_and_safety_all_pass"] is True

    labelled = tmp_path / "synthetic-labels.json"
    labelled.write_text(json.dumps(labels))
    assert benchmark.main(["summarise", *result_files, "--labels", str(labelled)]) == 0
    assert json.loads(capsys.readouterr().out)["quality"] == {
        "usable_with_light_edits": 4, "of": 5, "meets_minimum": True,
    }
    labels["cases"]["chorus"]["draft_sha256"] = "0" * 64
    labelled.write_text(json.dumps(labels))
    with pytest.raises(SystemExit) as stopped:
        benchmark.main(["summarise", *result_files, "--labels", str(labelled)])
    assert stopped.value.code == 2
    assert "Invalid label or draft hash for chorus" in capsys.readouterr().err
