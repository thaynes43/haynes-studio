"""The board clock (P-06, TIME-8, TIME-8a, TIME-9): pure, deterministic, film-free."""

from __future__ import annotations

import dataclasses
import hashlib
import inspect

import pytest

from haynes_studio.render import clock
from haynes_studio.render.base import SegmentRenderer, SegmentRequest

BOARD = "brd_01JCACHE000000000000000001"
OTHER = "brd_01JCACHE000000000000000002"


def test_loop_phase_is_the_contracts_formula():
    for slot in ("a", "b", clock.SET_SLOT):
        expected = int(hashlib.sha256(f"{BOARD}:{slot}".encode()).hexdigest()[:8], 16) % 240
        assert clock.loop_phase(BOARD, slot, 240) == expected
    assert clock.loop_phase(BOARD, "a", 240) != clock.loop_phase(OTHER, "a", 240)


def test_pingpong_runs_forward_and_back_with_period_2n_minus_2():
    assert [clock.pingpong(i, 4) for i in range(8)] == [0, 1, 2, 3, 2, 1, 0, 1]
    assert clock.loop_period(121) == 240 and clock.loop_period(1) == 1
    assert [clock.pingpong(i, 1) for i in range(3)] == [0, 0, 0]
    assert clock.loop_frame(0, 5, 4) == clock.pingpong(5, 4)


def test_board_frames_map_to_source_frames_by_time_8():
    assert [clock.source_frame(n, 16) for n in range(7)] == [0, 0, 1, 2, 2, 3, 4]  # floor(2n/3)
    assert clock.source_frame(152, 16) == 101
    assert clock.source_frame(10, 24) == 10


# Contract section 3, the r4 worked example: frames -> S2V L requested, source frames needed.
R4 = [(153, 154, 102), (94, 65, 63), (146, 154, 97), (84, 57, 56), (83, 57, 55),
      (122, 154, 81), (251, 231, 167), (108, 73, 72)]


@pytest.mark.parametrize(("frames", "requested", "needed"), R4)
def test_s2v_request_and_source_frames_match_the_worked_example(frames, requested, needed):
    assert clock.s2v_request_frames(frames) == requested
    assert clock.source_frames_needed(frames, 16) == needed
    assert requested >= needed


def test_chain_policy_requests_whole_121_frame_clips_chained_with_one_shared_frame():
    """Story 427: n chained clips cover 1 + 120 n frames (121, 241, 361), at most 3."""
    assert clock.i2v_clip_lengths(46) == (121,)
    assert clock.i2v_clip_lengths(121) == (121,)
    assert clock.i2v_clip_lengths(144) == (121, 121)
    assert clock.i2v_clip_lengths(241) == (121, 121)
    assert clock.i2v_clip_lengths(242) == (121, 121, 121)  # whole clips without the shared frame: two
    assert clock.i2v_chain_frames((121, 121, 121)) == 361
    with pytest.raises(ValueError):
        clock.i2v_clip_lengths(362)


def test_procedural_randomness_is_a_pure_function_of_seed_board_and_index():
    forward = [clock.procedural_random(7, BOARD, i) for i in range(20)]
    backward = [clock.procedural_random(7, BOARD, i) for i in reversed(range(20))][::-1]
    assert forward == backward  # no generator state: draw order does not matter
    assert clock.procedural_random(7, BOARD, 3) == clock.stream_random(clock.board_stream(7, BOARD), 3)
    assert clock.procedural_random(7, OTHER, 3) != clock.procedural_random(7, BOARD, 3)
    assert clock.procedural_random(8, BOARD, 3) != clock.procedural_random(7, BOARD, 3)
    assert len(set(forward)) == 20


def test_nothing_on_the_board_clock_takes_a_film_frame():
    """P-06: no clock function, renderer or request has a film parameter or field."""
    names = []
    for _, function in inspect.getmembers(clock, inspect.isfunction):
        names += list(inspect.signature(function).parameters)
    names += list(inspect.signature(SegmentRenderer.render).parameters)
    names += [field.name for field in dataclasses.fields(SegmentRequest)]
    assert not [name for name in names if "film" in name or "offset" in name]


@pytest.mark.parametrize("call", [lambda: clock.pingpong(-1, 4), lambda: clock.loop_period(0),
                                  lambda: clock.loop_phase(BOARD, "a", 0),
                                  lambda: clock.source_frames_needed(0, 16),
                                  lambda: clock.s2v_request_frames(True)])
def test_clock_functions_refuse_bad_numbers(call):
    with pytest.raises((TypeError, ValueError)):
        call()
