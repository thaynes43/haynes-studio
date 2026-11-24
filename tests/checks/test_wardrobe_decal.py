from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from haynes_studio.build.validate import validate_run
from haynes_studio.checks import (
    ColorRange,
    DecalRegions,
    Observation,
    SleeveRegions,
    as_run_check,
    check_decal,
    check_wardrobe,
)
from haynes_studio.layered import keyed, keying
from haynes_studio.store import canonical_json
from tests.layered import media
from tests.layered.test_keying import make

BLUE = (25, 65, 195, 255)
YELLOW = (225, 200, 20, 255)
SKIN = (170, 115, 90, 255)
CLOTH = ColorRange((20, 55, 175), (40, 80, 215))
INK = ColorRange((210, 180, 5), (245, 220, 32))
BARE_ARM = ColorRange((160, 100, 75), (180, 130, 105))
DECAL_REGIONS = DecalRegions((3, 3, 116, 76), (20, 17, 95, 61), CLOTH, INK)
SLEEVE_REGIONS = SleeveRegions((10, 12, 18, 22), (10, 32, 18, 42),
                               (72, 12, 80, 22), (72, 32, 80, 42), CLOTH, BARE_ARM)
CLIP_SHA = hashlib.sha256(b"synthetic clip source").hexdigest()


def decal_frame(*, body_x=0, slide=0, double=False, visible=True, shirt_height=45):
    rgba = np.zeros((80, 120, 4), dtype=np.uint8)
    rgba[16:16 + shirt_height, 18 + body_x:98 + body_x] = BLUE
    if visible:
        positions = (34, 41, 48, 55, 62, 69)
        for x in positions:
            left = x + body_x + slide
            rgba[32:41, left:left + 3] = YELLOW
        if double:
            for x in positions:
                rgba[44:53, x + body_x:x + body_x + 3] = YELLOW
    return rgba


def write_keyed(tmp_path, frames, scores):
    header, first = keyed._frame_png(frames[0])
    payloads = [first, *(keyed._frame_png(frame)[1] for frame in frames[1:])]
    height, width = frames[0].shape[:2]
    decal = {"scores": scores} if scores is not None else None
    record = {"schema": keyed.SCHEMA, "frames": len(frames),
              "box": [0, 0, width, height], "decal": decal}
    path = tmp_path / "synthetic-keyed.png"
    path.write_bytes(keyed.write_apng(payloads, header, record, 24))
    return path.read_bytes()


def check(data, *, attempt=1, shown=None, regions=DECAL_REGIONS):
    return check_decal(data, clip_id="clip-a", clip_sha256=CLIP_SHA, attempt=attempt,
                       shown=shown, regions=regions)


def test_rigid_decal_passes_even_as_the_jacket_moves(tmp_path):
    data = write_keyed(tmp_path, [decal_frame(), decal_frame(body_x=10)], [0.9])
    result = check(data)
    assert result["result"] == "pass"
    assert result["confidence"] == "high"
    assert result["measured"]["visual"]["offset_peak"] == {"frame": 1, "value": 0.0}
    assert result["artifact_refs"] == {"source_clip": CLIP_SHA, "keyed_layer": hashlib.sha256(data).hexdigest()}
    assert result["escalation"] is None


@pytest.mark.parametrize("motion, issue, metric", [
    ({"slide": 6}, "decal.offset_high", "offset_peak"),
    ({"double": True}, "decal.ink_excess", "ink_ratio_peak"),
])
def test_visual_defect_fails_with_good_ecc(tmp_path, motion, issue, metric):
    result = check(write_keyed(tmp_path, [decal_frame(), decal_frame(body_x=5, **motion)], [0.95]))
    assert result["result"] == "fail"
    assert result["measured"]["ecc_gate"]["passed"]
    assert result["measured"]["visual"][metric]["frame"] == 1
    if metric == "ink_ratio_peak":
        assert result["measured"]["visual"][metric]["value"] == 2
    assert issue in result["issues"]
    assert result["escalation"]["action"] == "review"


@pytest.mark.parametrize("attempt, action", [(1, "reroll"), (2, "reroll"), (3, "stop_with_evidence"),
                                             (4, "stop_with_evidence")])
def test_lost_track_is_evidence_and_reroll_is_bounded(tmp_path, attempt, action):
    result = check(write_keyed(tmp_path, [decal_frame(), decal_frame()], [None]), attempt=attempt)
    assert result["result"] == "fail"
    assert result["measured"]["lost_frames"] == [1]
    assert result["measured"]["ecc_gate"]["result"]["failed_frames"] == 1
    assert result["escalation"] == {"action": action, "clip_id": "clip-a", "check": "decal.drift",
                                   "attempt": attempt, "max_rerolls": 2}


def test_stable_pixels_with_weak_ecc_escalate_without_lowering_floor(tmp_path):
    result = check(write_keyed(tmp_path, [decal_frame(), decal_frame(body_x=4)], [0.71]))
    assert result["result"] == "uncertain"
    assert result["confidence"] == "low"
    assert result["issues"] == ["decal.track_weak"]
    assert result["measured"]["visual"]["offset_peak"]["value"] == 0.0
    assert result["thresholds"]["min_ecc"] == keying.MIN_ECC
    mapped = as_run_check(result)
    assert mapped["result"] == "fail"
    assert mapped["actual"]["escalation"]["action"] == "reroll"
    canonical_json(mapped)
    run_example = Path(__file__).resolve().parents[2] / "docs/contracts/examples/valid/run-queued.json"
    run = json.loads(run_example.read_text())
    run["checks"] = [mapped]
    assert validate_run(run) == []


@pytest.mark.parametrize("score, verdict", [(None, "fail"), (0.71, "uncertain")])
def test_bad_visual_regions_preserve_the_ecc_finding(tmp_path, score, verdict):
    data = write_keyed(tmp_path, [decal_frame(), decal_frame()], [score])
    bad_regions = replace(DECAL_REGIONS, jacket=(0, 0, 999, 999))
    result = check(data, regions=bad_regions)
    assert result["result"] == verdict
    assert "decal.visual_invalid" in result["issues"]
    assert result["measured"]["lost_frames"] == ([1] if score is None else [])
    assert result["escalation"]["action"] == "reroll"
    assert check(data, regions=bad_regions, attempt=3)["escalation"]["action"] == "stop_with_evidence"


def test_gate_and_pixels_use_the_same_shown_frames(tmp_path):
    data = write_keyed(tmp_path, [decal_frame(), decal_frame(slide=9), decal_frame(body_x=6)], [None, 0.8])
    passing = check(data, shown={2})
    assert passing["result"] == "pass"
    assert passing["measured"]["shown_frames"] == [2]
    assert passing["measured"]["template_frame"] == 0
    assert passing["measured"]["visual"]["offset_peak"]["frame"] == 2
    assert passing["measured"]["ecc_gate"]["result"]["frames_gated"] == 1
    assert check(data, shown={0})["result"] == "uncertain"
    assert "decal.evidence_invalid" in check(data, shown={3})["issues"]


@pytest.mark.parametrize("motion", [{"visible": False}, {"shirt_height": 29}])
def test_missing_ink_or_changing_cloth_geometry_needs_review(tmp_path, motion):
    data = write_keyed(tmp_path, [decal_frame(), decal_frame(**motion)], [0.99])
    result = check(data)
    assert result["result"] == "uncertain"
    assert result["measured"]["visual"]["unmeasured_frames"] == [1]
    assert result["escalation"]["action"] == "review"


def test_no_track_or_regions_are_explicitly_unmeasured(tmp_path):
    data = write_keyed(tmp_path, [decal_frame(), decal_frame()], None)
    assert check(data)["issues"] == ["decal.track_unmeasured"]
    assert check(data, regions=None)["issues"] == ["decal.track_unmeasured", "decal.visual_unmeasured"]
    assert check(b"invalid media")["result"] == "uncertain"


def test_native_layered_artifact_uses_the_adapter_gate(tmp_path):
    clip = media.doll_clip(4)
    artifact, record, _ = make(clip)
    path = tmp_path / "native-keyed.png"
    path.write_bytes(artifact)
    result = check_decal(path.read_bytes(), clip_id="native", clip_sha256=hashlib.sha256(clip).hexdigest(),
                         attempt=1, shown={2, 3})
    assert result["result"] == "uncertain"  # no region observations
    gate = result["measured"]["ecc_gate"]
    assert gate["check"] == "layered.decal_gate"
    assert gate["passed"]
    assert gate["result"]["min_ecc"] == min(record["decal"]["scores"][1:])


def wardrobe_still(tmp_path, materials=(BLUE, BLUE, BLUE, BLUE)):
    frame = np.zeros((60, 90, 4), dtype=np.uint8)
    windows = (SLEEVE_REGIONS.left_upper, SLEEVE_REGIONS.left_forearm,
               SLEEVE_REGIONS.right_upper, SLEEVE_REGIONS.right_forearm)
    for material, (x0, y0, x1, y1) in zip(materials, windows):
        frame[y0:y1, x0:x1] = material
    path = tmp_path / "keyed-still.png"
    Image.fromarray(frame).save(path)
    return path.read_bytes()


@pytest.mark.parametrize("materials, expected, verdict, observed", [
    ((BLUE, BLUE, BLUE, BLUE), "full_length", "pass", "full_length"),
    ((SKIN, SKIN, SKIN, SKIN), "full_length", "fail", "sleeveless"),
    ((SKIN, BLUE, BLUE, BLUE), "full_length", "fail", "mixed"),
    ((SKIN, SKIN, SKIN, SKIN), "sleeveless", "pass", "sleeveless"),
    (((*BLUE[:3], 0), BLUE, BLUE, BLUE), "full_length", "uncertain", None),
])
def test_declared_sleeves_are_checked_against_both_arms(tmp_path, materials, expected, verdict, observed):
    still = wardrobe_still(tmp_path, materials)
    result = check_wardrobe(still, {"sleeves": expected}, sleeves=SLEEVE_REGIONS)
    assert result["result"] == verdict
    assert result["measured"]["attributes"]["sleeves"]["observed"] == observed
    assert result["passed"] == (verdict == "pass")
    if verdict != "pass":
        assert result["escalation"]["action"] == "review"
    assert result["artifact_refs"]["keyed_still"] == hashlib.sha256(still).hexdigest()


def test_invalid_sleeve_regions_and_empty_declaration_need_review(tmp_path):
    still = wardrobe_still(tmp_path)
    result = check_wardrobe(still, {"sleeves": "full_length"},
                            sleeves=replace(SLEEVE_REGIONS, left_upper=(0, 0, 999, 999)))
    assert result["result"] == "uncertain"
    assert "wardrobe.evidence_invalid" in result["issues"]
    assert check_wardrobe(still, {})["result"] == "uncertain"


@pytest.mark.parametrize("observed, confidence, expected_result", [
    ("jacket", "high", "pass"), ("vest", "high", "fail"), ("jacket", "low", "uncertain"),
    (None, "high", "uncertain"),
])
def test_vision_only_attributes_use_injected_observer(tmp_path, observed, confidence, expected_result):
    class FakeObserver:
        def observe(self, still, attribute):
            assert still.shape == (60, 90, 4)
            assert attribute == "garment"
            return Observation(observed, confidence)

    data = wardrobe_still(tmp_path)
    assert check_wardrobe(data, {"garment": "jacket"})["result"] == "uncertain"
    assert check_wardrobe(data, {"garment": "jacket"}, observer=FakeObserver())["result"] == expected_result
