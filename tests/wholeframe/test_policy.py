"""The whole-frame length policy and the chain maths, as pure functions (story 427).

The worked table is the reference's: the r4 board lengths, the clips requested at 121
frames, and each clip's share. E0 (``assembly-wf.json``) chained the same boards the
same way, except board 6, whose 122 frames it covered with one clip and a held last
frame, which P-05 forbids.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from haynes_studio.render.clock import (
    I2V_CLIP_FRAMES,
    I2V_MAX_CLIPS,
    i2v_chain_frames,
    i2v_clip_lengths,
    source_frames_needed,
)
from haynes_studio.wholeframe import assemble
from haynes_studio.wholeframe.errors import SOURCE_SHORT, WholeFrameError

ROOT = Path(__file__).resolve().parents[2]

# board frames -> clips requested, frames used from each clip, frames trimmed in all.
TABLE = [
    (46, 1, [46], 75),
    (83, 1, [83], 38),
    (84, 1, [84], 37),
    (94, 1, [94], 27),
    (108, 1, [108], 13),
    (121, 1, [121], 0),
    (122, 2, [121, 1], 119),
    (146, 2, [121, 25], 95),
    (153, 2, [121, 32], 88),
    (241, 2, [121, 120], 0),
    (242, 3, [121, 120, 1], 119),
    (251, 3, [121, 120, 10], 110),
    (361, 3, [121, 120, 120], 0),
]


def test_defaults_are_the_e0_profile():
    assert (I2V_CLIP_FRAMES, I2V_MAX_CLIPS) == (121, 3)


@pytest.mark.parametrize(("frames", "clips", "used", "trimmed"), TABLE)
def test_worked_table(frames, clips, used, trimmed):
    lengths = i2v_clip_lengths(source_frames_needed(frames, 24))
    assert lengths == (121,) * clips
    assembly = assemble(frames, list(lengths), source_fps=24)
    assert [clip.used for clip in assembly.clips] == used
    assert [clip.dropped for clip in assembly.clips] == [0] + [1] * (clips - 1)
    assert assembly.trimmed == trimmed == sum(clip.trimmed for clip in assembly.clips)
    assert assembly.available == i2v_chain_frames(lengths) == 121 + 120 * (clips - 1)


def test_the_policy_requests_what_e0_chained_except_the_held_board():
    """E0's whole-frame assembly: same clip counts, except shot 6 (hold-last)."""
    shots = json.loads((ROOT / "titles/the-winter-menu/video-e0/assembly-wf.json").read_text())["shots"]
    for shot in shots:
        lengths = i2v_clip_lengths(shot["frames"])
        if shot["mode"] == "hold-last":
            assert shot["source_frames"] < shot["frames"] and len(lengths) == len(shot["clips"]) + 1
        else:
            assert len(lengths) == len(shot["clips"]), shot["shot"]
            assert i2v_chain_frames(lengths) == shot["source_frames"]


def test_a_hold_edit_keeps_the_clips_until_the_chain_is_full():
    """Section 4: the clips are reused while the requested lengths are unchanged."""
    changes = [n for n in range(2, 362) if i2v_clip_lengths(n) != i2v_clip_lengths(n - 1)]
    assert changes == [122, 242]


def test_the_chain_limit_refuses_a_longer_board():
    assert i2v_clip_lengths(361) == (121, 121, 121)
    with pytest.raises(ValueError, match="chain limit is 3 clips"):
        i2v_clip_lengths(362)
    assert i2v_clip_lengths(73, 25) == (25, 25, 25)
    with pytest.raises(ValueError):
        i2v_clip_lengths(74, 25)
    assert len(i2v_clip_lengths(500, 121, max_clips=5)) == 5


@pytest.mark.parametrize("call", [lambda: i2v_clip_lengths(0), lambda: i2v_clip_lengths(True),
                                  lambda: i2v_clip_lengths(10, 1), lambda: i2v_clip_lengths(10, 121, 0),
                                  lambda: i2v_chain_frames([]), lambda: i2v_chain_frames([121, 0])])
def test_the_policy_refuses_bad_numbers(call):
    with pytest.raises((TypeError, ValueError)):
        call()


def test_the_chain_drops_each_boundary_duplicate():
    assembly = assemble(52, [25, 25, 25], source_fps=24)
    picks = list(assembly.picks())
    assert picks[24:27] == [(0, 24), (1, 1), (1, 2)]  # clip 1's frame 0 repeats clip 0's last
    assert picks[48:] == [(1, 24), (2, 1), (2, 2), (2, 3)]
    assert (1, 0) not in picks and (2, 0) not in picks
    assert assembly.needed == 52 and assembly.available == 73 and assembly.trimmed == 21
    assert assembly.to_document()["clips"][2] == {"index": 2, "delivered": 25, "dropped": 1,
                                                 "offered": 24, "used": 3, "trimmed": 21}


def test_time_8_maps_a_16_fps_chain():
    """The maths holds for any source rate (I2V is 24 fps): floor(2n / 3) at 16 fps."""
    assembly = assemble(30, [10, 15], source_fps=16)
    assert assembly.needed == source_frames_needed(30, 16) == 20
    assert [assembly.locate(i) for i in (9, 10)] == [(0, 9), (1, 1)]
    assert list(assembly.picks())[:4] == [(0, 0), (0, 0), (0, 1), (0, 2)]


@pytest.mark.parametrize("delivered", [[], [25, 0], [10], [25, 1, 1]])
def test_a_short_or_missing_clip_fails(delivered):
    with pytest.raises(WholeFrameError) as error:
        assemble(30, delivered, source_fps=24)
    assert error.value.code == SOURCE_SHORT and error.value.status == "failed"
