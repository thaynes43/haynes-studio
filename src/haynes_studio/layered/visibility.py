"""Measure an opted-in reference photo using its production compositor."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

import numpy as np
from PIL import Image

from haynes_studio.jsonio import thaw
from haynes_studio.layered.errors import LayeredError
from haynes_studio.store import canonical_json

CHECK = "layered.visibility"
VERSION = "1"
HIDDEN = "occlusion.hidden"
REVIEW = "occlusion.review_required"
UNSUPPORTED = "occlusion.unsupported"
BOUNDS = "occlusion.target_bounds"

# A source contribution must reach half intensity to count as a visible pixel.
PIXEL_FLOOR = 128
# At least 85% gives clear visibility. Losing half or more is a hard failure.
# The gap is reserved for a person's judgement.
VISIBLE_PERCENT = 85
HIDDEN_PERCENT = 50
THRESHOLDS = {"pixel_floor": PIXEL_FLOOR, "visible_percent": VISIBLE_PERCENT,
              "hidden_percent": HIDDEN_PERCENT}


def verdict(low: int, high: int, total: int) -> str:
    if not total or 100 * high <= HIDDEN_PERCENT * total:
        return "hidden"
    if 100 * low >= VISIBLE_PERCENT * total:
        return "visible"
    return "uncertain"


def evidence_digest(evidence: Mapping) -> str:
    return hashlib.sha256(canonical_json({key: value for key, value in evidence.items()
                                         if key != "artifact"})).hexdigest()


def reviewable(evidence, artifact: str) -> bool:
    if not isinstance(evidence, Mapping) or evidence.get("status") != "uncertain":
        return False
    low, high, total = (evidence.get(key) for key in ("lower_visible_px", "upper_visible_px", "target_px"))
    return (all(type(value) is int for value in (low, high, total))
            and 0 <= low <= high <= total
            and verdict(low, high, total) == "uncertain"
            and evidence.get("thresholds") == THRESHOLDS
            and evidence.get("version") == VERSION
            and evidence.get("artifact") == artifact == evidence_digest(evidence))


def _tag(cutout, box, *, support):
    """Colour only the target's pixels. The composite keeps the entire source alpha."""
    width, height = cutout.size
    x0, y0, x1, y1 = box or (0, 0, width, height)
    if x1 > width or y1 > height:
        raise LayeredError(BOUNDS, "the target box must fit the cast still",
                           where="/layout/check_poses")
    alpha = cutout.getchannel("A")
    tagged = Image.new("RGBA", cutout.size)
    tagged.paste((255, 0, 0, 0), (x0, y0, x1, y1))
    if support:
        coverage = Image.new("L", cutout.size)
        coverage.paste(alpha.crop((x0, y0, x1, y1)).point(lambda value: 255 if value else 0), (x0, y0))
        alpha = coverage
    tagged.putalpha(alpha)
    return tagged


def measure(scene, board) -> tuple[dict, ...]:
    """Render each target through the same production operations, including shadows.

    The red channel follows the target's contribution through the ordinary RGBA draw.
    Other sources are black. An isolated support render defines eligible output pixels
    in the same layout and camera. Every layer of this scene is known, so its two
    bounds coincide. An unreadable layer makes the scene unsupported before measurement.
    """
    poses = board.layout.check_poses or ({"key": "reference", "frame": 0},)
    black = Image.new("RGB", scene.size)
    neutral = {slot: Image.new("RGBA", still.size) for slot, still in scene.cast.items()}
    for slot, still in scene.cast.items():
        neutral[slot].putalpha(still.getchannel("A"))
    reference = scene.render(scene.background, scene.cast)
    reference_sha256 = hashlib.sha256(reference.tobytes()).hexdigest()
    measured = []
    for pose in poses:
        targets = pose.get("targets") or [{"slot": slot} for slot in scene.cast]
        for target in targets:
            slot, box = target["slot"], target.get("box_xyxy")
            still = scene.cast[slot]
            cast = {**neutral, slot: _tag(still, box, support=False)}
            painted = scene.render(black, cast)
            support = scene.render(black, {slot: _tag(still, box, support=True)}, isolated=True)
            eligible = np.asarray(support.getchannel("R")) >= PIXEL_FLOOR
            total = int(np.count_nonzero(eligible))
            visible = int(np.count_nonzero(eligible & (np.asarray(painted.getchannel("R")) >= PIXEL_FLOOR)))
            status = verdict(visible, visible, total)
            evidence = {
                "board_id": board.id, "board_revision": board.revision,
                "pose": thaw(pose), "target": thaw(target), "status": status,
                "lower_visible_px": visible, "upper_visible_px": visible, "target_px": total,
                "reference_rgb_sha256": reference_sha256, "photo_inputs": scene.inputs.signature,
                "version": VERSION, "thresholds": THRESHOLDS,
            }
            measured.append({**evidence, "artifact": evidence_digest(evidence)})
    return tuple(measured)


def run_checks(evidence, approved=()) -> list[dict]:
    return [{"check": CHECK, "version": VERSION, "slot": item["target"]["slot"],
             "artifact": item["artifact"], "thresholds": THRESHOLDS, "measured": item,
             "result": ("pass" if item["status"] == "visible" else
                        "overridden" if item["status"] == "uncertain" and item["artifact"] in approved else "fail")}
            for item in evidence]
