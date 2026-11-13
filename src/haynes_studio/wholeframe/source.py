"""The clip source interface of the whole-frame adapter (story 427).

A clip source turns one request (the board photo, prompt, profile and one
:class:`ClipSpec` per clip of the chain) into clips, each with the facts only the
engine knows: its job ID, engine and model files. Everything else in a clip's
provenance record (its hash, the frames it delivered, its start image) is measured
by the adapter (:mod:`.clips`), never taken from the source on trust.

How a chain is made (E0, ``poc/e0_batch.py``): clip 0 starts on the photo; clip *k*
starts on clip *k - 1*'s last frame, as a PNG made by :func:`last_frame_png` from that
clip's bytes, so the adapter can make the same PNG and check the chain. The seeds are
:func:`chain_seed` of the board's ``i2v:frame`` seed. A source makes the clips in order
and returns all of them, or raises; it never returns part of a chain.

The live source for the Wan service is a later story; :mod:`.fake` is the test source.
"""

from __future__ import annotations

import hashlib
import io
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import PIL.Image

from haynes_studio.render.encode import decode_frames

PHOTO = "photo"  # clip 0's start image role: the board's current photo version
PREVIOUS_LAST_FRAME = "previous_last_frame"  # clip k's: clip k - 1's last frame
PNG = "image/png"
MP4 = "video/mp4"


def chain_seed(seed: int, index: int) -> int:
    """The seed of clip ``index`` of a chain (**proposal**): the board's ``i2v:frame``
    seed plus the clip's index, so clip 0 uses the board's own seed and a re-roll (a
    seed edit) changes every clip. E0 used unrelated seeds for chained clips."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("a seed is an integer")
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise ValueError("a clip index is a non-negative integer")
    return seed + index


def png_bytes(frame: np.ndarray) -> bytes:
    """One RGB frame as PNG bytes, with no metadata, so the same pixels give the same
    bytes within one Pillow build."""
    buffer = io.BytesIO()
    PIL.Image.fromarray(np.ascontiguousarray(frame)).save(buffer, format="PNG")
    return buffer.getvalue()


def last_frame_png(clip: bytes) -> bytes:
    """The start image of the next clip of a chain: ``clip``'s last decoded frame as
    PNG (:func:`png_bytes`). A live source must make it with this function."""
    last = None
    for last in decode_frames(clip):
        pass
    if last is None:
        raise ValueError("the clip has no frame")
    return png_bytes(last)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class ClipSpec:
    """One clip to make: its place in the chain, its requested length and its seed."""

    index: int
    frames: int
    seed: int


@dataclass(frozen=True)
class ClipRequest:
    """Everything a source needs for one chain. ``key`` is the whole-frame clip key's
    value (the source may use it to name or deduplicate its jobs); ``profile`` is the
    key's profile (model, ``source_fps``, ``size``, ``adapter``, ``delivery``)."""

    key: str
    photo: bytes = field(repr=False)
    photo_sha256: str
    prompt: str
    seed: int
    profile: Mapping[str, Any]
    clips: tuple[ClipSpec, ...]

    @property
    def clip_lengths(self) -> tuple[int, ...]:
        return tuple(spec.frames for spec in self.clips)


@dataclass(frozen=True)
class SourceClip:
    """One clip as the engine delivered it.

    ``engine`` names the engine and its version (``wan-api/ti2v-5b``),
    ``engine_job_id`` the engine's job, ``files_sha256`` the model files it loaded
    (name to SHA-256, contract section 7's ``generator.files_sha256``),
    ``start_image_sha256`` the start image it was given, and ``extra`` any engine
    facts worth keeping (timings, temperatures, hardware), as plain JSON."""

    index: int
    data: bytes = field(repr=False)
    seed: int
    frames_requested: int
    start_image_sha256: str
    engine: str
    engine_job_id: str
    files_sha256: Mapping[str, str]
    media_type: str = MP4
    extra: Mapping[str, Any] = field(default_factory=dict)


class ClipSource(ABC):
    """Makes the clips of one chain. ``name`` (a version string) goes in the clip
    set's record; it is not a key input, because the key's profile names the model."""

    name: str

    @abstractmethod
    def generate(self, request: ClipRequest) -> Sequence[SourceClip]:
        """Every clip of ``request.clips``, in order, or an exception. Never part of a
        chain, never a clip of another length, size or start image than asked."""
