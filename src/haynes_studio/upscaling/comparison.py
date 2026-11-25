"""Compare the two scalers on one authorized still in a new private jobs directory."""

from contextlib import ExitStack
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path, PurePosixPath
import re
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image

from haynes_studio.store import canonical_json

from .backend import DIGEST, Engine
from .files import create_file, open_directory, read_file
from .fixtures import luma
from .observe import cgroup_peak, phase
from .pixels import crop_plate, decode_png, describe, encode_png, fits, lanczos
from .profile import (
    MAX_INPUT, MAX_LONG_EDGE, MAX_OUTPUT, MAX_PIXELS, PIN_MISMATCH, REQUEST_INVALID, RESPONSE_INVALID, UpscaleError,
)
from .service import listening, local_call
from .trial import frame

RUN = re.compile(r"upscaling-op461-compare-[a-f0-9]{12}")
RESERVE = 32 * 1024**3
BUDGET = 8 * 1024**3


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


def _measure(rgb, baseline, learned, rois):
    reference = luma(rgb)
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
    delta = np.abs(luma(baseline) - luma(learned))
    comparison["pair"] = {
        "luma_mae": float(delta.mean() / 255), "luma_p95": float(np.percentile(delta, 95) / 255),
        "roi_luma_mae": {name: float(delta[y0:y1, x0:x1].mean() / 255)
                         for name, (x0, y0, x1, y1) in rois.items()},
    }
    return comparison


def _publish(jobs: Path, allocation: str, pngs: dict, report: dict) -> int | None:
    with open_directory(jobs) as root:
        space = os.fstatvfs(root)
        if space.f_bavail * space.f_frsize < RESERVE + BUDGET:
            raise UpscaleError(REQUEST_INVALID)
        os.mkdir(allocation, mode=0o750, dir_fd=root)
        os.fsync(root)
        with open_directory(allocation, dir_fd=root) as output:
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


def compare(scratch: Path, weights: Path, share: Path, jobs: Path, profile, *,
            relative: str, source_sha256: str, allocation: str, target, plate=False, rois=None, factory=None) -> dict:
    if not RUN.fullmatch(allocation) or not DIGEST.fullmatch(source_sha256):
        raise UpscaleError(REQUEST_INVALID)
    rois = rois or {}
    for name, (x0, y0, x1, y1) in rois.items():
        if (name not in {"lettering", "hair", "face"}
                or not 0 <= x0 < x1 <= target[0] or x1 - x0 < 2
                or not 0 <= y0 < y1 <= target[1] or y1 - y0 < 2):
            raise UpscaleError(REQUEST_INVALID)
    phases, memory = {}, {}
    with phase(phases, "read_normalize"):
        data = _source(share, relative)
        if sha256(data).hexdigest() != source_sha256:
            raise UpscaleError(PIN_MISMATCH)
        rgb = _decode(data)
        original_size = rgb.size
        crop = None
        if plate:
            rgb, crop = crop_plate(rgb, target)
        if not fits(rgb.size, target):
            raise UpscaleError(REQUEST_INVALID)
        normalized = describe(encode_png(rgb), rgb.size)
    with phase(phases, "lanczos"):
        baseline = lanczos(rgb, target)
        baseline_png = encode_png(baseline)
        if len(baseline_png) > MAX_OUTPUT:
            raise UpscaleError(RESPONSE_INVALID)
        decode_png(baseline_png, target, RESPONSE_INVALID)
    with TemporaryDirectory(prefix="compare-", dir=scratch) as work:
        root = Path(work)
        socket = root / "upscale.sock"
        with phase(phases, "startup"):
            engine = Engine(root, weights, profile, memory=memory, factory=factory)
        with engine, listening(socket, engine):
            status, ready = local_call(socket, "GET", "/v1/ready")
            if status != 200:
                raise UpscaleError(PIN_MISMATCH)
            with phase(phases, "fsrcnn"):
                learned_png, receipt, attempt = frame(
                    root, socket, rgb, target, engine.profile, ready["profile_sha256"],
                )
    phases["startup"]["worker"] = memory["startup"][0]
    phases["fsrcnn"]["worker"] = memory["requests"][attempt]
    with phase(phases, "metrics"):
        learned = decode_png(learned_png, target, RESPONSE_INVALID)
        objective = _measure(rgb, baseline, learned, rois)
    summary = {
        "source": {"sha256": source_sha256, "bytes": len(data), "size": list(original_size)},
        "normalized_source": normalized,
        "outputs": {"lanczos": describe(baseline_png, target), "fsrcnn": receipt["output"]},
        "profile_sha256": receipt["provenance"]["profile_sha256"],
        "receipt_sha256": sha256(canonical_json(receipt)).hexdigest(),
        "memory_by_phase": phases,
        "objective_measures": objective,
    }
    report = {"schema": "studio.upscaling-comparison/v1", **summary, "crop_xyxy": crop,
              "rois_xyxy": rois, "receipt": receipt, "review": "comparison pending"}
    summary["whole_job_cgroup_peak_bytes"] = _publish(
        jobs, allocation, {"lanczos": baseline_png, "fsrcnn": learned_png}, report,
    )
    return summary
