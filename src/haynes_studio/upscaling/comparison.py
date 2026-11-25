"""Compare the two scalers on one authorized private still or delivery frame."""

from contextlib import ExitStack
from hashlib import sha256
from io import BytesIO
import os
from math import log10
from pathlib import Path, PurePosixPath
import re
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image

from haynes_studio.render.delivery_profile import fit_set_plate, resolve_delivery_upscaler
from haynes_studio.store import canonical_json

from .backend import DIGEST, PLATE_COMPARISON_SCHEMA, Engine
from .files import create_file, open_directory, read_file
from .fixtures import luma
from .observe import cgroup_peak, phase
from .pixels import decode_png, describe, encode_png, fits, fits_plate
from .profile import (
    MAX_INPUT, MAX_LONG_EDGE, MAX_OUTPUT, MAX_PIXELS, PIN_MISMATCH, REQUEST_INVALID, RESPONSE_INVALID, TARGETS,
    THREADS, UpscaleError,
)
from .trial import evaluate, stage
from .video import read_frame, require_delivery_id

RESERVE = 32 * 1024**3
BUDGET = 8 * 1024**3
GROUND_TRUTH_SCOPE = (
    "The proxy is an encoded downscale of the master. These measures reward undoing that specific encode. "
    "They do not establish quality on real low-resolution sources. Tom's visual comparison is pending."
)
PAIRING_VERIFICATION = (
    "The caller verified the pairing against the delivery record. The Job relies on the caller for pairing."
)


def _source(share: Path, relative: str) -> bytes:
    path = PurePosixPath(relative)
    if (path.is_absolute() or path.as_posix() != relative
            or ".." in path.parts or not path.parts or len(path.parts) > 30
            or len(relative) > 1000):
        raise UpscaleError(REQUEST_INVALID)
    with ExitStack() as files:
        directory = files.enter_context(open_directory(share))
        for name in path.parts[:-1]:
            directory = files.enter_context(open_directory(name, dir_fd=directory))
        return read_file(directory, path.name, MAX_INPUT, REQUEST_INVALID)


def _decode(data: bytes) -> Image.Image:
    try:
        with Image.open(BytesIO(data), formats=("PNG", "JPEG")) as still:
            if (still.mode not in {"RGB", "L"} or still.width * still.height > MAX_PIXELS
                    or max(still.size) > MAX_LONG_EDGE or still.info.get("transparency") is not None
                    or still.info.get("icc_profile") is not None or still.getexif().get(274, 1) != 1
                    or getattr(still, "n_frames", 1) != 1):
                raise UpscaleError(REQUEST_INVALID)
            return still.convert("RGB")
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as error:
        raise UpscaleError(REQUEST_INVALID) from error


def _edge_energy(gray):
    dx, dy = np.diff(gray, axis=1), np.diff(gray, axis=0)
    return float((np.abs(dx).mean() + np.abs(dy).mean()) / (2 * 255))


def _fidelity(output, truth, rois):
    import cv2

    cv2.setNumThreads(THREADS)
    delta = np.abs(output - truth) / 255
    mse = float(np.square(delta).mean(dtype=np.float64))

    def local_mean(image):
        return cv2.GaussianBlur(image, (11, 11), 1.5)

    x, y = output.astype(np.float64) / 255, truth.astype(np.float64) / 255
    mx, my = local_mean(x), local_mean(y)
    vx, vy = local_mean(x * x) - mx * mx, local_mean(y * y) - my * my
    cov = local_mean(x * y) - mx * my
    c1, c2 = 0.01**2, 0.03**2
    ssim = ((2 * mx * my + c1) * (2 * cov + c2)) / ((mx * mx + my * my + c1) * (vx + vy + c2))
    return {
        "luma_mae": float(delta.mean()), "luma_psnr_db": -10 * log10(mse) if mse else None,
        "luma_ssim": float(ssim[5:-5, 5:-5].mean()),
        "roi_luma_mae": {name: float(delta[y0:y1, x0:x1].mean()) for name, (x0, y0, x1, y1) in rois.items()},
    }


def _measure(rgb, baseline, learned, rois, master=None):
    reference = luma(rgb)
    truth = luma(master) if master is not None else None
    comparison = {}
    for label, image in (("lanczos", baseline), ("fsrcnn", learned)):
        output = luma(image)
        projected = luma(image.resize(rgb.size, Image.Resampling.BOX))
        comparison[label] = {
            "source_scale_luma_mae": float(np.abs(projected - reference).mean() / 255),
            "mean_luma_edge_energy": _edge_energy(output),
            "roi_luma_edge_energy": {name: _edge_energy(output[y0:y1, x0:x1])
                                     for name, (x0, y0, x1, y1) in rois.items()},
        }
        if truth is not None:
            comparison[label]["ground_truth"] = _fidelity(output, truth, rois)
    delta = np.abs(luma(baseline) - luma(learned))
    comparison["pair"] = {
        "luma_mae": float(delta.mean() / 255), "luma_p95": float(np.percentile(delta, 95) / 255),
        "roi_luma_mae": {name: float(delta[y0:y1, x0:x1].mean() / 255)
                         for name, (x0, y0, x1, y1) in rois.items()},
    }
    return comparison


def _publish(directory: Path, pngs: dict, report: dict) -> int | None:
    with open_directory(directory) as output:
        space = os.fstatvfs(output)
        if os.listdir(output) or space.f_bavail * space.f_frsize < RESERVE + BUDGET:
            raise UpscaleError(REQUEST_INVALID)
        with phase(report["memory_by_phase"], "publish_pngs"):
            for label, data in pngs.items():
                name = label + ".png"
                create_file(output, name, data, durable=True)
                saved = read_file(output, name, MAX_OUTPUT, RESPONSE_INVALID)
                if saved != data:
                    raise UpscaleError(RESPONSE_INVALID)
        report["whole_job_cgroup_peak_bytes"] = cgroup_peak()
        manifest = canonical_json(report)
        create_file(output, ".report.part", manifest, durable=True)
        os.link(".report.part", "report.json", src_dir_fd=output, dst_dir_fd=output, follow_symlinks=False)
        os.unlink(".report.part", dir_fd=output)
        os.fsync(output)
        return report["whole_job_cgroup_peak_bytes"]


def compare(scratch: Path, weights: Path, share: Path, output: Path, profile, *, target,
            relative: str | None = None, source_sha256: str | None = None, plate=False, rois=None,
            proxy: str | None = None, frame_index: int | None = None, master: str | None = None,
            delivery_id: str | None = None, factory=None) -> dict:
    if target not in TARGETS:
        raise UpscaleError(REQUEST_INVALID)
    require_delivery_id(master, delivery_id)
    if proxy is None:
        if (relative is None or source_sha256 is None or not DIGEST.fullmatch(source_sha256)
                or frame_index is not None or master is not None):
            raise UpscaleError(REQUEST_INVALID)
    elif relative is not None or source_sha256 is not None or plate or type(frame_index) is not int:
        raise UpscaleError(REQUEST_INVALID)
    rois = rois or {}
    for name, (x0, y0, x1, y1) in rois.items():
        if (name not in {"lettering", "hair", "face"}
                or not 0 <= x0 < x1 <= target[0] or x1 - x0 < 2
                or not 0 <= y0 < y1 <= target[1] or y1 - y0 < 2):
            raise UpscaleError(REQUEST_INVALID)
    phases, memory, decoded = {}, {}, {}
    reference = reference_facts = None
    with phase(phases, "read_normalize"):
        if proxy is None:
            data = _source(share, relative)
            source_hash = sha256(data).hexdigest()
            if source_hash != source_sha256:
                raise UpscaleError(PIN_MISMATCH)
            rgb = _decode(data)
            if not (fits_plate if plate else fits)(rgb.size, target):
                raise UpscaleError(REQUEST_INVALID)
            source_facts = {"sha256": source_hash, "bytes": len(data), "size": list(rgb.size)}
        else:
            rgb, source_facts = read_frame(share, proxy, frame_index, target)
        normalized_png = encode_png(rgb)
        if proxy is not None:
            decoded["proxy"] = normalized_png
    if master is not None:
        with phase(phases, "read_master"):
            reference, reference_facts = read_frame(
                share, master, frame_index, target, master_frames=source_facts["frame_count"],
            )
            decoded["master"] = encode_png(reference)
            if len(decoded["master"]) > MAX_OUTPUT:
                raise UpscaleError(RESPONSE_INVALID)
    with phase(phases, "lanczos"):
        resize = fit_set_plate if plate else resolve_delivery_upscaler(None).scale
        baseline = resize(rgb, target)
        baseline_png = encode_png(baseline)
        if len(baseline_png) > MAX_OUTPUT:
            raise UpscaleError(RESPONSE_INVALID)
        decode_png(baseline_png, target, RESPONSE_INVALID)
    with TemporaryDirectory(prefix="compare-", dir=scratch) as work:
        root = Path(work)
        with phase(phases, "startup"):
            engine = Engine(root, weights, profile, memory=memory, factory=factory)
        with engine:
            ready = engine.readiness
            if ready is None:
                raise UpscaleError(PIN_MISMATCH)
            with phase(phases, "fsrcnn"):
                stage_options = {"schema": PLATE_COMPARISON_SCHEMA} if plate else {}
                value = stage(root, normalized_png, rgb.size, target, ready["profile_sha256"], **stage_options)
                learned_png, receipt, attempt = evaluate(root, value, engine.profile,
                                                         engine.compare_plate if plate else engine.run)
    phases["startup"]["worker"] = memory["startup"][0]
    phases["fsrcnn"]["worker"] = memory["requests"][attempt]
    with phase(phases, "metrics"):
        learned = decode_png(learned_png, target, RESPONSE_INVALID)
        source_grid = fit_set_plate(rgb, (target[0] // 2, target[1] // 2)) if plate else rgb
        objective = _measure(source_grid, baseline, learned, rois, reference)
    summary = {
        "source": source_facts,
        "normalized_source": value["request"]["source"],
        "outputs": {"lanczos": describe(baseline_png, target), "fsrcnn": receipt["output"]},
        "profile_sha256": receipt["provenance"]["profile_sha256"],
        "receipt_sha256": sha256(canonical_json(receipt)).hexdigest(),
        "memory_by_phase": phases,
        "objective_measures": objective,
    }
    if reference_facts is not None:
        summary["reference"] = reference_facts
        summary["normalized_reference"] = describe(decoded["master"], target)
        summary["delivery_id"] = delivery_id
        summary["pairing_verification"] = PAIRING_VERIFICATION
        summary["ground_truth_scope"] = GROUND_TRUTH_SCOPE
    report = {"schema": "studio.upscaling-comparison/v1", **summary, "plate": plate,
              "rois_xyxy": rois, "receipt": receipt, "review": "comparison pending"}
    summary["whole_job_cgroup_peak_bytes"] = _publish(
        output, {**decoded, "lanczos": baseline_png, "fsrcnn": learned_png}, report,
    )
    return summary
