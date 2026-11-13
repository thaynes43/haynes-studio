"""Code checks of a ``motion`` block, on a ``studio.asset-version/v1`` document the
schema has accepted (story 457). The schema holds each field's shape and what a use or
subject fixes (a loop is 24 fps ping-pong with no drive track; a timed clip has one and
starts at frame 0; a set loop is never keyed). The code checks what one field cannot:

| Rule | Code |
|---|---|
| a loop's period is ``2N - 2`` over its ``N`` trimmed frames (TIME-8a) | ``schema.invalid`` |
| the trim lies inside the clip | ``schema.invalid`` |
| a timed clip's trim is what its drive track's board needs (TIME-8) | ``schema.invalid`` |
| a timed clip holds at least that many frames (TIME-8, P-05) | ``time.source_short`` (failed) |
| a timed clip names its S2V adapter; a loop's profile names its own | ``schema.invalid`` |
| a box lies inside the frame, with ``x0 < x1`` and ``y0 < y1`` | ``schema.invalid`` |
| the content's size, and the generator's seed, prompt and engine job, agree with the block | ``schema.invalid`` |
| a doll clip is a ``motion_clip`` and a set loop a ``set_loop``, never both | ``asset.capability_mismatch`` |
| ``keys`` are the ones the inputs give | ``motion.identity_mismatch`` (proposal) |

Never raises for a document the schema accepted.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from haynes_studio.errors import Violation, pointer
from haynes_studio.motion.record import (
    DOLL,
    LOOP,
    SET,
    SUBJECT_CAPABILITY,
    TIMED,
    MotionRecord,
    timed_trim,
)
from haynes_studio.render.clock import loop_period

SCHEMA_INVALID = "schema.invalid"
CAPABILITY_MISMATCH = "asset.capability_mismatch"
SOURCE_SHORT = "time.source_short"  # contract section 3, status "failed stage"
IDENTITY_MISMATCH = "motion.identity_mismatch"  # proposal (story 457)
FAILED = "failed"


def _v(rule: str, path: str, message: str, status: str = "invalid") -> Violation:
    return Violation(rule, path, message, status)


def block_problems(doc: Mapping[str, Any]) -> list[Violation]:
    """Every code rule the ``motion`` block of version ``doc`` breaks (unsorted)."""
    block = doc["motion"]
    record = MotionRecord.from_block(block)
    found: list[Violation] = []
    found += _trim(record)
    found += _adapter(record)
    found += _boxes(record)
    found += _agreement(doc, record)
    found += _capabilities(record, doc["capabilities"])
    if not any(v.path.startswith(("/motion/trim", "/motion/playback", "/motion/source/adapter"))
               for v in found):
        found += identity_problems(record, doc["content"]["sha256"])
    return found


def _trim(record: MotionRecord) -> list[Violation]:
    found = []
    end = record.trim_start + record.trim_frames
    if end > record.frames:
        found.append(_v(SCHEMA_INVALID, "/motion/trim",
                        f"the trim ends at frame {end}, past the clip's {record.frames} frames"))
    if record.use == LOOP:
        period = loop_period(record.trim_frames)
        if record.period != period:
            found.append(_v(SCHEMA_INVALID, "/motion/playback/period",
                            f"must be {period}: 2N - 2 over the {record.trim_frames} trimmed "
                            "frames (TIME-8a)"))
        return found
    assert record.drive_track is not None  # the schema requires it on a timed clip
    needed = timed_trim(record.drive_track.board_frames, record.fps)
    if record.frames < needed:
        found.append(_v(SOURCE_SHORT, "/motion/frames",
                        f"a {record.drive_track.board_frames}-frame board needs {needed} source "
                        f"frames at {record.fps} fps; the clip has {record.frames} (TIME-8, P-05)",
                        FAILED))
    elif record.trim_frames != needed:
        found.append(_v(SCHEMA_INVALID, "/motion/trim/frames",
                        f"must be {needed}: floor((F - 1) * fs / 24) + 1 for the drive track's "
                        f"{record.drive_track.board_frames} board frames (TIME-8)"))
    return found


def _adapter(record: MotionRecord) -> list[Violation]:
    if record.use == TIMED and record.source.adapter is None:
        return [_v(SCHEMA_INVALID, "/motion/source/adapter",
                   "a timed speech-to-video clip names its adapter (section 4, S2V clip key)")]
    if record.use == LOOP and record.source.adapter is not None:
        return [_v(SCHEMA_INVALID, "/motion/source/adapter",
                   "a loop's profile names its adapter (section 4, doll clip or set loop key)")]
    return []


def _boxes(record: MotionRecord) -> list[Violation]:
    keying = record.keying
    if keying is None:
        return []
    boxes: list[tuple[str, tuple[int, ...]]] = [
        (pointer("motion", "keying", "protect_boxes", i), box)
        for i, box in enumerate(keying.protect_boxes)]
    if keying.decal_box is not None:
        boxes.append(("/motion/keying/decal_box", keying.decal_box))
    found = []
    for path, (x0, y0, x1, y1) in boxes:
        if not (x0 < x1 <= record.width and y0 < y1 <= record.height):
            found.append(_v(SCHEMA_INVALID, path,
                            f"a box is [x0, y0, x1, y1] with x0 < x1 <= {record.width} and "
                            f"y0 < y1 <= {record.height} (clip pixels)"))
    if keying.decal_box is None and keying.decal_version is not None:
        found.append(_v(SCHEMA_INVALID, "/motion/keying/decal_version",
                        "a decal version needs a decal box"))
    return found


def _agreement(doc: Mapping[str, Any], record: MotionRecord) -> list[Violation]:
    """The content's measured size and the generator's seed, prompt and engine job, where
    recorded, are the block's."""
    found = []
    content = doc["content"]
    for name, value in (("width", record.width), ("height", record.height)):
        if content.get(name) is not None and content[name] != value:
            found.append(_v(SCHEMA_INVALID, f"/content/{name}",
                            f"must be the motion block's {name}, {value}"))
    generator = doc["provenance"]["generator"]
    for name, value in (("seed", record.source.seed), ("prompt", record.source.prompt),
                        ("engine_job_id", record.source.engine_job_id)):
        if generator.get(name) is not None and generator[name] != value:
            found.append(_v(SCHEMA_INVALID, f"/provenance/generator/{name}",
                            f"must be the motion block's source {name}"))
    return found


def _capabilities(record: MotionRecord, capabilities: Iterable[str]) -> list[Violation]:
    claimed = set(capabilities)
    wanted = SUBJECT_CAPABILITY[record.subject]
    other = SUBJECT_CAPABILITY[SET if record.subject == DOLL else DOLL]
    found = []
    if wanted not in claimed:
        found.append(_v(CAPABILITY_MISMATCH, "/capabilities",
                        f"a {record.subject} clip has the {wanted} capability"))
    if other in claimed:
        found.append(_v(CAPABILITY_MISMATCH, "/capabilities",
                        f"a {record.subject} clip is not a {other}"))
    return found


def identity_problems(record: MotionRecord, clip_sha256: str) -> list[Violation]:
    """``motion.identity_mismatch`` for each recorded key that is not what the inputs
    give (a corrupt or hand-edited record); ``schema.invalid`` for an input a cache key
    refuses."""
    from haynes_studio.cache.errors import CacheError
    from haynes_studio.motion.identity import motion_identity

    try:
        identity = motion_identity(record, clip_sha256)
    except CacheError as error:
        return [_v(SCHEMA_INVALID, "/motion/source",
                   f"a cache key refuses an input at {error.where}: {error.message}"[:160])]
    except ValueError as error:  # text that is not valid UTF-8 (a lone surrogate)
        return [_v(SCHEMA_INVALID, "/motion",
                   f"the record cannot be written as canonical JSON: {error}"[:160])]
    found = []
    expected = identity.keys_block()
    recorded = {"clip": record.keys.clip, "identity": record.keys.identity}
    if record.keys.keyed is not None:
        recorded["keyed"] = record.keys.keyed
    for name in ("clip", "keyed", "identity"):
        if recorded.get(name) != expected.get(name):
            found.append(_v(IDENTITY_MISMATCH, f"/motion/keys/{name}",
                            f"must be {expected.get(name)}: the key its inputs give"))
    return found


__all__ = ["CAPABILITY_MISMATCH", "IDENTITY_MISMATCH", "SOURCE_SHORT", "block_problems",
           "identity_problems"]
