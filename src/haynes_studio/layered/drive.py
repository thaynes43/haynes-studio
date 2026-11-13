"""Speech-to-video drive tracks (story 426, TIME-9, keyed by ``s2v_drive_track_key``).

Each on-screen speaker of a layered S2V board gets one drive track: her takes on the
board at their TIME-2 starts, silence elsewhere, **exactly** the board's ``F / 24``
seconds. The key names her takes (hash and start in ms), ``frames``, ``fps``, ``rate``
and the assembler, and nothing else, so a line edit rebuilds only the tracks whose
takes or starts moved (P-25).

The track is assembled at the takes' own rate, as the board voice track is
(**proposal**: no resampling; the key's ``rate`` must be the takes' rate, 24 kHz for
Kokoro, and must make ``F / fps`` seconds and every millisecond whole samples). It is a
16-bit mono PCM WAV (``audio/wav``). A take of another format or rate, a take that
runs past the board's end, or a rate that cannot hold the board exactly is refused
(``layered.drive_invalid``); nothing is resampled, cut or padded to fit.
"""

from __future__ import annotations

import io
import wave
from collections.abc import Callable, Mapping
from typing import Any, BinaryIO

import numpy as np

from haynes_studio.cache.artifacts import ArtifactCache, CachedArtifact
from haynes_studio.cache.keys import S2V_DRIVE_TRACK, CacheKey
from haynes_studio.errors import ContractError
from haynes_studio.layered.errors import DRIVE_INVALID, UNSUPPORTED, LayeredError
from haynes_studio.layered.keyed import read_verified
from haynes_studio.voice.track import read_wav

ASSEMBLER = "studio.s2v.drive/1"  # the Toolchain's drive_assembler this stage implements
WAV = "audio/wav"


def drive_samples(frames: int, fps: int, rate: int) -> int:
    """The samples of a drive track for a board of ``frames`` at ``fps``: exactly
    ``frames / fps`` seconds, or ``layered.drive_invalid`` when ``rate`` cannot hold
    that, or a millisecond, in whole samples."""
    if rate % 1000 or (frames * rate) % fps:
        raise LayeredError(DRIVE_INVALID, f"{rate} Hz cannot hold {frames} frames at {fps} fps "
                           "and every millisecond in whole samples (TIME-9 asks for exactly F / 24 s)")
    return frames * rate // fps


def assemble_drive(document: Mapping[str, Any], takes: Mapping[str, bytes]) -> bytes:
    """The drive track of a ``s2v_drive_track`` key document from its takes' WAV bytes
    (by hash): each take at its start, silence elsewhere, exactly the board's length."""
    rate, frames, fps = document["rate"], document["frames"], document["fps"]
    total = drive_samples(frames, fps, rate)
    out = np.zeros(total, dtype=np.int32)
    for index, (sha, start_ms) in enumerate(document["lines"]):
        try:
            pcm = read_wav(takes[sha], f"/lines/{index}")
        except ContractError as error:
            raise LayeredError(DRIVE_INVALID, f"take {index} is not a speech take: {error}",
                               where=sha) from error
        if pcm.rate != rate:
            raise LayeredError(DRIVE_INVALID, f"take {index} is {pcm.rate} Hz; the drive track is "
                               f"{rate} Hz and nothing is resampled", where=sha)
        samples = np.frombuffer(pcm.data, dtype="<i2").astype(np.int32)
        start = start_ms * rate // 1000
        if start + samples.size > total:
            raise LayeredError(DRIVE_INVALID, f"take {index} ends at sample {start + samples.size}, "
                               f"after the board's {total}", where=sha)
        out[start:start + samples.size] += samples
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as track:
        track.setnchannels(1)
        track.setsampwidth(2)
        track.setframerate(rate)
        track.writeframes(np.clip(out, -32768, 32767).astype("<i2").tobytes())
    return buffer.getvalue()


def track_frames(data: bytes, fps: int = 24) -> tuple[int, int]:
    """A drive track's board frames and rate, from its length: ``(frames, rate)``.
    A track that is not a whole number of frames is ``layered.drive_invalid``."""
    try:
        with wave.open(io.BytesIO(data), "rb") as track:
            rate, samples = track.getframerate(), track.getnframes()
    except (wave.Error, EOFError, ValueError) as error:
        raise LayeredError(DRIVE_INVALID, f"the drive track is not a PCM WAV ({type(error).__name__})") from error
    if (samples * fps) % rate:
        raise LayeredError(DRIVE_INVALID, f"a drive track of {samples} samples at {rate} Hz is not "
                           f"a whole number of frames")
    return samples * fps // rate, rate


class DriveTracks:
    """The drive-track stage on ``cache``: a ``content`` source for ``s2v_drive_track``
    keys. ``read_take`` opens a take by hash (``audio/wav`` in the production)."""

    def __init__(self, cache: ArtifactCache, *, read_take: Callable[[str], BinaryIO],
                 assembler: str = ASSEMBLER):
        self.cache = cache
        self.read_take = read_take
        self.assembler = assembler
        self.made: list[str] = []

    def __call__(self, key: CacheKey) -> str:
        return self.track(key).sha256

    def track(self, key: CacheKey) -> CachedArtifact:
        if key.kind != S2V_DRIVE_TRACK:
            raise LookupError(f"the drive-track stage makes no {key.kind} artifacts")
        document = key.document
        if document["assembler"] != self.assembler:
            raise LayeredError(UNSUPPORTED, f"the key names assembler {document['assembler']!r}; "
                               f"this is {self.assembler!r}", where="/assembler")
        drive_samples(document["frames"], document["fps"], document["rate"])  # refuse first
        found = self.cache.lookup(key, WAV)
        if found is not None:
            return found
        takes = {sha: read_verified(self.read_take, sha, "a take") for sha, _ in document["lines"]}
        data = assemble_drive(document, takes)
        self.made.append(key.value)
        return self.cache.commit(key, data, WAV)


__all__ = ["ASSEMBLER", "DriveTracks", "WAV", "assemble_drive", "drive_samples", "track_frames"]
