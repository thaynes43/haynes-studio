"""Bounded serving smoke and optional offline load-strategy measurements."""

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
from .profile import (
    PROFILE_ID, REQUEST_SECONDS, RESOURCES, SERVING_PROFILE_ID, WEIGHT_LOAD, Profile, SegmentationError, digest,
)
from .service import listening, local_call

RESIDENT_GROWTH_BYTES = 64 * 1024**2
SERVING_PASS_SUFFIXES = ("", "_repeat", "_third")
STABILITY_PASSES = (2, 3)
SERVING_RUN_SECONDS = 840  # Leave time for Job startup, cleanup, and the report within 900 s.
CALL_TIMEOUT_SECONDS = REQUEST_SECONDS + 5


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
    status, reply = local_call(socket, "POST", "/v1/segment", payload, timeout=CALL_TIMEOUT_SECONDS)
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


def _phase_memory(memory, expected_requests, limit):
    startup = memory["startup"]
    requests = memory.get("requests", [])
    return (
        limit is not None
        and startup.keys() == {"verify_profile_and_files", "runtime_import", "load_dino", "load_sam"}
        and [set(request) for request in requests] == expected_requests
        and all(
            facts["phase_rss_peak_reset"] and all(
                type(facts.get(key)) is int and 0 < facts[key] <= limit
                for key in ("peak_rss_bytes", "resident_rss_bytes", "cgroup_resident_bytes",
                            "cgroup_peak_since_start_bytes")
            )
            for phases in [startup, *requests] for facts in phases.values()
        )
    )


def _request_phases(fixture, result):
    phases = {"source_validation"}
    if not fixture.hint:
        phases.add("grounding")
    if result["status"] == "ready":
        phases.update(("sam", "mask_publication"))
    return phases


def _pass_memory(requests, case_count, pass_cgroup):
    report = {
        "tolerance_bytes": RESIDENT_GROWTH_BYTES,
        "compared_passes": list(STABILITY_PASSES),
        "max_resident_rss_bytes": [],
        "max_cgroup_resident_bytes": [],
        "cgroup_resident_bytes": pass_cgroup,
    }
    for index in range(len(pass_cgroup)):
        phases = [
            phase
            for request in requests[index * case_count:(index + 1) * case_count]
            for phase in request.values()
        ]
        for key in ("resident_rss_bytes", "cgroup_resident_bytes"):
            report[f"max_{key}"].append(
                max((phase[key] for phase in phases if type(phase.get(key)) is int), default=None)
            )
    return report


def _memory_stable(passes):
    reference, comparison = (number - 1 for number in STABILITY_PASSES)
    return all(
        len(values) == len(SERVING_PASS_SUFFIXES)
        and all(type(value) is int and value > 0 for value in (values[reference], values[comparison]))
        and values[comparison] <= values[reference] + RESIDENT_GROWTH_BYTES
        for values in (
            passes["max_resident_rss_bytes"],
            passes["max_cgroup_resident_bytes"],
        )
    )


def _smoke_run(scratch, weights, profile, strategy, inputs, report, *, repeat=False):
    results = {}
    masks = {}
    request_phases = []
    report.update({"weight_load": strategy, "memory": {}, "verdicts": {}, "cases": {}, "readiness": {}})
    pass_cgroup = []
    checks = report["verdicts"]
    pin = digest(profile.manifest())
    socket = scratch / "segment.sock"
    cold_start = monotonic()
    deadline = cold_start + SERVING_RUN_SECONDS
    with Engine(scratch, weights, profile, memory=report["memory"], load_strategy=strategy) as engine:
        report["cold_load_ms"] = round((monotonic() - cold_start) * 1000)
        with listening(socket, engine):
            expected = {"profile_id": PROFILE_ID, "profile_sha256": pin, "device": "cpu"}
            status, report["readiness"]["initial"] = local_call(socket, "GET", "/v1/ready", timeout=5)
            checks["ready_initial"] = (status, report["readiness"]["initial"]) == (200, expected)
            if not checks["ready_initial"]:
                return results
            cases = list(inputs.items())
            suffixes = SERVING_PASS_SUFFIXES if repeat else ("",)
            if repeat:
                checks["time_budget"] = True
            for index, (name, fixture) in enumerate(cases * len(suffixes)):
                if repeat and monotonic() + CALL_TIMEOUT_SECONDS > deadline:
                    checks["time_budget"] = False
                    break
                suffix = suffixes[index // len(cases)]
                case = name + suffix
                payload, status, result, png, mask, elapsed = _call(scratch, socket, name, fixture)
                request_phases.append(_request_phases(fixture, result))
                passes, metrics = _verdict(name, fixture, status, result, mask)
                checks[case] = passes
                required_models = (["dino"] if not fixture.hint else []) + (
                    ["sam"] if result["status"] == "ready" else []
                )
                parameters = result["provenance"]["parameters"]
                applied = {key: parameters[key] for key in (
                    "prompt", "detector_resize_wh", "detector_canvas_wh", "sam_hint", "weight_load",
                ) if key in parameters}
                checks[f"{case}_provenance"] = (
                    result["provenance"] == profile.provenance(required_models, applied)
                    and applied.get("weight_load") == strategy and result["provenance"]["profile"]["sha256"] == pin
                )
                receipt = canonical_json(result)
                report["cases"][case] = {
                    "status": result["status"], "reason": result["reason"], "elapsed_ms": elapsed, **metrics,
                    "result_sha256": digest(receipt), "mask_sha256": digest(png) if png else None,
                }
                if not repeat and "weight_load" in parameters:
                    # The two receipts differ in the recorded experimental load
                    # strategy. Compare every other byte along with the mask PNG.
                    del parameters["weight_load"]
                    receipt = canonical_json(result)
                results[case] = receipt, png
                if suffix:
                    checks[f"{case}_byte_parity"] = results[case] == results[name]
                if mask is not None:
                    masks[name] = mask
                if result["status"] == "failed":
                    return results
                if name == "foreground" and not suffix and strategy == WEIGHT_LOAD and passes:
                    old = scratch / payload["attempt_id"]
                    before = (old / "result.json").read_bytes(), (old / "mask.png").read_bytes()
                    replay_status, _ = local_call(socket, "POST", "/v1/segment", payload, timeout=5)
                    checks["create_only_replay"] = (
                        replay_status == 400
                        and before == ((old / "result.json").read_bytes(), (old / "mask.png").read_bytes())
                    )
                    if not repeat:
                        _, fresh_status, fresh_result, fresh_png, _, _ = _call(scratch, socket, name, fixture)
                        request_phases.append(_request_phases(fixture, fresh_result))
                        checks["create_only_replay"] &= (
                            fresh_status == 200 and before == (canonical_json(fresh_result), fresh_png)
                        )
                if (index + 1) % len(cases) == 0:
                    checks[f"visibility{suffix}"] = False
                    if {"foreground", "visible_face", "hidden_prop"} <= masks.keys():
                        visible = visible_fraction(masks["visible_face"], masks["foreground"])
                        hidden = visible_fraction(masks["hidden_prop"], masks["foreground"])
                        report[f"visible_fractions{suffix}"] = {"face": visible, "prop": hidden}
                        checks[f"visibility{suffix}"] = visible >= 0.95 and hidden <= 0.05
                        checks[f"hidden_prop_fails_fixture_gate{suffix}"] = hidden <= 0.50
                    masks.clear()
                    if repeat:
                        pass_cgroup.append(cgroup_bytes("current"))
                    if not checks[f"visibility{suffix}"]:
                        break
            status, report["readiness"]["after"] = local_call(socket, "GET", "/v1/ready", timeout=5)
            checks["ready_after"] = (status, report["readiness"]["after"]) == (200, expected)
    checks["phase_memory"] = _phase_memory(report["memory"], request_phases, cgroup_bytes("max"))
    if repeat:
        report["memory"]["passes"] = _pass_memory(
            report["memory"].get("requests", []), len(cases), pass_cgroup,
        )
        checks["memory_stable"] = _memory_stable(report["memory"]["passes"])
    return results


def smoke(scratch: Path, weights: Path, strategies: tuple[str, ...] = ()) -> dict:
    serving = not strategies
    strategies = strategies or (WEIGHT_LOAD,)
    report = {"schema": "studio.segmentation-smoke/v1", "runs": [], "verdicts": {}, "passed": False}
    checks = report["verdicts"]
    try:
        profile = Profile.installed()
        report.update({
            "profile_id": SERVING_PROFILE_ID, "profile_sha256": digest(profile.manifest()),
            "image_digest": profile.image_digest, "mode": "serving" if serving else "measurement",
            "models": profile.model_files(), "runtime": profile.runtime(),
        })
        checks["workload"] = (os.geteuid() == os.getegid() == 10001
                              and bool(os.statvfs("/").f_flag & os.ST_RDONLY)
                              and bool(os.statvfs(weights).f_flag & os.ST_RDONLY))
        inputs = fixtures()
        suffixes = SERVING_PASS_SUFFIXES if serving else ("",)
        expected_cases = {name + suffix for name in inputs for suffix in suffixes}
        baseline = None
        for strategy in strategies:
            run = {}
            report["runs"].append(run)
            results = _smoke_run(scratch, weights, profile, strategy, inputs, run, repeat=serving)
            if baseline is None:
                baseline = results
            else:
                checks["byte_parity"] = results == baseline and results.keys() == inputs.keys()
            if (run["verdicts"].get("visibility") is False
                    or any(case["status"] == "failed" for case in run["cases"].values())):
                break
        allowance = RESOURCES["serving" if serving else "measurement"]["limit_gib"] * 1024**3
        peak = cgroup_bytes("peak")
        limit = cgroup_bytes("max")
        checks["cgroup_allowance"] = (
            limit is not None and peak is not None and peak <= limit
            and (limit == allowance if serving else limit >= allowance)
        )
        checks["all_strategies"] = len(report["runs"]) == len(strategies)
        checks["fixtures"] = all(
            run["cases"].keys() == expected_cases and run["verdicts"] and all(run["verdicts"].values())
            for run in report["runs"]
        )
        report["passed"] = all(checks.values())
    except (SegmentationError, OSError, ValueError, KeyError) as error:
        report["failure"] = getattr(error, "reason", "smoke_failed")
    finally:
        report["cgroup_peak_bytes"] = cgroup_bytes("peak")
        report["cgroup_limit_bytes"] = cgroup_bytes("max")
    return report
