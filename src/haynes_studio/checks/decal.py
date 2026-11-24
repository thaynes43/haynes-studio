"""Read story 426's track and measure lettering in jacket-local coordinates."""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from haynes_studio.layered import keying
from haynes_studio.layered.errors import LayeredError
from haynes_studio.layered.keyed import decode_png, frame_pngs, read_record
from haynes_studio.layered.renderer import decal_check
from haynes_studio.store import is_sha256

from ._evidence import OPAQUE_ALPHA, Box, ColorRange, Verdict, crop, result_document

CHECK = "decal.drift"
VERSION = "1"
MAX_OFFSET = 0.035  # distance in units of jacket width and height
MAX_INK_RATIO = 1.35  # new ink relative to reference ink, normalized by jacket area
MIN_INK_RATIO = 0.65
MIN_PIXELS = 24
MAX_CLOTH_ASPECT_CHANGE = 1.20
MAX_REROLLS = 2  # CR-02


@dataclass(frozen=True)
class DecalRegions:
    """Boxes in keyed-frame coordinates, large enough for all measured motion."""

    jacket: Box
    lettering: Box
    cloth: ColorRange
    ink: ColorRange

    def __post_init__(self) -> None:
        if self.cloth.overlaps(self.ink):
            raise ValueError("decal ink and jacket cloth color ranges overlap")


@dataclass(frozen=True)
class DecalPixels:
    """Ink centroid and area in units of the visible cloth's bounding box."""

    x: float
    y: float
    area: float
    aspect: float


def measure_decal_frame(frame: np.ndarray, regions: DecalRegions) -> DecalPixels | None:
    """Measure two visible color regions without estimating or applying a warp."""
    jacket = crop(frame, regions.jacket)
    lettering = crop(frame, regions.lettering)
    cloth = regions.cloth.mask(jacket) & (jacket[..., 3] >= OPAQUE_ALPHA)
    ink = regions.ink.mask(lettering) & (lettering[..., 3] >= OPAQUE_ALPHA)
    cy, cx = np.nonzero(cloth)
    iy, ix = np.nonzero(ink)
    if len(cx) < MIN_PIXELS or len(ix) < MIN_PIXELS:
        return None
    # A search edge may have cut off part of the reference/ink, biasing the measurement.
    if any(mask[0].any() or mask[-1].any() or mask[:, 0].any() or mask[:, -1].any()
           for mask in (cloth, ink)):
        return None
    width = int(cx.max() - cx.min() + 1)
    height = int(cy.max() - cy.min() + 1)
    if width < 2 or height < 2:
        return None
    x = (float(ix.mean()) + regions.lettering[0] - int(cx.min()) - regions.jacket[0]) / width
    y = (float(iy.mean()) + regions.lettering[1] - int(cy.min()) - regions.jacket[1]) / height
    if not (0 <= x <= 1 and 0 <= y <= 1):
        return None
    return DecalPixels(x, y, len(ix) / (width * height), width / height)


def compare_decal(reference: DecalPixels, current: DecalPixels) -> tuple[float, float, float]:
    """Return jacket-relative displacement, ink-area ratio and cloth aspect change."""
    offset = math.hypot(current.x - reference.x, current.y - reference.y)
    aspect_change = max(current.aspect / reference.aspect, reference.aspect / current.aspect)
    return offset, current.area / reference.area, aspect_change


def _valid_score(score: Any) -> bool:
    # OpenCV's rounding can put a coefficient just outside [-1, 1].
    return score is None or (type(score) in (int, float) and -1.0001 <= score <= 1.0001)


def check_decal(keyed: bytes, *, clip_id: str, clip_sha256: str, attempt: int,
                regions: DecalRegions | None = None,
                shown: set[int] | None = None) -> dict[str, Any]:
    """Check a story 426 keyed APNG. Attempt 1 is the original clip.

    `shown` contains zero-based source frame numbers. Frame 0 is the template
    even when trimmed from the board. Clip identity and attempt are caller facts.
    """
    if not isinstance(clip_id, str) or not clip_id.strip() or not is_sha256(clip_sha256):
        raise ValueError("decal check requires a clip ID and source SHA256")
    if type(attempt) is not int or attempt < 1:
        raise ValueError("decal attempt must be a positive integer")

    artifact = hashlib.sha256(keyed).hexdigest()
    issues: list[str] = []
    visual: dict[str, Any] = {"frames_measured": 0, "unmeasured_frames": [],
                              "offset_peak": None, "ink_ratio_peak": None, "ink_ratio_min": None}
    measured: dict[str, Any] = {"clip_id": clip_id, "attempt": attempt, "ecc_gate": None,
                                 "shown_frames": None, "template_frame": 0,
                                 "lost_frames": [], "visual": visual,
                                 "regions": asdict(regions) if regions is not None else None}
    weak = lost = False
    try:
        record = read_record(keyed)
        count = record["frames"]
        if type(count) is not int or count < 1:
            raise ValueError("invalid frame count")
        indices = set(range(count)) if shown is None else shown
        if any(type(i) is not int or i < 0 or i >= count for i in indices):
            raise ValueError("shown frames are outside the keyed clip")
        measured["shown_frames"] = sorted(indices)
        frames = sorted(indices - {0})
        decal = record.get("decal")
        scores = decal["scores"] if decal is not None else []
        if decal is not None and (not isinstance(scores, list) or len(scores) != count - 1
                                  or not all(_valid_score(score) for score in scores)):
            raise ValueError("invalid track evidence")
        gate = decal_check(artifact, record, keying.MIN_ECC, indices)
        measured["ecc_gate"] = gate
        if gate is None or not gate["result"]["frames_gated"]:
            issues.append("decal.track_unmeasured")
        else:
            measured["lost_frames"] = [i for i in frames if scores[i - 1] is None]
            lost = bool(measured["lost_frames"])
            weak = not gate["passed"]
            if lost:
                issues.append("decal.track_lost")
            if gate["result"]["min_ecc"] is not None and gate["result"]["min_ecc"] < keying.MIN_ECC:
                issues.append("decal.track_weak")

    except (LayeredError, KeyError, ValueError, TypeError):
        issues.append("decal.evidence_invalid")
    else:
        if regions is not None and frames:
            try:
                _measure_visual(keyed, record, regions, frames, visual)
            except (LayeredError, KeyError, ValueError, TypeError, IndexError, struct.error):
                issues.append("decal.visual_invalid")

    offset = visual["offset_peak"]
    ratio = visual["ink_ratio_peak"]
    slides = offset is not None and offset["value"] > MAX_OFFSET
    extra_ink = ratio is not None and ratio["value"] > MAX_INK_RATIO
    if slides:
        issues.append("decal.offset_high")
    if extra_ink:
        issues.append("decal.ink_excess")
    if not visual["frames_measured"] or visual["unmeasured_frames"]:
        issues.append("decal.visual_unmeasured")
    verdict: Verdict = "pass"
    if slides or extra_ink or lost:
        verdict = "fail"
    elif issues:
        verdict = "uncertain"
    escalation = None
    if verdict != "pass":
        action = "review"
        if weak:
            action = "reroll" if attempt <= MAX_REROLLS else "stop_with_evidence"
        escalation = {"action": action, "clip_id": clip_id, "check": CHECK,
                      "attempt": attempt, "max_rerolls": MAX_REROLLS}
    return result_document(
        CHECK, VERSION, {"keyed_layer": artifact, "source_clip": clip_sha256}, verdict,
        thresholds={"min_ecc": keying.MIN_ECC, "max_offset": MAX_OFFSET,
                    "max_ink_ratio": MAX_INK_RATIO, "min_ink_ratio": MIN_INK_RATIO,
                    "opaque_alpha": OPAQUE_ALPHA, "min_pixels": MIN_PIXELS,
                    "max_cloth_aspect_change": MAX_CLOTH_ASPECT_CHANGE},
        measured=measured, issues=issues, escalation=escalation,
    )


def _measure_visual(keyed: bytes, record: dict[str, Any], regions: DecalRegions,
                    frames: list[int], visual: dict[str, Any]) -> None:
    pngs = frame_pngs(keyed, record)
    reference = measure_decal_frame(decode_png(pngs[0]), regions)
    if reference is None:
        visual["unmeasured_frames"].extend(frames)
        return
    for index in frames:
        current = measure_decal_frame(decode_png(pngs[index]), regions)
        if current is None:
            visual["unmeasured_frames"].append(index)
            continue
        offset, ratio, aspect_change = compare_decal(reference, current)
        if aspect_change > MAX_CLOTH_ASPECT_CHANGE or ratio < MIN_INK_RATIO:
            visual["unmeasured_frames"].append(index)
            continue
        visual["frames_measured"] += 1
        for name, value, extreme in (("offset_peak", offset, max), ("ink_ratio_peak", ratio, max),
                                     ("ink_ratio_min", ratio, min)):
            previous = visual[name]
            if previous is None or extreme(value, previous["value"]) != previous["value"]:
                visual[name] = {"frame": index, "value": value}
