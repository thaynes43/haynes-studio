"""A motion record's identity: one pure function of its inputs (story 457).

Built on the cache keys of story 380 (:mod:`haynes_studio.cache.keys`), called, never
copied:

- the **clip key**, what generated the bytes: section 4's ``motion_clip_key`` (still,
  prompt, seed, profile) for a loop, and ``s2v_clip_key`` (drive track, start still,
  prompt, negative prompt, seed, profile, adapter) for a timed speech-to-video clip,
  which ``motion_clip_key`` cannot key because it has no drive track (proposal);
- the **keyed key**, how a doll clip is keyed: ``keyed_frames_key`` (the clip's bytes,
  the still the decal is cut from, key thresholds, protect boxes, decal box, decal
  version, keyer). None when the record holds no keying (a set loop, or a legacy doll
  clip whose keying no record holds).

The **identity** is ``sha256:`` of the canonical JSON (section 4's form) of a document
holding both keys and the inputs neither key covers: the use and subject, the still
the clip stands in for, the clip's own bytes, its frames, fps, size and trim, the
negative prompt (``motion_clip_key`` has none), the drive track's board frames and the
decal gate. A changed setting, seed, start image, still, key or decal setting, or other
bytes, gives a new identity; a label, name, note or engine job does not. The identity
is what the library pins for a motion version with a block (``model.pin``), so the same
record imported twice is the same version, and a re-keyed clip is the next version of
its asset, never an overwrite.

Pure: no file, clock, environment or service is read.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from haynes_studio.cache.keys import CacheKey, keyed_frames_key, motion_clip_key, s2v_clip_key
from haynes_studio.canonical.jsonvalues import normalize
from haynes_studio.jsonio import freeze, thaw
from haynes_studio.motion.record import IDENTITY_SCHEME, TIMED, MotionRecord
from haynes_studio.store import canonical_json


@dataclass(frozen=True)
class MotionIdentity:
    clip: CacheKey  # the generation's cache key
    keyed: CacheKey | None  # the keyed frames' cache key; None without keying
    value: str  # "sha256:<64 hex>"
    document: Mapping[str, Any] = field(repr=False)  # what the identity hashes

    def keys_block(self) -> dict[str, str]:
        """The block's ``keys`` as they must be recorded."""
        out = {"clip": self.clip.value, "identity": self.value}
        if self.keyed is not None:
            out["keyed"] = self.keyed.value
        return out


def clip_key(record: MotionRecord) -> CacheKey:
    """The generation's cache key (section 4): a loop's ``motion_clip_key``, a timed
    clip's ``s2v_clip_key``. Raises the cache's ``CacheError``
    (``cache.key_input_invalid``) for an input a key refuses."""
    source = record.source
    if record.use == TIMED:
        if record.drive_track is None:
            raise ValueError("a timed clip records its drive track")
        return s2v_clip_key(drive_track=record.drive_track.sha256, start_still=source.image_sha256,
                            prompt=source.prompt, negative_prompt=source.negative_prompt or "",
                            seed=source.seed, profile=thaw(source.profile),
                            adapter=source.adapter)
    return motion_clip_key(still=source.image_sha256, prompt=source.prompt, seed=source.seed,
                           profile=thaw(source.profile))


def keyed_key(record: MotionRecord, clip_sha256: str) -> CacheKey | None:
    """The keyed frames' cache key, or None without keying. The decal's still is the
    clip's own start image, as legacy ``DollClip.cache_dir`` hashed it (proposal)."""
    keying = record.keying
    if keying is None:
        return None
    return keyed_frames_key(
        clip=clip_sha256, still=record.source.image_sha256,
        key_thresholds=thaw(keying.key_thresholds),
        protect_boxes=[list(box) for box in keying.protect_boxes],
        decal_box=None if keying.decal_box is None else list(keying.decal_box),
        decal_version=keying.decal_version, keyer=keying.keyer)


def motion_identity(record: MotionRecord, clip_sha256: str) -> MotionIdentity:
    """The identity of ``record`` for the clip bytes ``clip_sha256`` (the version's
    ``content.sha256``), from its inputs; the record's own ``keys`` are not read."""
    clip = clip_key(record)
    keyed = keyed_key(record, clip_sha256)
    drive = record.drive_track
    document = {
        "scheme": IDENTITY_SCHEME, "use": record.use, "subject": record.subject,
        "still": record.still_sha256, "clip": clip_sha256, "clip_key": clip.value,
        "negative_prompt": record.source.negative_prompt,
        "frames": record.frames, "fps": record.fps, "width": record.width,
        "height": record.height,
        "trim": {"start": record.trim_start, "frames": record.trim_frames},
        "board_frames": None if drive is None else drive.board_frames,
        "keyed_key": None if keyed is None else keyed.value,
        "decal_min_ecc": None if record.keying is None else record.keying.decal_min_ecc,
    }
    # Integral floats are the integers they equal (section 2), as the validators read a
    # document, so a block read back from JSON has the identity it was written with.
    document = normalize(document)
    value = "sha256:" + hashlib.sha256(canonical_json(document)).hexdigest()
    return MotionIdentity(clip=clip, keyed=keyed, value=value, document=freeze(document))


# What each input feeds: the reference's field table, and the test that changes each.
IDENTITY_INPUTS: Mapping[str, str] = freeze({
    "use": "identity", "subject": "identity", "still_sha256": "identity",
    "content.sha256": "identity, keyed key", "frames": "identity", "fps": "identity",
    "width": "identity", "height": "identity", "trim": "identity",
    "source.image_sha256": "clip key, keyed key", "source.prompt": "clip key",
    "source.negative_prompt": "identity (loop), clip key (timed)", "source.seed": "clip key",
    "source.profile": "clip key", "source.adapter": "clip key (timed)",
    "drive_track.sha256": "clip key (timed)", "drive_track.board_frames": "identity",
    "keying.keyer": "keyed key", "keying.key_thresholds": "keyed key",
    "keying.protect_boxes": "keyed key", "keying.decal_box": "keyed key",
    "keying.decal_version": "keyed key", "keying.decal_min_ecc": "identity",
})
NOT_IDENTITY = ("source.engine_job_id", "note", "playback (fixed by use and trim)",
                "keys (the result)", "labels", "name", "attributes", "state", "provenance",
                "licence", "content.bytes", "content.locator")

__all__ = ["IDENTITY_INPUTS", "NOT_IDENTITY", "MotionIdentity", "clip_key",
           "keyed_key", "motion_identity"]
