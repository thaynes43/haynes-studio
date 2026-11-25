"""Run the profile's bounded install smoke and return path-free evidence."""

from __future__ import annotations

import os
import resource
from dataclasses import asdict, replace
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
    COMMAND_FAILED, GRAPH_NAME, MEMORY_LIMIT_BYTES, PROFILE_ID, PROVIDER, REQUEST_INVALID,
    RESPONSE_INVALID, REQUEST_SECONDS, STARTUP_SECONDS, MatteError, Profile, SessionSettings,
)
from .service import listening, local_call

# studio-matting-smoke-02-r3, story 459 comment 9985, matched 01-r2 byte for byte.
# The receipt and request signature include the profile pin and change with a new build.
INSTALLED_FIXTURE_HASHES = {
    "bust": {
        "source": "765d8d4cf8b625840e5e6620d3f6d25eb5365a50a40753db45270ab666087b89",
        "cutout": "7a83461da9e129d4182095527f003e10c32dcd602b93574ca6ab4eac5e500417",
        "mask": "415e39805163f7bdcdc4e88f0b24174be8b62065a4c0d862ed011134f51cef36",
    },
    "green_eyes": {
        "source": "e7e5497d9ec327376c0ea30c77d27946d991e38946e784d13d111d0cd8765de1",
        "cutout": "90751848a67239ea43f0597a738bc0feb2ff1a9231bdaf24e46d19fdcc1e7561",
        "mask": "4c9d3616c90889f71bbbe32ec9c97782191d8875d6456c315b9b078e7bbace59",
    },
    "smaller_bust": {
        "source": "e267942efd6f72a0dff11eda1a6446862dbb3f00ac47e759e365c08f0dee4165",
        "cutout": "50d8063195984e965018c2fcf9a135142c6d1cdd63fe78765d06c9032b0c4bd9",
        "mask": "6b3152a5f4a936c694d18f50916d22ab69db4cae92c735b80649c3774c5ac6a0",
    },
}


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


def _installed_matches(inferences: dict) -> dict:
    matches = {}
    for name, expected in INSTALLED_FIXTURE_HASHES.items():
        for inference in (name, "replay") if name == "bust" else (name,):
            item = inferences.get(inference, {})
            actual = {"source": item.get("source_sha256"), **item.get("artifact_sha256", {})}
            matches[inference] = {artifact: actual.get(artifact) == digest for artifact, digest in expected.items()}
    return matches


def _report_memory(memory: dict, report: dict) -> None:
    startup = memory.get("session_creation")
    first, *warm = (memory.get("requests") or [None])[:4]
    samples = [sample for sample in (startup, first, *warm) if sample is not None]
    report["worker_memory"] = {
        "session_creation": startup,
        "first_inference": first,
        "steady_state": {
            "peak_rss_bytes": max((sample["peak_rss_bytes"] for sample in warm if sample is not None), default=None),
            "rss_after_request_bytes": [sample["rss_after_bytes"] if sample else None for sample in warm],
        },
    }
    # Linux ru_maxrss is in KiB. Keep the maximum across the sampled phases
    # as well, since resetting the worker's high-water mark can affect rusage.
    report["process_peak_rss_bytes"] = {
        "supervisor": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "worker": max(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024,
                      max((sample["peak_rss_bytes"] for sample in samples), default=0)),
    }
    report["peak_rss_upper_bound_bytes"] = sum(report["process_peak_rss_bytes"].values())
    report["memory_limit_bytes"] = MEMORY_LIMIT_BYTES
    report["verdicts"]["memory_phases_measured"] = len(samples) == 5


def smoke(scratch: Path, weights: Path, settings: SessionSettings = SessionSettings()) -> dict:
    started = monotonic()
    report = {"profile_id": PROFILE_ID, "session_settings": asdict(settings),
              "inferences": {}, "scores": {}, "verdicts": {}}
    memory = {}
    verdicts = report["verdicts"]
    try:
        pinned_profile = Profile.installed()
        profile = replace(pinned_profile, session=settings)
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
                engine = Engine(root, weights, pinned_profile, smoke_settings=settings, memory=memory)
            finally:
                report["cold_load_seconds"] = round(monotonic() - cold, 6)
            with engine, listening(root / "matte.sock", engine):
                status, ready = local_call(root / "matte.sock", "GET", "/v1/ready", timeout=3)
                if status != 200 or ready.get("provider") != PROVIDER or ready.get("profile_id") != PROFILE_ID:
                    raise MatteError(RESPONSE_INVALID)
                digest = sha256(profile.manifest()).hexdigest()
                if ready.get("profile_sha256") != digest:
                    raise MatteError(RESPONSE_INVALID)
                report.update({"profile_sha256": digest,
                               "pinned_profile_sha256": sha256(pinned_profile.manifest()).hexdigest(),
                               "provider": ready["provider"],
                               "graph_sha256": {GRAPH_NAME: profile.graph_sha256}})
                verdicts["profile_provenance_readback"] = True
                _check_fixtures(root, profile, digest, report)
    except MatteError as error:
        report["code"] = error.code
    except (OSError, HTTPException, ValueError, RuntimeError):
        report["code"] = COMMAND_FAILED

    _report_memory(memory, report)
    report["installed_hash_matches"] = _installed_matches(report["inferences"])
    report["total_wall_seconds"] = round(monotonic() - started, 6)
    verdicts.update({
        "cold_load_bounded": report.get("cold_load_seconds", float("inf")) <= STARTUP_SECONDS,
        "request_times_bounded": len(report["inferences"]) == 4 and all(
            item["wall_seconds"] <= REQUEST_SECONDS for item in report["inferences"].values()),
        "total_time_bounded": report["total_wall_seconds"] <= 300,
        "memory_bounded": report["peak_rss_upper_bound_bytes"] <= MEMORY_LIMIT_BYTES,
        "installed_artifacts_match": all(
            match for item in report["installed_hash_matches"].values() for match in item.values()),
        "fixture_scores": len(report["scores"]) == 3 and all(
            metric["passed"] for group in report["scores"].values() for metric in group.values()),
    })
    report["passed"] = "code" not in report and all(verdicts.values())
    return report
