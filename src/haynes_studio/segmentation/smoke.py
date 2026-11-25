"""Measured offline install smoke, including paired load strategies."""

from __future__ import annotations

import os
from pathlib import Path
from time import monotonic
from uuid import uuid4

from haynes_studio.store import canonical_json

from .backend import Engine
from .fixtures import fixtures, visible_fraction
from .inference import box_iou
from .memory import cgroup_bytes
from .pixels import describe_mask, mask_iou, tight_box
from .profile import PROFILE_ID, RESOURCES, Profile, SegmentationError, digest
from .service import listening, local_call


def stage(scratch: Path, data: bytes, request: dict) -> dict:
    attempt = uuid4().hex
    directory = scratch / attempt
    directory.mkdir(mode=0o700)
    with (directory / "input").open("xb") as output:
        output.write(data)
    return {"attempt_id": attempt, "request": request}


def _call(scratch, socket, name, fixture):
    data, request = fixture.request(name)
    payload = stage(scratch, data, request)
    start = monotonic()
    status, reply = local_call(socket, "POST", "/v1/segment", payload)
    elapsed_ms = round((monotonic() - start) * 1000)
    result = reply["result"]
    directory = scratch / payload["attempt_id"]
    result_bytes = (directory / "result.json").read_bytes()
    if (result_bytes != canonical_json(result) or digest(result_bytes) != reply["result_sha256"]
            or digest(data) != result["input"]["sha256"] or result["input"] != request["input"]
            or digest(canonical_json(request)) != result["request_sha256"]
            or result["target"] != request["target"]):
        raise SegmentationError("invalid_output")
    png, mask = None, None
    if result["status"] == "ready":
        png = (directory / "mask.png").read_bytes()
        descriptor, mask = describe_mask(png, fixture.image.size)
        if descriptor != result["mask"] or tight_box(mask) != result["box_xyxy"]:
            raise SegmentationError("invalid_output")
    elif (directory / "mask.png").exists():
        raise SegmentationError("invalid_output")
    return payload, status, result, png, mask, elapsed_ms


def _verdict(name, fixture, status, result, mask) -> tuple[bool, dict]:
    if name == "absent_gavel":
        return (status == 200 and result["status"] == "needs_hint" and mask is None), {}
    if status != 200 or result["status"] != "ready":
        return False, {}
    target = tight_box(fixture.truth)
    metrics = {"mask_iou": mask_iou(mask, fixture.truth), "box_iou": box_iou(result["box_xyxy"], target)}
    if name == "grounded_ball":
        detector = result["detector_box_xyxy"]
        metrics["detector_box_iou"] = box_iou(detector, target) if detector else 0
        return metrics["mask_iou"] >= 0.85 and metrics["detector_box_iou"] >= 0.70, metrics
    return metrics["mask_iou"] >= 0.90 and metrics["box_iou"] >= 0.85, metrics


def _smoke_run(scratch, weights, profile, strategy, inputs, report):
    results = {}
    masks = {}
    report.update({"weight_load": strategy, "memory": {}, "verdicts": {}, "cases": {}})
    checks = report["verdicts"]
    pin = digest(profile.manifest())
    socket = scratch / "segment.sock"
    cold_start = monotonic()
    with Engine(scratch, weights, profile, memory=report["memory"], load_strategy=strategy) as engine:
        report["cold_load_ms"] = round((monotonic() - cold_start) * 1000)
        with listening(socket, engine):
            expected = {"profile_id": PROFILE_ID, "profile_sha256": pin, "device": "cpu"}
            checks["ready_initial"] = local_call(socket, "GET", "/v1/ready") == (200, expected)
            if not checks["ready_initial"]:
                return results
            for name, fixture in inputs.items():
                payload, status, result, png, mask, elapsed = _call(scratch, socket, name, fixture)
                passes, metrics = _verdict(name, fixture, status, result, mask)
                checks[name] = passes
                required_models = (["dino"] if not fixture.hint else []) + (
                    ["sam"] if result["status"] == "ready" else []
                )
                parameters = result["provenance"]["parameters"]
                applied = {key: parameters[key] for key in (
                    "prompt", "detector_resize_wh", "detector_canvas_wh", "sam_hint", "weight_load",
                ) if key in parameters}
                checks[f"{name}_provenance"] = (
                    result["provenance"] == profile.provenance(required_models, applied)
                    and applied.get("weight_load") == strategy and result["provenance"]["profile"]["sha256"] == pin
                )
                report["cases"][name] = {
                    "status": result["status"], "reason": result["reason"], "elapsed_ms": elapsed, **metrics,
                    "result_sha256": digest(canonical_json(result)), "mask_sha256": digest(png) if png else None,
                }
                if "weight_load" in parameters:
                    # The two receipts differ in the recorded experimental load
                    # strategy. Compare every other byte along with the mask PNG.
                    del parameters["weight_load"]
                results[name] = canonical_json(result), png
                if mask is not None:
                    masks[name] = mask
                if result["status"] == "failed":
                    return results
                if name == "foreground" and strategy == "mmap" and passes:
                    old = scratch / payload["attempt_id"]
                    before = (old / "result.json").read_bytes(), (old / "mask.png").read_bytes()
                    replay_status, _ = local_call(socket, "POST", "/v1/segment", payload)
                    _, fresh_status, fresh_result, fresh_png, _, _ = _call(scratch, socket, name, fixture)
                    checks["create_only_replay"] = (
                        replay_status == 400 and fresh_status == 200
                        and before == ((old / "result.json").read_bytes(), (old / "mask.png").read_bytes())
                        and before == (canonical_json(fresh_result), fresh_png)
                    )
            if {"foreground", "visible_face", "hidden_prop"} <= masks.keys():
                visible = visible_fraction(masks["visible_face"], masks["foreground"])
                hidden = visible_fraction(masks["hidden_prop"], masks["foreground"])
                report["visible_fractions"] = {"face": visible, "prop": hidden}
                checks["visibility"] = visible >= 0.95 and hidden <= 0.05
                checks["hidden_prop_fails_fixture_gate"] = hidden <= 0.50
            else:
                checks["visibility"] = False
            checks["ready_after"] = local_call(socket, "GET", "/v1/ready") == (200, expected)
    startup = report["memory"]["startup"]
    requests = report["memory"].get("requests", [])
    expected_startup = {"verify_profile_and_files", "runtime_import", "load_dino", "load_sam"}
    required_facts = {"peak_rss_bytes", "resident_rss_bytes", "cgroup_resident_bytes"}
    checks["phase_memory"] = (
        expected_startup <= startup.keys() and len(requests) >= len(inputs)
        and all({"source_validation"} <= phase.keys() for phase in requests)
        and all(all(facts.get(key) is not None for key in required_facts)
                and facts["phase_rss_peak_reset"]
                for phases in [startup, *requests] for facts in phases.values())
    )
    return results


def smoke(scratch: Path, weights: Path, strategies: tuple[str, ...]) -> dict:
    report = {"schema": "studio.segmentation-smoke/v1", "runs": [], "verdicts": {}, "passed": False}
    checks = report["verdicts"]
    try:
        profile = Profile.installed()
        report.update({
            "profile_sha256": digest(profile.manifest()), "image_digest": profile.image_digest,
            "models": profile.model_files(), "runtime": profile.runtime(),
        })
        checks["workload"] = (os.geteuid() == os.getegid() == 10001
                              and bool(os.statvfs("/").f_flag & os.ST_RDONLY)
                              and bool(os.statvfs(weights).f_flag & os.ST_RDONLY))
        inputs = fixtures()
        baseline = None
        for strategy in strategies:
            run = {}
            report["runs"].append(run)
            results = _smoke_run(scratch, weights, profile, strategy, inputs, run)
            if baseline is None:
                baseline = results
            else:
                checks["byte_parity"] = results == baseline and results.keys() == inputs.keys()
            if (run["verdicts"].get("visibility") is False
                    or any(case["status"] == "failed" for case in run["cases"].values())):
                break
        serving = RESOURCES["serving"] if len(strategies) == 1 else None
        allowance = (serving or RESOURCES["measurement"])["limit_gib"] * 1024**3
        peak = cgroup_bytes("peak")
        limit = cgroup_bytes("max")
        checks["cgroup_allowance"] = (
            limit is not None and peak is not None and peak <= limit
            and (limit == allowance if serving else limit >= allowance)
        )
        checks["all_strategies"] = len(report["runs"]) == len(strategies)
        checks["fixtures"] = all(
            run["cases"].keys() == inputs.keys() and run["verdicts"] and all(run["verdicts"].values())
            for run in report["runs"]
        )
        report["passed"] = all(checks.values())
    except (SegmentationError, OSError, ValueError, KeyError) as error:
        report["failure"] = getattr(error, "reason", "smoke_failed")
    finally:
        report["cgroup_peak_bytes"] = cgroup_bytes("peak")
        report["cgroup_limit_bytes"] = cgroup_bytes("max")
    return report
