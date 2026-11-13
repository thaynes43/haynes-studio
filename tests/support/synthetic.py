"""Synthetic media made at test time with the standard library.

Committed fixtures are text only (contract section 14). A test that needs audio asks
for the ``synthetic_wav`` fixture, or calls ``write_sine_wav`` with a path under its
own ``tmp_path``. These helpers refuse a path inside the checkout and refuse clips
longer than ``MAX_SECONDS``.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

from tests.support.policy import REPO_ROOT

MAX_SECONDS = 10.0


def _refuse_checkout(path: Path) -> Path:
    resolved = path.resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise ValueError(f"synthetic media must be written outside the checkout: {path}")
    return resolved


def write_sine_wav(
    path: Path,
    *,
    seconds: float = 1.0,
    rate: int = 16_000,
    frequency: float = 440.0,
    amplitude: float = 0.25,
) -> Path:
    """Write a mono 16-bit PCM sine tone and return its resolved path."""
    if not 0 < seconds <= MAX_SECONDS:
        raise ValueError(f"synthetic clips are 0 to {MAX_SECONDS:g} s, not {seconds:g} s")
    target = _refuse_checkout(Path(path))
    frames = round(seconds * rate)
    peak = int(32767 * amplitude)
    samples = (
        round(peak * math.sin(2 * math.pi * frequency * n / rate)) for n in range(frames)
    )
    with wave.open(str(target), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"".join(struct.pack("<h", s) for s in samples))
    return target
