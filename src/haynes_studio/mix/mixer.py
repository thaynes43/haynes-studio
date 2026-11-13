"""The film mix (story 841): a pure function of the mix key's inputs.

Ported from the legacy mixer (``poc/edit.py``, ``audio``), as contract v1 records it
(section 6, VOICE-7) and on the film clock (section 4). Its input is exactly the key
document :func:`haynes_studio.cache.keys.mix_key` made, plus the bytes its hashes name:

1. **Lines.** Each board voice track (16-bit mono PCM at the takes' rate, VOICE-2) is
   cut at each line's span, ``[start_ms, end_ms)`` on the board clock, converted to
   48 000 Hz stereo, set to ``line_rms_dbfs`` RMS, faded 5 ms at each edge and added
   at mix sample ``F[k] * 2000 + start_ms * 48`` (TIME-7) for exactly
   ``(end_ms - start_ms) * 48`` samples.
2. **Sound cues.** Each sound is decoded to 48 000 Hz stereo, trimmed to
   ``trim_ms * 48`` samples, set to its ``level_rms_dbfs`` RMS, faded in over 10 ms and
   out over 50 ms, and added at its ``start_sample``. A sound that runs past the film's
   end is cut there, and the cut is recorded (TIME-10).
3. **Beds.** Each bed is set to its RMS level, looped with 1 s crossfades under the
   whole film, faded in over 0.5 s and added.
4. **Headroom.** If the peak is over 0.5, the mix is scaled to a peak of 0.5.
5. **Loudness.** The gain to ``master_lufs`` (measured integrated loudness), then a
   peak limiter at 1 dB under ``true_peak_dbtp`` (attack 2 ms, release 60 ms, no
   auto-level, delay compensated), as one libavfilter graph.

The result is 48 000 Hz stereo 24-bit PCM of exactly ``frames * 2000`` samples (TIME-11)
and a placement record of what was placed where. Nothing reads the clock, the
environment or a file name. Reference: ``docs/reference/studio-mix.md``.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from haynes_studio.mix.audio import (
    decode_audio,
    filter_build,
    measure,
    read_pcm,
    run_filters,
    to_mix_rate,
    write_wav24,
)
from haynes_studio.mix.errors import CONSERVATION, CUE_OUT_OF_RANGE, INPUT_INVALID, MixError
from haynes_studio.store import HASH_MISMATCH, StoreError, canonical_json
from haynes_studio.timebase import MIX_RATE, SAMPLES_PER_FRAME, SAMPLES_PER_MS

Reader = Callable[[str, str], bytes]
"""Reads an input by content hash: ``read(sha256, where)`` returns exactly those bytes
or raises (the store's ``store.blob_missing`` or ``store.hash_mismatch``)."""

PLACEMENT_SCHEMA = "studio.mix-placement/v1"  # proposal


@dataclass(frozen=True)
class MixerSettings:
    """The mixer's behaviour, every number of it. Its :meth:`version` is the mix key's
    ``mixer`` input, so a change to any number here is a new mix (section 4: the mixer
    digest, including its fades). Values are the legacy ones (``poc/edit.py``) unless
    marked."""

    rate: int = MIX_RATE  # section 3; legacy RATE
    line_fade_ms: int = 5  # section 6; legacy edge = 240 samples
    sound_fade_in_ms: int = 10  # section 6; legacy 480 samples
    sound_fade_out_ms: int = 50  # section 6; legacy 2400 samples
    bed_crossfade_ms: int = 1000  # section 6; legacy fade = RATE
    bed_fade_in_ms: int = 500  # section 6; legacy RATE // 2
    rms_floor: float = 1e-8  # legacy max(rms, 1e-8)
    headroom_peak: float = 0.5  # legacy premaster step
    limiter_margin_db: float = 1.0  # legacy: limit 1 dB under the true-peak target
    limiter_attack_ms: int = 2  # legacy alimiter attack=2
    limiter_release_ms: int = 60  # legacy alimiter release=60
    limiter_latency: bool = True  # proposal: legacy left the 2 ms look-ahead delay in
    pcm_bits: int = 24  # legacy soundtrack.wav pcm_s24le
    resampler: str = "swr"  # libswresample defaults, as legacy read_audio
    build: str = field(default_factory=filter_build)

    def samples(self, ms: int) -> int:
        return ms * self.rate // 1000

    def version(self) -> str:
        """``studio.mixer/1:<16 hex>``: the scheme and a digest of every setting."""
        digest = hashlib.sha256(canonical_json(asdict(self))).hexdigest()[:16]
        return f"studio.mixer/1:{digest}"


MIXER = MixerSettings()


@dataclass(frozen=True)
class MixResult:
    """The mix's WAV bytes and its placement record (a JSON document)."""

    wav: bytes
    placement: dict[str, Any]


def _gain(samples: np.ndarray, level_dbfs: float, floor: float) -> float:
    """Legacy level: scale so the RMS over every sample of every channel is
    ``level_dbfs``."""
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2))) if samples.size else 0.0
    return 10 ** (level_dbfs / 20) / max(rms, floor)


def _db(gain: float) -> float | None:
    return round(20 * math.log10(gain), 6) if gain > 0 else None


def _ramp(n: int, up: bool) -> np.ndarray:
    ramp = np.linspace(0, 1, n, dtype=np.float64) if up else np.linspace(1, 0, n, dtype=np.float64)
    return ramp.astype(np.float32)[:, None]


def _int(document: Mapping[str, Any], name: str, where: str) -> int:
    value = document.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise MixError(INPUT_INVALID, f"{name} is an integer", where=where)
    return value


class _Mix:
    def __init__(self, document: Mapping[str, Any], read: Reader, settings: MixerSettings):
        self.doc, self.read, self.s = document, read, settings
        if document.get("kind") != "mix":
            raise MixError(INPUT_INVALID, f"not a mix key document: {document.get('kind')!r}")
        if _int(document, "rate", "rate") != settings.rate:
            raise MixError(INPUT_INVALID, f"the key mixes at {document['rate']} Hz, the mixer "
                           f"at {settings.rate}", where="rate")
        self.frames = _int(document, "frames", "frames")
        self.total = self.frames * SAMPLES_PER_FRAME
        self.mix = np.zeros((self.total, 2), np.float32)
        self.lines: list[dict[str, Any]] = []
        self.sounds: list[dict[str, Any]] = []
        self.beds: list[dict[str, Any]] = []

    def _bytes(self, sha256: str, where: str) -> bytes:
        data = self.read(sha256, where)
        if hashlib.sha256(data).hexdigest() != sha256:  # the reader's promise, kept here too
            raise StoreError(HASH_MISMATCH, f"{where} is not the bytes its key names")
        return data

    def place_lines(self) -> None:
        s = self.s
        edge = s.samples(s.line_fade_ms)
        tracks = self.doc["voice_tracks"]
        for t, track in enumerate(tracks):
            where = f"voice_tracks/{t}"
            pcm = read_pcm(self._bytes(track["track"], where), where=where)
            if pcm.channels != 1 or pcm.width != 2:
                raise MixError(INPUT_INVALID, "a board voice track is 16-bit mono PCM (VOICE-2)",
                               where=where)
            base = track["start_frame"] * SAMPLES_PER_FRAME
            limit = (tracks[t + 1]["start_frame"] * SAMPLES_PER_FRAME
                     if t + 1 < len(tracks) else self.total)
            for i, span in enumerate(track["spans"]):
                start_ms, end_ms = span
                where_line = f"{where}/spans/{i}"
                if not 0 <= start_ms < end_ms:
                    raise MixError(INPUT_INVALID, f"a line span is [{start_ms}, {end_ms}) ms",
                                   where=where_line)
                lo, hi = start_ms * pcm.rate // 1000, end_ms * pcm.rate // 1000
                if hi > pcm.samples.shape[0]:
                    raise MixError(INPUT_INVALID, f"the line ends at track sample {hi}, the "
                                   f"track has {pcm.samples.shape[0]}", where=where_line)
                length = (end_ms - start_ms) * SAMPLES_PER_MS
                line = to_mix_rate(pcm.samples[lo:hi], pcm.rate, where=where_line)
                line = _fit(line, length)
                gain = _gain(line, self.doc["line_rms_dbfs"], s.rms_floor)
                line = line * np.float32(gain)
                n = min(edge, length)
                line[:n] *= _ramp(edge, True)[:n]
                line[-n:] *= _ramp(edge, False)[-n:]
                at = base + start_ms * SAMPLES_PER_MS
                if at + length > limit:
                    raise MixError(CONSERVATION, f"the line ends at mix sample {at + length}, "
                                   f"after its board's end or the film's ({limit}) (TIME-11)",
                                   where=where_line)
                self.mix[at:at + length] += line
                self.lines.append({
                    "track": t, "line": i, "track_sha256": track["track"],
                    "start_frame": track["start_frame"], "board_start_ms": start_ms,
                    "board_end_ms": end_ms, "start_sample": at, "end_sample": at + length,
                    "level_rms_dbfs": self.doc["line_rms_dbfs"], "gain_db": _db(gain)})

    def place_sounds(self) -> None:
        s = self.s
        fade_in, fade_out = s.samples(s.sound_fade_in_ms), s.samples(s.sound_fade_out_ms)
        for c, cue in enumerate(self.doc["sounds"]):
            where = f"sounds/{c}"
            start = cue["start_sample"]
            if not 0 <= start < self.total:
                raise MixError(CUE_OUT_OF_RANGE, f"the sound starts at mix sample {start}, "
                               f"outside the film's {self.total} (TIME-10)", where=where)
            sound = decode_audio(self._bytes(cue["sound"], where), where=where)
            source = sound.shape[0]
            trim = cue.get("trim_ms")
            if trim is not None:
                lo, hi = trim[0] * SAMPLES_PER_MS, trim[1] * SAMPLES_PER_MS
                if not 0 <= lo < hi <= source:
                    raise MixError(INPUT_INVALID, f"trim {list(trim)} ms is outside the sound's "
                                   f"{source} samples", where=where)
                sound = sound[lo:hi]
            if sound.shape[0] < fade_out:
                raise MixError(INPUT_INVALID, f"the sound is {sound.shape[0]} samples, shorter "
                               f"than its {fade_out}-sample fade out", where=where)
            gain = _gain(sound, cue["level_rms_dbfs"], s.rms_floor)
            sound = sound * np.float32(gain)
            sound[:fade_in] *= _ramp(fade_in, True)
            sound[-fade_out:] *= _ramp(fade_out, False)
            length = sound.shape[0]
            placed = min(length, self.total - start)
            self.mix[start:start + placed] += sound[:placed]
            self.sounds.append({
                "sound": c, "sha256": cue["sound"], "start_sample": start,
                "end_sample": start + placed, "samples": length, "source_samples": source,
                "trim_ms": None if trim is None else list(trim),
                "cut_at_film_end": placed < length, "cut_samples": length - placed,
                "level_rms_dbfs": cue["level_rms_dbfs"], "gain_db": _db(gain)})

    def place_beds(self) -> None:
        s = self.s
        fade = s.samples(s.bed_crossfade_ms)
        fade_in = s.samples(s.bed_fade_in_ms)
        for b, bed in enumerate(self.doc["beds"]):
            where = f"beds/{b}"
            if bed.get("clock", "film") != "film":
                raise MixError(INPUT_INVALID, f"a bed runs on the film clock, got "
                               f"{bed.get('clock')!r}", where=where)
            sound = decode_audio(self._bytes(bed["sound"], where), where=where)
            if sound.shape[0] <= 2 * fade:
                raise MixError(INPUT_INVALID, f"a bed is longer than {2 * fade} samples to loop "
                               f"with {fade}-sample crossfades, got {sound.shape[0]}", where=where)
            gain = _gain(sound, bed["level_rms_dbfs"], s.rms_floor)
            sound = sound * np.float32(gain)
            loop, loops = _loop(sound, fade, self.total)
            n = min(fade_in, self.total)
            loop[:n] *= _ramp(fade_in, True)[:n]
            self.mix += loop
            self.beds.append({
                "bed": b, "sha256": bed["sound"], "start_sample": 0, "end_sample": self.total,
                "source_samples": sound.shape[0], "loops": loops,
                "level_rms_dbfs": bed["level_rms_dbfs"], "gain_db": _db(gain)})

    def master(self) -> dict[str, Any]:
        s, doc = self.s, self.doc
        peak = float(np.max(np.abs(self.mix))) if self.total else 0.0
        headroom_db = 0.0
        if peak > s.headroom_peak:
            self.mix *= np.float32(s.headroom_peak / peak)
            headroom_db = 20 * math.log10(s.headroom_peak / peak)
        before = measure(self.mix, where="mix")
        if before.integrated_lufs is None:
            gain_db = 0.0  # a silent programme has no loudness to set (proposal)
        else:
            gain_db = doc["master_lufs"] - before.integrated_lufs
        limit = 10 ** ((doc["true_peak_dbtp"] - s.limiter_margin_db) / 20)
        limiter = (f"limit={limit:.4f}:attack={s.limiter_attack_ms}:release={s.limiter_release_ms}"
                   f":level=0:latency={int(s.limiter_latency)}")
        out, _ = run_filters(self.mix, s.rate, (("volume", f"{gain_db}dB"), ("alimiter", limiter)),
                             where="limiter")
        if out.shape != (self.total, 2):
            raise MixError(CONSERVATION, f"the limiter gave {out.shape[0]} samples, the film "
                           f"has {self.total} (TIME-11)", where="limiter")
        self.mix = out
        return {"premaster_peak": round(peak, 9), "headroom_db": round(headroom_db, 6),
                "premaster_lufs": before.integrated_lufs, "master_gain_db": round(gain_db, 6),
                "limiter": {"limit": float(f"{limit:.4f}"), "attack_ms": s.limiter_attack_ms,
                            "release_ms": s.limiter_release_ms, "latency": s.limiter_latency}}


def _fit(samples: np.ndarray, length: int) -> np.ndarray:
    """Exactly ``length`` samples: the resampler's output trimmed, or padded with
    silence (only at a take rate that is not a whole number of samples per ms)."""
    if samples.shape[0] >= length:
        return np.array(samples[:length], dtype=np.float32)
    pad = np.zeros((length - samples.shape[0], samples.shape[1]), np.float32)
    return np.concatenate([samples, pad])


def _loop(bed: np.ndarray, fade: int, total: int) -> tuple[np.ndarray, int]:
    """The legacy bed loop, without its repeated concatenation: copy *k* starts at
    ``k * (len - fade)`` and crossfades linearly into the one before over ``fade``
    samples, until the loop covers ``total``; then it is cut to ``total``."""
    length = bed.shape[0]
    step = length - fade
    copies = 1
    while (copies - 1) * step + length < total:
        copies += 1
    out = np.zeros(((copies - 1) * step + length, 2), np.float32)
    out[:length] = bed
    ramp = np.linspace(0, 1, fade)[:, None]
    for k in range(1, copies):
        at = k * step
        out[at:at + fade] = out[at:at + fade] * (1 - ramp) + bed[:fade] * ramp
        out[at + fade:at + length] = bed[fade:]
    return out[:total].copy(), copies


def mix(document: Mapping[str, Any], read: Reader, *,
        settings: MixerSettings = MIXER) -> MixResult:
    """Mix the film the mix key ``document`` describes, reading each input by hash with
    ``read``. Raises :class:`~haynes_studio.mix.errors.MixError` (or the store's error
    for a missing or damaged input) and publishes nothing."""
    if document.get("mixer") != settings.version():
        raise MixError(INPUT_INVALID, f"the key names mixer {document.get('mixer')!r}, this "
                       f"mixer is {settings.version()!r}", where="mixer")
    job = _Mix(document, read, settings)
    job.place_lines()
    job.place_sounds()
    job.place_beds()
    loudness = job.master()
    placement = {
        "schema": PLACEMENT_SCHEMA, "mixer": settings.version(), "rate": settings.rate,
        "frames": job.frames, "samples": job.total, "channels": 2,
        "lines": job.lines, "sounds": job.sounds, "beds": job.beds, **loudness}
    return MixResult(wav=write_wav24(job.mix, settings.rate), placement=placement)


def planned_starts(document: Mapping[str, Any]) -> dict[str, list[dict[str, int]]]:
    """Where each line and sound of a mix key starts and (for lines) ends, in mix
    samples, from the key alone (TIME-7): no audio is read. A line's end is its span's;
    a sound's end needs its audio."""
    lines = [{"track": t, "line": i, "start_sample": track["start_frame"] * SAMPLES_PER_FRAME
              + span[0] * SAMPLES_PER_MS, "end_sample": track["start_frame"] * SAMPLES_PER_FRAME
              + span[1] * SAMPLES_PER_MS}
             for t, track in enumerate(document["voice_tracks"])
             for i, span in enumerate(track["spans"])]
    sounds = [{"sound": c, "start_sample": cue["start_sample"]}
              for c, cue in enumerate(document["sounds"])]
    return {"lines": lines, "sounds": sounds}
