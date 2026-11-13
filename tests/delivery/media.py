"""Synthetic masters for the delivery tests, made at test time under ``tmp_path``.

Pictures are flat grey frames whose level changes per frame (cheap to encode), or, for
the proxy's bit-rate cap, 4x4 blocks of noise (hard to compress). Audio is a quiet
440 Hz tone. Encoders run with at most 2 threads. A clip is at most 10 s, except the
one 60 s proxy fixture contract section 14 allows for story 381 (``long=True``).
Nothing here is ever written inside the checkout.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import av
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MAX_SECONDS = 10
LONG_SECONDS = 60
FORMATS = {"mp4": "mp4", "mov": "mov", "mkv": "matroska"}


def write_master(path: Path, *, frames: int, width: int = 1080, height: int = 1920,
                 fps: int = 24, video_codec: str = "libx264", audio_codec: str | None = "aac",
                 audio_rate: int = 48_000, audio_samples: int | None = None,
                 container: str = "mp4", noise: bool = False, seed: int = 0,
                 threads: int = 2, long: bool = False) -> Path:
    """Write a synthetic master and return its path. ``audio_samples`` defaults to
    ``frames x audio_rate / fps`` (2000 per frame at 48 kHz); ``audio_codec=None``
    writes no audio stream."""
    path = Path(path)
    if path.resolve().is_relative_to(ROOT):
        raise ValueError(f"synthetic media must be written outside the checkout: {path}")
    limit = LONG_SECONDS if long else MAX_SECONDS
    if not 0 < frames <= limit * fps:
        raise ValueError(f"synthetic masters are at most {limit} s, not {frames} frames")
    rng = np.random.default_rng(seed)
    with av.open(str(path), "w", format=FORMATS[container]) as out:
        options = {"preset": "ultrafast", "crf": "30"} if video_codec == "libx264" else {}
        video = out.add_stream(video_codec, rate=fps, options=options)
        video.width, video.height, video.pix_fmt = width, height, "yuv420p"
        video.codec_context.thread_count = threads
        audio = None
        if audio_codec is not None:
            audio = out.add_stream(audio_codec, rate=audio_rate, layout="stereo")
            audio.codec_context.thread_count = 1
        for index in range(frames):
            if noise:
                blocks = rng.integers(16, 236, (height * 3 // 8, width // 4), dtype=np.uint8)
                planes = np.repeat(np.repeat(blocks, 4, axis=0), 4, axis=1)
            else:
                planes = np.full((height * 3 // 2, width), 128, dtype=np.uint8)
                planes[:height] = 16 + (index * 7) % 220
            frame = av.VideoFrame.from_ndarray(planes, format="yuv420p")
            frame.pts, frame.time_base = index, Fraction(1, fps)
            for packet in video.encode(frame):
                out.mux(packet)
        for packet in video.encode(None):
            out.mux(packet)
        if audio is not None:
            total = frames * audio_rate // fps if audio_samples is None else audio_samples
            size = audio.codec_context.frame_size or 1024
            for start in range(0, total, size):
                count = min(size, total - start)
                tone = 0.1 * np.sin(2 * np.pi * 440 * np.arange(start, start + count) / audio_rate)
                samples = np.ascontiguousarray(np.stack([tone, tone]).astype(np.float32))
                fmt = audio.codec_context.format.name
                if fmt == "s16p":
                    samples = (samples * 32767).astype(np.int16)
                elif fmt == "s16":
                    samples = (samples.T.reshape(1, -1) * 32767).astype(np.int16)
                elif fmt == "flt":
                    samples = np.ascontiguousarray(samples.T.reshape(1, -1))
                piece = av.AudioFrame.from_ndarray(samples, format=fmt, layout="stereo")
                piece.sample_rate, piece.pts = audio_rate, start
                piece.time_base = Fraction(1, audio_rate)
                for packet in audio.encode(piece):
                    out.mux(packet)
            for packet in audio.encode(None):
                out.mux(packet)
    return path
