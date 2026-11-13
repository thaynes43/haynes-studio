"""Measured takes and the assembled board voice track, with the standard library only.

A take is a 16-bit PCM mono WAV at 8000 to 48000 Hz, what the speech service answers
(Kokoro: 24 kHz mono); anything else is ``voice.format_mismatch``, decided from the
header before the frames are read. The track is the takes at their TIME-2 offsets with
silence for the lead and the gaps, at the takes' own sample rate: no resampling happens
here (the mix converts to 48 kHz later, VOICE-7). Take *i* starts at sample
``offset_ms[i] * rate div 1000`` and the track ends at sample
``speech_end_ms * rate div 1000``; at 24 kHz both are exact (24 samples per ms). TIME-1
rounds a take's length up to the millisecond, so the silence after a take is whole
samples and never negative, at any rate. Proposal (story 405): this layout, and the
track ending at the last take's TIME-2 end (the tail is not part of the voice).

Bounds (proposal, story 405), checked before any buffer is sized: a take, the lead and
each gap are at most 120000 ms, and the track at most 600000 ms (``schema.invalid``), so
the track's PCM is at most :data:`TRACK_MAX_BYTES` (600 s at 48 kHz, mono, 16-bit).
"""

from __future__ import annotations

import io
import wave
from collections.abc import Sequence
from dataclasses import dataclass, field

from haynes_studio.canonical.validate import SCHEMA_INVALID
from haynes_studio.errors import ContractError, Violation
from haynes_studio.timebase import take_duration_ms
from haynes_studio.voice.model import GAP_MAX_MS, LEAD_MAX_MS, TAKE_MAX_MS, TRACK_MAX_MS

FORMAT_MISMATCH = "voice.format_mismatch"  # proposal
SAMPLE_WIDTH = 2  # 16-bit PCM, as Kokoro answers
CHANNELS = 1  # mono, as Kokoro answers
RATE_MIN, RATE_MAX = 8000, 48000
TRACK_MAX_BYTES = TRACK_MAX_MS * RATE_MAX // 1000 * CHANNELS * SAMPLE_WIDTH  # 57 600 000


def _error(path: str, message: str, rule: str = FORMAT_MISMATCH) -> ContractError:
    return ContractError("<voice track>", [Violation(rule, path, message)])


def _invalid(path: str, message: str) -> ContractError:
    return _error(path, message, SCHEMA_INVALID)


def _take_format(channels: int, width: int, rate: int, frames: int) -> str | None:
    """Why this is not a take the speech service could have answered, or None."""
    if (width, channels) != (SAMPLE_WIDTH, CHANNELS) or not RATE_MIN <= rate <= RATE_MAX or frames < 1:
        return (f"a take is 16-bit PCM, mono, {RATE_MIN} to {RATE_MAX} Hz, with audio; this one "
                f"is {channels} channel(s), {8 * width}-bit, {rate} Hz, {frames} frames")
    return None


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
    """The PCM frames of a take: 16-bit PCM, mono, 8000 to 48000 Hz
    (``voice.format_mismatch``), at most 120000 ms (``schema.invalid``). Both are decided
    from the header, before the frames are read."""
    try:
        reader = wave.open(io.BytesIO(data), "rb")
    except (wave.Error, EOFError, ValueError) as error:
        raise _error(path, f"not a PCM WAV ({type(error).__name__})") from None
    with reader:
        channels, width, rate = reader.getnchannels(), reader.getsampwidth(), reader.getframerate()
        frames = reader.getnframes()
        refused = _take_format(channels, width, rate, frames)
        if refused is not None:
            raise _error(path, refused)
        duration = take_duration_ms(frames, rate)
        if duration > TAKE_MAX_MS:
            raise _invalid(path, f"a take is at most {TAKE_MAX_MS} ms; this one is {duration} ms")
        try:
            pcm = reader.readframes(frames)
        except (wave.Error, EOFError, ValueError) as error:
            raise _error(path, f"not a PCM WAV ({type(error).__name__})") from None
    if len(pcm) != frames * channels * width:
        raise _error(path, "the WAV holds fewer frames than its header says")
    return Pcm(channels=channels, sample_width=width, rate=rate, frames=frames, data=pcm)


def _whole_ms(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def assemble(takes: Sequence[Pcm], offsets_ms: Sequence[int], speech_end_ms: int) -> bytes:
    """The board voice track: each take at its offset, silence elsewhere, ending at
    ``speech_end_ms``. Every take must be a 16-bit mono take of one rate
    (``voice.format_mismatch``). A take, the lead (the first offset) and each gap are at
    most 120000 ms and the track at most 600000 ms (``schema.invalid``); the buffer
    (at most :data:`TRACK_MAX_BYTES`) is sized only after every check."""
    if not takes or len(takes) != len(offsets_ms):
        raise _error("/takes", "one offset per take, and at least one take")
    if not all(_whole_ms(offset) for offset in offsets_ms) or not _whole_ms(speech_end_ms):
        raise _invalid("/takes", "offsets and the end are integer milliseconds")
    channels, width, rate = takes[0].shape
    durations = []
    for i, take in enumerate(takes):
        refused = _take_format(*take.shape, take.frames)
        if refused is not None:
            raise _error(f"/takes/{i}", refused)
        if take.shape != (channels, width, rate):
            raise _error(f"/takes/{i}",
                         f"takes differ in format ({take.shape} after {takes[0].shape}); the "
                         "track is assembled without resampling")
        durations.append(take_duration_ms(take.frames, rate))
        if durations[-1] > TAKE_MAX_MS:
            raise _invalid(f"/takes/{i}", f"a take is at most {TAKE_MAX_MS} ms; this one is "
                                          f"{durations[-1]} ms")
        if len(take.data) != take.frames * channels * width:
            raise _error(f"/takes/{i}", "the take holds another number of frames than it says")
    end_ms = None
    for i, (duration, offset) in enumerate(zip(durations, offsets_ms)):
        silence, limit, what = ((offset, LEAD_MAX_MS, "the lead") if end_ms is None
                                else (offset - end_ms, GAP_MAX_MS, "a gap"))
        if silence > limit:
            raise _invalid(f"/takes/{i}", f"{what} is at most {limit} ms; this one is {silence} ms")
        end_ms = offset + duration
    if speech_end_ms > TRACK_MAX_MS:
        raise _invalid("/speech_end_ms", f"a track is at most {TRACK_MAX_MS} ms; this one is "
                                         f"{speech_end_ms} ms")
    frame_bytes = channels * width
    total = speech_end_ms * rate // 1000
    if total * frame_bytes > TRACK_MAX_BYTES:  # follows from the checks above; kept explicit
        raise _invalid("/speech_end_ms", f"a track's PCM is at most {TRACK_MAX_BYTES} bytes")
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
        writer.writeframes(out)
    return buffer.getvalue()


__all__ = ["CHANNELS", "FORMAT_MISMATCH", "RATE_MAX", "RATE_MIN", "SAMPLE_WIDTH",
           "TRACK_MAX_BYTES", "Pcm", "assemble", "read_wav"]
