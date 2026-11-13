"""The drawing rules ported from the PoC (story 426) as pure functions: motion on the
board clock, the voice envelope, the camera, placement refusals, and the pre-build
check."""

from __future__ import annotations

import copy

import numpy as np
import PIL.Image
import pytest

from haynes_studio.canonical import load_story
from haynes_studio.layered import check_board, compose
from haynes_studio.layered.errors import LAYOUT_INVALID, LayeredError
from haynes_studio.layered.pin import pin_board
from tests.cache import fixtures as fx
from tests.layered import helpers as h

STYLE = {"idle_scale": 0.3, "talk_hop": 34, "talk_tilt": 3.2, "talk_shuffle": 7}


def test_poses_are_held_two_frames_and_idle_wobble_needs_no_film_time():
    puppet = compose.Puppet("a", 0, single=False)
    poses = [compose.motion(puppet, n, STYLE, (), ()) for n in range(48)]
    assert all(poses[2 * k] == poses[2 * k + 1] for k in range(24))  # 12 poses a second
    assert len(set(poses)) > 10  # the doll rocks
    still = [compose.motion(puppet, n, h.STILL_STYLE, (), ()) for n in range(48)]
    assert set(still) == {(0.0, 0.0, 0.0)}


def test_talk_bounce_moves_only_the_speaker_and_only_while_she_speaks():
    talk = (compose.Talk("c", 500, (1.0, 0.5, 1.0, 0.2)),)  # 4 poses from 0.5 s
    c, a = compose.Puppet("c", 1, single=False), compose.Puppet("a", 0, single=False)
    quiet = dict(STYLE, idle_scale=0)
    for n in range(48):
        moved = compose.motion(c, n, quiet, talk, ())
        speaking = 12 <= n < 20  # poses 6..9 at 12 a second: frames 12 to 19
        assert (moved != (0.0, 0.0, 0.0)) == speaking, n
        assert compose.motion(a, n, quiet, talk, ()) == (0.0, 0.0, 0.0)
    assert compose.motion(c, 12, quiet, talk, ())[1] == pytest.approx(-34 * 0.7)  # a group hop


def test_moves_add_up_in_held_steps_from_their_start():
    move = {"slot": "b", "start_ms": 500, "duration_ms": 250, "dx_px": 30, "dy_px": -6,
            "angle_deg": 3, "steps": 3}
    snap = {**move, "start_ms": 1000, "duration_ms": 0, "dx_px": -10, "dy_px": 0, "angle_deg": 0}
    b = compose.Puppet("b", 1, single=True)
    quiet = dict(STYLE, idle_scale=0)
    xs = [compose.motion(b, n, quiet, (), (move, snap))[0] for n in range(30)]
    assert xs[:12] == [0.0] * 12  # before 500 ms (frame 12)
    assert xs[12] == 0.0 and xs[14] == pytest.approx(10.0)  # u = 0 at the start, then 1/3
    assert xs[22] == pytest.approx(30.0) and xs[24] == pytest.approx(20.0)  # the snap at 1000 ms
    assert compose.motion(compose.Puppet("a", 0, True), 20, quiet, (), (move,)) == (0.0, 0.0, 0.0)


def test_the_envelope_is_each_lines_loudness_from_the_board_track():
    rate = 24_000
    track = np.zeros(rate * 2)
    track[rate // 2:rate] = np.sin(np.arange(rate // 2) / 5) * np.linspace(0, 1, rate // 2)
    (talk,) = compose.envelope(track, rate, [{"speaker": "a", "start_ms": 500, "end_ms": 1000}])
    assert talk.start_ms == 500 and len(talk.curve) == 6 and max(talk.curve) == 1.0
    assert list(talk.curve) == sorted(talk.curve)  # louder through the line
    (silent,) = compose.envelope(track, rate, [{"speaker": "a", "start_ms": 0, "end_ms": 400}])
    assert set(silent.curve) == {0.0}


def test_the_camera_pushes_in_from_its_cue_and_holds_zoom_from_before_it():
    frame = PIL.Image.fromarray(np.tile(np.arange(360, dtype=np.uint8)[None, :, None], (640, 1, 3)))
    cue = {"start_ms": 500, "duration_ms": 0, "zoom_from": 1.0, "zoom_to": 2.0, "center_px": [90, 320]}
    assert compose.camera(frame, cue, 0.4) is frame  # zoom 1 before the cue
    pushed = np.asarray(compose.camera(frame, cue, 0.5))
    assert pushed[0, 0, 0] == 0 and pushed[0, -1, 0] < 200  # the left half, scaled up
    eased = {**cue, "duration_ms": 1000}
    half = np.asarray(compose.camera(frame, eased, 1.0))  # u = 0.5, eased: 0.875 of the way
    assert abs(half[0, -1, 0] - 360 / (1 + 0.875)) < 20


def test_placement_refuses_what_it_cannot_place():
    layout = h.LAYOUTS["trio"]
    assert compose.slot_of(h.LAYOUTS["single"], "z").x == 0.5 and compose.is_single(h.LAYOUTS["single"])
    assert not compose.is_single(layout)
    for bad in ({"slots": {}}, {"slots": {"a": {"x": "left", "height": 10, "bottom": 1}}},
                {"slots": {"a": {"x": 0.5, "height": 10.5, "bottom": 1}}},
                {"slots": {"a": {"x": 0.5, "height": 10, "bottom": 1, "crop": [0, 0, 2, 1]}}}):
        with pytest.raises(LayeredError) as error:
            compose.slot_of(bad, "a")
        assert error.value.code == LAYOUT_INVALID, bad
    with pytest.raises(LayeredError):
        compose.place((100, 200), compose.slot_of({"slots": {"a": {"x": 2.0, "height": 200,
                                                                    "bottom": 600}}}, "a"), 360, "a")
    assert compose.sprite_size((120, 240), compose.slot_of(layout, "a")) == (100, 200)


def test_the_pre_build_check_lists_every_refusal(world):
    document = h.story_document()
    b1 = fx.board_of(document, h.B1)
    b1["cues"] = [
        {"id": fx.ident("cue", 1), "type": "camera", "anchor": {"at_ms": 0}, "duration_ms": 1,
         "zoom_from": 1, "zoom_to": 1.1, "center_px": [1, 1], "easing": "ease_out_cubic"},
        {"id": fx.ident("cue", 2), "type": "camera", "anchor": {"at_ms": 0}, "duration_ms": 1,
         "zoom_from": 1, "zoom_to": 1.1, "center_px": [1, 1], "easing": "ease_out_cubic"}]
    document["layouts"]["trio"]["slots"].pop("c")
    story = load_story(copy.deepcopy(document), context="write", source="check")
    board = next(b for b in story.boards if b.id == h.B1)
    library = world.library(without=frozenset({h.LOOP["b"]}))
    motion = pin_board(document["boards"][0], library, world.store.verify, story=document)
    found = {(v.rule, v.path) for v in check_board(story, board, motion=motion)}
    assert found == {("layered.layout_invalid", "/cast/2"), ("layered.unsupported", "/cues/1"),
                     ("motion.clip_absent", "/cast/1/motion_asset_version_id")}
    sized = check_board(story, board, motion=motion, frame_size=(640, 360), s2v_size=(160, 256))
    assert {(v.rule, v.path) for v in sized} - found == {
        ("layered.unsupported", "/set/motion_asset_version_id"),  # a 9:16 loop on a 16:9 board
        ("layered.unsupported", "/cast/0"), ("layered.unsupported", "/cast/2")}  # a, c speak; b has no loop
    clean = load_story(h.story_document(), context="write", source="check")
    assert check_board(clean, clean.boards[0], motion=pin_board(
        h.story_document()["boards"][0], world.library(), world.store.verify,
        story=h.story_document())) == []
