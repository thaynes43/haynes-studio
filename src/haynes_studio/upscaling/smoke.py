"""Measure the pinned profile and a lower-memory candidate on synthetic frames."""

from copy import deepcopy
from functools import partial
from hashlib import sha256
from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic, sleep

import numpy as np
from PIL import Image

from haynes_studio.render.delivery_profile import resolve_delivery_upscaler
from haynes_studio.store import canonical_json

from .backend import Engine
from .fixtures import EDGE_ROWS, FEATURES, FLAT, MOTION, STATIC, Motion, portrait, scores, verdicts
from .observe import cgroup_limit, cgroup_peak, phase
from .opencv import Fsrcnn
from .pixels import crop_plate, decode_png, describe, encode_png
from .profile import (
    MAX_INPUT, PIN_MISMATCH, PROVIDER, REQUEST_INVALID, REQUEST_SECONDS, RESOURCES, RESPONSE_INVALID,
    TIMEOUT, UpscaleError,
)
from .service import listening, local_call
from .trial import frame, stage

PORTRAIT = (1080, 1920)
LANDSCAPE = (1920, 1080)
SOURCE = (576, 1024)


def _low(image: Image.Image, size=SOURCE) -> Image.Image:
    return image.resize(size, Image.Resampling.BOX)


def _record_bytes(path: Path, png: bytes, *, replay: bool) -> bool:
    if replay:
        return path.read_bytes() == png
    with path.open("xb") as output:
        output.write(png)
    return True


def _exercise(root: Path, weights: Path, pinned, settings, captured: Path, *, factory=None) -> dict:
    memory, phases, records, exact = {}, {}, {}, {}
    baseline_motion, learned_motion = Motion(), Motion()
    replay_png = replay_receipt = None
    socket = root / "upscale.sock"
    startup = monotonic()
    with phase(phases, "startup"):
        engine = Engine(root, weights, pinned, smoke_settings=settings, memory=memory, factory=factory)
    cold_seconds = monotonic() - startup
    phases["startup"]["worker"] = memory["startup"][0]
    with engine, listening(socket, engine):
        status, ready = local_call(socket, "GET", "/v1/ready")
        if status != 200 or ready["provider"] != PROVIDER:
            raise UpscaleError(PIN_MISMATCH)
        digest = ready["profile_sha256"]

        def run_one(name, rgb, target):
            nonlocal replay_png, replay_receipt
            with phase(phases, name + "_lanczos"):
                baseline = resolve_delivery_upscaler(None).scale(rgb, target)
                baseline_png = encode_png(baseline)
            with phase(phases, name + "_fsrcnn"):
                data, receipt, attempt = frame(root, socket, rgb, target, engine.profile, digest)
            phases[name + "_fsrcnn"]["worker"] = memory["requests"][attempt]
            exact[name] = _record_bytes(captured / (name + ".png"), data, replay=settings != "default")
            learned = decode_png(data, target, RESPONSE_INVALID)
            if name == "motion_00":
                replay_png, replay_receipt = data, canonical_json(receipt)
            records[name] = {"source": receipt["source"], "lanczos": describe(baseline_png, target),
                             "fsrcnn": receipt["output"], "request_sha256": receipt["request_sha256"],
                             "receipt_sha256": sha256(canonical_json(receipt)).hexdigest()}
            return baseline, learned

        with phase(phases, "fixture_portrait"):
            original = portrait()
            rgb = _low(original)
        for i in range(16):
            with phase(phases, f"fixture_motion_{i:02}"):
                reference = original if i == 0 else portrait(i)
                motion_rgb = rgb if i == 0 else _low(reference)
            baseline, learned = run_one(f"motion_{i:02}", motion_rgb, PORTRAIT)
            with phase(phases, f"metrics_{i:02}"):
                baseline_motion.add(baseline, reference, i)
                learned_motion.add(learned, reference, i)
                if i == 0:
                    baseline_quality, quality = scores(baseline, original), scores(learned, original)
        baseline_quality["motion"] = baseline_motion.report()
        quality["motion"] = learned_motion.report()

        run_one("landscape", _low(original.transpose(Image.Transpose.TRANSPOSE), SOURCE[::-1]), LANDSCAPE)
        plate = Image.new("RGB", (626, 1024), (240, 180, 20))
        plate.paste(rgb, (25, 0))
        cropped, crop = crop_plate(plate, PORTRAIT)
        run_one("plate", cropped, PORTRAIT)
        run_one("max_graph_input", _low(original, (720, 1280)), PORTRAIT)

        # Check rejection after the ordinary frames so refusal measurements do
        # not enter the mean/p95 samples. No existing output is a test target.
        value = stage(root, encode_png(rgb), rgb.size, PORTRAIT, digest)
        refusals = {}
        for name, key, field, changed, code, expected_status in (
            ("unknown_profile", None, "profile_id", "unknown", PIN_MISMATCH, 409),
            ("wrong_input_hash", "source", "sha256", "0" * 64, PIN_MISMATCH, 409),
            ("oversized_input", "source", "bytes", MAX_INPUT + 1, REQUEST_INVALID, 400),
        ):
            bad = deepcopy(value)
            request = bad["request"]
            (request if key is None else request[key])[field] = changed
            refusals[name] = local_call(socket, "POST", "/v1/upscale-frame", bad) == (
                expected_status, {"code": code},
            )
        refusals["no_output"] = not (root / value["attempt_id"] / "result").exists()

    # The repeated dispatch uses a fresh worker, identical input and settings.
    replay_memory = {}
    with phase(phases, "replay_startup"):
        replay = Engine(root, weights, pinned, smoke_settings=settings, memory=replay_memory, factory=factory)
    phases["replay_startup"]["worker"] = replay_memory["startup"][0]
    with replay, listening(socket, replay):
        with phase(phases, "replayed_frame"):
            png, receipt, attempt = frame(root, socket, rgb, PORTRAIT, replay.profile, digest)
    phases["replayed_frame"]["worker"] = replay_memory["requests"][attempt]
    repeat = replay_png == png and replay_receipt == canonical_json(receipt)
    worker_count = len(records)
    times = [phases[name + "_fsrcnn"]["wall_seconds"] for name in records]
    # Output 24 fps on the existing 16 fps source clock. The scaler dispatches
    # each distinct frame once and has no control of the replay cadence.
    cadence = [i * 16 // 24 for i in range(24)]
    expected_cadence = [index for i in range(0, 16, 2) for index in (i, i, i + 1)]
    cadence_ok = cadence == expected_cadence
    repeated = [records[f"motion_{i:02}"]["fsrcnn"]["sha256"] for i in cadence]
    return {
        "profile_sha256": digest, "allocator": settings, "cold_seconds": round(cold_seconds, 6),
        "frames": records, "frame_count": worker_count,
        "staged_bytes": sum(sum(item[key]["bytes"] for key in ("source", "lanczos", "fsrcnn"))
                            for item in records.values()),
        "repeat_byte_match": repeat, "allocator_png_byte_matches": exact,
        "timing": {"warm_mean_seconds": mean(times[1:]), "warm_p95_seconds": float(np.percentile(times[1:], 95)),
                   "max_seconds": max(times), "estimated_100_frame_seconds": mean(times[1:]) * 100},
        "memory_by_phase": phases, "baseline_quality": baseline_quality, "quality": quality,
        "quality_verdicts": verdicts(baseline_quality, quality),
        "refusals": refusals, "plate_crop": list(crop), "cadence_24fps": cadence,
        "cadence_verified": cadence_ok, "cadence_output_sha256": repeated,
    }


class FailFirstFrame:
    """Finish inference, then stall on one request to exercise the actual kill."""

    def __init__(self, graph, *, profile, marker):
        self.model = Fsrcnn(graph, identity=profile.identity, settings=profile.settings)
        self.marker = marker

    def __call__(self, rgb):
        result = self.model(rgb)
        try:
            with self.marker.open("xb"):
                pass
        except FileExistsError:
            return result
        Event().wait(60)
        return result


def _deadline(root, weights, profile, *, factory=None, seconds=REQUEST_SECONDS) -> bool:
    socket = root / "upscale.sock"
    mark = root / "inferred"
    if factory is None:
        factory = partial(FailFirstFrame, profile=profile, marker=mark)
    with Engine(root, weights, profile, factory=factory, request_seconds=seconds) as engine, listening(socket, engine):
        rgb = Image.new("RGB", SOURCE, (100, 100, 100))
        data = encode_png(rgb)
        digest = engine.readiness["profile_sha256"]
        attempt = stage(root, data, SOURCE, PORTRAIT, digest)
        response = local_call(socket, "POST", "/v1/upscale-frame", attempt)
        old = root / attempt["attempt_id"]
        if (response != (504, {"code": TIMEOUT}) or (old / "result").exists()
                or (old / "input.png").read_bytes() != data or not mark.is_file()):
            return False
        stop = monotonic() + 31
        while engine.readiness is None and monotonic() < stop:
            sleep(0.05)
        if engine.readiness is None:
            return False
        _, receipt, _ = frame(root, socket, rgb, PORTRAIT, engine.profile, digest)
        return (receipt["source"]["sha256"] == sha256(data).hexdigest() and not (old / "result").exists()
                and (old / "input.png").read_bytes() == data)


def smoke(scratch: Path, weights: Path, profile, *, try_compact=True, factory=None) -> dict:
    report = {
        "schema": "studio.upscaling-smoke/v1", "image_digest": profile.image_digest, "provider": PROVIDER,
        "profile_sha256": sha256(profile.manifest()).hexdigest(),
        "cpu": profile.document()["cpu"],
        "rois": {"face": FEATURES, "flat": FLAT, "edge_rows": EDGE_ROWS, "motion": MOTION, "static": STATIC},
        "quality_peak_bytes": RESOURCES["quality_peak_gib"] * 1024**3,
        "measuring_limit_bytes": cgroup_limit(),
        "settings": {},
    }
    with TemporaryDirectory(prefix="smoke-", dir=scratch) as work:
        root = Path(work)
        captured = root / "captured"
        captured.mkdir()
        for settings in (("default", "compact-allocator") if try_compact else ("default",)):
            attempt = root / settings
            attempt.mkdir()
            report["settings"][settings] = _exercise(attempt, weights, profile, settings, captured, factory=factory)
        try_dir = root / "deadline"
        try_dir.mkdir()
        with phase(report, "forced_timeout_phase"):
            deadline = _deadline(try_dir, weights, profile)
    baseline = report["settings"]["default"]
    compact = report["settings"].get("compact-allocator")
    peak = cgroup_peak()
    report["whole_job_cgroup_peak_bytes"] = peak
    report["verdicts"] = {
        **baseline["quality_verdicts"], **baseline["refusals"],
        "plate_crop": baseline["plate_crop"] == [25, 0, 601, 1024] and all(
            baseline["frames"]["plate"][kind] == baseline["frames"]["motion_00"][kind]
            for kind in ("source", "lanczos", "fsrcnn")
        ),
        "cadence": baseline["cadence_verified"],
        "forced_timeout_retry": deadline,
        "fresh_worker_repeat": all(item["repeat_byte_match"] for item in report["settings"].values()),
        "phase_memory_measured": all(
            observation["cgroup_sampled_peak_bytes"] is not None and observation["parent"] is not None
            and ("worker" not in observation or observation["worker"] is not None)
            for item in report["settings"].values() for observation in item["memory_by_phase"].values()
        ),
        "quality_memory_target": peak is not None and peak <= report["quality_peak_bytes"],
        "warm_timing": all(
            item["timing"]["warm_mean_seconds"] <= 0.80 and item["timing"]["warm_p95_seconds"] <= 2
            and item["timing"]["max_seconds"] < REQUEST_SECONDS for item in report["settings"].values()
        ),
    }
    if try_compact:
        report["verdicts"]["allocator_measured"] = compact is not None
        report["verdicts"]["allocator_byte_match"] = compact is not None and all(
            compact["allocator_png_byte_matches"].values()
        )
    # A failed quality gate is evidence. Emit the report before returning failure.
    report["passed"] = all(report["verdicts"].values())
    return report
