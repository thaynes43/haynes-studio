"""The layered renderer (story 426): which source frame every board frame shows, for
every layer kind, read off the decoded frames; every refusal before the first frame."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from haynes_studio.jsonio import thaw
from haynes_studio.layered import LayeredRenderer, reader
from haynes_studio.layered.errors import (
    CLIP_INVALID,
    DECAL_WEAK,
    METHOD_UNAVAILABLE,
    SOURCE_SHORT,
    UNSUPPORTED,
    LayeredError,
)
from haynes_studio.render.base import SegmentRequest
from haynes_studio.render.clock import loop_phase, pingpong
from haynes_studio.store import HASH_MISMATCH, StoreError
from tests.cache import fixtures as fx
from tests.cache.fixtures import PRODUCTION
from tests.layered import helpers as h
from tests.layered import media


def test_every_speech_to_video_layer_shows_floor_2n_over_3(world, first):
    """TIME-8 at 16 fps: board frame n shows source frame floor(2n / 3); nothing held."""
    frames = h.segment_frames(world, first.plan, h.B1)
    assert len(frames) == 48
    for n, frame in enumerate(frames):
        assert [h.read_slot(world, first.plan, h.B1, slot, frame) for slot in "abc"] == [2 * n // 3] * 3, n


def test_loops_ping_pong_on_the_board_clock_from_their_hashed_phase(world, first):
    """TIME-8a: board frame n shows pingpong(n + phase, N), phase from the board ID and
    slot (P-06); the set loop likewise (slot "set")."""
    frames = h.segment_frames(world, first.plan, h.B2)
    assert len(frames) == 28
    for slot in "ac":
        phase = loop_phase(h.B2, slot, 2 * h.LOOP_N - 2)
        shown = [h.read_slot(world, first.plan, h.B2, slot, f, preset="pair") for f in frames]
        assert shown == [pingpong(n + phase, h.LOOP_N) for n in range(28)], slot
    phase = loop_phase(h.B2, "set", 2 * h.SET_N - 2)
    suns = [round((media.sun_x(f, 2.0) - 8) / 2) for f in frames]  # the sun moves 2 px a frame
    assert suns == [pingpong(n + phase, h.SET_N) for n in range(28)]


def test_an_idle_doll_on_a_speech_to_video_board_loops(world, first):
    frames = h.segment_frames(world, first.plan, h.B4)
    phase = loop_phase(h.B4, "a", 2 * h.LOOP_N - 2)
    assert [h.read_slot(world, first.plan, h.B4, "a", f) for f in frames] == \
        [pingpong(n + phase, h.LOOP_N) for n in range(38)]
    assert [h.read_slot(world, first.plan, h.B4, "c", f) for f in frames] == [2 * n // 3 for n in range(38)]


def segment(first, board):
    planned = first.plan.artifacts[f"{board}/segment"]
    return planned.key.value, thaw(planned.key.document)


def render(world, key, inputs, read=None):
    request = SegmentRequest(key=key, inputs=inputs,
                             open_input=read or reader(world.store, [PRODUCTION, "library"]))
    renderer = LayeredRenderer()
    return renderer, renderer.render(request)


def refused(world, key, inputs, read=None) -> LayeredError | StoreError:
    with pytest.raises((LayeredError, StoreError)) as error:
        render(world, key, inputs, read)
    return error.value


def test_a_short_missing_or_damaged_layer_fails_before_any_frame(world, first):
    key, inputs = segment(first, h.B1)
    fast = copy.deepcopy(inputs)
    fast["layers"][0]["source_fps"] = 24  # 48 source frames needed; the clip has 37
    assert refused(world, key, fast).code == SOURCE_SHORT
    key2, idle = segment(first, h.B2)
    more = copy.deepcopy(idle)
    more["layers"][0]["clip_frames"] = h.LOOP_N + 1  # the record says 14; 13 were keyed
    assert refused(world, key2, more).code == SOURCE_SHORT
    fewer = copy.deepcopy(idle)
    fewer["layers"][0]["clip_frames"] = h.LOOP_N - 1
    assert refused(world, key2, fewer).code == CLIP_INVALID
    long_loop = copy.deepcopy(idle)
    long_loop["layers"][0]["trim_frames"] = h.LOOP_N + 1  # N past the keyed frames
    assert refused(world, key2, long_loop).code == SOURCE_SHORT
    missing = copy.deepcopy(idle)
    missing["layers"][1]["keyed"] = "7" * 64
    assert refused(world, key2, missing).code == SOURCE_SHORT
    no_set = copy.deepcopy(idle)
    no_set["set_layer"]["loop"] = "8" * 64
    assert refused(world, key2, no_set).code == SOURCE_SHORT
    read = reader(world.store, [PRODUCTION])

    def other_bytes(sha256):
        return read(idle["layers"][1]["keyed"] if sha256 == idle["layers"][0]["keyed"] else sha256)
    assert refused(world, key2, idle, other_bytes).code == HASH_MISMATCH


def test_unsupported_segments_are_refused_never_ignored(world, first):
    key, inputs = segment(first, h.B1)

    def changed(**changes):
        out = copy.deepcopy(inputs)
        out.update(changes)
        return out
    cases = {
        METHOD_UNAVAILABLE: [changed(method={"layer": "whole_frame", "motion": "s2v"})],
        UNSUPPORTED: [
            changed(method={"layer": "whole_frame", "motion": "i2v"}),
            changed(fps=25), changed(extra="input"), changed(layers=[]), changed(set_layer=None),
            changed(whole_frame_clip="9" * 64), changed(layout=None),
            changed(cues=[{"type": "sound"}]),
            changed(cues=[{"type": "move", "slot": "d", "start_ms": 0, "duration_ms": 0,
                           "dx_px": 1, "dy_px": 0, "angle_deg": 0, "steps": 3}]),
            changed(cues=[{"type": "camera", "start_ms": 0, "duration_ms": 0, "zoom_from": 1,
                           "zoom_to": 1.2, "center_px": [1, 1], "easing": "linear"}]),
            changed(cues=[{"type": "camera", "start_ms": 0, "duration_ms": 0, "zoom_from": 1,
                           "zoom_to": 1.2, "center_px": [1, 1], "easing": "ease_out_cubic"}] * 2),
        ],
    }
    for code, documents in cases.items():
        for document in documents:
            assert refused(world, key, document).code == code, document
    # A plan without motion records (story 380's placeholders) cannot be drawn.
    placeholder = fx.plan(h.story_document(), toolchain=h.TOOLS, pinned=False, blobs=world.blobs)
    doc = thaw(placeholder.artifacts[f"{h.B2}/segment"].key.document)
    assert refused(world, key, doc).code == UNSUPPORTED


def test_a_layout_that_cannot_place_a_slot_is_refused(world, first):
    key, inputs = segment(first, h.B1)
    unplaced = copy.deepcopy(inputs)
    del unplaced["layout"]["slots"]["c"]
    off = copy.deepcopy(inputs)
    off["layout"]["slots"]["c"]["x"] = 3.0
    crop = copy.deepcopy(inputs)
    crop["layout"]["slots"]["c"]["crop"] = [0.5, 0, 0.2, 1]
    for document in (unplaced, off, crop):
        assert refused(world, key, document).code == "layered.layout_invalid"


def test_a_weak_decal_track_fails_the_board_unless_its_record_allows_it(tmp_path):
    weak = h.make_world(tmp_path / "weak", weak="a")
    document = h.story_document()
    document.update(boards=[fx.board_of(document, h.B2)], board_order=[h.B2])
    with pytest.raises(LayeredError) as error:
        h.build(weak, document, h.RUN[1])
    assert error.value.code == DECAL_WEAK
    check = error.value.check
    assert check["check"] == "layered.decal_gate" and not check["passed"]
    assert check["result"]["failed_frames"] == 0 and check["result"]["min_ecc"] < 0.8
    assert check["thresholds"] == {"min_ecc": 0.8}
    # The same clip, recorded with a floor below its track (a record a person wrote):
    loose = [d for d in weak.docs if d["id"] != h.LOOP["a"]]
    loop = next(d for d in weak.docs if d["id"] == h.LOOP["a"])
    allowed = h.loop_doc(weak, fx.ident("asv", 160), 220, still_sha=loop["motion"]["still_sha256"],
                         clip=media.doll_clip(h.LOOP_N, moving=False, weak=True),
                         start=media.start_image(), number=3, decal_min_ecc=0.5)
    from haynes_studio.library import Library
    built = h.build(weak, document, h.RUN[2], (h.RUN[1],),
                    library=Library.from_version_documents([*loose, allowed]))
    checks = built.renderer.checks[built.plan.artifacts[f"{h.B2}/segment"].key.value]
    assert {c["slot"]: c["passed"] for c in checks} == {"a": True, "c": True}
    assert built.stages.made["keyed"] == []  # the keyed frames were made once, then gated


def test_motion_style_cues_and_foreground_draw_without_touching_the_clock(world, first, tmp_path):
    """Talk bounce, moves, a camera push and the foreground edge are drawn (frames
    differ from the still style) and remain a function of the board alone."""
    document = h.story_document(style={"idle_scale": 0.3, "talk_hop": 34, "talk_tilt": 3.2,
                                       "talk_shuffle": 7}, foreground=True)
    b1 = fx.board_of(document, h.B1)
    b1["cues"] = [
        {"id": fx.ident("cue", 1), "type": "move", "slot": "b", "anchor": {"at_ms": 300},
         "duration_ms": 250, "dx_px": 30, "dy_px": 0, "angle_deg": -4, "steps": 3},
        {"id": fx.ident("cue", 2), "type": "camera", "anchor": {"after_line_id": h.L2, "offset_ms": 0},
         "duration_ms": 350, "zoom_from": 1.0, "zoom_to": 1.2, "center_px": [180, 400],
         "easing": "ease_out_cubic"}]
    document.update(boards=[b1], board_order=[h.B1])
    moved = h.build(world, document, h.RUN[20], (h.RUN[1],))
    assert moved.stages.made == {"drive": [], "s2v_clip": [], "keyed": []}  # only the segment
    ours = h.segment_frames(world, moved.plan, h.B1)
    plain = h.segment_frames(world, first.plan, h.B1)
    assert any(not np.array_equal(a, b) for a, b in zip(ours, plain))
    assert not np.array_equal(ours[-1], plain[-1])  # zoomed in at the end
