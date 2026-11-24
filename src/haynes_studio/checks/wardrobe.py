"""Compare declared costume attributes with evidence from a keyed still."""

from __future__ import annotations

import hashlib
import io
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol

import numpy as np
from PIL import Image

from haynes_studio.store import canonical_json

from ._evidence import OPAQUE_ALPHA, Box, ColorRange, Verdict, crop, result_document

CHECK = "wardrobe.attributes"
VERSION = "1"
MIN_OPAQUE_FRACTION = 0.50
MIN_COLOR_FRACTION = 0.80
MIN_OPAQUE_PIXELS = 16
SLEEVE_WINDOWS = ("left_upper", "left_forearm", "right_upper", "right_forearm")


@dataclass(frozen=True)
class SleeveRegions:
    """Four arm-interior windows on a keyed still, as seen by the camera."""

    left_upper: Box
    left_forearm: Box
    right_upper: Box
    right_forearm: Box
    fabric: ColorRange
    bare_arm: ColorRange

    def __post_init__(self) -> None:
        if self.fabric.overlaps(self.bare_arm):
            raise ValueError("sleeve fabric and bare arm color ranges overlap")
        if len({getattr(self, name) for name in SLEEVE_WINDOWS}) != len(SLEEVE_WINDOWS):
            raise ValueError("each sleeve window must identify a different arm region")


@dataclass(frozen=True)
class Observation:
    value: str | None
    confidence: Literal["high", "low"]


class AttributeObserver(Protocol):
    """Observe a declared attribute when the pixel method cannot resolve it."""

    def observe(self, still: np.ndarray, attribute: str) -> Observation: ...


def measure_sleeves(still: np.ndarray, regions: SleeveRegions) -> tuple[str | None, dict[str, Any]]:
    """Measure opaque support and material coverage in the four arm windows."""
    windows = {}
    for name in SLEEVE_WINDOWS:
        pixels = crop(still, getattr(regions, name))
        opaque = pixels[..., 3] >= OPAQUE_ALPHA
        support = int(np.count_nonzero(opaque))
        visible = support / opaque.size
        covered = exposed = None
        observed = None
        if support >= MIN_OPAQUE_PIXELS and visible >= MIN_OPAQUE_FRACTION:
            covered = int(np.count_nonzero(opaque & regions.fabric.mask(pixels))) / support
            exposed = int(np.count_nonzero(opaque & regions.bare_arm.mask(pixels))) / support
            if covered >= MIN_COLOR_FRACTION:
                observed = "fabric"
            elif exposed >= MIN_COLOR_FRACTION:
                observed = "bare_arm"
        windows[name] = {"opaque_pixels": support, "opaque_fraction": visible, "fabric_fraction": covered,
                         "bare_arm_fraction": exposed, "observed": observed}

    materials = {window["observed"] for window in windows.values()}
    if materials == {"fabric"}:
        return "full_length", windows
    if materials == {"bare_arm"}:
        return "sleeveless", windows
    if {"fabric", "bare_arm"} <= materials:
        return "mixed", windows
    return None, windows


def check_wardrobe(keyed_still: bytes, costume: Mapping[str, str], *,
                   sleeves: SleeveRegions | None = None,
                   observer: AttributeObserver | None = None) -> dict[str, Any]:
    """Check each declared attribute of a costume against a single keyed RGBA still."""
    declared = dict(costume)
    if any(not isinstance(name, str) or not name.strip() or not isinstance(value, str)
           or not value.strip() for name, value in declared.items()):
        raise ValueError("costume attributes and their declared values must be nonempty strings")

    issues: list[str] = []
    attributes = {}
    still = None
    try:
        with Image.open(io.BytesIO(keyed_still)) as image:
            if image.mode != "RGBA" or getattr(image, "n_frames", 1) != 1:
                raise ValueError("wardrobe check needs one keyed RGBA frame")
            still = np.asarray(image)
    except (OSError, ValueError, Image.DecompressionBombError):
        issues.append("wardrobe.evidence_invalid")
    if not declared:
        issues.append("wardrobe.costume_unmeasured")

    for name, expected in declared.items():
        windows = None
        observed = Observation(None, "low")
        method = None
        supported = name == "sleeves" and expected in {"full_length", "sleeveless"}
        if still is not None and sleeves is not None and supported:
            method = "arm_color"
            try:
                value, windows = measure_sleeves(still, sleeves)
                if value is None and any(window["observed"] == (
                    "bare_arm" if expected == "full_length" else "fabric"
                ) for window in windows.values()):
                    value = "contradicted"
                observed = Observation(value, "high" if value is not None else "low")
            except ValueError:
                issues.append("wardrobe.evidence_invalid")
        if still is not None and observed.value is None and observer is not None:
            method = "attribute_observer"
            observed = observer.observe(still, name)
        verdict: Verdict = "uncertain"
        if observed.confidence == "high" and observed.value:
            verdict = "pass" if observed.value == expected else "fail"
        attributes[name] = {"expected": expected, "observed": observed.value,
                            "confidence": observed.confidence, "method": method,
                            "windows": windows, "result": verdict}

    outcomes = {evidence["result"] for evidence in attributes.values()}
    if "fail" in outcomes:
        issues.append("wardrobe.attribute_mismatch")
    if "uncertain" in outcomes:
        issues.append("wardrobe.attribute_unmeasured")
    verdict = "fail" if "fail" in outcomes else "uncertain" if issues else "pass"
    return result_document(
        CHECK, VERSION, {"keyed_still": hashlib.sha256(keyed_still).hexdigest(),
                         "costume_record": hashlib.sha256(canonical_json(declared)).hexdigest()},
        verdict,
        thresholds={"opaque_alpha": OPAQUE_ALPHA, "min_opaque_fraction": MIN_OPAQUE_FRACTION,
                    "min_color_fraction": MIN_COLOR_FRACTION, "min_opaque_pixels": MIN_OPAQUE_PIXELS},
        measured={"attributes": attributes, "sleeve_regions": asdict(sleeves) if sleeves else None},
        issues=issues, escalation={"action": "review", "check": CHECK} if issues else None,
    )
