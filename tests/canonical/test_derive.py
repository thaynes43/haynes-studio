"""Derived values: board length from measured takes or the hold, film placement, voice
and photo states, story totals and the timing summary with the D45 warning."""

from __future__ import annotations

import copy

from haynes_studio.canonical import (
    Board,
    Facts,
    FormatLength,
    PhotoVersionFacts,
    Story,
    VoiceVersionFacts,
    timing_summary,
    to_document,
    validate_story_timing,
    with_derived,
)
from haynes_studio.canonical.derive import (
    board_clock,
    board_derived,
    boards_derived,
    photo_state,
    resolve_anchor,
    story_derived,
    voice_state,
)
from haynes_studio.timebase import mix_sample
from tests.canonical.fixtures import example, example_context


def story_example() -> Story:
    return Story.from_document(example("valid/story-winter-menu-r4.json"))


def board(number: int) -> Board:
    return next(b for b in story_example().boards if b.number == number)


FACTS = example_context().facts


def test_spoken_board_length_from_takes_with_explicit_pad_and_rounding():
    one = board_clock(board(1), FACTS)
    assert (one.content_ms, one.frames) == (500 + 5163 + 700, 153)  # TIME-3
    assert one.frames * 1000 // 24 - one.content_ms == 12  # the remainder lands in the tail


def test_board_8_line_offsets_and_gavel_match_the_worked_example():
    vote = board(8)
    clock = board_clock(vote, FACTS)
    assert (clock.content_ms, clock.frames) == (10427, 251)
    spans = [(clock.spans[line.id].start_ms, clock.spans[line.id].end_ms) for line in vote.lines]
    assert spans == [(1900, 2903), (3203, 4014), (4214, 5089), (5339, 5851), (6551, 7575),
                     (8475, 9627)]
    gavel = vote.cues[1]
    assert resolve_anchor(gavel.anchor, clock) == 7625
    assert mix_sample(728, 7625) == 1_822_000


def test_silent_board_uses_its_hold():
    seven = board_clock(board(7), Facts())
    assert (seven.content_ms, seven.frames) == (1900, 46)  # TIME-4, no voice needed


def test_voice_states_are_explicit():
    one = board(1)
    version, line = one.voice.current_version_id, one.lines[0].id
    assert voice_state(one, Facts()) == "absent"
    assert voice_state(one, Facts.build(voices=[VoiceVersionFacts(version, {line: 5163})])) == "current"
    assert voice_state(one, Facts.build(voices=[VoiceVersionFacts(version, {})])) == "stale"
    assert voice_state(one, Facts.build(
        voices=[VoiceVersionFacts(version, {line: 5163}, matches_board=False)])) == "stale"
    assert voice_state(one, Facts.build(generating=[(one.id, "voice")])) == "generating"
    assert voice_state(board(7), Facts()) == "not_needed"
    assert board_derived(one, Facts(), 0).timing_state == "untimed"
    assert board_derived(one, Facts(), 0).frames is None


def test_photo_states_are_explicit():
    one = board(1)
    photo = one.photo.current_version_id
    assert photo_state(one, Facts()) == "absent"
    assert photo_state(one, Facts.build(photos=[PhotoVersionFacts(photo)])) == "current"
    assert photo_state(one, Facts.build(photos=[PhotoVersionFacts(photo, False)])) == "stale"
    assert photo_state(one, Facts.build(generating=[(one.id, "photo")])) == "generating"


def test_film_starts_stop_after_an_untimed_board():
    boards = story_example().ordered_boards()
    no_voice_3 = Facts.build(voices=[v for k, v in FACTS.voice_versions.items()
                                     if k != boards[2].voice.current_version_id])
    derived = boards_derived(boards, no_voice_3)
    assert [d.film_start_frame for d in derived[:3]] == [0, 153, None]
    assert all(d.film_start_frame is None for d in derived[2:])
    assert derived[3].frames == 84  # later boards still know their own length


def test_with_derived_reproduces_the_contract_story_example():
    want = example("valid/story-winter-menu-r4.json")
    write = copy.deepcopy(want)
    del write["derived"]
    for item in write["boards"]:
        del item["derived"]
    assert with_derived(write, facts=FACTS) == want


def test_story_derived_counts_and_number_sequence():
    story = story_example()
    derived = story_derived(story, story.ordered_boards(), FACTS, highest_number_issued=12)
    assert (derived.frames, derived.duration_ms, derived.next_board_number) == (1087, 45291, 13)


def _timing_story() -> dict:
    """Revision 2 of the example story: board 9 replaced by board A with no voice yet."""
    story = copy.deepcopy(example("valid/story-winter-menu-r4.json"))
    del story["derived"]
    for item in story["boards"]:
        del item["derived"]
    new = copy.deepcopy(story["boards"][8])
    new.update(id="brd_01M79V9FC0000000000000000A", number=10, title="Needs salt, take two")
    new["voice"]["current_version_id"] = None
    new["origin"] = None
    new["lines"][0]["id"] = "lin_01M79V9FC0000000000000000E"
    new["cues"][0]["id"] = "cue_01M79V9FC0000000000000000K"
    new["notes"][0]["id"] = "nte_01M79V9FC00000000000000004"
    story["boards"][8] = new
    story["board_order"][8] = new["id"]
    story["revision"] = 2
    return story


def test_timing_summary_reproduces_the_contract_example():
    want = example("valid/story-timing-summary.json")
    length = FormatLength(**want["format_length"])
    got = to_document(timing_summary(_timing_story(), facts=FACTS, format_length=length))
    assert got == want
    assert validate_story_timing(got) == []


def test_length_warning_on_a_complete_story():
    story = example("valid/story-winter-menu-r4.json")
    length = FormatLength(format_version_id="fmv_01M79V9FC00000000000000001", min_ms=15000,
                          max_ms=45000)
    summary = timing_summary(story, facts=FACTS, format_length=length)
    assert summary.complete and summary.build_allowed
    assert [w.message for w in summary.warnings] == [
        "The story runs 45.292 s, past the format maximum of 45 s."]
    roomy = FormatLength(format_version_id=length.format_version_id, min_ms=0, max_ms=45292)
    assert timing_summary(story, facts=FACTS, format_length=roomy).warnings == ()
