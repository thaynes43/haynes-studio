"""Synthetic audio and a store-backed build for the sound tests (story 841).

Everything is made at test time and kept small: tones, constant (DC) signals whose
fades can be read sample by sample, noise beds and a few seconds of the cache
fixture's synthetic picture. Media never touches the checkout: in-memory bytes, or a
store under ``tmp_path``.
"""

from __future__ import annotations

import copy
import hashlib
import io
import wave
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np

from haynes_studio.cache import ArtifactCache, BoardVoice, TakeFacts, plan_story
from haynes_studio.cache.build import PictureBuilder
from haynes_studio.cache.keys import CacheKey, mix_key
from haynes_studio.cache.plan import StoryPlan, Toolchain, take_keys
from haynes_studio.canonical import Story, load_story
from haynes_studio.mix import MIXER, SoundBuilder, sound_toolchain
from haynes_studio.render.synthetic import SyntheticRenderer
from haynes_studio.store import LocalStore
from tests.cache import fixtures as fx

TAKE_RATE = 24_000


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def wav16(samples: np.ndarray, rate: int) -> bytes:
    """16-bit PCM WAV of float samples, (n,) mono or (n, channels)."""
    data = samples if samples.ndim == 2 else samples[:, None]
    codes = np.clip(np.rint(data * 32767), -32768, 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(data.shape[1])
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(codes.tobytes())
    return buffer.getvalue()


def tone(samples: int, rate: int, freq: float, amp: float,
         phase: float = np.pi / 2) -> np.ndarray:
    t = np.arange(samples) / rate
    return (amp * np.sin(2 * np.pi * freq * t + phase)).astype(np.float32)


def noise(samples: int, amp: float, seed: int) -> np.ndarray:
    return (amp * np.random.default_rng(seed).standard_normal(samples)).astype(np.float32)


class Blobs(dict):
    """Bytes by hash: an in-memory reader for :func:`haynes_studio.mix.mix`."""

    def add(self, data: bytes) -> str:
        digest = sha(data)
        self[digest] = data
        return digest

    def read(self, sha256: str, where: str) -> bytes:
        return self[sha256]


def track(takes: Sequence[np.ndarray], offsets_ms: Sequence[int], end_ms: int,
          rate: int = TAKE_RATE) -> bytes:
    """A board voice track as story 405 assembles it: take *i* at sample
    ``offset_ms * rate div 1000``, silence between, ending at ``end_ms``."""
    out = np.zeros(end_ms * rate // 1000, np.float32)
    for take, offset in zip(takes, offsets_ms):
        at = offset * rate // 1000
        out[at:at + take.shape[0]] = take
    return wav16(out, rate)


def key(*, tracks=(), sounds=(), beds=(), frames: int, line_rms: float = -22,
        lufs: float = -20, true_peak: float = -3.5, mixer: str | None = None) -> CacheKey:
    return mix_key(voice_tracks=list(tracks), sounds=list(sounds), beds=list(beds),
                   line_rms_dbfs=line_rms, master_lufs=lufs, true_peak_dbtp=true_peak,
                   frames=frames, rate=48_000, mixer=mixer or MIXER.version())


# The cache fixture story with real synthetic audio ---------------------------------------


def take_audio(text: str) -> np.ndarray:
    """A take exactly ``take_ms(text)`` ms long at 24 kHz: a tone per text."""
    n = fx.take_ms(text) * TAKE_RATE // 1000
    return tone(n, TAKE_RATE, 180 + 7 * len(text), 0.25)


def real_voices(story: Story, store: LocalStore,
                toolchain: Toolchain = Toolchain()) -> dict[str, BoardVoice]:
    """Each spoken board's voice with a real track published in the production's folder
    (takes keep the cache fixture's stand-in hashes and lengths)."""
    out = {}
    for board in story.ordered_boards():
        if not board.spoken:
            continue
        keys = take_keys(story, board, voice_ids=fx.VOICE_IDS, toolchain=toolchain)
        takes, offsets, at = [], [], board.timing.lead_ms
        for i, line in enumerate(board.lines):
            at += 0 if i == 0 else line.gap_before_ms
            offsets.append(at)
            takes.append(take_audio(line.text))
            at += fx.take_ms(line.text)
        data = track(takes, offsets, at)
        store.publish(data, scope=fx.PRODUCTION, media_type="audio/wav")
        out[board.id] = BoardVoice(
            takes={line.id: TakeFacts(sha256=fx.stand_in(keys[line.id]),
                                      duration_ms=fx.take_ms(line.text))
                   for line in board.lines},
            track_sha256=sha(data))
    return out


def library_sounds(store: LocalStore) -> dict[str, str]:
    """The fixture's sound cue and bed as real WAVs in the library: asset version to
    content hash."""
    sound = np.stack([noise(48_000, 0.3, 1) * np.exp(-np.arange(48_000) / 9600)] * 2, 1)
    bed = np.stack([noise(3 * 44_100, 0.05, 2), noise(3 * 44_100, 0.05, 3)], 1)
    out = {}
    for asv, data in ((fx.SOUND, wav16(sound, 48_000)), (fx.BED_SOUND, wav16(bed, 44_100))):
        store.publish(data, scope="library", media_type="audio/wav")
        out[asv] = sha(data)
    return out


TOOLCHAIN = sound_toolchain(Toolchain())


class Build:
    """One build of a fixture document: picture and sound through one store."""

    def __init__(self, store: LocalStore, document: dict[str, Any], run_id: str,
                 earlier: Sequence[str] = (), *, blobs: Mapping[str, str] | None = None,
                 check_story: bool = True):
        self.story = load_story(copy.deepcopy(document), context="write", source="mix fixture")
        self.cache = ArtifactCache(store, production_id=fx.PRODUCTION, run_id=run_id,
                                   earlier_runs=earlier)
        self.sound = SoundBuilder(self.cache, story=self.story if check_story else None,
                                  upstream=fx.stand_in)
        self.picture = PictureBuilder(self.cache, SyntheticRenderer(), upstream=self.sound)
        self.voices = real_voices(self.story, store, TOOLCHAIN)
        self.blobs = {**fx.BLOBS, **library_sounds(store), **(blobs or {})}

    def plan(self, content: Callable[[CacheKey], str] | None = None) -> StoryPlan:
        return plan_story(self.story, voices=self.voices, blobs=self.blobs,
                          voice_ids=fx.VOICE_IDS, toolchain=TOOLCHAIN, media=fx.MEDIA,
                          content=content or self.picture)
