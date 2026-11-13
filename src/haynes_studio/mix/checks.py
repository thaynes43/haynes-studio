"""Sound checks as data (story 841): each a check result keyed by ``check_result_key``.

A check measures one artifact (the mix or the master) against its thresholds and
returns a JSON document; it never raises for a failing measurement. The thresholds
carry every story value the verdict depends on (the loudness target, the film's
length), so a check result is a pure function of its key: the artifact's hash, the
check, its version and its thresholds. A meter build can read a programme slightly
differently, so the version names the filter build and every threshold is a stated
tolerance; decoded samples are compared, never file hashes.

- ``mix.length`` (mix): 48 000 Hz, 2 channels, 24-bit PCM, exactly ``frames x 2000``
  samples (TIME-11).
- ``mix.loudness``, ``master.loudness``: integrated loudness within 1.5 LU of the
  story's target (legacy ``validate``: ``abs(I - lufs) <= 1.5``).
- ``mix.true_peak``, ``master.true_peak``: true peak at most 1 dB over the story's
  target (legacy ``validate``: ``input_tp <= -2.5`` at r4's -3.5; proposal: relative).
- ``mix.clipping``, ``master.clipping``: no sample at full scale (legacy ``validate``:
  ``abs(a) >= 1`` on the master).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from haynes_studio.cache.keys import CacheKey, check_result_key
from haynes_studio.mix.audio import (
    FULL_SCALE_24,
    Loudness,
    decode_audio,
    filter_build,
    measure,
    read_pcm,
)
from haynes_studio.mix.errors import MixError
from haynes_studio.timebase import MIX_RATE, SAMPLES_PER_FRAME

SCHEMA = "studio.check-result/v1"  # proposal
LOUDNESS_TOLERANCE_LU = 1.5  # legacy validate
TRUE_PEAK_MARGIN_DB = 1.0  # legacy validate: -2.5 dBTP at r4's -3.5 target (proposal: relative)
MIX, MASTER = "mix", "master"
CHECKS = ("mix.length", "mix.loudness", "mix.true_peak", "mix.clipping",
          "master.loudness", "master.true_peak", "master.clipping")


def version() -> str:
    """Every check's version: the scheme and the decoder and meter build."""
    return f"1/{filter_build()}"


def thresholds(check: str, mix_document: Mapping[str, Any]) -> dict[str, Any]:
    """The thresholds of ``check`` for the film whose mix key document is given: the
    story's targets and the film's length come from it."""
    family = check.split(".", 1)[1]
    if family == "length":
        return {"samples": mix_document["frames"] * SAMPLES_PER_FRAME, "rate": MIX_RATE,
                "channels": 2, "bits": 24}
    if family == "loudness":
        return {"target_lufs": mix_document["master_lufs"],
                "tolerance_lu": LOUDNESS_TOLERANCE_LU}
    if family == "true_peak":
        return {"max_dbtp": mix_document["true_peak_dbtp"] + TRUE_PEAK_MARGIN_DB}
    if family == "clipping":
        return {"max_clipped_samples": 0}
    raise ValueError(f"unknown sound check {check!r}")


def check_key(check: str, artifact: str, mix_document: Mapping[str, Any]) -> CacheKey:
    """The check result's key (section 4: artifact hash, check version, thresholds)."""
    return check_result_key(artifact=artifact, check=check, version=version(),
                            thresholds=thresholds(check, mix_document))


@dataclass
class Measured:
    """What one artifact measured, computed once for all its checks."""

    samples: np.ndarray
    loudness: Loudness
    clipped: int
    header: dict[str, int] | None = None


def measure_mix(data: bytes) -> Measured:
    pcm = read_pcm(data, where="mix")
    samples = pcm.samples
    # A 24-bit sample is at full scale at code +8388607 or -8388608.
    full = np.float32(FULL_SCALE_24 / 8388608.0)
    clipped = int(np.count_nonzero(np.abs(samples) >= full))
    loud = measure(samples, where="mix") if pcm.channels == 2 and pcm.rate == MIX_RATE \
        else Loudness(None, None)
    return Measured(samples=samples, loudness=loud, clipped=clipped,
                    header={"samples": samples.shape[0], "rate": pcm.rate,
                            "channels": pcm.channels, "bits": 8 * pcm.width})


def measure_master(data: bytes) -> Measured:
    samples = decode_audio(data, where="master")
    clipped = int(np.count_nonzero(np.abs(samples) >= 1.0))
    return Measured(samples=samples, loudness=measure(samples, where="master"), clipped=clipped)


def evaluate(check: str, key: CacheKey, measured: Measured) -> dict[str, Any]:
    """The check result document for ``key``, from what the artifact measured."""
    limits = dict(key.document["thresholds"])
    family = check.split(".", 1)[1]
    if family == "length":
        got = dict(measured.header or {})
        passed = got == limits
        values: dict[str, Any] = got
    elif family == "loudness":
        lufs = measured.loudness.integrated_lufs
        values = {"integrated_lufs": lufs}
        passed = lufs is not None and abs(lufs - limits["target_lufs"]) <= limits["tolerance_lu"]
    elif family == "true_peak":
        peak = measured.loudness.true_peak_dbtp
        values = {"true_peak_dbtp": None if peak is None else round(peak, 3)}
        passed = peak is None or peak <= limits["max_dbtp"]
    elif family == "clipping":
        values = {"clipped_samples": measured.clipped}
        passed = measured.clipped <= limits["max_clipped_samples"]
    else:
        raise MixError("mix.check_failed", f"unknown sound check {check!r}")
    return {"schema": SCHEMA, "check": check, "version": key.document["version"],
            "artifact": key.document["artifact"], "thresholds": limits, "measured": values,
            "passed": bool(passed)}
