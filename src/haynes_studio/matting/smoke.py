"""Run the profile's bounded install smoke and return path-free evidence."""

from __future__ import annotations

import os
import resource
from hashlib import sha256
from http.client import HTTPException
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from uuid import uuid4

from haynes_studio.store import canonical_json

from .backend import Engine, verify_result
from .fixtures import GREEN, bust, score_eyes, score_shape, score_size
from .pixels import MODES, describe_png, encode_png, measure_shape
from .profile import (
    COMMAND_FAILED, GRAPH_NAME, PROFILE_ID, PROVIDER, REQUEST_INVALID, RESPONSE_INVALID,
    REQUEST_SECONDS, STARTUP_SECONDS, MatteError, Profile,
)
from .service import listening, local_call

GIB = 1024**3


def _request(directory: Path, data: bytes, width: int, height: int, digest: str,
             *, backing=None, target=None) -> dict:
    attempt = uuid4().hex
    root = directory / attempt
    root.mkdir(mode=0o700)
    (root / "input").write_bytes(data)
    return {"attempt_id": attempt, "request": {
        "schema": "studio.matte-request/v1",
        "job_id": "job_00000000000000000000000001",
        "source": {
            "asset_version_id": "asv_00000000000000000000000001",
            "production_id": None, "sha256": sha256(data).hexdigest(), "bytes": len(data),
            "media_type": "image/png", "width": width, "height": height,
        },
        "profile_id": PROFILE_ID, "profile_sha256": digest,
        "parameters": {"chroma_rgb": list(backing) if backing is not None else None, "target_height_px": target},
    }}


def _dispatch(root: Path, profile: Profile, value: dict, measures: dict, name: str):
    started = monotonic()
    item = measures[name] = {}
    try:
        status, reply = local_call(root / "matte.sock", "POST", "/v1/matte", value)
    finally:
        item["wall_seconds"] = round(monotonic() - started, 6)
    if status != 200:
        item["code"] = reply.get("code", COMMAND_FAILED)
        raise MatteError(item["code"])
    attempt = root / value["attempt_id"]
    artifacts = {key: (attempt / (key + ".png")).read_bytes() for key in MODES}
    request = value["request"]
    verify_result(request, reply, artifacts, profile)
    size = request["source"]["width"], request["source"]["height"]
    item.update({
        "source_sha256": request["source"]["sha256"], "input_signature": reply["input_signature"],
        "receipt_sha256": sha256(canonical_json(reply)).hexdigest(),
        "artifact_sha256": {key: facts["sha256"] for key, facts in reply["artifacts"].items()},
        "shape": reply["shape"],
    })
    return reply, describe_png(artifacts["cutout"], "RGBA", size)[1]


def _check_fixtures(root: Path, profile: Profile, digest: str, report: dict) -> None:
    grey, green, small = bust(), bust(green=True), bust(smaller=True)
    true_shape = measure_shape(grey.alpha, None)
    target = true_shape["bbox_height_px"]
    grey_data = encode_png(grey.rgb)
    measures, scores = report["inferences"], report["scores"]

    base_req = _request(root, grey_data, 384, 512, digest, target=target)
    base, rgba = _dispatch(root, profile, base_req, measures, "bust")
    scores["shape_fringe"] = score_shape(grey, rgba[..., 3])

    green_req = _request(root, encode_png(green.rgb), 384, 512, digest, backing=GREEN)
    _, rgba = _dispatch(root, profile, green_req, measures, "green_eyes")
    scores["green_eyes"] = score_eyes(green, rgba)

    small_req = _request(root, encode_png(small.rgb), 384, 512, digest, target=target)
    sized, _ = _dispatch(root, profile, small_req, measures, "smaller_bust")
    scores["size_match"] = score_size(true_shape, base["shape"], measure_shape(small.alpha, None), sized["shape"])

    repeated_req = _request(root, grey_data, 384, 512, digest, target=target)
    repeated, _ = _dispatch(root, profile, repeated_req, measures, "replay")
    report["verdicts"]["deterministic_replay"] = repeated == base

    bad_req = _request(root, grey_data, 384, 512, digest, target=target)
    bad_req["request"]["source"]["sha256"] = "0" * 64
    status, refusal = local_call(root / "matte.sock", "POST", "/v1/matte", bad_req)
    report["verdicts"]["bad_digest_refused"] = (
        status == 400 and refusal == {"code": REQUEST_INVALID}
        and set(item.name for item in (root / bad_req["attempt_id"]).iterdir()) == {"input"}
    )


def _mount_readonly(path: Path) -> bool:
    return bool(os.statvfs(path).f_flag & os.ST_RDONLY)


def smoke(scratch: Path, weights: Path) -> dict:
    started = monotonic()
    report = {"profile_id": PROFILE_ID, "inferences": {}, "scores": {}, "verdicts": {}}
    verdicts = report["verdicts"]
    try:
        profile = Profile.installed()
        report["image_digest"] = profile.image_digest
        uid, gid = os.geteuid(), os.getegid()
        report.update({"uid": uid, "gid": gid})
        verdicts.update({
            "uid_gid": uid == gid == 10001,
            "root_read_only": _mount_readonly(Path("/")),
            "weights_read_only": _mount_readonly(weights),
        })
        if not all(verdicts.values()):
            raise MatteError(COMMAND_FAILED)
        with TemporaryDirectory(prefix="smoke-", dir=scratch) as name:
            root = Path(name)
            cold = monotonic()
            try:
                engine = Engine(root, weights, profile)
            finally:
                report["cold_load_seconds"] = round(monotonic() - cold, 6)
            with engine, listening(root / "matte.sock", engine):
                status, ready = local_call(root / "matte.sock", "GET", "/v1/ready", timeout=3)
                if status != 200 or ready.get("provider") != PROVIDER or ready.get("profile_id") != PROFILE_ID:
                    raise MatteError(RESPONSE_INVALID)
                digest = sha256(profile.manifest()).hexdigest()
                if ready.get("profile_sha256") != digest:
                    raise MatteError(RESPONSE_INVALID)
                report.update({"profile_sha256": digest, "provider": ready["provider"],
                               "graph_sha256": {GRAPH_NAME: profile.graph_sha256}})
                verdicts["profile_provenance_readback"] = True
                _check_fixtures(root, profile, digest, report)
    except MatteError as error:
        report["code"] = error.code
    except (OSError, HTTPException, ValueError, RuntimeError):
        report["code"] = COMMAND_FAILED

    # ru_maxrss on Linux is in KiB. A sum of process peaks is an upper bound
    # because the parent's and the inference child's peaks can occur at different times.
    report["process_peak_rss_bytes"] = {
        name: resource.getrusage(who).ru_maxrss * 1024
        for name, who in (("supervisor", resource.RUSAGE_SELF), ("worker", resource.RUSAGE_CHILDREN))
    }
    report["peak_rss_upper_bound_bytes"] = sum(report["process_peak_rss_bytes"].values())
    report["total_wall_seconds"] = round(monotonic() - started, 6)
    verdicts.update({
        "cold_load_bounded": report.get("cold_load_seconds", float("inf")) <= STARTUP_SECONDS,
        "request_times_bounded": len(report["inferences"]) == 4 and all(
            item["wall_seconds"] <= REQUEST_SECONDS for item in report["inferences"].values()),
        "total_time_bounded": report["total_wall_seconds"] <= 300,
        "memory_bounded": report["peak_rss_upper_bound_bytes"] <= 6 * GIB,
        "fixture_scores": len(report["scores"]) == 3 and all(
            metric["passed"] for group in report["scores"].values() for metric in group.values()),
    })
    report["passed"] = "code" not in report and all(verdicts.values())
    return report
