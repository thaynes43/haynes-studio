"""The invalidation table of contract section 4, row by row (story 380).

Each test makes one edit to the four-board fixture story and compares the key plans
before and after: the artifacts whose key changed or that are new must be exactly the
documented set, and everything else keeps its key (so the cache reuses it). Where the
keys as written do not give the table's wording, the test asserts what the keys give
and says so; the PR reports those rows to the contract owner.
"""

from __future__ import annotations

import copy
import re
from dataclasses import replace

import pytest

from haynes_studio.cache.plan import KeyDiff, MediaFormat, Toolchain, diff
from tests.cache import fixtures as fx
from tests.cache.fixtures import B1, B2, B3, B4, B5, L1, L2, L3, L4, L5, L6, L7
from tests.support.policy import REPO_ROOT

CHECKS = {"check/master.decode", "check/master.transcript"}
FILM = {"film/picture", "film/mix", "film/master", "film/proxy"} | CHECKS
PICTURE_FILM = FILM - {"film/mix"}  # a picture-only edit: the mix keeps its key
MIX_FILM = FILM - {"film/picture"}  # a mix-only edit: every picture keeps its key


def take(board: str, line: str) -> str:
    return f"{board}/take/{line}"


def s2v(board: str, slot: str) -> set[str]:
    """A speaker's speech-to-video chain on a board: drive track, clip, keyed frames."""
    return {f"{board}/drive/{slot}", f"{board}/s2v_clip/{slot}", f"{board}/keyed/{slot}"}


def seg(*boards: str) -> set[str]:
    return {f"{board}/segment" for board in boards}


def track(*boards: str) -> set[str]:
    return {f"{board}/voice_track" for board in boards}


def of_board(names, board: str) -> set[str]:
    return {name for name in names if name.startswith(board + "/")}


def edit(change=None, **after) -> tuple[KeyDiff, object, object]:
    """Plan the fixture, apply ``change`` to a copy of its document (and ``after``'s
    plan options), plan again and compare."""
    document = fx.story_document()
    before = fx.plan(document)
    edited = copy.deepcopy(document)
    if change is not None:
        change(edited)
    second = fx.plan(edited, **after)
    return diff(before, second), before, second


def frames(plan, board: str) -> int:
    return next(b.frames for b in plan.boards if b.board_id == board)


def line(document, board: str, line_id: str) -> dict:
    return next(item for item in fx.board_of(document, board)["lines"] if item["id"] == line_id)


def assert_only(d: KeyDiff, rebuilt: set[str], *, removed: set[str] = frozenset()) -> None:
    """Exactly ``rebuilt`` changed or appeared and exactly ``removed`` went away;
    every other artifact kept its key."""
    assert d.rebuilt == rebuilt, (f"unexpected: {sorted(d.rebuilt - rebuilt)}; "
                                  f"missing: {sorted(rebuilt - d.rebuilt)}")
    assert d.removed == removed


# Rows of the table, in the contract's order -------------------------------------------


def test_line_text_same_length_rebuilds_the_take_its_speaker_and_the_segment():
    def change(doc):
        line(doc, B1, L3)["text"] = "Noted and ignored!"  # same length: same take length

    d, before, after = edit(change)
    assert frames(before, B1) == frames(after, B1)
    assert_only(d, {take(B1, L3)} | track(B1) | s2v(B1, "c") | seg(B1) | FILM)


def test_line_text_with_a_new_length_also_rebuilds_every_speaker_with_a_later_line():
    def change(doc):
        line(doc, B1, L2)["text"] = "Objection, again!!"  # one character: +10 ms

    d, before, after = edit(change)
    assert frames(before, B1) == frames(after, B1)  # the edit stays inside the frame
    # a speaks only before the edit: reused. b (edited) and c (later line) rebuild.
    assert_only(d, {take(B1, L2)} | track(B1) | s2v(B1, "b") | s2v(B1, "c") | seg(B1) | FILM)


def test_line_text_that_changes_the_frames_rebuilds_every_s2v_clip_of_the_board():
    def change(doc):
        line(doc, B1, L3)["text"] = "Noted, minuted, filed and then ignored entirely."

    d, before, after = edit(change)
    assert frames(before, B1) != frames(after, B1)
    assert_only(d, {take(B1, L3)} | track(B1) | s2v(B1, "a") | s2v(B1, "b") | s2v(B1, "c")
                | seg(B1) | FILM)


def test_line_added_makes_only_its_take_and_rebuilds_that_board():
    def change(doc):
        fx.board_of(doc, B4)["lines"].append(
            {"id": L7, "speaker": "c", "text": "Carried.", "gap_before_ms": 300})

    d, before, after = edit(change)
    assert frames(before, B4) != frames(after, B4)
    assert d.added == {take(B4, L7)}  # TTS only for the new take
    assert_only(d, {take(B4, L7)} | track(B4) | s2v(B4, "b") | s2v(B4, "c") | seg(B4) | FILM)


def test_line_removed_drops_its_take_and_rebuilds_that_board_only():
    def change(doc):
        lines = fx.board_of(doc, B1)["lines"]
        lines[:] = [item for item in lines if item["id"] != L3]

    d, before, after = edit(change)
    assert frames(before, B1) != frames(after, B1)  # 780 ms shorter
    # c no longer speaks on B1: her speech-to-video layer becomes an idle doll layer.
    assert d.removed == {take(B1, L3), f"{B1}/drive/c", f"{B1}/s2v_clip/c"}
    assert_only(d, track(B1) | {f"{B1}/keyed/c", f"{B1}/doll_clip/c"} | s2v(B1, "a")
                | s2v(B1, "b") | seg(B1) | FILM, removed=d.removed)


def test_line_speaker_rebuilds_its_take_and_the_old_and_new_speakers():
    def change(doc):
        line(doc, B1, L2)["speaker"] = "c"  # b's line goes to c (another voice)

    d, before, after = edit(change)
    assert frames(before, B1) == frames(after, B1)
    # b keeps no line on B1, so her S2V layer is replaced by a doll layer.
    assert d.removed == {f"{B1}/drive/b", f"{B1}/s2v_clip/b"}
    assert d.added == {f"{B1}/doll_clip/b"}
    assert_only(d, {take(B1, L2)} | track(B1) | {f"{B1}/keyed/b", f"{B1}/doll_clip/b"}
                | s2v(B1, "c") | seg(B1) | FILM, removed=d.removed)
    assert s2v(B1, "a") <= d.kept and {take(B1, L1), take(B1, L3)} <= d.kept


def test_line_speaker_between_two_slots_of_one_voice_still_rebuilds_the_segment():
    """Same take, same track: only who speaks changes. The segment's ``talk`` input
    (proposal) keys which doll the voice envelope moves, so the bounce is redrawn."""
    document = fx.story_document()
    document["cast"][2]["voice_version_id"] = fx.VOICE_A  # a and c share one voice
    before = fx.plan(document)
    edited = copy.deepcopy(document)
    line(edited, B2, L4)["speaker"] = "a"  # the layered I2V board: talk bounce only
    line(edited, B1, L3)["speaker"] = "a"  # the layered S2V board: drive tracks too
    d = diff(before, fx.plan(edited))
    assert {take(B2, L4), take(B1, L3)} <= d.kept and track(B1, B2) <= d.kept
    assert d.removed == {f"{B1}/drive/c", f"{B1}/s2v_clip/c"}
    assert_only(d, seg(B1, B2) | {f"{B1}/drive/a", f"{B1}/s2v_clip/a", f"{B1}/keyed/a",
                                  f"{B1}/keyed/c", f"{B1}/doll_clip/c"} | PICTURE_FILM,
                removed=d.removed)


def test_gap_edit_reassembles_without_tts_and_rebuilds_only_later_speakers():
    def change(doc):
        line(doc, B1, L3)["gap_before_ms"] = 310

    d, before, after = edit(change)
    assert frames(before, B1) == frames(after, B1)
    assert_only(d, track(B1) | s2v(B1, "c") | seg(B1) | FILM)  # no take: no TTS


def test_lead_edit_moves_every_speaker():
    def change(doc):
        fx.board_of(doc, B1)["timing"]["lead_ms"] = 490

    d, before, after = edit(change)
    assert frames(before, B1) == frames(after, B1)
    assert_only(d, track(B1) | s2v(B1, "a") | s2v(B1, "b") | s2v(B1, "c") | seg(B1) | FILM)


def test_tail_edit_inside_the_frame_changes_no_key():
    def change(doc):
        fx.board_of(doc, B1)["timing"]["tail_ms"] = 710

    d, before, after = edit(change)
    assert frames(before, B1) == frames(after, B1)
    assert_only(d, set())


def test_tail_edit_that_changes_the_frames_rebuilds_the_s2v_clips_and_segment():
    def change(doc):
        fx.board_of(doc, B1)["timing"]["tail_ms"] = 1700

    d, before, after = edit(change)
    assert frames(before, B1) != frames(after, B1)
    assert_only(d, s2v(B1, "a") | s2v(B1, "b") | s2v(B1, "c") | seg(B1) | FILM)


def test_hold_edit_rebuilds_the_segment_and_reuses_the_whole_frame_clip():
    def change(doc):
        fx.board_of(doc, B3)["timing"]["hold_ms"] = 3000

    d, before, after = edit(change)
    assert frames(before, B3) != frames(after, B3)
    assert f"{B3}/whole_frame_clip" in d.kept  # the requested clip lengths are unchanged
    assert_only(d, seg(B3) | FILM)


def test_hold_edit_past_the_requested_clip_length_rebuilds_the_whole_frame_clip():
    def change(doc):
        fx.board_of(doc, B3)["timing"]["hold_ms"] = 6000  # 144 frames: two 121-frame clips

    d, _, _ = edit(change)
    assert_only(d, {f"{B3}/whole_frame_clip"} | seg(B3) | FILM)


def test_hold_edit_inside_the_frame_changes_no_key():
    """Not in the table's wording ("segment"): a hold edit that keeps the frame count
    changes no key, as the tail row says for tails. Reported to the contract owner."""
    def change(doc):
        fx.board_of(doc, B3)["timing"]["hold_ms"] = 1910

    d, before, after = edit(change)
    assert frames(before, B3) == frames(after, B3)
    assert_only(d, set())


def test_reorder_reuses_every_board_and_rebuilds_the_film():
    def change(doc):
        doc["board_order"] = [B1, B3, B2, B4]

    d, _, _ = edit(change)
    assert_only(d, FILM)  # film offsets move: the picture's order and the mix's F[k]


def test_add_a_board_makes_only_that_board():
    def change(doc):
        doc["boards"].append(fx.extra_board())
        doc["board_order"].append(B5)

    d, _, after = edit(change)
    assert d.added == {name for name in after.keys() if name.startswith(B5 + "/")}
    assert d.added >= seg(B5) | {take(B5, L7)}
    assert d.changed == FILM and not d.removed


def test_remove_a_board_drops_only_that_board():
    def change(doc):
        doc["boards"] = [board for board in doc["boards"] if board["id"] != B2]
        doc["board_order"].remove(B2)

    d, before, _ = edit(change)
    assert d.removed == {name for name in before.keys() if name.startswith(B2 + "/")}
    assert d.changed == FILM and not d.added


def test_method_edit_rebuilds_that_boards_clips_and_segment():
    def change(doc):
        board = fx.board_of(doc, B2)
        board["method"]["motion"] = "s2v"
        board["seeds"] = {"s2v:c": 21}

    d, _, _ = edit(change)
    # c speaks on B2: an S2V layer replaces her doll layer; a stays an idle doll.
    assert d.removed == {f"{B2}/doll_clip/c"}
    assert_only(d, s2v(B2, "c") | seg(B2) | PICTURE_FILM, removed=d.removed)
    assert {f"{B2}/doll_clip/a", f"{B2}/keyed/a", take(B2, L4)} <= d.kept | set()


def test_s2v_seed_edit_rebuilds_that_clip_and_segment():
    def change(doc):
        fx.board_of(doc, B1)["seeds"]["s2v:a"] = 99

    d, _, _ = edit(change)
    assert f"{B1}/drive/a" in d.kept
    assert_only(d, {f"{B1}/s2v_clip/a", f"{B1}/keyed/a"} | seg(B1) | PICTURE_FILM)


def test_i2v_seed_edit_rebuilds_that_clip_and_segment():
    def change(doc):
        fx.board_of(doc, B3)["seeds"]["i2v:frame"] = 99

    d, _, _ = edit(change)
    assert_only(d, {f"{B3}/whole_frame_clip"} | seg(B3) | PICTURE_FILM)


def swap_still(old: str, new: str):
    """Every board placing ``old`` places ``new`` (the next version of that still)."""
    def change(doc):
        for board in doc["boards"]:
            for entry in board["cast"]:
                if entry["asset_version_id"] == old:
                    entry["asset_version_id"] = new
    return change


def test_cast_still_version_rebuilds_clips_from_it_on_every_board_using_it():
    """Story 426: the new still resolves its own pinned loop, whose start image and
    keying a speaker's S2V clip and keyed frames take."""
    d, _, _ = edit(swap_still(fx.STILL_B, fx.STILL_B2))
    # b is on B1 and B4 (S2V speaker on both); her drive tracks are audio and stay.
    assert {f"{B1}/drive/b", f"{B4}/drive/b"} <= d.kept
    assert_only(d, {f"{B1}/s2v_clip/b", f"{B1}/keyed/b", f"{B4}/s2v_clip/b", f"{B4}/keyed/b"}
                | seg(B1, B4) | PICTURE_FILM)


def test_cast_still_version_of_an_idle_doll_rebuilds_its_doll_clip():
    """Story 426: the idle doll's clip is the new still's pinned library loop (not made
    by the build), and its keyed frames are keyed again."""
    d, _, _ = edit(swap_still(fx.STILL_A, fx.STILL_A2))
    assert_only(d, {f"{B1}/s2v_clip/a", f"{B1}/keyed/a", f"{B2}/doll_clip/a", f"{B2}/keyed/a"}
                | seg(B1, B2) | PICTURE_FILM)


def test_board_photo_version_rebuilds_a_whole_frame_board():
    d, _, _ = edit(blobs={**fx.BLOBS, fx.PHOTO_3: fx.sha("a new photo version")})
    assert_only(d, {f"{B3}/whole_frame_clip"} | seg(B3) | PICTURE_FILM)


def test_board_photo_version_of_a_layered_board_is_reused():
    d, _, _ = edit(blobs={**fx.BLOBS, fx.PHOTO_1: fx.sha("a new photo version")})
    assert_only(d, set())  # Q-03: a layered board's photo is not a build input


def test_layout_preset_values_rebuild_the_segments_using_it():
    def change(doc):
        doc["layouts"]["pair"]["slots"]["c"]["x"] = 0.75

    d, _, _ = edit(change)
    assert_only(d, seg(B2, B4) | PICTURE_FILM)


def test_move_cue_rebuilds_only_the_segment():
    def change(doc):
        fx.board_of(doc, B1)["cues"][0]["dx_px"] = 60

    d, _, _ = edit(change)
    assert_only(d, seg(B1) | PICTURE_FILM)


def test_camera_cue_rebuilds_only_the_segment():
    def change(doc):
        fx.board_of(doc, B3)["cues"][0]["zoom_to"] = 1.3

    d, _, _ = edit(change)
    assert_only(d, seg(B3) | PICTURE_FILM)


@pytest.mark.parametrize("what", ["sound level", "sound trim", "sound anchor", "bed level",
                                  "loudness target", "line rms"])
def test_mix_only_edits_reuse_every_picture(what):
    def change(doc):
        sound = fx.board_of(doc, B1)["cues"][2]
        if what == "sound level":
            sound["level_rms_dbfs"] = -18.5
        elif what == "sound trim":
            sound["trim_ms"] = [0, 300]
        elif what == "sound anchor":
            sound["anchor"] = {"at_ms": 100}
        elif what == "bed level":
            doc["beds"][0]["level_rms_dbfs"] = -38
        elif what == "loudness target":
            doc["mix"]["master_lufs"] = -16
        else:
            doc["mix"]["line_rms_dbfs"] = -20

    d, _, _ = edit(change)
    assert_only(d, MIX_FILM)


@pytest.mark.parametrize("what", ["note", "board title", "story title"])
def test_notes_and_titles_invalidate_nothing(what):
    def change(doc):
        if what == "note":
            fx.board_of(doc, B1)["notes"].append({"id": fx.ident("nte", 1), "text": "louder here"})
        elif what == "board title":
            fx.board_of(doc, B2)["title"] = "Renamed"
        else:
            doc["title"] = "Renamed story"

    d, _, _ = edit(change)
    assert_only(d, set())


def test_story_motion_style_rebuilds_every_segment_with_bounce():
    def change(doc):
        doc["motion_style"]["talk_hop"] = 40

    d, _, _ = edit(change)
    assert_only(d, seg(B1, B2, B4) | PICTURE_FILM)  # every layered board; not whole-frame B3


def test_a_cast_slots_voice_remakes_every_take_of_that_speaker():
    def change(doc):
        doc["cast"][2]["voice_version_id"] = fx.VOICE_N  # c gets another stock voice

    d, _, _ = edit(change)
    takes = {take(B1, L3), take(B2, L4), take(B4, L6)}
    # Per board as "line text" (same text, so same length): c's takes, the tracks,
    # c's S2V layers and the segments; a and b keep their S2V clips.
    assert_only(d, takes | track(B1, B2, B4) | s2v(B1, "c") | s2v(B4, "c") | seg(B1, B2, B4) | FILM)
    assert s2v(B1, "a") | s2v(B1, "b") | s2v(B4, "b") <= d.kept


@pytest.mark.parametrize("tool", ["compositor", "encoder", "s2v_profile", "keyer", "tts_model",
                                  "splicer", "mixer"])
def test_toolchain_digest_rebuilds_every_artifact_that_tool_made(tool):
    tools = Toolchain()
    changed = {
        "compositor": replace(tools, compositor="studio.render.synthetic/2"),
        "encoder": replace(tools, encoder={**tools.encoder, "crf": 20}),
        "s2v_profile": replace(tools, s2v_profile={**tools.s2v_profile, "steps": 6}),
        "keyer": replace(tools, keyer="studio.keyer/2"),
        "tts_model": replace(tools, tts_model="sha256:" + "1" * 64),
        "splicer": replace(tools, splicer="studio.splice/2"),
        "mixer": replace(tools, mixer="studio.mixer/2"),
    }[tool]
    d, _, after = edit(toolchain=changed)
    names = after.keys()
    if tool == "keyer":  # story 380's placeholder path still keys with the toolchain's
        unpinned = diff(fx.plan(fx.story_document(), pinned=False),
                        fx.plan(fx.story_document(), toolchain=changed, pinned=False))
        assert unpinned.rebuilt == {n for n in names if "/keyed/" in n} | seg(B1, B2, B4) | PICTURE_FILM
    s2v_all = s2v(B1, "a") | s2v(B1, "b") | s2v(B1, "c") | s2v(B4, "b") | s2v(B4, "c")
    expected = {
        "compositor": seg(B1, B2, B3, B4) | PICTURE_FILM,
        "encoder": seg(B1, B2, B3, B4) | PICTURE_FILM,
        "s2v_profile": {n for n in s2v_all if "/drive/" not in n} | seg(B1, B4) | PICTURE_FILM,
        # Story 426: keying comes from the pinned records, so the toolchain's keyer
        # changes nothing; a record's keyer does (test_a_records_keyer_rekeys_its_layers).
        "keyer": set(),
        "tts_model": {n for n in names if "/take/" in n} | track(B1, B2, B4) | s2v_all
        | seg(B1, B2, B4) | FILM,
        "splicer": PICTURE_FILM,
        "mixer": MIX_FILM,
    }[tool]
    assert_only(d, expected)


def test_a_records_keyer_rekeys_its_layers():
    """Story 426: c's loop keyed by another keyer is a new version of her loop (a
    record never changes); every layer keyed with it is keyed again: her idle doll on
    B2 and her S2V layers on B1 and B4, which take her loop's keying."""
    before = fx.plan(fx.story_document())
    old = fx.loop_doc(fx.STILL_C, fx.LOOPS[fx.STILL_C], 53)
    new = fx.loop_doc(fx.STILL_C, fx.ident("asv", 57), 53,
                      keying={**fx.KEYING, "keyer": "studio.layered.keyer/1"})
    new["number"], old["state"] = 2, "candidate"
    lib = fx.library(old, new, without=frozenset({fx.LOOPS[fx.STILL_C]}))
    d = diff(before, fx.plan(fx.story_document(), lib=lib))
    # The clip is the same bytes (its key and hash stay); only its keyed frames change.
    assert {f"{B2}/doll_clip/c"} <= d.kept
    assert_only(d, {f"{B1}/keyed/c", f"{B2}/keyed/c", f"{B4}/keyed/c"} | seg(B1, B2, B4)
                | PICTURE_FILM)


def _changed_tool(tools: Toolchain, name: str):
    value = getattr(tools, name)
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return value + 0.5
    if isinstance(value, str):
        return value + "-2"
    if isinstance(value, tuple):
        return (*value, [0, 0, 8, 8])
    if value is None:
        return (1, 2, 3, 4) if name == "decal_box" else "v2"
    if name == "checks":
        return {**value, "master.decode": {**value["master.decode"], "version": "2"}}
    return {**value, "variant": 2}


# What each tool may make, by artifact name. A tool's change must change some key, and
# only keys of what it makes or of what is made from that.
PICTURE = r"/(segment|s2v_clip|doll_clip|whole_frame_clip|keyed)|^film/(picture|master|proxy)$|^check/"
SPOKEN = r"/(take|voice_track|drive)/?|^film/mix$|" + PICTURE[1:]
MADE_BY = {
    "tts_model": SPOKEN, "take_rate": SPOKEN, "speed": SPOKEN, "track_assembler": SPOKEN,
    "mix_rate": SPOKEN, "drive_assembler": SPOKEN, "drive_rate": SPOKEN,
    "s2v_adapter": PICTURE, "s2v_profile": PICTURE, "s2v_prompt": PICTURE,
    "s2v_negative_prompt": PICTURE, "motion_profile": PICTURE, "motion_prompt": PICTURE,
    "motion_seed": PICTURE, "i2v_profile": PICTURE, "i2v_prompt": PICTURE,
    "i2v_clip_frames": PICTURE, "keyer": PICTURE, "key_thresholds": PICTURE,
    "protect_boxes": PICTURE, "decal_box": PICTURE, "decal_version": PICTURE,
    "compositor": PICTURE, "encoder": PICTURE, "procedural_seed": PICTURE, "splicer": PICTURE,
    "mixer": r"^film/(mix|master|proxy)$|^check/", "mux": r"^film/(master|proxy)$|^check/",
    "proxy_profile": r"^film/proxy$", "checks": r"^check/master\.decode$",
}


# Story 426: the layered path plans doll clips and keying from pinned records, so these
# toolchain placeholders change no key of a pinned plan (they still key the placeholder
# path, story 380's, which the layered renderer refuses to draw).
PLACEHOLDERS = {"motion_profile", "motion_prompt", "motion_seed", "keyer", "key_thresholds",
                "protect_boxes", "decal_box", "decal_version"}


@pytest.mark.parametrize("name", [f.name for f in __import__("dataclasses").fields(Toolchain)])
def test_every_toolchain_field_changes_only_what_that_tool_makes(name):
    tools = Toolchain()
    if name == "i2v_clip_frames":
        changed = replace(tools, i2v_clip_frames=40)  # 46 frames now need two clips
    else:
        changed = replace(tools, **{name: _changed_tool(tools, name)})
    d, _, _ = edit(toolchain=changed)
    if name in PLACEHOLDERS:
        assert not d.rebuilt and not d.removed, f"{name} is a placeholder of a pinned plan"
        document = fx.story_document()
        d = diff(fx.plan(document, pinned=False), fx.plan(document, toolchain=changed, pinned=False))
    assert d.rebuilt, f"{name} changes no key"
    assert not d.removed and not d.added
    pattern = re.compile(MADE_BY[name])
    assert not [n for n in d.rebuilt if not pattern.search(n)], name


def test_media_kind_frame_size_rebuilds_every_picture():
    d, _, after = edit(media=MediaFormat(width=640, height=360))  # short (9:16) to video (16:9)
    # Story 426: an idle doll's pinned library loop and its keyed frames are sprites
    # placed by the layout, so they are reused; every generated clip (S2V, whole-frame),
    # an S2V clip's keyed frames and every segment rebuild.
    dolls = {n for n in after.keys() if re.search(r"/doll_clip/", n)}
    idle_keyed = {n.replace("/doll_clip/", "/keyed/") for n in dolls}
    picture = {n for n in after.keys() if re.search(r"/(s2v_clip|whole_frame_clip|keyed|segment)", n)}
    assert dolls | idle_keyed <= d.kept
    # The mix has no picture input and keeps its key (see the PR's observations); the
    # drive tracks are audio and keep theirs.
    assert_only(d, (picture - idle_keyed) | PICTURE_FILM)


def test_another_fps_is_refused_rather_than_half_applied():
    """The fps half of the row does not apply in contract v1: both media kinds deliver
    at 24 fps and board frames are counted at 24 fps (TIME-3)."""
    with pytest.raises(ValueError):
        MediaFormat(width=360, height=640, fps=25)
    with pytest.raises(ValueError):
        MediaFormat(width=361, height=640)


def test_frame_size_at_the_same_aspect_rebuilds_only_segments():
    """Proposal: clips are made for the media kind's aspect and fps, so a size change at
    the same aspect re-composites without regenerating a clip."""
    d, _, _ = edit(media=MediaFormat(width=720, height=1280))
    assert_only(d, seg(B1, B2, B3, B4) | PICTURE_FILM)


# The table in the contract and the table tested are the same table ---------------------

ROWS = {
    "Line text, line added or removed": [
        test_line_text_same_length_rebuilds_the_take_its_speaker_and_the_segment,
        test_line_text_with_a_new_length_also_rebuilds_every_speaker_with_a_later_line,
        test_line_text_that_changes_the_frames_rebuilds_every_s2v_clip_of_the_board,
        test_line_added_makes_only_its_take_and_rebuilds_that_board,
        test_line_removed_drops_its_take_and_rebuilds_that_board_only],
    "Line speaker": [test_line_speaker_rebuilds_its_take_and_the_old_and_new_speakers,
                     test_line_speaker_between_two_slots_of_one_voice_still_rebuilds_the_segment],
    "Lead or gap": [test_gap_edit_reassembles_without_tts_and_rebuilds_only_later_speakers,
                    test_lead_edit_moves_every_speaker],
    "Tail": [test_tail_edit_inside_the_frame_changes_no_key,
             test_tail_edit_that_changes_the_frames_rebuilds_the_s2v_clips_and_segment],
    "Hold (silent board)": [test_hold_edit_rebuilds_the_segment_and_reuses_the_whole_frame_clip,
                            test_hold_edit_past_the_requested_clip_length_rebuilds_the_whole_frame_clip,
                            test_hold_edit_inside_the_frame_changes_no_key],
    "Reorder boards": [test_reorder_reuses_every_board_and_rebuilds_the_film],
    "Add or remove a board": [test_add_a_board_makes_only_that_board,
                              test_remove_a_board_drops_only_that_board],
    "Method (layer or motion)": [test_method_edit_rebuilds_that_boards_clips_and_segment],
    "Seed": [test_s2v_seed_edit_rebuilds_that_clip_and_segment,
             test_i2v_seed_edit_rebuilds_that_clip_and_segment],
    "Cast still version": [test_cast_still_version_rebuilds_clips_from_it_on_every_board_using_it,
                           test_cast_still_version_of_an_idle_doll_rebuilds_its_doll_clip],
    "Board photo version": [test_board_photo_version_rebuilds_a_whole_frame_board,
                            test_board_photo_version_of_a_layered_board_is_reused],
    "Layout preset values": [test_layout_preset_values_rebuild_the_segments_using_it],
    "Move or camera cue": [test_move_cue_rebuilds_only_the_segment,
                           test_camera_cue_rebuilds_only_the_segment],
    "Sound cue, bed, level, loudness target": [test_mix_only_edits_reuse_every_picture],
    "Note or title": [test_notes_and_titles_invalidate_nothing],
    "Story motion style": [test_story_motion_style_rebuilds_every_segment_with_bounce],
    "A cast slot's voice": [test_a_cast_slots_voice_remakes_every_take_of_that_speaker],
    "Toolchain or profile digest": [test_toolchain_digest_rebuilds_every_artifact_that_tool_made,
                                    test_every_toolchain_field_changes_only_what_that_tool_makes,
                                    test_a_records_keyer_rekeys_its_layers],
    "Media kind frame size or fps": [test_media_kind_frame_size_rebuilds_every_picture,
                                     test_frame_size_at_the_same_aspect_rebuilds_only_segments,
                                     test_another_fps_is_refused_rather_than_half_applied],
}


def contract_rows() -> list[str]:
    text = (REPO_ROOT / "docs" / "contracts" / "studio-contracts-v1.md").read_text(encoding="utf-8")
    section = text.split("### Invalidation set per edit", 1)[1].split("\n## ", 1)[0]
    rows = [line.split("|")[1].strip() for line in section.splitlines() if line.startswith("| ")]
    return [row for row in rows if row and row != "Edit"]


def test_every_row_of_the_contracts_table_is_tested_and_no_other():
    assert list(ROWS) == contract_rows()


def test_the_reference_page_lists_every_row():
    page = (REPO_ROOT / "docs" / "reference" / "cache-and-splice.md").read_text(encoding="utf-8")
    missing = [row for row in contract_rows() if f"| {row} |" not in page]
    assert not missing


def test_no_key_document_holds_an_identifier():
    plan = fx.plan(fx.story_document())
    pattern = re.compile(r"\b[a-z]{3}_[0-7][0-9A-HJKMNP-TV-Z]{25}\b")
    for name, planned in plan.artifacts.items():
        assert not pattern.search(planned.key.canonical.decode()), name
