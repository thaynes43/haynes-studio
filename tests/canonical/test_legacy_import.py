"""The legacy import: r4 reproduces the contract's story, r1 to r3 import with story
378's frame totals, a second import returns the same IDs, and nothing is lost."""

from __future__ import annotations

import json
import re

import pytest

from haynes_studio.canonical import (
    LegacyImport,
    MethodCapabilities,
    Production,
    Story,
    StoryTiming,
    to_document,
    validate_legacy_import,
    validate_story,
)
from haynes_studio.canonical.ids import Minter
from haynes_studio.canonical.legacy_import import import_manifest
from haynes_studio.canonical.methods import MATRIX
from haynes_studio.canonical.model import Principal
from haynes_studio.errors import ContractError
from haynes_studio.legacy import load, load_speech
from haynes_studio.legacy.manifest import from_document
from tests.canonical.fixtures import (
    NOW,
    OPERATOR,
    REVISIONS,
    example,
    manifest_path,
    speech_path,
)

ID = re.compile(r"^(asv|cue|nte)_[0-7][0-9A-HJKMNP-TV-Z]{25}$")
# Fields of the contract's story example that a manifest and its speech.json cannot
# give (the PR lists each with its reason).
NOT_DERIVABLE = (
    re.compile(r"^/boards/\d+/title$"),  # hand-written board titles; legacy shots have none
    re.compile(r"^/boards/\d+/photo/current_version_id$"),  # E0 keyframes.json photos
    re.compile(r"^/boards/\d+/derived/photo_state$"),  # follows from the photo above
    re.compile(r"^/boards/\d+/seeds/.+$"),  # E0 clip-records-s2v.jsonl seeds
)


def run_import(revision: int, existing=None, **kwargs):
    operator = Principal.from_document(OPERATOR)
    label = f"titles/the-winter-menu/{REVISIONS[revision][0]}"
    return import_manifest(load(manifest_path(revision)), load_speech(speech_path(revision)),
                           manifest_label=label, operator=operator, now=NOW,
                           existing=existing, **kwargs)


def diff(got, want, path="", out=None):
    """(path, got, want) for every leaf that differs."""
    out = [] if out is None else out
    if isinstance(got, dict) and isinstance(want, dict):
        for key in sorted(set(got) | set(want)):
            diff(got.get(key, "<absent>"), want.get(key, "<absent>"), f"{path}/{key}", out)
    elif isinstance(got, list) and isinstance(want, list) and len(got) == len(want):
        for i, (a, b) in enumerate(zip(got, want)):
            diff(a, b, f"{path}/{i}", out)
    elif got != want:
        out.append((path, got, want))
    return out


@pytest.fixture(scope="module")
def r4():
    return run_import(4, existing=example("valid/legacy-import-map.json"))


def test_r4_with_the_contract_map_reproduces_the_contract_story(r4):
    want = example("valid/story-winter-menu-r4.json")
    renaming: dict[str, str] = {}
    unexplained = []
    for path, got, expected in diff(r4.story, want):
        if any(pattern.match(path) for pattern in NOT_DERIVABLE):
            continue
        if isinstance(got, str) and isinstance(expected, str) and ID.match(got) \
                and ID.match(expected) and got[:3] == expected[:3]:
            assert renaming.setdefault(got, expected) == expected, path
            continue
        unexplained.append((path, got, expected))
    assert unexplained == []
    # IDs the contract map does not record were minted: one new ID per contract ID.
    assert len(set(renaming.values())) == len(renaming)
    assert {key[:3] for key in renaming} == {"asv", "cue", "nte"}


def test_r4_reuses_every_id_the_contract_map_records(r4):
    contract = example("valid/legacy-import-map.json")
    assert r4.reused == 2 + 9 + 13  # production, story, boards, lines
    got = {(b["legacy_shot"], b["board_id"], tuple((l["legacy_k"], l["line_id"]) for l in b["lines"]))
           for b in r4.import_map["boards_from_r4"]}
    want = {(b["legacy_shot"], b["board_id"], tuple((l["legacy_k"], l["line_id"]) for l in b["lines"]))
            for b in contract["boards_from_r4"]}
    assert got == want
    entry = next(r for r in r4.import_map["revisions"] if r["legacy_revision"] == 4)
    original = next(r for r in contract["revisions"] if r["legacy_revision"] == 4)
    assert {k: v for k, v in entry.items() if k != "speech_sha256"} == original
    assert [r["legacy_revision"] for r in r4.import_map["revisions"]] == [1, 2, 3, 4]
    for field in ("e0_deliveries", "imported_run_notes", "hidden_candidates", "not_imported"):
        assert r4.import_map[field] == contract[field]


def test_r4_keeps_every_line_cue_note_and_layout(r4):
    manifest = load(manifest_path(4))
    boards = r4.story["boards"]
    assert [b["origin"]["legacy_shot"] for b in boards] == [shot.id for shot in manifest.shots]
    for board, shot in zip(boards, manifest.shots):
        assert [(l["speaker"], l["text"]) for l in board["lines"]] == \
            [(line.doll, line.text) for line in shot.lines]
        assert len(board["cues"]) == len(shot.sfx) + len(shot.moves) + (shot.camera is not None)
        assert [n["text"] for n in board["notes"]] == ([shot.note] if shot.note else [])
        assert board["layout"]["preset"] == shot.layout
        assert [c["slot"] for c in board["cast"]] == [slot for slot, _ in shot.dolls]
    assert set(r4.story["layouts"]) == set(manifest.layouts)


@pytest.mark.parametrize("revision", [1, 2, 3, 4])
def test_each_revision_imports_with_story_378s_frames(revision):
    result = run_import(revision)
    frames = REVISIONS[revision][2]
    assert result.story["derived"]["frames"] == frames
    assert result.story["derived"]["untimed_boards"] == 0
    assert validate_story(result.story, facts=result.facts) == []
    assert validate_legacy_import(result.import_map) == []
    assert result.import_map["revisions"][0]["frames"] == frames
    assert result.reused == 0


@pytest.mark.parametrize("revision", [1, 4])
def test_a_second_import_returns_the_same_ids(revision):
    first = run_import(revision)
    again = run_import(revision, existing=json.loads(json.dumps(first.import_map)))
    assert again.minted == 0 and again.reused == first.minted
    assert again.story == first.story
    assert again.import_map == first.import_map


def test_the_contract_map_round_trips_through_a_second_import(r4):
    again = run_import(4, existing=r4.import_map)
    assert again.minted == 0
    assert again.story == r4.story


def test_a_map_that_does_not_fit_is_refused():
    contract = example("valid/legacy-import-map.json")
    with pytest.raises(ContractError) as error:
        run_import(3, existing=contract)
    assert [(v.rule, v.path) for v in error.value.violations] == [
        ("legacy.import_map_mismatch", "/draft_from_revision")]
    changed = json.loads(json.dumps(contract))
    changed["revisions"][3]["manifest_sha256"] = "0" * 64
    with pytest.raises(ContractError) as error:
        run_import(4, existing=changed)
    assert [v.path for v in error.value.violations] == ["/revisions/3/manifest_sha256"]
    with pytest.raises(ContractError) as error:
        run_import(4, existing=contract, production_id="prd_01M79V9FC00000000000000002")
    assert [v.path for v in error.value.violations] == ["/production_id"]
    broken = dict(contract, story_id="story-1")
    with pytest.raises(ContractError) as error:
        run_import(4, existing=broken)
    assert [v.rule for v in error.value.violations] == ["id.malformed"]


def test_fresh_ids_are_minted_in_order_and_production_can_be_given():
    clock = iter(range(1_700_000_000_000, 1_700_000_001_000)).__next__
    result = run_import(1, minter=Minter(clock=clock, random_bits=lambda: 0),
                        production_id="prd_01M79V9FC00000000000000009")
    assert result.story["production_id"] == "prd_01M79V9FC00000000000000009"
    board_ids = result.story["board_order"]
    assert board_ids == sorted(board_ids)


def test_operator_must_be_human():
    with pytest.raises(ValueError):
        import_manifest(load(manifest_path(1)), load_speech(speech_path(1)), manifest_label="x",
                        operator=Principal(kind="agent", key_id="key_01M79V9FC00000000000000001"),
                        now=NOW)


def test_the_manifest_must_come_from_its_file():
    """The map records the manifest's SHA-256, so a manifest built from a document (no
    bytes) is refused up front rather than producing a map that breaks its schema."""
    raw = json.loads(manifest_path(4).read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="loaded from its file"):
        import_manifest(from_document(raw), load_speech(speech_path(4)), manifest_label="x",
                        operator=Principal.from_document(OPERATOR), now=NOW)


# Round trips -------------------------------------------------------------------------


@pytest.mark.parametrize("name,model", [
    ("valid/story-winter-menu-r4.json", Story), ("valid/production.json", Production),
    ("valid/story-timing-summary.json", StoryTiming),
    ("valid/method-capabilities.json", MethodCapabilities),
])
def test_examples_round_trip_through_the_models(name, model):
    document = example(name)
    assert to_document(model.from_document(document)) == document


def test_imports_round_trip_through_json_and_the_models(r4):
    text = json.dumps({"story": r4.story, "map": r4.import_map})
    back = json.loads(text)
    assert to_document(Story.from_document(back["story"])) == r4.story
    assert LegacyImport.from_document(back["map"]).to_json() == r4.import_map
    assert LegacyImport.from_document(back["map"]).boards_field == "boards_from_r4"


def test_the_method_matrix_matches_the_contract_example():
    cells = example("valid/method-capabilities.json")["cells"]
    assert {(c["layer"], c["motion"]): c["status"] for c in cells} == dict(MATRIX)


# Review fixes of story 404 -------------------------------------------------------------


def test_a_changed_speech_file_is_refused_by_the_map(tmp_path):
    """A map that recorded the speech.json bytes refuses other takes, so a voice version
    ID never names two sets of takes."""
    first = run_import(4)
    speech = json.loads(speech_path(4).read_text(encoding="utf-8"))
    speech["lines"][0]["duration_s"] = round(speech["lines"][0]["duration_s"] + 2.0, 3)
    changed = tmp_path / "speech.json"
    changed.write_text(json.dumps(speech), encoding="utf-8")
    with pytest.raises(ContractError) as error:
        import_manifest(load(manifest_path(4)), load_speech(changed), manifest_label="x",
                        operator=Principal.from_document(OPERATOR), now=NOW,
                        existing=first.import_map)
    assert [(v.rule, v.path) for v in error.value.violations] == [
        ("legacy.import_map_mismatch", "/revisions/0/speech_sha256")]
    assert run_import(4, existing=first.import_map).minted == 0  # the recorded bytes still fit


@pytest.mark.parametrize("field,value", [("source_key", "legacy:another-title"),
                                         ("media_kind", "video")])
def test_a_map_from_another_title_or_media_kind_is_refused(field, value):
    other = dict(example("valid/legacy-import-map.json"), **{field: value})
    with pytest.raises(ContractError) as error:
        run_import(4, existing=other)
    assert [(v.rule, v.path) for v in error.value.violations] == [
        ("legacy.import_map_mismatch", f"/{field}")]


def test_a_map_with_repeated_entries_is_refused():
    repeated = example("valid/legacy-import-map.json")
    repeated["boards_from_r4"].append(dict(repeated["boards_from_r4"][0],
                                           board_id="brd_01M79V9FC000000000000000ZZ", lines=[]))
    with pytest.raises(ContractError) as error:
        run_import(4, existing=repeated)
    assert [(v.rule, v.path) for v in error.value.violations] == [
        ("ref.duplicate", "/boards_from_r4/9/legacy_shot")]


@pytest.mark.parametrize("existing", [None, [], {}, "map"])
def test_a_map_that_is_not_an_import_map_is_refused(existing):
    if existing is None:
        assert run_import(1).reused == 0  # no map: every ID is minted
        return
    with pytest.raises(ContractError) as error:
        run_import(4, existing=existing)
    assert {v.rule for v in error.value.violations} == {"schema.invalid"}


def test_a_map_nested_too_deeply_is_refused_without_recursion():
    deep: object = 1
    for _ in range(3000):
        deep = {"a": deep}
    import_map = dict(example("valid/legacy-import-map.json"), hidden_candidates=[deep])
    with pytest.raises(ContractError) as error:
        run_import(4, existing=import_map)
    assert [(v.rule, v.path) for v in error.value.violations] == [("schema.invalid", "")]


def test_a_given_production_counts_as_given_not_reused():
    result = run_import(1, production_id="prd_01M79V9FC00000000000000009")
    assert (result.given, result.reused) == (1, 0)
    assert result.minted > 0
    assert run_import(4, existing=example("valid/legacy-import-map.json")).given == 0


def test_optional_story_fields_round_trip_when_absent(tmp_path):
    story = example("valid/story-winter-menu-r4.json")
    del story["set"]["note"]
    story["checks"] = {}
    assert to_document(Story.from_document(story)) == story
    raw = json.loads(manifest_path(4).read_text(encoding="utf-8"))
    del raw["set"]["note"], raw["asr_tolerances"], raw["asr_tolerances_note"]
    plain = tmp_path / "manifest-r4.json"
    plain.write_text(json.dumps(raw), encoding="utf-8")
    imported = import_manifest(load(plain), load_speech(speech_path(4)), manifest_label="x",
                               operator=Principal.from_document(OPERATOR), now=NOW).story
    assert "note" not in imported["set"] and imported["checks"] == {}
    assert to_document(Story.from_document(imported)) == imported
