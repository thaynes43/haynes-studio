"""Model-independent selection and uncertainty rules."""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
from PIL import Image

from haynes_studio.schemas import validator_for
from haynes_studio.store import canonical_json

from .pixels import mask_iou
from .profile import (
    BOTTOM_COVERAGE, DETECTOR_FLOOR, FOREGROUND_QUERY, MASK_AGREEMENT, MASK_FLOOR, MASK_SCORE_GAP,
    MAX_PIXELS, MAX_SHORT_SIDE, MIN_MODEL_PIXELS, NMS_IOU, SCORE_LEAD, Profile, SegmentationError, digest,
)

REQUEST_SCHEMA = "studio.segmentation-request.v1.schema.json"
RESULT_SCHEMA = "studio.segmentation-result.v1.schema.json"


def validate_request(request: object) -> None:
    if not validator_for(REQUEST_SCHEMA).is_valid(request):
        raise SegmentationError("invalid_input")
    source, target, hint = request["input"], request["target"], request["hint"]
    width, height = source["width"], source["height"]
    if (type(width) is not int or type(height) is not int or min(width, height) > MAX_SHORT_SIDE
            or width * height > MAX_PIXELS or not re.fullmatch(r"[a-f0-9]{64}", source["sha256"])
            or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", target["key"])
            or (target["kind"] == "prop" and target["label"] is None)):
        raise SegmentationError("invalid_input")
    texts = [target["label"]]
    if hint and hint["kind"] == "text":
        texts.append(hint["text"])
    for value in texts:
        if value is not None and (value != value.strip() or not unicodedata.is_normalized("NFC", value)
                                  or any(unicodedata.category(c).startswith("C") for c in value)):
            raise SegmentationError("invalid_input")
    if hint and hint["kind"] != "text":
        coordinates = hint.get("xy", hint.get("xyxy"))
        if any(type(value) is not int for value in coordinates):
            raise SegmentationError("invalid_input")
        if hint["kind"] == "point":
            x, y = coordinates
            valid = 0 <= x < width and 0 <= y < height
        else:
            x, y, right, bottom = coordinates
            valid = 0 <= x < right <= width and 0 <= y < bottom <= height
        if not valid:
            raise SegmentationError("invalid_input")


Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class Candidate:
    box: Box
    score: float
    phrase: str


@dataclass(frozen=True)
class Grounding:
    candidates: list[Candidate]
    # Predictions are normalized by the unpadded image size by DINO. The
    # adapter converts them to these content pixels before passing them here.
    resized: tuple[int, int]
    canvas: tuple[int, int]


class Detector(Protocol):
    def __call__(self, image: Image.Image, prompt: str) -> Grounding: ...


class Segmenter(Protocol):
    def __call__(self, image: Image.Image, hint: dict) -> tuple[np.ndarray, list[float]]: ...


class Phases(Protocol):
    def __call__(self, name: str): ...


def box_iou(first, second) -> float:
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    intersection = (max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
                    * max(0.0, min(first[3], second[3]) - max(first[1], second[1])))
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


def select_boxes(grounding: Grounding) -> list[Candidate]:
    width, height = grounding.resized
    canvas_width, canvas_height = grounding.canvas
    if not (0 < width <= canvas_width and 0 < height <= canvas_height):
        raise SegmentationError("invalid_output")
    candidates = []
    for candidate in grounding.candidates:
        x0, y0, x1, y1 = candidate.box
        if (not all(map(math.isfinite, (*candidate.box, candidate.score))) or not x0 < x1 or not y0 < y1):
            raise SegmentationError("invalid_output")
        clipped = (max(0.0, x0), max(0.0, y0), min(width, x1), min(height, y1))
        if (clipped[0] < clipped[2] and clipped[1] < clipped[3] and candidate.score >= DETECTOR_FLOOR
                and any(character.isalnum() for character in candidate.phrase)):
            candidates.append(Candidate(clipped, candidate.score, candidate.phrase))
    kept = []
    for candidate in sorted(candidates, key=lambda item: (-item.score, item.box, item.phrase)):
        if all(box_iou(candidate.box, picked.box) <= NMS_IOU for picked in kept):
            kept.append(candidate)
    return kept


def _source_box(box: Box, resized: tuple[int, int], size: tuple[int, int]) -> list[int]:
    scale_x, scale_y = size[0] / resized[0], size[1] / resized[1]
    return [
        max(0, math.floor(box[0] * scale_x)), max(0, math.floor(box[1] * scale_y)),
        min(size[0], math.ceil(box[2] * scale_x)), min(size[1], math.ceil(box[3] * scale_y)),
    ]


def _prompt(request: dict) -> str:
    hint, target = request["hint"], request["target"]
    if hint and hint["kind"] == "text":
        label = hint["text"]
    elif target["label"]:
        label = target["label"]
    else:
        return "doll face." if target["kind"] == "face" else FOREGROUND_QUERY
    return label.lower().rstrip(".") + "."


@dataclass
class Observation:
    detector_box: list[int] | None = None
    detector_score: float | None = None
    mask_score: float | None = None
    executed: list[str] = field(default_factory=list)
    applied: dict = field(default_factory=dict)

    def receipt(self, request: dict, profile: Profile, status: str, reason: str | None = None, *,
                mask: dict | None = None, box: list[int] | None = None) -> dict:
        document = {
            "schema": "studio.segmentation-result/v1", "request_sha256": digest(canonical_json(request)),
            "input": request["input"], "target": request["target"], "status": status, "reason": reason,
            "box_xyxy": box, "detector_box_xyxy": self.detector_box,
            "scores": {"detector": self.detector_score, "mask_iou": self.mask_score}, "mask": mask,
            "provenance": profile.provenance(self.executed, self.applied),
        }
        if not validator_for(RESULT_SCHEMA).is_valid(document):
            raise SegmentationError("invalid_output")
        return document


def observe(image: Image.Image, alpha: np.ndarray | None, request: dict,
            detector: Detector, segmenter: Segmenter, observation: Observation,
            phase: Phases) -> tuple[str | None, np.ndarray | None]:
    hint = request["hint"]
    grounded = hint is None or hint["kind"] == "text"
    if grounded:
        prompt = _prompt(request)
        observation.applied["prompt"] = prompt
        with phase("grounding"):
            observation.executed.append("dino")
            grounding = detector(image, prompt)
            candidates = select_boxes(grounding)
        observation.applied["detector_resize_wh"] = list(grounding.resized)
        observation.applied["detector_canvas_wh"] = list(grounding.canvas)
        if not candidates:
            return "no_match", None
        top = candidates[0]
        observation.detector_score = top.score
        observation.detector_box = _source_box(top.box, grounding.resized, image.size)
        if len(candidates) > 1 and top.score < candidates[1].score + SCORE_LEAD:
            return "ambiguous_match", None
        left, top_y, right, bottom = top.box
        if min(right - left, bottom - top_y) < MIN_MODEL_PIXELS:
            return "too_small", None
        hint = {"kind": "box", "xyxy": observation.detector_box}

    observation.applied["sam_hint"] = hint
    with phase("sam"):
        observation.executed.append("sam")
        logits, scores = segmenter(image, hint)
        if (logits.ndim != 3 or logits.shape[1:] != (image.height, image.width)
                or len(logits) != len(scores) or not len(scores) or not np.isfinite(logits).all()):
            raise SegmentationError("invalid_output")
        ranked = sorted((index for index, score in enumerate(scores) if math.isfinite(score)),
                        key=lambda index: (-scores[index], index))
        if not ranked:
            return "mask_uncertain", None
        best = ranked[0]
        observation.mask_score = score = float(scores[best])
        if score < MASK_FLOOR:
            return "mask_uncertain", None
        raw_mask = logits[best] > 0
        if not raw_mask.any() or raw_mask.all():
            return "mask_uncertain", None
        mask = raw_mask if alpha is None else raw_mask & alpha
        if not mask.any():
            return "mask_uncertain", None
        for index in ranked[1:]:
            if score > scores[index] + MASK_SCORE_GAP:
                break
            other = logits[index] > 0
            if alpha is not None:
                other &= alpha
            if mask_iou(mask, other) < MASK_AGREEMENT:
                return "mask_uncertain", None
        if hint["kind"] == "point":
            x, y = hint["xy"]
            if not mask[y, x]:
                return "mask_uncertain", None
        if grounded and request["target"]["kind"] == "foreground" and mask[-1].mean() < BOTTOM_COVERAGE:
            return "foreground_depth_ambiguous", None
    return None, mask
