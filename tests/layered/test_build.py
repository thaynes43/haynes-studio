"""The layered adapter through the cache (story 426): what a build makes, reuses and
never asks again; edits rebuild only what contract section 4 says; an earlier board's
length changes no frame of a later board; a library timed clip made from the board's
own drive track is used and never made again."""

from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json

import numpy as np
import pytest

from haynes_studio.cache import CacheError
from haynes_studio.motion.winter_menu import complete_block
from haynes_studio.render.encode import decode_frames
from tests.cache import fixtures as fx
from tests.layered import helpers as h
from tests.layered import media
from tests.motion import fixtures as mf


def names(plan, *parts):
    return {name for name in plan.artifacts if all(p in name for p in parts)}


def frame_inputs(plan, board):
    """Hashes at each stage, plus the segment's layer order and board-clock inputs."""
    return {
        "artifacts": {name: {"key": artifact.key.value, "content": artifact.content}
                      for name, artifact in sorted(plan.artifacts.items())
                      if name.startswith(f"{board}/")},
        "segment_inputs": plan.artifacts[f"{board}/segment"].key.inputs(),
    }


def assert_same_frames(board, ours, theirs, inputs):
    """Exact equality, with zero-based board frames and input hashes on a mismatch."""
    if len(ours) != len(theirs):
        pytest.fail(f"board={board} frame counts differ: {len(ours)} != {len(theirs)}\n{inputs()}",
                    pytrace=False)
    first = None
    largest, largest_frame = 0, None
    for n, (a, b) in enumerate(zip(ours, theirs)):
        if np.array_equal(a, b):
            continue
        if a.shape != b.shape:
            pytest.fail(f"board={board} frame={n} shapes differ: {a.shape} != {b.shape}\n{inputs()}",
                        pytrace=False)
        if first is None:
            first = n
        difference = int(np.abs(a.astype(np.int16) - b.astype(np.int16)).max())
        if difference > largest:
            largest, largest_frame = difference, n
    if first is not None:
        pytest.fail(f"board={board} first differing frame={first} max_abs_diff={largest} "
                    f"at frame={largest_frame}\n{inputs()}", pytrace=False)


def test_frame_mismatch_reports_board_frame_and_largest_unsigned_pixel_difference():
    black = np.zeros((1, 1, 3), dtype=np.uint8)
    ours = [black, np.full_like(black, 255)]
    theirs = [np.full_like(black, 1), black]
    with pytest.raises(pytest.fail.Exception) as error:
        assert_same_frames("B4", ours, theirs, lambda: "input-layer-hashes")
    assert str(error.value) == ("board=B4 first differing frame=0 max_abs_diff=255 at frame=1\n"
                                "input-layer-hashes")


def test_frame_mismatch_reports_every_input_layers_hash(world, first):
    black = np.zeros((1, 1, 3), dtype=np.uint8)
    with pytest.raises(pytest.fail.Exception) as error:
        assert_same_frames(h.B4, [black], [np.ones_like(black)], lambda: json.dumps(
            frame_inputs(first.plan, h.B4), sort_keys=True))
    diagnostic = json.loads(str(error.value).split("\n", 1)[1])
    inputs, artifacts = diagnostic["segment_inputs"], diagnostic["artifacts"]
    assert [layer["slot"] for layer in inputs["layers"]] == list("abc")
    for layer, slot, role in zip(inputs["layers"], "abc", ("doll_clip", "s2v_clip", "s2v_clip")):
        assert layer["still"] == world.blobs[h.STILL[slot]]
        for field, stage in (("clip", role), ("keyed", "keyed")):
            name = f"{h.B4}/{stage}/{slot}"
            assert layer[field] == first.plan.artifacts[name].content == artifacts[name]["content"]
            assert artifacts[name]["key"] == first.plan.artifacts[name].key.value
    assert inputs["set_layer"]["plate"] == world.blobs[h.PLATE]
    assert inputs["set_layer"]["loop"] == world.library().version(h.SET_LOOP).content.sha256
    assert inputs["voice_envelope"] == first.plan.artifacts[f"{h.B4}/voice_track"].content


def test_a_first_build_makes_every_layer_and_renders_every_board(first):
    assert len(first.builder.rendered) == 3
    assert {k: len(v) for k, v in first.stages.made.items()} == {"drive": 5, "s2v_clip": 5, "keyed": 7}
    assert len(first.source.calls) == 5  # B1 a, b, c; B4 b, c
    assert [b.frames for b in first.plan.boards] == [48, 28, 38]


def test_a_second_build_renders_nothing_keys_nothing_and_asks_the_source_nothing(world, first):
    second = h.build(world, h.story_document(), h.RUN[2], (h.RUN[1],))
    assert second.builder.rendered == [] and second.builder.spliced == []
    assert second.stages.made == {"drive": [], "s2v_clip": [], "keyed": []}
    assert second.source.calls == []
    assert second.plan.keys() == first.plan.keys()


def test_a_line_edit_rebuilds_only_that_speakers_layer_and_board(world, first):
    document = h.story_document()
    fx.board_of(document, h.B1)["lines"][2]["text"] = "Do."  # c's line, same length
    edited = h.build(world, document, h.RUN[3], (h.RUN[1],))
    c = {f"{h.B1}/drive/c", f"{h.B1}/s2v_clip/c", f"{h.B1}/keyed/c"}
    assert edited.stages.made == {k: [edited.plan.artifacts[n].key.value for n in sorted(c) if f"/{p}/" in n]
                                  for k, p in (("drive", "drive"), ("s2v_clip", "s2v_clip"), ("keyed", "keyed"))}
    assert [r.seed for r in edited.source.calls] == [13]  # only c's clip, with her seed
    assert edited.builder.rendered == [edited.plan.artifacts[f"{h.B1}/segment"].key.value]


def test_an_earlier_boards_length_changes_no_frame_of_a_later_board(world, first, tmp_path):
    longer = h.story_document(b1_lead=400)  # B1 starts its lines 300 ms later: 7 more frames
    edited = h.build(world, longer, h.RUN[4], (h.RUN[1],))
    assert [b.frames for b in edited.plan.boards] == [55, 28, 38]
    assert edited.builder.rendered == [edited.plan.artifacts[f"{h.B1}/segment"].key.value]
    for board in (h.B2, h.B4):
        assert edited.plan.artifacts[f"{board}/segment"] == first.plan.artifacts[f"{board}/segment"]
    # A full render of the edited story in an empty store draws B2 and B4 frame for frame
    # as the first build did: nothing they draw depends on where they land in the film.
    fresh = h.make_world(tmp_path / "fresh")
    alone = h.build(fresh, longer, h.RUN[1])
    assert len(alone.builder.rendered) == 3
    for board in (h.B2, h.B4):
        ours, theirs = h.segment_frames(world, first.plan, board), h.segment_frames(fresh, alone.plan, board)
        assert_same_frames(board, ours, theirs, lambda: json.dumps({
            "first": frame_inputs(first.plan, board), "fresh": frame_inputs(alone.plan, board),
        }, sort_keys=True))


def test_the_film_holds_every_boards_frames_in_order(world, first):
    film = list(decode_frames(world.read(first.plan.film_picture.content)))
    assert len(film) == first.plan.frames == 48 + 28 + 38  # TIME-11
    at = 0
    for board in first.plan.boards:
        segment = h.segment_frames(world, first.plan, board.board_id)
        assert all(np.array_equal(film[at + n], segment[n]) for n in (0, board.frames - 1))
        at += board.frames


def timed_doc(world, *, still: str, start: bytes, drive: str, board_frames: int, frames: int,
              version: str, asset: int, seed: int) -> dict:
    """A promoted timed clip of ``still`` made from ``drive`` (TIME-8: 16 fps)."""
    clip = media.doll_clip(frames, fps=16, moving=False)
    clip_sha = world.publish(clip, "video/mp4")
    needed = (board_frames - 1) * 16 // 24 + 1
    block = mf.timed_block(still_sha256=still, frames=frames, width=media.CLIP_W, height=media.CLIP_H,
                           trim={"start": 0, "frames": needed},
                           drive_track={"sha256": drive, "board_frames": board_frames},
                           keying={**h.KEYING, "decal_min_ecc": 0.5})
    block["source"] = {**block["source"], "image_sha256": world.publish(start, "image/png"),
                       "seed": seed}
    doc = mf.version(None, n=1, clip=clip_sha)
    doc["provenance"]["generator"]["seed"] = seed
    doc["motion"] = complete_block(block, clip_sha)
    doc["content"]["bytes"] = len(clip)
    return fx.scoped(doc, version, asset)


def test_a_library_timed_clip_made_from_the_boards_drive_track_is_used(world, first):
    drive = first.plan.artifacts[f"{h.B4}/drive/b"].content
    still = world.blobs[h.STILL["b"]]
    doc = timed_doc(world, still=still, start=media.start_image(tint=h.TINT["b"]), drive=drive,
                    board_frames=38, frames=30, version=fx.ident("asv", 150), asset=250, seed=41)
    built = h.build(world, h.story_document(), h.RUN[5], (h.RUN[1],), library=world.library(doc))
    assert built.plan.artifacts[f"{h.B4}/s2v_clip/b"].content == doc["content"]["sha256"]
    assert built.source.calls == []  # nothing is generated for b on B4
    assert built.stages.made["s2v_clip"] == [] and len(built.stages.made["keyed"]) == 1
    assert built.builder.rendered == [built.plan.artifacts[f"{h.B4}/segment"].key.value]
    report = built.renderer.reports[built.plan.artifacts[f"{h.B4}/segment"].key.value]
    b = next(layer for layer in report.layers if layer["slot"] == "b")
    assert (b["play"], b["first"], b["last"], b["trimmed"]) == ("timed", 0, 24, 5)  # 30 - 25
    # A seed edit is a re-roll: the stored clip was made with seed 41, so b on B4 gets a
    # new clip from the source (contract section 4, "Seed"), and nothing else changes.
    rerolled = h.story_document()
    fx.board_of(rerolled, h.B4)["seeds"]["s2v:b"] = 1041
    again = h.build(world, rerolled, h.RUN[8], (h.RUN[1], h.RUN[5]), library=world.library(doc))
    assert [r.seed for r in again.source.calls] == [1041]
    assert again.plan.artifacts[f"{h.B4}/s2v_clip/b"].content != doc["content"]["sha256"]
    assert again.builder.rendered == [again.plan.artifacts[f"{h.B4}/segment"].key.value]


def test_a_speakers_loop_of_another_size_than_speech_to_video_stops_the_plan(world, first):
    tools = replace(h.TOOLS, s2v_profile={**h.S2V_PROFILE, "size": [160, 256]})
    with pytest.raises(CacheError) as error:
        h.build(world, h.story_document(), h.RUN[9], (h.RUN[1],), tools=tools)
    assert error.value.code == "cache.key_input_invalid" and "keying boxes" in error.value.message


def test_a_cast_still_without_a_loop_stops_the_plan(world):
    library = world.library(without=frozenset({h.LOOP["c"]}))
    with pytest.raises(CacheError) as error:
        h.build(world, h.story_document(), h.RUN[6], (h.RUN[1],), library=library)
    assert error.value.code == "motion.clip_absent"


def test_a_new_cast_still_version_plays_its_own_loop(world, first):
    document = h.story_document()
    for board in document["boards"]:
        for entry in board["cast"]:
            if entry["asset_version_id"] == h.STILL["a"]:
                entry["asset_version_id"] = h.STILL2["a"]
    built = h.build(world, document, h.RUN[7], (h.RUN[1],))
    loop2 = world.library().version(h.LOOP2["a"])
    assert built.plan.artifacts[f"{h.B2}/doll_clip/a"].content == loop2.content.sha256
    (request,) = built.source.calls  # a speaks on B1: her new loop's start image
    assert request.start_image_sha256 == loop2.motion["source"]["image_sha256"]
    assert hashlib.sha256(request.start_image).hexdigest() == request.start_image_sha256
    assert len(built.builder.rendered) == 3  # B4 places a as an idle doll too
    assert copy.deepcopy(built.plan.keys()) != first.plan.keys()
