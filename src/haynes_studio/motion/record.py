"""The ``motion`` block of a library ``motion`` asset version (story 457, a proposal for
contract sections 3, 4, 5 and 9), read as an immutable :class:`MotionRecord`.

A motion version is one generated clip and how it is played and keyed:

- **use** ``loop`` (TIME-8a): a reusable doll clip or set loop. It plays ping-pong
  under a board of any length, period ``2N - 2`` over the ``N`` trimmed frames, from
  the board's hashed phase; it is never "short".
- **use** ``timed`` (TIME-8): a clip made for one board's speech. It records the drive
  track it was made from; board frame ``n`` shows source frame ``floor(n * fs / 24)``;
  extra source frames are trimmed and recorded, and a board longer than the clip fails
  (``time.source_short``, P-05). It is never played as a loop.
- **subject** ``doll`` (keyed over the set) or ``set`` (an opaque set loop).
- **still** (``still_sha256``): the cast still or set image the clip stands in for,
  which a board names. Absent when no public record ties the clip to one (a legacy
  import); such a clip is used only where a board pins it.
- **source**: the start image the engine animated, prompt, negative prompt, seed,
  profile, adapter (a timed clip's S2V adapter) and the engine job.
- **keying** (doll clips): keyer, key thresholds, protect boxes, decal box, decal
  version and the decal gate. Absent for a set loop (nothing is keyed) and for a doll
  clip whose keying the records do not hold.
- **keys**: the cache keys the identity is built on and the identity itself
  (:mod:`haynes_studio.motion.identity`).

Nothing here reads a file, the clock or a service.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from haynes_studio.jsonio import freeze, thaw
from haynes_studio.render.clock import loop_frame, loop_period, source_frame, source_frames_needed
from haynes_studio.timebase import DELIVERY_FPS

LOOP, TIMED = "loop", "timed"
DOLL, SET = "doll", "set"
PINGPONG, NONE = "pingpong", "none"
FAIL, TRIM = "fail", "trim"

# The capability each subject's clip carries (proposal; model.KIND_CAPABILITIES).
SUBJECT_CAPABILITY = {DOLL: "motion_clip", SET: "set_loop"}

# Proposal: the identity scheme. Changing what the identity covers bumps it.
IDENTITY_SCHEME = "studio.motion-record/v1"


@dataclass(frozen=True, slots=True)
class Source:
    image_sha256: str
    prompt: str
    negative_prompt: str | None
    seed: int
    profile: Mapping[str, Any]
    engine_job_id: str | None
    adapter: str | None = None


@dataclass(frozen=True, slots=True)
class DriveTrack:
    sha256: str
    board_frames: int


@dataclass(frozen=True, slots=True)
class Keying:
    keyer: str
    key_thresholds: Mapping[str, Any]
    protect_boxes: tuple[tuple[int, ...], ...]
    decal_box: tuple[int, ...] | None
    decal_version: str | None
    decal_min_ecc: float | None = None


@dataclass(frozen=True, slots=True)
class Keys:
    clip: str
    identity: str
    keyed: str | None = None


@dataclass(frozen=True, slots=True)
class MotionRecord:
    """One ``motion`` block, as recorded. :meth:`from_block` reads a block the schema
    has accepted."""

    use: str
    subject: str
    still_sha256: str | None
    frames: int
    fps: int
    width: int
    height: int
    trim_start: int
    trim_frames: int
    period: int | None
    source: Source
    drive_track: DriveTrack | None
    keying: Keying | None
    keys: Keys
    note: str | None = None

    @classmethod
    def from_block(cls, block: Mapping[str, Any]) -> MotionRecord:
        source, keying, drive = block["source"], block.get("keying"), block.get("drive_track")
        keys = block["keys"]
        return cls(
            use=block["use"], subject=block["subject"], still_sha256=block.get("still_sha256"),
            frames=block["frames"], fps=block["fps"], width=block["width"],
            height=block["height"], trim_start=block["trim"]["start"],
            trim_frames=block["trim"]["frames"], period=block["playback"]["period"],
            source=Source(image_sha256=source["image_sha256"], prompt=source["prompt"],
                          negative_prompt=source["negative_prompt"], seed=source["seed"],
                          profile=freeze(thaw(source["profile"])),
                          engine_job_id=source["engine_job_id"], adapter=source.get("adapter")),
            drive_track=(None if drive is None
                         else DriveTrack(drive["sha256"], drive["board_frames"])),
            keying=None if keying is None else Keying(
                keyer=keying["keyer"], key_thresholds=freeze(thaw(keying["key_thresholds"])),
                protect_boxes=tuple(tuple(box) for box in keying["protect_boxes"]),
                decal_box=None if keying["decal_box"] is None else tuple(keying["decal_box"]),
                decal_version=keying["decal_version"], decal_min_ecc=keying.get("decal_min_ecc")),
            keys=Keys(clip=keys["clip"], identity=keys["identity"], keyed=keys.get("keyed")),
            note=block.get("note"))

    @property
    def is_loop(self) -> bool:
        return self.use == LOOP

    @property
    def trimmed(self) -> int:
        """Source frames the clip has but never shows."""
        return self.frames - self.trim_frames

    def board_frame(self, n: int, *, phase: int = 0) -> int:
        """The source frame (in the file) board frame ``n`` shows.

        A loop: ``trim_start + pingpong(n + phase, N)`` over its ``N`` trimmed frames
        (TIME-8a). A timed clip: ``floor(n * fs / 24)`` (TIME-8); ``phase`` must be 0 and
        ``n`` inside the board its drive track was made for. Raises :class:`ValueError`
        for a frame the clip cannot show."""
        if self.is_loop:
            return self.trim_start + loop_frame(n, phase, self.trim_frames)
        if phase:
            raise ValueError("a timed clip has no loop phase (TIME-8)")
        assert self.drive_track is not None
        if not 0 <= n < self.drive_track.board_frames:
            raise ValueError(f"frame {n} is outside the {self.drive_track.board_frames}-frame "
                             "board this clip was made for")
        return source_frame(n, self.fps)

    def to_block(self) -> dict[str, Any]:
        """The block as plain JSON (absent fields left out)."""
        out: dict[str, Any] = {
            "use": self.use, "subject": self.subject, "frames": self.frames, "fps": self.fps,
            "width": self.width, "height": self.height,
            "trim": {"start": self.trim_start, "frames": self.trim_frames},
            "playback": playback(self.use, self.trim_frames),
            "source": _source_document(self.source),
            "keys": {"clip": self.keys.clip, "identity": self.keys.identity},
        }
        if self.still_sha256 is not None:
            out["still_sha256"] = self.still_sha256
        if self.drive_track is not None:
            out["drive_track"] = {"sha256": self.drive_track.sha256,
                                  "board_frames": self.drive_track.board_frames}
        if self.keying is not None:
            out["keying"] = keying_document(self.keying)
            out["keys"]["keyed"] = self.keys.keyed
        if self.note is not None:
            out["note"] = self.note
        return out


def playback(use: str, trim_frames: int) -> dict[str, Any]:
    """What a board of another length does with the clip, fixed by its use: a loop
    ping-pongs both ways (TIME-8a); a timed clip trims a shorter board's extra frames
    and fails a longer one (TIME-8, P-05)."""
    if use == LOOP:
        return {"loop": PINGPONG, "period": loop_period(trim_frames), "board_longer": PINGPONG,
                "board_shorter": PINGPONG}
    return {"loop": NONE, "period": None, "board_longer": FAIL, "board_shorter": TRIM}


def timed_trim(board_frames: int, fps: int) -> int:
    """TIME-8: the source frames a board of ``board_frames`` needs from a clip at
    ``fps``; the rest of the clip is trimmed."""
    return source_frames_needed(board_frames, fps, DELIVERY_FPS)


def _source_document(source: Source) -> dict[str, Any]:
    out = {"image_sha256": source.image_sha256, "prompt": source.prompt,
           "negative_prompt": source.negative_prompt, "seed": source.seed,
           "profile": thaw(source.profile), "engine_job_id": source.engine_job_id}
    if source.adapter is not None:
        out["adapter"] = source.adapter
    return out


def keying_document(keying: Keying) -> dict[str, Any]:
    out = {"keyer": keying.keyer, "key_thresholds": thaw(keying.key_thresholds),
           "protect_boxes": [list(box) for box in keying.protect_boxes],
           "decal_box": None if keying.decal_box is None else list(keying.decal_box),
           "decal_version": keying.decal_version}
    if keying.decal_min_ecc is not None:
        out["decal_min_ecc"] = keying.decal_min_ecc
    return out


__all__ = [
    "DOLL", "FAIL", "IDENTITY_SCHEME", "LOOP", "NONE", "PINGPONG", "SET", "SUBJECT_CAPABILITY",
    "TIMED", "TRIM", "DriveTrack", "Keying", "Keys", "MotionRecord", "Source", "keying_document",
    "playback", "timed_trim",
]
