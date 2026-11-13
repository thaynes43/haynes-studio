"""The speech-to-video clip source of the layered adapter (story 426).

A source turns one :class:`S2VRequest` (one speaker's drive track, her start image,
prompt, negative prompt, seed ``s2v:<slot>``, profile and the requested length ``L`` of
TIME-9) into one :class:`S2VClip` with the facts only the engine knows: its job ID,
engine and model files. Everything else in the clip's provenance record (its hash, the
frames it decodes to, its size) is measured by the adapter (:mod:`.s2v`), never taken
from the source on trust.

The live source for the Wan service is story 842's; :mod:`.fake` is the test source.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

MP4 = "video/mp4"


@dataclass(frozen=True)
class S2VRequest:
    """Everything a source needs for one speaker's clip. ``key`` is the S2V clip key's
    value (to name or deduplicate the job); ``profile`` is the key's profile (model,
    LoRA, steps, cfg, ``size`` ``[width, height]``, ``chunk``, ``source_fps``,
    ``delivery``); ``frames`` is TIME-9's ``L``; ``board_frames`` the board's ``F`` and
    ``frames_needed`` TIME-8's ``floor((F - 1) * fs / 24) + 1``."""

    key: str
    drive_track: bytes = field(repr=False)
    drive_track_sha256: str
    start_image: bytes = field(repr=False)
    start_image_sha256: str
    prompt: str
    negative_prompt: str
    seed: int
    profile: Mapping[str, Any]
    adapter: str
    frames: int
    board_frames: int
    frames_needed: int


@dataclass(frozen=True)
class S2VClip:
    """One clip as the engine delivered it. ``engine`` names the engine and version,
    ``engine_job_id`` its job, ``files_sha256`` the model files it loaded (name to
    SHA-256, contract section 7), ``start_image_sha256`` and ``drive_track_sha256``
    what it was given, ``extra`` engine facts worth keeping, as plain JSON."""

    data: bytes = field(repr=False)
    seed: int
    frames_requested: int
    start_image_sha256: str
    drive_track_sha256: str
    engine: str
    engine_job_id: str
    files_sha256: Mapping[str, str]
    media_type: str = MP4
    extra: Mapping[str, Any] = field(default_factory=dict)


class S2VSource(ABC):
    """Makes one speech-to-video clip. ``name`` (a version string) goes in the clip's
    provenance record; it is not a key input, because the key's profile names the
    model."""

    name: str

    @abstractmethod
    def generate(self, request: S2VRequest) -> S2VClip:
        """The clip, or an exception. Never a clip of another size, seed, start image
        or drive track than asked, never one it did not make."""


__all__ = ["MP4", "S2VClip", "S2VRequest", "S2VSource"]
