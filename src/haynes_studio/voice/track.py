"""Measured takes and the assembled board voice track, with the standard library only.

A take is a 16-bit PCM WAV (Kokoro answers 24 kHz mono). The track is the takes at
their TIME-2 offsets with silence for the lead and the gaps, at the takes' own sample
rate: no resampling happens here (the mix converts to 48 kHz later, VOICE-7). Take
*i* starts at sample ``offset_ms[i] * rate div 1000`` and the track ends at sample
``speech_end_ms * rate div 1000``; at 24 kHz both are exact (24 samples per ms).
TIME-1 rounds a take's length up to the millisecond, so the silence after a take is
whole samples and never negative, at any rate. Proposal (story 405): this layout, and
the track ending at the last take's TIME-2 end (the tail is not part of the voice).
"""

from __future__ import annotations

import io
import wave
from collections.abc import Sequence
from dataclasses import dataclass, field

from haynes_studio.errors import ContractError, Violation

FORMAT_MISMATCH = "voice.format_mismatch"  # proposal
SAMPLE_WIDTH = 2  # 16-bit PCM, as Kokoro answers


def _error(path: str, message: str) -> ContractError:
    return ContractError("<voice track>", [Violation(FORMAT_MISMATCH, path, message)])


@dataclass(frozen=True)
class Pcm:
    """One WAV's PCM frames and format."""

    channels: int
    sample_width: int
    rate: int
    frames: int
    data: bytes = field(repr=False)

    @property
    def shape(self) -> tuple[int, int, int]:
        return (self.channels, self.sample_width, self.rate)


def read_wav(data: bytes, path: str = "") -> Pcm:
    """The PCM frames of a 16-bit WAV, or ``voice.format_mismatch``."""
    try:
        with wave.open(io.BytesIO(data), "rb") as reader:
            channels, width, rate = (reader.getnchannels(), reader.getsampwidth(),
                                     reader.getframerate())
            frames = reader.getnframes()
            pcm = reader.readframes(frames)
    except (wave.Error, EOFError, ValueError) as error:
        raise _error(path, f"not a PCM WAV ({type(error).__name__})") from None
    if width != SAMPLE_WIDTH or channels < 1 or rate < 1 or frames < 1:
        raise _error(path, f"a take is 16-bit PCM with audio; this one is {channels} channel(s), "
                           f"{8 * width}-bit, {rate} Hz, {frames} frames")
    if len(pcm) != frames * channels * width:
        raise _error(path, "the WAV holds fewer frames than its header says")
    return Pcm(channels=channels, sample_width=width, rate=rate, frames=frames, data=pcm)


def assemble(takes: Sequence[Pcm], offsets_ms: Sequence[int], speech_end_ms: int) -> bytes:
    """The board voice track: each take at its offset, silence elsewhere, ending at
    ``speech_end_ms``. Every take must share one channel count, width and rate."""
    if not takes or len(takes) != len(offsets_ms):
        raise _error("/takes", "one offset per take, and at least one take")
    channels, width, rate = takes[0].shape
    for i, take in enumerate(takes):
        if take.shape != (channels, width, rate):
            raise _error(f"/takes/{i}",
                         f"takes differ in format ({take.shape} after {takes[0].shape}); the "
                         "track is assembled without resampling")
    frame_bytes = channels * width
    total = speech_end_ms * rate // 1000
    out = bytearray(total * frame_bytes)  # zeros: 16-bit silence
    cursor = 0
    for i, (take, offset) in enumerate(zip(takes, offsets_ms)):
        start = offset * rate // 1000
        if start < cursor or start + take.frames > total:
            raise _error(f"/takes/{i}", "the take does not fit between its offset and the next "
                                        "(TIME-1, TIME-2)")
        out[start * frame_bytes:(start + take.frames) * frame_bytes] = take.data
        cursor = start + take.frames
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(width)
        writer.setframerate(rate)
        writer.writeframes(bytes(out))
    return buffer.getvalue()


__all__ = ["FORMAT_MISMATCH", "SAMPLE_WIDTH", "Pcm", "assemble", "read_wav"]
