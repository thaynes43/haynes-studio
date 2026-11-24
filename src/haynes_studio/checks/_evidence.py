"""Shared result and pixel primitives for the technical checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

Box = tuple[int, int, int, int]
RGB = tuple[int, int, int]
Verdict = Literal["pass", "fail", "uncertain"]
OPAQUE_ALPHA = 224


@dataclass(frozen=True)
class ColorRange:
    """Inclusive RGB bounds for a declared material in the supplied image."""

    low: RGB
    high: RGB

    def __post_init__(self) -> None:
        if len(self.low) != 3 or len(self.high) != 3 or any(
            type(lo) is not int or type(hi) is not int or not 0 <= lo <= hi <= 255
            for lo, hi in zip(self.low, self.high)
        ):
            raise ValueError("color bounds must be ordered RGB triples in 0..255")

    def mask(self, rgba: np.ndarray) -> np.ndarray:
        rgb = rgba[..., :3]
        return ((rgb >= self.low) & (rgb <= self.high)).all(axis=-1)

    def overlaps(self, other: ColorRange) -> bool:
        return all(max(lo, other_lo) <= min(hi, other_hi)
                   for lo, hi, other_lo, other_hi in zip(self.low, self.high, other.low, other.high))


def crop(frame: np.ndarray, box: Box) -> np.ndarray:
    x0, y0, x1, y1 = box
    height, width = frame.shape[:2]
    if any(type(edge) is not int for edge in box) or not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise ValueError("a measurement box is outside its keyed frame")
    return frame[y0:y1, x0:x1]


def result_document(check: str, version: str, refs: dict[str, str], verdict: Verdict, *,
                    thresholds: dict[str, Any], measured: dict[str, Any],
                    issues: list[str], escalation: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "schema": "studio.check-result/v1",
        "check": check,
        "version": version,
        "artifact": next(iter(refs.values())),
        "artifact_refs": refs,
        "result": verdict,
        "passed": verdict == "pass",
        "confidence": "low" if verdict == "uncertain" else "high",
        "thresholds": thresholds,
        "measured": measured,
        "issues": issues,
        "escalation": escalation,
    }


def as_run_check(evidence: dict[str, Any]) -> dict[str, Any]:
    """Project into the current run schema, with uncertainty blocking the gate."""
    return {
        "check": evidence["check"],
        "version": evidence["version"],
        "artifact": evidence["artifact"],
        "result": "pass" if evidence["passed"] else "fail",
        "actual": evidence,
    }
