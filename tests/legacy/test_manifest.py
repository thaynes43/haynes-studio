"""legacy.manifest/v1: detection, the shipped schema, validation rules and the typed,
read-only model of The Winter Menu r1 to r4."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
from importlib.resources import files

import pytest
from jsonschema import Draft202012Validator

from haynes_studio.errors import ContractError
from haynes_studio.jsonio import read_json
from haynes_studio.legacy import manifest as lm
from tests.support.policy import REPO_ROOT

TITLE = REPO_ROOT / "titles" / "the-winter-menu"
REVISIONS = {1: "manifest.json", 2: "manifest-r2.json", 3: "manifest-r3.json",
             4: "manifest-r4.json"}
IMPORT_MAP = REPO_ROOT / "docs" / "contracts" / "examples" / "valid" / "legacy-import-map.json"
INVALID_EXAMPLE = (REPO_ROOT / "docs" / "contracts" / "examples" / "invalid"
                   / "legacy-duration-with-lines.json")


def fixture(revision: int):
    return TITLE / REVISIONS[revision]


# A small synthetic manifest: one spoken shot and one silent shot with a sound.
BASE = {
    "title": "Example",
    "job": "example-r1",
    "frame": {"width": 1080, "height": 1920, "fps": 24},
    "sfx": {"crow": {"file": "sfx/crow.wav", "trim": [0.45, 1.6], "gain_db": -26}},
    "shots": [
        {"id": 1, "layout": "single", "dolls": {"a": "cutouts/a.png"},
         "line": {"doll": "a", "text": "Example line.", "start": 0.5}, "tail": 0.7},
        {"id": 2, "layout": "single", "dolls": {"b": "cutouts/b.png"}, "duration": 2.0,
         "sfx": [{"cue": "crow", "at": 0.5}]},
    ],
}


def base():
    return copy.deepcopy(BASE)


def rules(document):
    return {(v.rule, v.path) for v in lm.validate(document)}


# Fixtures ---------------------------------------------------------------------------


@pytest.mark.parametrize("revision", REVISIONS)
def test_winter_menu_manifest_validates_and_loads(revision):
    document = read_json(fixture(revision)).document
    assert lm.detect(document) == "legacy.manifest/v1"
    assert lm.validate(document) == []
    manifest = lm.load(fixture(revision))
    assert manifest.revision == revision
    assert manifest.revision_field_present is (revision != 1)  # r1 has no revision field
    assert manifest.schema == "legacy.manifest/v1"
    assert manifest.frame == lm.Frame(1080, 1920, 24)


def test_fixture_hashes_and_shot_counts_agree_with_the_contract_import_map():
    import_map = json.loads(IMPORT_MAP.read_text(encoding="utf-8"))
    for entry in import_map["revisions"]:
        manifest = lm.load(REPO_ROOT / entry["manifest"])
        assert manifest.revision == entry["legacy_revision"]
        assert manifest.revision_field_present is entry["revision_field_present"]
        assert manifest.sha256 == entry["manifest_sha256"]
        assert manifest.job == entry["job"]
        assert len(manifest.shots) == entry["shots"]


def test_loading_never_changes_the_file():
    path = fixture(4)
    before = (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
    lm.load(path)
    assert (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) == before


def test_r4_multi_line_shot_normalizes_to_lines():
    shot = lm.load(fixture(4)).shot(8)
    assert shot.spoken and shot.lines_field == "lines"
    assert shot.lead_ms == 1900 and shot.tail_ms == 800 and shot.duration_ms is None
    assert [line.doll for line in shot.lines] == ["b", "a", "c", "d", "b", "b"]
    assert [line.gap_ms for line in shot.lines] == [None, 300, 200, 250, 700, 900]
    assert not any(line.gap_defaulted for line in shot.lines)
    assert [line.k for line in shot.lines] == [0, 1, 2, 3, 4, 5]
    crow, gavel = shot.sfx
    assert crow.anchor == lm.Anchor(at_ms=750, after_line=None, offset_ms=None)
    assert gavel.anchor == lm.Anchor(at_ms=None, after_line=4, offset_ms=50)
    assert [d for d, _ in shot.dolls] == ["a", "c", "d", "b"]  # draw order kept
    assert shot.moves[4].anchor == lm.Anchor(None, 4, 80) and shot.moves[4].dur_ms == 0


def test_r4_single_line_and_silent_shots():
    manifest = lm.load(fixture(4))
    first = manifest.shot(1)
    assert first.lines_field == "line" and len(first.lines) == 1
    assert first.lines[0].gap_ms is None and first.lead_ms == 500 and first.tail_ms == 700
    silent = manifest.shot(7)
    assert not silent.spoken and silent.duration_ms == 1900 and silent.tail_ms is None
    assert silent.lead_ms is None and silent.lines_field is None
    assert silent.foreground is False and first.foreground is None  # absent stays None
    assert silent.camera == lm.Camera(zoom=(1.0, 1.2), over_ms=350, center=(400, 620))
    gavel = manifest.sound("gavel")
    assert gavel.trim_ms == (1300, 1950) and gavel.level_rms_dbfs == -20
    assert [bed.name for bed in manifest.beds] == ["fire"]
    assert [member.slot for member in manifest.cast] == ["a", "b", "c", "d"]


def test_r1_reads_with_its_two_absences():
    manifest = lm.load(fixture(1))
    assert manifest.revision == 1 and not manifest.revision_field_present
    assert manifest.beds == () and manifest.motion is None and manifest.revision_note is None
    assert manifest.shot(5).duration_ms == 3000 and manifest.shot(5).sfx[0].anchor.at_ms == 1100


def test_model_is_read_only():
    manifest = lm.load(fixture(4))
    with pytest.raises(dataclasses.FrozenInstanceError):
        manifest.title = "x"
    with pytest.raises(dataclasses.FrozenInstanceError):
        manifest.shots[0].lines[0].text = "x"
    with pytest.raises(TypeError):
        manifest.layouts["single"] = {}
    with pytest.raises(TypeError):
        manifest.set["fire"]["seed"] = 1
    assert isinstance(manifest.set["foreground_edge"], tuple)


# Normalization ----------------------------------------------------------------------


def test_a_later_line_without_gap_gets_the_legacy_default():
    document = base()
    shot = document["shots"][0]
    del shot["line"]
    shot["lines"] = [{"doll": "a", "text": "One.", "start": 0.4},
                     {"doll": "a", "text": "Two."},
                     {"doll": "a", "text": "Three.", "gap": 0.2}]
    lines = lm.from_document(document).shots[0].lines
    assert [(line.gap_ms, line.gap_defaulted) for line in lines] == [
        (None, False), (300, True), (200, False)]


def test_line_and_a_one_item_lines_load_the_same():
    single = lm.from_document(base()).shots[0]
    document = base()
    document["shots"][0]["lines"] = [document["shots"][0].pop("line")]
    listed = lm.from_document(document).shots[0]
    assert dataclasses.replace(listed, lines_field="line") == single


def test_missing_revision_reads_as_one_and_an_explicit_one_is_marked():
    assert lm.from_document(base()).revision == 1
    document = base()
    document["revision"] = 1
    manifest = lm.from_document(document)
    assert manifest.revision == 1 and manifest.revision_field_present


# Rules ------------------------------------------------------------------------------


def _set(path, value):
    def mutate(document):
        target = document
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = value
    return mutate


def _delete(path):
    def mutate(document):
        target = document
        for part in path[:-1]:
            target = target[part]
        del target[path[-1]]
    return mutate


def _both(*mutations):
    def mutate(document):
        for mutation in mutations:
            mutation(document)
    return mutate


CASES = {
    "unknown top field": (_set(["colour"], "red"), {("schema.unknown_field", "/colour")}),
    "unknown shot field": (_set(["shots", 0, "colour"], 1),
                           {("schema.unknown_field", "/shots/0/colour")}),
    "unknown line field": (_set(["shots", 0, "line", "voice"], "x"),
                           {("schema.unknown_field", "/shots/0/line/voice")}),
    "duration with line": (_set(["shots", 0, "duration"], 3.0),
                           {("legacy.duration_with_lines", "/shots/0")}),
    "duration with lines": (
        _both(_delete(["shots", 0, "line"]),
              _set(["shots", 0, "lines"], [{"doll": "a", "text": "x", "start": 0.5}]),
              _set(["shots", 0, "duration"], 3.0)),
        {("legacy.duration_with_lines", "/shots/0")}),
    "line and lines": (_set(["shots", 0, "lines"], [{"doll": "a", "text": "x", "start": 0.5}]),
                       {("legacy.invalid", "/shots/0/lines")}),
    "first line gap": (_set(["shots", 0, "line", "gap"], 0.3),
                       {("time.first_line_gap", "/shots/0/line/gap")}),
    "later line start": (
        _both(_delete(["shots", 0, "line"]),
              _set(["shots", 0, "lines"], [{"doll": "a", "text": "x", "start": 0.5},
                                           {"doll": "a", "text": "y", "start": 1.0}])),
        {("legacy.invalid", "/shots/0/lines/1/start")}),
    "tail too short": (_set(["shots", 0, "tail"], 0.2), {("time.tail_too_short", "/shots/0/tail")}),
    "negative start": (_set(["shots", 0, "line", "start"], -0.1),
                       {("time.negative", "/shots/0/line/start")}),
    "negative cue time": (_set(["shots", 1, "sfx", 0, "at"], -1),
                          {("time.negative", "/shots/1/sfx/0/at")}),
    "sub-millisecond tail": (_set(["shots", 0, "tail"], 0.7005),
                             {("time.not_integer_ms", "/shots/0/tail")}),
    "sub-millisecond trim": (_set(["sfx", "crow", "trim"], [0.4501, 1.6]),
                             {("time.not_integer_ms", "/sfx/crow/trim/0")}),
    "spoken shot without tail": (_delete(["shots", 0, "tail"]), {("legacy.invalid", "/shots/0")}),
    "silent shot with tail": (_set(["shots", 1, "tail"], 0.7),
                              {("legacy.invalid", "/shots/1/tail")}),
    "shot without lines or duration": (_delete(["shots", 1, "duration"]),
                                       {("legacy.invalid", "/shots/1")}),
    "sound not in the table": (_set(["shots", 1, "sfx", 0, "cue"], "owl"),
                               {("legacy.reference", "/shots/1/sfx/0/cue")}),
    "no sfx table": (_delete(["sfx"]), {("legacy.reference", "/shots/1/sfx/0/cue")}),
    "after_line out of range": (
        _set(["shots", 0, "sfx"], [{"cue": "crow", "after_line": 1, "offset": 0.05}]),
        {("legacy.reference", "/shots/0/sfx/0/after_line")}),
    "after_line on a silent shot": (
        _set(["shots", 1, "sfx"], [{"cue": "crow", "after_line": 0, "offset": 0.0}]),
        {("legacy.reference", "/shots/1/sfx/0/after_line")}),
    "after_line without offset": (_set(["shots", 0, "sfx"], [{"cue": "crow", "after_line": 0}]),
                                  {("legacy.invalid", "/shots/0/sfx/0")}),
    "two anchors": (_set(["shots", 1, "sfx", 0, "after_line"], 0),
                    {("legacy.invalid", "/shots/1/sfx/0"),
                     ("legacy.reference", "/shots/1/sfx/0/after_line")}),
    "move without anchor": (_set(["shots", 0, "moves"], [{"doll": "a", "dx": 4}]),
                            {("legacy.invalid", "/shots/0/moves/0")}),
    "duplicate shot id": (_set(["shots", 1, "id"], 1), {("legacy.reference", "/shots/1/id")}),
    "fps not 24": (_set(["frame", "fps"], 25), {("legacy.invalid", "/frame/fps")}),
    "bad cast slot": (_set(["cast"], {"A": {"name": "x", "voice": "af_heart"}}),
                      {("legacy.invalid", "/cast/A")}),
    "reversed trim": (_set(["sfx", "crow", "trim"], [1.6, 0.45]),
                      {("legacy.invalid", "/sfx/crow/trim")}),
    "revision zero": (_set(["revision"], 0), {("legacy.invalid", "/revision")}),
    "string shot": (_set(["shots", 1], "shot"), {("legacy.invalid", "/shots/1")}),
    "missing title": (_delete(["title"]), {("legacy.invalid", "")}),
    "empty shots": (_set(["shots"], []), {("legacy.invalid", "/shots")}),
    "text not a string": (_set(["shots", 0, "line", "text"], 3),
                          {("legacy.invalid", "/shots/0/line/text")}),
}


def test_base_document_is_valid():
    assert lm.validate(base()) == []


@pytest.mark.parametrize("name", CASES)
def test_rule(name):
    mutate, expected = CASES[name]
    document = base()
    mutate(document)
    assert rules(document) == expected
    with pytest.raises(ContractError):
        lm.from_document(document)


@pytest.mark.parametrize("document", [
    {"schema": "studio.story/v1", "shots": [], "frame": {}, "job": "x"},
    {"shots": [], "frame": {}},
    [],
    "manifest",
])
def test_a_document_that_is_not_a_legacy_manifest(document):
    assert lm.detect(document) is None
    assert rules(document) == {("schema.unsupported", "")}


def test_the_contract_invalid_example_fails_with_exactly_its_rule():
    case = json.loads(INVALID_EXAMPLE.read_text(encoding="utf-8"))
    found = lm.validate(case["document"], context=case["context"])
    assert [(v.rule, v.status, v.path) for v in found] == [
        (case["rule"], case["expect"], case["path"])]


def test_unknown_context_is_a_programming_error():
    with pytest.raises(ValueError):
        lm.validate(base(), context="publish")


def test_errors_name_the_file_rule_and_path(tmp_path):
    document = base()
    document["colour"] = "red"
    document["shots"][0]["duration"] = 3.0
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ContractError) as caught:
        lm.load(path)
    assert str(caught.value).splitlines() == [
        f"{path}: rule schema.unknown_field at /colour: unknown field 'colour'",
        f"{path}: rule legacy.duration_with_lines at /shots/0: a shot with lines has no "
        "duration; the legacy editor silently let duration win",
    ]
    assert caught.value.source == str(path)


@pytest.mark.parametrize(("text", "message"), [
    ('{"job": "a", "job": "b"}', "duplicate key 'job'"),
    ('{"job": NaN}', "NaN is not JSON"),
    ("{", "not JSON"),
])
def test_strict_json(tmp_path, text, message):
    path = tmp_path / "manifest.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ContractError, match=message) as caught:
        lm.load(path)
    assert caught.value.violations[0].rule == "legacy.invalid"


# The schema file --------------------------------------------------------------------


def test_schema_ships_as_package_data_and_is_draft_2020_12():
    text = files("haynes_studio.schemas").joinpath(lm.SCHEMA_FILE).read_text(encoding="utf-8")
    schema = json.loads(text)
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["title"] == "legacy.manifest/v1"
    assert schema["required"] == ["title", "job", "frame", "shots"]


def test_schema_alone_accepts_the_fixtures_and_refuses_the_invalid_example():
    validator = Draft202012Validator(json.loads(
        files("haynes_studio.schemas").joinpath(lm.SCHEMA_FILE).read_text(encoding="utf-8")))
    for revision in REVISIONS:
        assert list(validator.iter_errors(read_json(fixture(revision)).document)) == []
    case = json.loads(INVALID_EXAMPLE.read_text(encoding="utf-8"))
    assert [error.validator for error in validator.iter_errors(case["document"])] == ["not"]
