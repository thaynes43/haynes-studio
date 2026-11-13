"""Validators: every example's exact rule, status and path; JSON Schema and Python agree;
and the rules the examples do not reach."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from haynes_studio.canonical import (
    Facts,
    VoiceVersionFacts,
    validate_board,
    validate_legacy_import,
    validate_method_capabilities,
    validate_production,
    validate_story,
    validate_story_timing,
)
from haynes_studio.canonical.validate import SCHEMA_FILES
from haynes_studio.errors import WARNING
from haynes_studio.schemas import validator_for
from tests.canonical.fixtures import EXAMPLES, board_context, example, example_context
from tests.contracts import harness
from tests.contracts.registry import VALIDATORS

TYPES = ("production", "story", "board", "story-timing", "method-capabilities", "legacy-import")
# Rules the JSON Schema files carry (x-studio, const, additionalProperties); every other
# rule needs more than one field and is checked in code only.
SCHEMA_RULES = {"schema.unknown_field", "schema.unsupported", "id.malformed", "id.type_mismatch",
                "time.not_integer_ms", "time.negative", "time.tail_too_short",
                "time.hold_out_of_range", "time.duration_is_derived", "method.unknown",
                "cue.type_unknown"}


def _examples(kind: str):
    out = []
    for path in sorted((EXAMPLES / kind).glob("*.json")):
        item, _ = harness.load(path.resolve())
        if item is not None and item.type in TYPES:
            out.append(item)
    return out


VALID, INVALID = _examples("valid"), _examples("invalid")


def _id(item) -> str:
    return Path(item.label).name


def blocking(found):
    return [(v.rule, v.status, v.path) for v in found if v.status != WARNING]


def test_every_type_has_examples():
    # Boards have no valid example of their own; the story example embeds nine.
    assert {item.type for item in VALID} == set(TYPES) - {"board"}
    assert {item.type for item in INVALID} == {"board", "story"}


@pytest.mark.parametrize("number", range(1, 10))
def test_each_embedded_board_validates_alone(number):
    found = next(b for b in example("valid/story-winter-menu-r4.json")["boards"]
                 if b["number"] == number)
    assert blocking(VALIDATORS["board"](found, context="read")) == []


@pytest.mark.parametrize("item", INVALID, ids=_id)
def test_invalid_case_fails_with_exactly_its_rule_status_and_path(item):
    context = item.data["context"]
    found = blocking(VALIDATORS[item.type](item.document, context=context))
    assert found == [(item.rule, item.data["expect"], item.data["path"])]


@pytest.mark.parametrize("item", VALID + INVALID, ids=_id)
def test_json_schema_and_python_agree(item):
    """A plain draft 2020-12 validator (no rule mapping) accepts every valid example,
    rejects every case whose rule the schema carries, and accepts the rest, which the
    code rejects."""
    shipped = validator_for(SCHEMA_FILES[f"studio.{item.type}/v1"])
    assert isinstance(shipped, Draft202012Validator)
    errors = list(shipped.iter_errors(item.document))
    if item.kind == "valid":
        assert errors == []
    elif item.rule in SCHEMA_RULES:
        assert errors, f"the schema accepts a {item.rule} case"
    else:
        assert errors == [], f"the schema rejects a {item.rule} case the code owns"


@pytest.mark.parametrize("context", ["read", "write", "queue_run"])
def test_contract_story_example_is_buildable(context):
    story = example("valid/story-winter-menu-r4.json")
    if context != "read":
        story = _write_form(story)
    assert blocking(validate_story(story, context=context, facts=example_context().facts)) == []


# Helpers ----------------------------------------------------------------------------


def _write_form(document):
    out = {k: copy.deepcopy(v) for k, v in document.items() if k != "derived"}
    if "boards" in out:
        out["boards"] = [{k: v for k, v in b.items() if k != "derived"} for b in out["boards"]]
    return out


def board(number: int) -> dict:
    """Board ``number`` of the r4 story example, as a client would write it."""
    story = example("valid/story-winter-menu-r4.json")
    found = next(b for b in story["boards"] if b["number"] == number)
    return _write_form(found)


def check(document, context="write", **kwargs):
    kwargs = {**board_context(document), **kwargs}
    return blocking(validate_board(document, context=context, **kwargs))


# Board rules beyond the examples ----------------------------------------------------


def test_silent_board_needs_a_positive_hold():
    silent = board(7)
    silent["timing"]["hold_ms"] = None
    assert check(silent) == [("time.hold_out_of_range", "invalid", "/timing/hold_ms")]
    silent["timing"]["hold_ms"] = 0
    assert check(silent) == [("time.hold_out_of_range", "invalid", "/timing/hold_ms")]
    silent["timing"].update(hold_ms=1900, lead_ms=500)
    assert check(silent) == [("schema.invalid", "invalid", "/timing/lead_ms")]


def test_s2v_without_a_line_is_rejected():
    silent = board(7)
    silent["method"]["motion"] = "s2v"
    assert check(silent) == [("method.s2v_needs_line", "invalid", "/method/motion")]


def test_spoken_board_needs_lead_tail_and_later_gaps():
    spoken = board(8)
    spoken["timing"]["tail_ms"] = None
    spoken["lines"][3]["gap_before_ms"] = None
    assert check(spoken) == [("schema.invalid", "invalid", "/lines/3/gap_before_ms"),
                             ("schema.invalid", "invalid", "/timing/tail_ms")]


def test_whole_frame_s2v_saves_with_a_warning_and_fails_at_queue():
    design = board(1)
    design["method"]["layer"] = "whole_frame"
    write = validate_board(design, context="write", **board_context(design))
    assert [(v.rule, v.status) for v in write] == [("method.unavailable", "warning")]
    assert check(design, "queue_run") == [("method.unavailable", "unavailable", "/method")]


def test_narrator_lines_need_a_narrator_board():
    spoken = board(1)
    spoken["lines"][0]["speaker"] = "narrator"
    assert ("voice.speaker_not_in_cast", "invalid", "/lines/0/speaker") in check(spoken)


def test_speaker_rule_needs_the_story_cast():
    spoken = board(8)
    spoken["lines"][1]["speaker"] = "e"
    assert check(spoken, story_cast=None) == []  # a lone board cannot see the cast
    assert check(spoken) == [("voice.speaker_not_in_cast", "invalid", "/lines/1/speaker")]


def test_layout_preset_and_duplicates():
    group = board(8)
    group["layout"]["preset"] = "crowd"
    group["cast"].append({"slot": "a", "asset_version_id": group["cast"][0]["asset_version_id"]})
    group["cues"][3]["id"] = group["cues"][2]["id"]
    assert check(group) == [("ref.duplicate", "invalid", "/cast/4/slot"),
                            ("ref.duplicate", "invalid", "/cues/3/id"),
                            ("ref.unknown", "invalid", "/layout/preset")]


def test_capability_mismatch_needs_a_layer_capability():
    one = board(1)
    still = one["cast"][0]["asset_version_id"]
    facts = example_context().facts.merged(Facts.build(capabilities={still: ["opaque_photo"]}))
    assert check(one, facts=facts) == [
        ("asset.capability_mismatch", "invalid", "/cast/0/asset_version_id")]
    assert check(one, facts=example_context().facts) == []  # rgba_cutout (asset example)


def test_cue_after_line_anchor_out_of_range():
    vote = board(8)
    vote["cues"][1]["anchor"]["offset_ms"] = 3000  # 7575 + 3000 >= 251 frames (10458 ms)
    assert check(vote) == [("cue.out_of_range", "invalid", "/cues/1/anchor/offset_ms")]


def test_cue_range_waits_for_a_timed_board():
    late = board(9)
    late["cues"][0]["anchor"]["at_ms"] = 5000
    assert check(late, facts=Facts()) == []  # untimed on write: checked at queue_run
    assert check(late, "queue_run", facts=Facts()) == [
        ("voice.absent", "invalid", "/voice/current_version_id")]


def test_queue_run_voice_and_photo_states():
    one = board(1)
    version = one["voice"]["current_version_id"]
    line = one["lines"][0]["id"]
    stale = Facts.build(voices=[VoiceVersionFacts(version, {line: 5163}, matches_board=False)])
    assert check(one, "queue_run", facts=stale) == [
        ("voice.stale", "invalid", "/voice/current_version_id")]
    running = Facts.build(voices=[VoiceVersionFacts(version, {line: 5163})],
                          generating=[(one["id"], "voice")])
    assert check(one, "queue_run", facts=running) == [("asset.generating", "invalid", "/voice")]
    frame = board(7)
    frame["method"]["layer"] = "whole_frame"
    frame["photo"]["current_version_id"] = None
    assert check(frame) == []
    assert check(frame, "queue_run") == [("photo.absent", "invalid", "/photo/current_version_id")]


def test_notes_are_text_only_and_nfc():
    note = board(7)
    note["notes"][0]["text"] = "Café"
    assert check(note) == [("schema.invalid", "invalid", "/notes/0/text")]


def test_derived_is_rejected_on_write_only():
    read = example("valid/story-winter-menu-r4.json")["boards"][0]
    assert check(read, "read") == []
    assert check(read, "write") == [("schema.unknown_field", "invalid", "/derived")]


def test_other_types_and_majors_are_unsupported():
    assert check({**board(1), "schema": "studio.board/v2"}) == [
        ("schema.unsupported", "invalid", "/schema")]
    assert check(example("valid/production.json")) == [
        ("schema.unsupported", "invalid", "/schema")]
    assert check([]) == [("schema.invalid", "invalid", "")]
    with pytest.raises(ValueError):
        validate_board(board(1), context="draft")


# Story rules ------------------------------------------------------------------------


def story_write():
    return _write_form(example("valid/story-winter-menu-r4.json"))


def check_story(document, context="write", **kwargs):
    kwargs.setdefault("facts", example_context().facts)
    return blocking(validate_story(document, context=context, **kwargs))


def test_story_board_order_and_membership():
    story = story_write()
    story["board_order"] = story["board_order"][:-1] + [story["board_order"][0]]
    assert check_story(story) == [("ref.duplicate", "invalid", "/board_order/8"),
                                  ("story.board_order", "invalid", "/boards/8/id")]
    story = story_write()
    story["boards"][2]["story_id"] = "sty_01M79V9FC00000000000000002"
    story["boards"][3]["number"] = 2
    assert check_story(story) == [("ref.unknown", "invalid", "/boards/2/story_id"),
                                  ("ref.duplicate", "invalid", "/boards/3/number")]


def test_story_checks_each_board_against_its_cast_and_ids_across_boards():
    story = story_write()
    story["boards"][7]["lines"][1]["speaker"] = "e"
    story["boards"][8]["notes"][0]["id"] = story["boards"][7]["notes"][0]["id"]
    assert check_story(story) == [
        ("voice.speaker_not_in_cast", "invalid", "/boards/7/lines/1/speaker"),
        ("ref.duplicate", "invalid", "/boards/8/notes/0/id")]


def test_story_media_kind_and_narrator_voice():
    story = story_write()
    assert check_story(story, enabled_media_kinds={"video"}) == [
        ("ref.unknown", "invalid", "/media_kind")]
    story["boards"][0]["voice"]["style"] = "narrator"
    assert check_story(story) == []
    assert ("voice.absent", "invalid", "/narrator_voice_version_id") in \
        check_story(story, "queue_run")


def test_story_schema_error_in_one_board_keeps_the_others_checked():
    story = story_write()
    story["boards"][0]["timing"]["lead_ms"] = -1
    story["boards"][7]["timing"]["hold_ms"] = 2000
    assert check_story(story) == [("time.negative", "invalid", "/boards/0/timing/lead_ms"),
                                  ("time.hold_on_spoken_board", "invalid", "/boards/7/timing/hold_ms")]


# The other four types -----------------------------------------------------------------


def test_production_profiles_and_kinds():
    production = example("valid/production.json")
    production["media_types"][0]["width"] = 1920
    assert [r for r, _, _ in blocking(validate_production(production))] == ["schema.invalid"]
    production = example("valid/production.json")
    production["media_types"].append(dict(production["media_types"][0]))
    assert blocking(validate_production(production)) == [
        ("ref.duplicate", "invalid", "/media_types/1/kind")]


def test_story_timing_rows():
    timing = example("valid/story-timing-summary.json")
    timing["boards"][8]["frames"] = 108  # untimed rows carry no frames
    assert [r for r, _, _ in blocking(validate_story_timing(timing))] == ["schema.invalid"]


def test_method_capabilities_each_cell_once():
    methods = example("valid/method-capabilities.json")
    methods["cells"][3] = dict(methods["cells"][2])
    assert blocking(validate_method_capabilities(methods)) == [
        ("ref.duplicate", "invalid", "/cells/3")]


def test_legacy_import_board_map_name_and_ids():
    import_map = example("valid/legacy-import-map.json")
    import_map["draft_from_revision"] = 3
    assert blocking(validate_legacy_import(import_map)) == [
        ("schema.invalid", "invalid", "/boards_from_r4")]
    import_map = example("valid/legacy-import-map.json")
    import_map["boards_from_r4"][1]["lines"][0]["line_id"] = \
        import_map["boards_from_r4"][0]["lines"][0]["line_id"]
    assert blocking(validate_legacy_import(import_map)) == [
        ("ref.duplicate", "invalid", "/boards_from_r4/1/lines/0/line_id")]
