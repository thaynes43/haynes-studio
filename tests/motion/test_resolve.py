"""A board's motion loops (story 457): the pinned clip or the one promoted loop of a
still, the same answer every time, and each problem with its own code."""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from haynes_studio.jsonio import freeze, thaw
from haynes_studio.library import Library
from haynes_studio.motion.resolve import (
    CODES,
    resolve_board,
    resolve_story,
    resolve_timed,
)
from haynes_studio.render.clock import loop_phase
from tests.motion.fixtures import (
    CAST_A,
    CAST_B,
    DRIVE,
    SET_PLATE,
    STILL_A,
    Verify,
    board,
    entry,
    ident,
    library,
    loop_block,
    set_block,
    sha,
    still_version,
    story,
    timed_block,
    version,
)

LOOP_A, LOOP_A2, SET_LOOP, TIMED_A, EMPTY_MOTION = 10, 11, 12, 13, 14


def loop_a(n=LOOP_A, *, state="promoted", **changes):
    return version(loop_block(**changes), n=n, clip=sha("a"), state=state)


def standard(*extra):
    """A doll loop of still A, a set loop and a timed clip of still A."""
    return library(loop_a(), version(set_block(), n=SET_LOOP, clip=sha("9")),
                   version(timed_block(), n=TIMED_A, clip=sha("8")), *extra)


def problems(result):
    return {(v.rule, v.path) for v in result.problems}


def test_a_board_used_twice_resolves_the_same_pinned_clip():
    lib, verify = standard(), Verify()
    first = resolve_board(board(entry("a")), lib, verify)
    second = resolve_board(copy.deepcopy(board(entry("a"))), lib, verify)
    assert first.complete and second.complete
    assert first == second
    (clip,) = first.cast
    assert (clip.version_id, clip.slot, clip.pinned) == (ident("asv", LOOP_A), "a", False)
    assert clip.path == "/cast/0/motion_asset_version_id"


def test_a_pinned_board_used_twice_resolves_the_same_clip():
    lib = standard()
    first = resolve_board(board(entry("a", pin=LOOP_A)), lib, Verify())
    second = resolve_board(board(entry("a", pin=LOOP_A)), lib, Verify())
    assert first == second and first.cast[0].pinned


def test_one_pin_on_two_boards_is_one_version_with_each_boards_phase():
    lib = standard()
    one = board(entry("a", pin=LOOP_A))
    two = {**board(entry("a", pin=LOOP_A)), "id": ident("brd", 2)}
    first, second = (resolve_board(b, lib, Verify()).cast[0] for b in (one, two))
    assert first.version_id == second.version_id and first.identity == second.identity
    assert (first.phase, second.phase) == (loop_phase(ident("brd", 1), "a", 240),
                                           loop_phase(ident("brd", 2), "a", 240))


def test_a_pin_is_used_and_gives_the_same_clip():
    lib = standard()
    pinned = resolve_board(board(entry("a", pin=LOOP_A)), lib, Verify())
    unpinned = resolve_board(board(entry("a")), lib, Verify())
    assert pinned.complete and pinned.cast[0].pinned
    assert pinned.cast[0].version_id == unpinned.cast[0].version_id
    assert pinned.cast[0].identity == unpinned.cast[0].identity


def test_which_frames_and_keying_inputs():
    clip = resolve_board(board(entry("a")), standard(), Verify()).cast[0]
    phase = loop_phase(ident("brd", 1), "a", 240)
    assert clip.phase == phase
    assert clip.source_frame(0) == clip.record.board_frame(0, phase=phase)
    assert clip.keyed_key == clip.identity.keyed.value
    assert clip.record.keying.decal_version == "erase-v2"
    assert clip.sha256 == sha("a") and clip.locator.endswith(f"{sha('a')}.mp4")


def test_the_set_loop_resolves_from_the_story():
    lib = standard()
    pinned = resolve_story(story(board(entry("a")), set_pin=SET_LOOP), lib, Verify())[0]
    unpinned = resolve_story(story(board(entry("a"))), lib, Verify())[0]
    assert pinned.complete and unpinned.complete
    assert pinned.set.version_id == unpinned.set.version_id == ident("asv", SET_LOOP)
    assert pinned.set.path == "/set/motion_asset_version_id"
    assert pinned.cast[0].path == "/boards/0/cast/0/motion_asset_version_id"
    assert pinned.clip_for("set") is pinned.set and pinned.clip_for("a") is pinned.cast[0]


def test_no_set_loop_is_a_static_plate():
    result = resolve_story(story(board(entry("a"))), library(loop_a()), Verify())[0]
    assert result.complete and result.set is None


@pytest.mark.parametrize(("layer", "motion", "lines", "needed"), [
    ("layered", "i2v", [], {"a", "b"}),
    ("layered", "s2v", [{"speaker": "a"}], {"b"}),
    ("whole_frame", "i2v", [], set()),
])
def test_which_cast_entries_play_a_loop(layer, motion, lines, needed):
    lib = library(loop_a(), version(loop_block(still_sha256=sha("b")), n=20, clip=sha("2")))
    result = resolve_board(board(entry("a"), entry("b", still=CAST_B), layer=layer,
                                 motion=motion, lines=lines), lib, Verify())
    assert result.complete
    assert {clip.slot for clip in result.cast} == needed


def test_a_pin_is_checked_on_any_board():
    result = resolve_board(board(entry("a", pin=TIMED_A), layer="whole_frame"), standard(),
                           Verify())
    assert problems(result) == {("motion.timed_not_loop", "/cast/0/motion_asset_version_id")}


# Problems, each with its own code ------------------------------------------------------------

AT = "/cast/0/motion_asset_version_id"


def corrupt_library():
    """A library whose loop's recorded identity was changed after it was written."""
    good = library(loop_a())
    version_ = good.version(ident("asv", LOOP_A))
    block = thaw(version_.motion)
    block["keys"]["identity"] = "sha256:" + "1" * 64
    bad = replace(version_, motion=freeze(block))
    return Library.build(good.assets.values(),
                         [bad if v.id == bad.id else v for v in good.versions.values()])


CASES = {
    "no clip of the still": (lambda: library(), entry("a"), Verify(),
                             {("motion.clip_absent", AT)}),
    "several promoted clips": (
        lambda: library(loop_a(), version(loop_block(), n=LOOP_A2, clip=sha("1"))),
        entry("a"), Verify(), {("motion.clip_ambiguous", AT)}),
    "a candidate is never found": (lambda: library(loop_a(state="candidate")), entry("a"),
                                   Verify(), {("motion.clip_absent", AT)}),
    "a timed clip asked for as a loop": (standard, entry("a", pin=TIMED_A), Verify(),
                                         {("motion.timed_not_loop", AT)}),
    "a set loop pinned for a doll": (standard, entry("a", pin=SET_LOOP), Verify(),
                                     {("asset.capability_mismatch", AT),
                                      ("motion.still_mismatch", AT)}),
    "a clip of another still": (standard, entry("b", still=CAST_B, pin=LOOP_A), Verify(),
                                {("motion.still_mismatch", AT)}),
    "an unknown pin": (standard, entry("a", pin=99), Verify(), {("ref.unknown", AT)}),
    "a pin of another kind": (standard, entry("a", pin=CAST_B), Verify(),
                              {("asset.kind_mismatch", AT)}),
    "a motion version without a block": (
        lambda: library(version(None, n=EMPTY_MOTION, clip=sha("e"))),
        entry("a", pin=EMPTY_MOTION), Verify(), {("motion.record_missing", AT)}),
    "a doll clip with no keying": (
        lambda: library(version({k: v for k, v in loop_block().items() if k != "keying"},
                                n=LOOP_A, clip=sha("a"))),
        entry("a"), Verify(), {("motion.keying_missing", AT)}),
    "missing bytes": (standard, entry("a"), Verify(missing=[sha("a")]),
                      {("asset.bytes_missing", AT)}),
    "corrupt bytes": (standard, entry("a"), Verify(mismatch=[sha("a")]),
                      {("store.hash_mismatch", AT)}),
    "a corrupt record": (corrupt_library, entry("a", pin=LOOP_A), Verify(),
                         {("motion.identity_mismatch", AT)}),
    "an unknown still": (standard, {"slot": "a", "asset_version_id": ident("asv", 98)}, Verify(),
                         {("ref.unknown", "/cast/0/asset_version_id")}),
}


@pytest.mark.parametrize("case", CASES)
def test_each_problem_has_its_own_code(case):
    make, cast, verify, expected = CASES[case]
    result = resolve_board(board(cast), make(), verify)
    assert problems(result) == expected
    assert not result.complete


def test_corrupt_bytes_fail_and_missing_bytes_are_invalid():
    lib = standard()
    corrupt = resolve_board(board(entry("a")), lib, Verify(mismatch=[sha("a")]))
    missing = resolve_board(board(entry("a")), lib, Verify(missing=[sha("a")]))
    assert [v.status for v in corrupt.problems] == ["failed"]
    assert [v.status for v in missing.problems] == ["invalid"]


def test_every_code_is_named_once():
    assert len(set(CODES)) == len(CODES)
    seen = {rule for case in CASES.values() for rule, _ in case[3]}
    assert seen <= set(CODES)
    # Tested below: scope with a production, the drive track with resolve_timed.
    assert set(CODES) - seen == {"asset.scope_mismatch", "motion.drive_track_mismatch"}


def test_the_set_pin_is_checked():
    lib = standard()
    doll_as_set = resolve_story(story(board(entry("a")), set_pin=LOOP_A), lib, Verify())[0]
    timed_as_set = resolve_story(story(board(entry("a")), set_pin=TIMED_A), lib, Verify())[0]
    at = "/set/motion_asset_version_id"
    assert problems(doll_as_set) == {("asset.capability_mismatch", at),
                                     ("motion.still_mismatch", at)}
    assert problems(timed_as_set) == {("motion.timed_not_loop", at)}


def test_two_promoted_set_loops_are_ambiguous():
    lib = library(loop_a(), version(set_block(), n=SET_LOOP, clip=sha("9")),
                  version(set_block(source={**set_block()["source"], "seed": 7}), n=15,
                          clip=sha("7")))
    result = resolve_story(story(board(entry("a"))), lib, Verify())[0]
    assert problems(result) == {("motion.clip_ambiguous", "/set/motion_asset_version_id")}


def test_a_set_loop_with_no_recorded_still_resolves_only_by_pin():
    lib = library(loop_a(), version({k: v for k, v in set_block().items() if k != "still_sha256"},
                                    n=SET_LOOP, clip=sha("9")))
    assert resolve_story(story(board(entry("a"))), lib, Verify())[0].set is None
    pinned = resolve_story(story(board(entry("a")), set_pin=SET_LOOP), lib, Verify())[0]
    assert pinned.complete and pinned.set.version_id == ident("asv", SET_LOOP)


def test_the_production_scope_is_respected():
    other = loop_a()
    other["scope"] = {"production_id": "prd_01M79V9FC00000000000000002"}
    other["content"]["locator"] = other["content"]["locator"].replace(
        "prd_01M79V9FC00000000000000001", "prd_01M79V9FC00000000000000002")
    lib = library(other)
    result = resolve_story(story(board(entry("a"))), lib, Verify())[0]
    assert problems(result) == {("motion.clip_absent", "/boards/0/cast/0/motion_asset_version_id")}


def test_verify_is_asked_once_per_clip():
    verify = Verify()
    lib = standard()
    resolve_story(story(board(entry("a"), entry("b", pin=LOOP_A)), board(entry("a")),
                        set_pin=SET_LOOP), lib, verify)
    assert sorted(verify.asked) == sorted({
        (lib.version(ident("asv", n)).content.locator, lib.version(ident("asv", n)).content.sha256)
        for n in (LOOP_A, SET_LOOP)})


def test_a_clip_with_a_blocking_problem_is_not_returned():
    result = resolve_board(board(entry("a")), standard(), Verify(mismatch=[sha("a")]))
    assert result.cast == () and result.clip_for("a") is None
    pinned_set = resolve_story(story(board(entry("a")), set_pin=LOOP_A), standard(), Verify())[0]
    assert pinned_set.set is None and not pinned_set.complete


OTHER = "prd_01M79V9FC00000000000000002"


def other_production(document):
    document["scope"] = {"production_id": OTHER}
    document["content"]["locator"] = document["content"]["locator"].replace(
        "prd_01M79V9FC00000000000000001", OTHER)
    return document


def test_a_pin_of_another_production_is_a_scope_mismatch():
    lib = library(other_production(loop_a()))
    result = resolve_board(board(entry("a", pin=LOOP_A)), lib, Verify(),
                           production_id="prd_01M79V9FC00000000000000001")
    assert problems(result) == {("asset.scope_mismatch", AT)}
    assert resolve_board(board(entry("a", pin=LOOP_A)), lib, Verify()).complete  # unscoped


def test_a_malformed_board_never_raises():
    s2v = {"layer": "layered", "motion": "s2v"}
    for bad in ({}, {"cast": 3}, {"cast": [7, {"slot": 3}]}, {"method": "x", "cast": [{}]},
                {"method": s2v, "lines": [{"speaker": []}, 4], "cast": [entry("a")]},
                {"method": s2v, "lines": {"speaker": "a"}, "cast": [entry("a")]}):
        resolve_board(bad, standard(), Verify())
        resolve_story({"boards": [bad], "set": 3}, standard(), Verify())


# Timed clips -------------------------------------------------------------------------------


def test_a_timed_clip_resolves_for_its_drive_track():
    clip, found = resolve_timed(standard(), Verify(), still_sha256=STILL_A,
                                drive_track_sha256=DRIVE, board_frames=153, slot="a")
    assert found == () and clip.version_id == ident("asv", TIMED_A)
    assert clip.phase is None and clip.source_frame(152) == 101


def test_a_timed_clip_for_another_board_length_is_refused():
    _, found = resolve_timed(standard(), Verify(), still_sha256=STILL_A, drive_track_sha256=DRIVE,
                             board_frames=160, slot="a", path="/x")
    assert {(v.rule, v.path) for v in found} == {("motion.drive_track_mismatch", "/x")}


def test_a_loop_is_never_a_timed_clip():
    _, found = resolve_timed(library(loop_a()), Verify(), still_sha256=STILL_A,
                             drive_track_sha256=DRIVE, board_frames=153, slot="a", path="/x")
    assert {(v.rule, v.path) for v in found} == {("motion.clip_absent", "/x")}


def test_stills_used_by_fixtures():
    assert still_version(CAST_A, STILL_A)["content"]["sha256"] == STILL_A
    assert SET_PLATE == 3
