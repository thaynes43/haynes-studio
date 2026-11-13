"""Motion record identity (story 457): one pure function of the record's inputs, built
on story 380's cache keys. Each identity input changed alone gives a new identity; a
label, note or engine job does not."""

from __future__ import annotations

import builtins
import copy
import os

import pytest

from haynes_studio.cache.keys import keyed_frames_key, motion_clip_key, s2v_clip_key
from haynes_studio.motion.identity import IDENTITY_INPUTS, motion_identity
from haynes_studio.motion.record import MotionRecord, playback
from haynes_studio.motion.winter_menu import complete_block
from tests.motion.fixtures import loop_block, sha, timed_block

CLIP = sha("c")


def identity(block, clip=CLIP):
    return motion_identity(MotionRecord.from_block(complete_block(block, clip)), clip)


def changed(block, path, value):
    out = copy.deepcopy(block)
    *head, last = path.split(".")
    target = out
    for name in head:
        target = target[name]
    if value is DELETE:
        del target[last]
    else:
        target[last] = value
    return out


DELETE = object()

# (field, fixture, new value): every input the identity covers.
INPUTS = [
    ("use", timed_block, "loop"),
    ("subject", loop_block, "set"),
    ("still_sha256", loop_block, sha("e")),
    ("still_sha256", loop_block, DELETE),
    ("frames", loop_block, 122),
    ("fps", timed_block, 24),
    ("width", loop_block, 600),
    ("height", loop_block, 1100),
    ("trim.start", loop_block, 1),
    ("trim.frames", loop_block, 120),
    ("source.image_sha256", loop_block, sha("7")),
    ("source.prompt", loop_block, "a plastic doll sways on green"),
    ("source.negative_prompt", loop_block, None),
    ("source.negative_prompt", timed_block, "blurry"),
    ("source.seed", loop_block, 312),
    ("source.profile.model", loop_block, "Wan2.2 TI2V-5B v2"),
    ("source.profile.length", loop_block, 81),
    ("source.adapter", timed_block, "studio.s2v/2"),
    ("drive_track.sha256", timed_block, sha("8")),
    ("drive_track.board_frames", timed_block, 152),
    ("keying", loop_block, DELETE),
    ("keying.keyer", loop_block, "studio.keyer/2"),
    ("keying.key_thresholds", loop_block, {"lo": 25, "hi": 70}),
    ("keying.protect_boxes", loop_block, []),
    ("keying.decal_box", loop_block, [265, 702, 455, 781]),
    ("keying.decal_box", loop_block, None),
    ("keying.decal_version", loop_block, "erase-v3"),
    ("keying.decal_min_ecc", loop_block, 0.65),
]


@pytest.mark.parametrize(("path", "fixture", "value"), INPUTS,
                         ids=[f"{p}-{f.__name__}-{i}" for i, (p, f, _) in enumerate(INPUTS)])
def test_each_input_changes_the_identity(path, fixture, value):
    base = fixture()
    if path == "keying.decal_box" and value is None:
        base = changed(base, "keying.decal_version", None)  # no box, no decal
    assert identity(changed(base, path, value)).value != identity(base).value


def test_other_bytes_are_another_identity():
    assert identity(loop_block(), sha("c")).value != identity(loop_block(), sha("f")).value


def test_every_input_of_the_table_is_changed_by_a_test():
    """The reference's field table (IDENTITY_INPUTS) and this file's changes agree."""
    paths = [path for path, _, _ in INPUTS] + ["content.sha256"]  # bytes: the test above

    def covers(name, path):
        return path == name or path.startswith(name + ".") or name.startswith(path + ".")

    assert [name for name in IDENTITY_INPUTS if not any(covers(name, p) for p in paths)] == []
    assert [p for p in paths if not any(covers(name, p) for name in IDENTITY_INPUTS)] == []


@pytest.mark.parametrize(("path", "value"), [
    ("source.engine_job_id", "another-job"),
    ("source.engine_job_id", None),
    ("note", "a note"),
])
def test_provenance_and_notes_are_not_identity(path, value):
    base = loop_block()
    assert identity(changed(base, path, value)).value == identity(base).value


def test_the_same_inputs_give_the_same_identity():
    first, second = identity(loop_block()), identity(loop_block())
    assert first.value == second.value
    assert first.keys_block() == second.keys_block()
    assert first.value.startswith("sha256:") and len(first.value) == 71


def test_recorded_keys_are_not_inputs():
    block = complete_block(loop_block(), CLIP)
    tampered = copy.deepcopy(block)
    tampered["keys"] = {"clip": "sha256:" + "1" * 64, "keyed": "sha256:" + "2" * 64,
                        "identity": "sha256:" + "3" * 64}
    recomputed = motion_identity(MotionRecord.from_block(tampered), CLIP)
    assert recomputed.value == block["keys"]["identity"]


def test_a_loop_is_keyed_by_the_motion_clip_and_keyed_frames_keys():
    block = loop_block()
    source, keying = block["source"], block["keying"]
    result = identity(block)
    assert result.clip == motion_clip_key(still=source["image_sha256"], prompt=source["prompt"],
                                          seed=source["seed"], profile=source["profile"])
    assert result.keyed == keyed_frames_key(
        clip=CLIP, still=source["image_sha256"], key_thresholds=keying["key_thresholds"],
        protect_boxes=keying["protect_boxes"], decal_box=keying["decal_box"],
        decal_version=keying["decal_version"], keyer=keying["keyer"])
    assert result.document["clip_key"] == result.clip.value
    assert result.document["keyed_key"] == result.keyed.value


def test_a_timed_clip_is_keyed_by_the_s2v_clip_key():
    block = timed_block()
    source = block["source"]
    assert identity(block).clip == s2v_clip_key(
        drive_track=block["drive_track"]["sha256"], start_still=source["image_sha256"],
        prompt=source["prompt"], negative_prompt=source["negative_prompt"], seed=source["seed"],
        profile=source["profile"], adapter=source["adapter"])


def test_a_set_loop_has_no_keyed_key():
    block = loop_block(subject="set")
    del block["keying"]
    result = identity(block)
    assert result.keyed is None and "keyed" not in result.keys_block()


def test_identity_reads_no_file(monkeypatch):
    block = complete_block(loop_block(), CLIP)
    record = MotionRecord.from_block(block)

    def refuse(*args, **kwargs):
        raise AssertionError("the identity read the file system")

    monkeypatch.setattr(builtins, "open", refuse)
    monkeypatch.setattr(os, "open", refuse)
    monkeypatch.setattr(os, "stat", refuse)
    assert motion_identity(record, CLIP).value == block["keys"]["identity"]


# Playback ----------------------------------------------------------------------------------


def test_playback_is_fixed_by_use():
    assert playback("loop", 121) == {"loop": "pingpong", "period": 240,
                                     "board_longer": "pingpong", "board_shorter": "pingpong"}
    assert playback("timed", 102) == {"loop": "none", "period": None, "board_longer": "fail",
                                      "board_shorter": "trim"}


@pytest.mark.parametrize(("n", "phase", "frame"), [
    (0, 0, 0), (120, 0, 120), (121, 0, 119), (239, 0, 1), (240, 0, 0), (0, 5, 5), (236, 5, 1),
])
def test_a_loop_plays_ping_pong_over_any_board_length(n, phase, frame):
    record = MotionRecord.from_block(complete_block(loop_block(), CLIP))
    assert record.board_frame(n, phase=phase) == frame
    assert record.board_frame(10_000_000) in range(121)  # never "short" (TIME-8a)


def test_a_trimmed_loop_plays_inside_its_trim():
    block = loop_block(trim={"start": 1, "frames": 120})
    record = MotionRecord.from_block(complete_block(block, CLIP))
    assert record.period == 238
    assert [record.board_frame(n) for n in (0, 119, 120, 238)] == [1, 120, 119, 1]


def test_a_timed_clip_follows_time_8_and_never_loops():
    record = MotionRecord.from_block(complete_block(timed_block(), CLIP))
    assert record.trimmed == 56  # the r4 worked example's board 1: 158 returned, 102 used
    assert [record.board_frame(n) for n in (0, 1, 2, 3, 152)] == [0, 0, 1, 2, 101]
    with pytest.raises(ValueError, match="outside"):
        record.board_frame(153)
    with pytest.raises(ValueError, match="no loop phase"):
        record.board_frame(0, phase=3)
