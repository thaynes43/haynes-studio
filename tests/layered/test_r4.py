"""The Winter Menu r4 boards plan and resolve against the E0 motion records (story 426),
from public text only: no media is read. Also the E0 check of the proposals a speaker's
speech-to-video layer is built on (her start image and keying come from her cast
still's loop), against ``clipmap-s2v.json`` as story 457 imported it."""

from __future__ import annotations

import copy
from dataclasses import replace
from functools import cache

from haynes_studio.cache import BoardVoice, TakeFacts, plan_story
from haynes_studio.cache.keys import S2V_CLIP, S2V_DRIVE_TRACK
from haynes_studio.cache.plan import MediaFormat
from haynes_studio.canonical import load_story
from haynes_studio.layered.pin import pin_story
from haynes_studio.motion.record import DOLL, LOOP, MotionRecord
from haynes_studio.motion.resolve import candidates
from haynes_studio.motion.winter_menu import build_e0_motion, load_e0_sources
from haynes_studio.render.clock import loop_phase
from tests.cache import fixtures as fx
from tests.canonical.fixtures import NOW
from tests.layered import helpers as h
from tests.library.fixtures import BY, imported, register, winter_menu
from tests.motion.fixtures import Verify
from tests.support.policy import REPO_ROOT

MEDIA = MediaFormat(width=1080, height=1920)


@cache
def e0():
    return build_e0_motion(load_e0_sources(REPO_ROOT), production_id=imported(4).story["production_id"],
                           licences=register(), by=BY, now=NOW, library=winter_menu(4).library)


def timed_rows():
    return [row for row in e0().rows if row.outcome == "timed clip"]


def r4_document():
    document = copy.deepcopy(imported(4).story)
    for board in document["boards"]:  # the server writes seeds; a test writes them here
        if board["method"]["motion"] == "s2v":
            board["seeds"] = {f"s2v:{line['speaker']}": 500 + i for i, line in enumerate(board["lines"])}
    return document


def r4_plan(asked: list):
    library = e0().library
    document = r4_document()
    story = load_story(copy.deepcopy(document), context="read", source="r4")
    voices = {}
    for board in story.ordered_boards():
        if board.spoken:
            takes = library.takes(board.voice.current_version_id)
            voices[board.id] = BoardVoice(
                takes={t.line_id: TakeFacts(sha256=t.sha256, duration_ms=t.duration_ms) for t in takes},
                track_sha256="0" * 64)  # legacy board voices have no assembled track
    blobs = {v.id: v.content.sha256 for v in library.versions.values() if v.content is not None}
    voice_ids = {v.id: library.assets[v.asset_id].attributes["voice_id"]
                 for v in library.versions.values() if v.kind == "voice"}
    # E0's drive tracks by (board frames, speaker): the build's drive track is assumed to
    # be the one E0's timed clip was made from, so the plan finds that clip.
    drives = {}
    for row in timed_rows():
        record = MotionRecord.from_block(library.version(row.version_id).motion)
        drives[(record.drive_track.board_frames, row.slot)] = record.drive_track.sha256

    def content(key):
        asked.append(key.kind)
        if key.kind == S2V_DRIVE_TRACK:
            return drives[(key.document["frames"], key.document["speaker"])]
        return fx.stand_in(key)
    motion = pin_story(document, library, Verify(), production_id=story.production_id)
    return story, plan_story(story, voices=voices, blobs=blobs, voice_ids=voice_ids,
                             toolchain=replace(h.TOOLS, s2v_profile=fx.Toolchain().s2v_profile),
                             media=MEDIA, content=content, motion=motion)


def test_the_r4_boards_plan_with_the_right_clip_for_every_doll_on_every_board():
    asked: list = []
    story, plan = r4_plan(asked)
    library = e0().library
    assert [b.frames for b in plan.boards] == [153, 94, 146, 84, 83, 122, 46, 251, 108]
    by_number = {b.id: b.number for b in story.boards}
    used = {}
    for name, planned in plan.artifacts.items():
        board, kind, *slot = name.split("/")
        if kind in ("doll_clip", "s2v_clip"):
            version = next(v for v in library.versions.values()
                           if v.kind == "motion" and v.content.sha256 == planned.content)
            used[(by_number[board], kind, slot[0])] = version.legacy["path"].removeprefix("clips/")
    assert used == {
        (1, "s2v_clip", "a"): "s1-a-lightning.mp4", (2, "s2v_clip", "b"): "s2-b-lightning.mp4",
        (3, "s2v_clip", "c"): "s3-c-lightning.mp4", (4, "s2v_clip", "a"): "s4-a-lightning.mp4",
        (5, "s2v_clip", "d"): "s5-d-lightning.mp4", (6, "s2v_clip", "c"): "s6-c-lightning.mp4",
        (7, "doll_clip", "d"): "layer-d-shocked-v2-green.mp4",
        (8, "s2v_clip", "a"): "s8-a-lightning.mp4", (8, "s2v_clip", "b"): "s8-b-lightning.mp4",
        (8, "s2v_clip", "c"): "s8-c-lightning.mp4", (8, "s2v_clip", "d"): "s8-d-lightning.mp4",
        (9, "doll_clip", "a"): "layer-a-green.mp4", (9, "s2v_clip", "b"): "s9-b-lightning.mp4",
        (9, "doll_clip", "c"): "layer-c-suspicious-green.mp4"}
    assert S2V_CLIP not in asked  # every speaker's clip exists: nothing would be generated


def test_the_r4_segments_carry_each_records_play_rule():
    _, plan = r4_plan([])
    for board in plan.boards:
        layers = plan.artifacts[f"{board.board_id}/segment"].key.document["layers"]
        for layer in layers:
            if layer["play"] == "loop":  # TIME-8a, phase on this board (P-06)
                assert (layer["trim_frames"], layer["source_fps"]) == (121, 24)
                assert layer["phase"] == loop_phase(board.board_id, layer["slot"], 240)
            else:  # TIME-8: the record's trim is section 3's worked example
                assert layer["source_fps"] == 16 and layer["phase"] is None
                assert layer["trim_frames"] == (board.frames - 1) * 16 // 24 + 1
        set_layer = plan.artifacts[f"{board.board_id}/segment"].key.document["set_layer"]
        assert set_layer["loop"] is None and set_layer["plate"]  # r4 pins no set loop: a plate


def test_e0s_speech_to_video_clips_started_on_their_cast_stills_loop_image():
    """The proposal (start image = the cast still's loop's ``source.image_sha256``)
    holds for all 11 E0 timed clips; their decal boxes and versions match too. Keying
    differs where E0 keyed a speaking clip by hand: no eye-protect boxes on A's three
    clips, and the gate floors of six clips (the reference lists them)."""
    library = e0().library
    protect, floors = [], []
    for row in timed_rows():
        timed = MotionRecord.from_block(library.version(row.version_id).motion)
        (loop,) = candidates(library, use=LOOP, subject=DOLL, still_sha256=timed.still_sha256,
                             production_id=imported(4).story["production_id"])
        loop = MotionRecord.from_block(loop.motion)
        assert timed.source.image_sha256 == loop.source.image_sha256, row.name
        assert (timed.keying.decal_box, timed.keying.decal_version, timed.keying.keyer,
                dict(timed.keying.key_thresholds)) == (loop.keying.decal_box, loop.keying.decal_version,
                                                       loop.keying.keyer, dict(loop.keying.key_thresholds))
        if timed.keying.protect_boxes != loop.keying.protect_boxes:
            protect.append(row.name)
        if timed.keying.decal_min_ecc != loop.keying.decal_min_ecc:
            floors.append((row.name, timed.keying.decal_min_ecc, loop.keying.decal_min_ecc))
    assert len(timed_rows()) == 11
    assert sorted(protect) == ["s1-a-lightning", "s4-a-lightning", "s8-a-lightning"]
    assert sorted(floors) == [("s1-a-lightning", 0.7, 0.8), ("s2-b-lightning", 0.8, 0.65),
                              ("s5-d-lightning", 0.8, 0.6), ("s8-b-lightning", 0.8, 0.65),
                              ("s8-d-lightning", 0.8, 0.6), ("s9-b-lightning", 0.78, 0.65)]
