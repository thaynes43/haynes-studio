"""Asset and asset-version validators: every example's exact rule, status and path; the
JSON Schema files and the Python checks agree on the examples and on mutations of
them; and the rules the examples do not reach."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from haynes_studio.errors import WARNING
from haynes_studio.library import validate_asset, validate_asset_version
from haynes_studio.library.model import KOKORO
from haynes_studio.library.validate import ASSET_FILE, ASSET_VERSION_FILE
from haynes_studio.schemas import validator_for
from tests.canonical.fixtures import EXAMPLES, example
from tests.contracts import harness
from tests.contracts.registry import VALIDATORS
from tests.library.fixtures import record_id, winter_menu

# Every asset-version rule the examples name is carried by the schema file.
SCHEMA_RULES = {"schema.unknown_field", "schema.unsupported", "schema.invalid", "id.malformed",
                "id.type_mismatch", "store.locator_invalid", "prov.licence_missing",
                "prov.external_incomplete", "voice.not_stock"}


def _examples(kind: str):
    out = []
    for path in sorted((EXAMPLES / kind).glob("*.json")):
        item, _ = harness.load(path.resolve())
        if item is not None and item.type in ("asset", "asset-version"):
            out.append(item)
    return out


VALID, INVALID = _examples("valid"), _examples("invalid")


def _id(item) -> str:
    return Path(item.label).name


def check(document, context="write"):
    return [(v.rule, v.status, v.path) for v in validate_asset_version(document, context=context)
            if v.status != WARNING]


def plain_rules(document, filename=ASSET_VERSION_FILE) -> set[str]:
    """The rules a plain draft 2020-12 validator's errors carry, read from the schema
    file's own annotations (as tests/canonical/test_validate.py does)."""
    rules = set()
    for error in validator_for(filename).iter_errors(document):
        if error.validator == "additionalProperties":
            rules.add("schema.unknown_field")
            continue
        schema = error.schema if isinstance(error.schema, dict) else {}
        rules.add(schema.get("x-studio", {}).get(error.validator, {}).get("rule", "schema.invalid"))
    return rules


def cast():
    return example("valid/asset-version-cast.json")


def photo():
    return example("valid/asset-version-photo-external.json")


def board_voice():
    return example("valid/asset-version-board-voice.json")


def voice():
    """A valid stock voice version: the voice-not-stock case made stock."""
    doc = example("invalid/voice-not-stock.json")["document"]
    doc["attributes"] = {"voice_id": "af_heart", "stock": True}
    doc["name"] = "af_heart (Kokoro stock voice)"
    doc["provenance"]["origin"] = "declared"
    doc["provenance"]["generator"] = {"role": "voice", "engine": "ai/deploy/kokoro (Wyoming)",
                                      "model": KOKORO, "voice_id": "af_heart"}
    return doc


# Examples --------------------------------------------------------------------------------


def test_the_examples_cover_both_rule_families():
    assert {item.type for item in VALID} == {"asset-version"}
    assert sorted(item.rule for item in INVALID) == [
        "prov.external_incomplete", "prov.licence_missing", "store.locator_invalid",
        "voice.not_stock"]


@pytest.mark.parametrize("item", VALID, ids=_id)
@pytest.mark.parametrize("context", ["read", "write", "queue_run"])
def test_valid_examples_validate_in_every_context(item, context):
    assert check(item.document, context) == []


@pytest.mark.parametrize("item", INVALID, ids=_id)
def test_invalid_case_fails_with_exactly_its_rule_status_and_path(item):
    found = check(item.document, item.data["context"])
    assert found == [(item.rule, item.data["expect"], item.data["path"])]
    assert VALIDATORS["asset-version"] is validate_asset_version


@pytest.mark.parametrize("item", VALID + INVALID, ids=_id)
def test_json_schema_and_python_agree_on_the_examples(item):
    shipped = validator_for(ASSET_VERSION_FILE)
    assert isinstance(shipped, Draft202012Validator)
    if item.kind == "valid":
        assert list(shipped.iter_errors(item.document)) == []
    else:
        assert item.rule in SCHEMA_RULES
        assert plain_rules(item.document) == {item.rule}


def test_every_valid_example_is_a_valid_voice_too():
    assert check(voice()) == []


# Mutations: the schema carries a rule, or the code owns it ------------------------------

H = "4ea3005f4effebda7f4ce9b083da55e8529db4269c96104364e5dc74b25969de"
PRD = "prd_01M79V9FC00000000000000001"


def _set(path, value):
    def change(doc):
        target = doc
        for key in path[:-1]:
            target = target[key]
        if value is _DELETE:
            del target[path[-1]]
        else:
            target[path[-1]] = value
    return change


_DELETE = object()

SCHEMA_CASES = [
    # (base, change, rule, path)
    (cast, _set(["content", "locator"], f"library/sha256/4e/{H}.png\n"),
     "store.locator_invalid", "/content/locator"),
    (cast, _set(["content", "locator"], f"/studio/library/sha256/4e/{H}.png"),
     "store.locator_invalid", "/content/locator"),
    (cast, _set(["content", "locator"], f"library/sha256/4E/{H.upper()}.png"),
     "store.locator_invalid", "/content/locator"),
    (cast, _set(["content", "locator"], f"library/sha256/4e/{H}.gif"),
     "store.locator_invalid", "/content/locator"),
    (cast, _set(["content", "locator"], f"productions/{PRD}/records/run_x/stage.json"),
     "store.locator_invalid", "/content/locator"),
    (cast, _set(["content", "locator"], f"productions/{PRD}/sha256/4e/../{H}.png"),
     "store.locator_invalid", "/content/locator"),
    (cast, _set(["licence"], None), "prov.licence_missing", "/licence"),
    (cast, _set(["licence", "commercial_use"], _DELETE), "prov.licence_missing", "/licence"),
    (cast, lambda d: d["licence"].update(commercial_use="allowed", name="Apache-2.0",
                                         checked_at="2026-11-13T08:00:00Z"),
     "schema.invalid", "/licence/checked_by"),
    (photo, _set(["provenance", "external"], None), "prov.external_incomplete", "/provenance/external"),
    (photo, _set(["provenance", "external"], _DELETE),
     "prov.external_incomplete", "/provenance/external"),
    (cast, _set(["provenance", "external"], _DELETE), "schema.invalid", "/provenance"),
    (photo, _set(["provenance", "generator", "model"], None),
     "prov.external_incomplete", "/provenance/generator/model"),
    (photo, _set(["provenance", "generator", "prompt"], _DELETE),
     "prov.external_incomplete", "/provenance/generator"),
    (photo, _set(["provenance", "external", "paid_api"], True),
     "prov.external_incomplete", "/provenance/external/paid_api"),
    (photo, _set(["provenance", "external", "agent", "session"], _DELETE),
     "prov.external_incomplete", "/provenance/external/agent"),
    (photo, _set(["provenance", "external", "server_computed_sha256"], False),
     "prov.external_incomplete", "/provenance/external/server_computed_sha256"),
    (voice, _set(["content"], cast()["content"]), "voice.not_stock", "/content"),
    (voice, _set(["attributes", "stock"], _DELETE), "voice.not_stock", "/attributes"),
    (cast, _set(["asset_id"], "asv_01M79V9FC00000000000000001"), "id.type_mismatch", "/asset_id"),
    (cast, _set(["id"], "asv_01M79V9FC0000000000000001"), "id.malformed", "/id"),
    (cast, _set(["id"], "asv_01M79V9FC00000000000000001\n"), "id.malformed", "/id"),
    (cast, _set(["scope", "production_id"], "sty_01M79V9FC00000000000000001"),
     "id.type_mismatch", "/scope/production_id"),
    (cast, _set(["colour"], "red"), "schema.unknown_field", "/colour"),
    (cast, _set(["provenance", "generator", "colour"], "red"),
     "schema.unknown_field", "/provenance/generator/colour"),
    (cast, _set(["state"], "board"), "schema.invalid", ("/kind", "/scope")),
    (cast, _set(["content"], None), "schema.invalid", "/content"),
    (cast, _set(["kind"], "character_card"), "schema.invalid", "/kind"),
    (cast, _set(["capabilities"], ["rgba_cutout", "rgba_cutout"]), "schema.invalid", "/capabilities"),
    (cast, _set(["capabilities"], []), "schema.invalid", "/capabilities"),
    (cast, _set(["labels"], ["A", "tab\there"]), "schema.invalid", "/labels/1"),
    (cast, _set(["number"], 0), "schema.invalid", "/number"),
    (board_voice, _set(["voice"], _DELETE), "schema.invalid", ""),
    (board_voice, _set(["state"], "promoted"), "schema.invalid", ("/scope", "/state")),
    (board_voice, _set(["voice", "takes", 0, "duration_ms"], 1003.5),
     "time.not_integer_ms", "/voice/takes/0/duration_ms"),
    (photo, _set(["state"], "candidate"), "schema.invalid", ("/scope", "/state")),
    (photo, _set(["content", "bytes"], None), "schema.invalid", "/provenance/origin"),
    (cast, _set(["attributes", "mood\n"], "x"), "schema.invalid", "/attributes/mood\n"),
]

CODE_CASES = [
    (cast, _set(["content", "locator"], f"productions/{PRD}/sha256/4e/{'0' * 64}.png"),
     "store.locator_invalid", "/content/locator"),
    (cast, _set(["content", "locator"], f"productions/{PRD}/sha256/00/{H}.png"),
     "store.locator_invalid", "/content/locator"),
    (cast, _set(["content", "locator"], f"productions/{PRD}/sha256/4e/{H}.jpg"),
     "store.locator_invalid", "/content/locator"),
    (cast, _set(["content", "locator"], f"productions/prd_01M79V9FC00000000000000002/sha256/4e/{H}.png"),
     "store.locator_invalid", "/content/locator"),
    (cast, _set(["capabilities"], ["sound_effect"]), "asset.capability_mismatch", "/capabilities/0"),
    (cast, _set(["capabilities"], ["opaque_photo", "keyed_layer"]),
     "asset.capability_mismatch", "/capabilities/1"),
    (photo, _set(["capabilities"], ["rgba_cutout"]), "asset.capability_mismatch", "/capabilities/0"),
    (cast, _set(["labels"], ["A", "A"]), "ref.duplicate", "/labels/1"),
    (cast, _set(["legacy", "source_key"], "legacy:the-winter-menu-r4:still:cutouts/b.png"),
     "schema.invalid", "/legacy/source_key"),
    (voice, lambda d: (d["attributes"].update(voice_id="cloned-from-sample"),
                       d["provenance"]["generator"].update(voice_id="cloned-from-sample")),
     "voice.not_stock", "/attributes/voice_id"),
    (voice, _set(["provenance", "generator", "model"], "another-tts 1.0"),
     "voice.not_stock", "/attributes/voice_id"),
    (voice, _set(["provenance", "generator", "voice_id"], "af_bella"),
     "voice.not_stock", "/provenance/generator/voice_id"),
    (voice, _set(["provenance", "origin"], "generated"), "voice.not_stock", "/provenance/origin"),
    (voice, _set(["provenance", "generator", "source_sample_sha256"], "e" * 64),
     "voice.not_stock", "/provenance/generator/source_sample_sha256"),
    (board_voice, _set(["voice", "takes", 1, "offset_ms"], 3202),
     "schema.invalid", "/voice/takes/1/offset_ms"),
    (board_voice, _set(["voice", "gaps_ms"], [300]), "schema.invalid", "/voice/gaps_ms"),
    (board_voice, _set(["voice", "speech_end_ms"], 9628), "schema.invalid", "/voice/speech_end_ms"),
    (board_voice, _set(["voice", "takes", 0, "voice_id"], "cloned-from-sample"),
     "voice.not_stock", "/voice/takes/0/voice_id"),
    (board_voice, _set(["voice", "takes", 1, "line_id"], "lin_01M79V9FC00000000000000007"),
     "ref.duplicate", "/voice/takes/1/line_id"),
]


def _case_id(case):
    paths = (case[3],) if isinstance(case[3], str) else case[3]
    return f"{case[0].__name__}:{case[2]}:{'+'.join(p or '(root)' for p in paths)}"


def _expected(rule, paths):
    return [(rule, "invalid", p) for p in ((paths,) if isinstance(paths, str) else paths)]


@pytest.mark.parametrize("case", SCHEMA_CASES, ids=[_case_id(c) for c in SCHEMA_CASES])
def test_the_schema_carries_its_rules(case):
    base, change, rule, paths = case
    document = base()
    change(document)
    assert check(document) == _expected(rule, paths)
    assert plain_rules(document) == {rule}


@pytest.mark.parametrize("case", CODE_CASES, ids=[_case_id(c) for c in CODE_CASES])
def test_the_code_owns_what_one_field_cannot_show(case):
    base, change, rule, path = case
    document = base()
    change(document)
    assert check(document) == [(rule, "invalid", path)]
    assert plain_rules(document) == set(), f"the schema rejects a {rule} case the code owns"


def test_measured_takes_follow_time_1():
    document = board_voice()
    take = document["voice"]["takes"][0]
    take.update(samples=24072, sample_rate=24000, duration_source="samples")  # 1003 ms
    assert check(document) == []
    take["samples"] = 24073  # 1003.04 ms rounds up to 1004
    assert check(document) == [("schema.invalid", "invalid", "/voice/takes/0/duration_ms")]
    take["samples"] = None
    assert check(document) == [("schema.invalid", "invalid", "/voice/takes/0/samples")]


def test_a_checked_licence_names_who_checked_it():
    document = cast()
    document["licence"].update(name="Apache-2.0", commercial_use="allowed",
                               checked_at="2026-11-13T08:00:00Z",
                               checked_by=document["provenance"]["created_by"]["operator"])
    assert check(document) == []


def test_global_versions_live_in_the_library_folder():
    document = cast()
    document["scope"]["production_id"] = None
    assert check(document) == [("store.locator_invalid", "invalid", "/content/locator")]
    document["content"]["locator"] = f"library/sha256/4e/{H}.png"
    assert check(document) == []
    produced = cast()  # a production's version may name library bytes
    produced["content"]["locator"] = f"library/sha256/4e/{H}.png"
    assert check(produced) == []


def test_integral_floats_are_integers():
    document = cast()
    document["number"] = 1.0
    document["content"]["bytes"] = 1850605.0
    assert check(document) == []
    voiced = board_voice()
    voiced["voice"]["lead_ms"] = 1900.0
    assert check(voiced) == []


@pytest.mark.parametrize("document,rule,path", [
    ([], "schema.invalid", ""),
    ("text", "schema.invalid", ""),
    ({}, "schema.invalid", "/schema"),
    ({"schema": "studio.asset-version/v2"}, "schema.unsupported", "/schema"),
    ({"schema": "studio.asset/v1"}, "schema.unsupported", "/schema"),
])
def test_other_types_and_majors_stop_validation(document, rule, path):
    assert check(document) == [(rule, "invalid", path)]


@pytest.mark.parametrize("change", [
    lambda d: d.update(content="bytes"),
    lambda d: d.update(voice=[1, 2]),
    lambda d: d["provenance"].update(generator=None),
    lambda d: d.update(capabilities="rgba_cutout"),
    lambda d: d.update(scope=None),
    lambda d: d.update(kind=7),
])
def test_malformed_documents_return_violations(change):
    document = cast()
    change(document)
    assert check(document)  # never raises


def test_a_document_nested_too_deeply_is_refused():
    document = cast()
    deep = {}
    document["provenance"]["generator"]["params"] = deep
    for _ in range(70):
        deep["x"] = {}
        deep = deep["x"]
    assert check(document) == [("schema.invalid", "invalid", "")]


def test_an_unknown_context_is_a_programming_error():
    with pytest.raises(ValueError):
        validate_asset_version(cast(), context="publish")


# studio.asset/v1 --------------------------------------------------------------------------


def asset_document():
    built = winter_menu().library
    return built.asset_of(record_id(4, "still:cutouts/a-proud.png")).to_document()


def test_library_assets_validate():
    built = winter_menu().library
    for asset in built.assets.values():
        assert validate_asset(asset.to_document()) == []


@pytest.mark.parametrize("change,rule,path", [
    (lambda d: d.update(id="asv_01M79V9FC00000000000000001"), "id.type_mismatch", "/id"),
    (lambda d: d.update(revision=0), "schema.invalid", "/revision"),
    (lambda d: d.update(labels=["A", "A"]), "ref.duplicate", "/labels/1"),
    (lambda d: d.update(kind="voice", attributes={"voice_id": "cloned", "stock": True}),
     "voice.not_stock", "/attributes/voice_id"),
    (lambda d: d.update(kind="voice", attributes={"voice_id": "af_heart", "stock": False}),
     "voice.not_stock", "/attributes/stock"),
    (lambda d: d["scope"].update(story_id="sty_01M79V9FC00000000000000001",
                                 board_id="brd_01M79V9FC00000000000000001"),
     "schema.invalid", "/scope"),
    (lambda d: d.update(kind="board_voice"), "schema.invalid", "/scope"),
    (lambda d: d["attributes"].update(character_slot="A"), "schema.invalid", "/attributes/character_slot"),
    (lambda d: d.update(derived={}), "schema.unknown_field", "/derived"),
])
def test_asset_rules(change, rule, path):
    document = asset_document()
    change(document)
    found = [(v.rule, v.status, v.path) for v in validate_asset(document, context="write")]
    assert found == [(rule, "invalid", path)]
    schema_owned = rule not in ("ref.duplicate",) and not (rule == "voice.not_stock" and path.endswith("voice_id"))
    assert plain_rules(document, ASSET_FILE) == ({rule} if schema_owned else set())


def test_asset_schema_file_is_shipped_and_valid():
    copy.deepcopy(validator_for(ASSET_FILE).schema)
    assert validate_asset({"schema": "studio.asset/v2"}) [0].rule == "schema.unsupported"
