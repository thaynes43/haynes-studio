"""Immutable image, graph, CPU and artifact pins for the comparison worker."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from hashlib import file_digest, sha1, sha256
from importlib import import_module
from importlib.metadata import PackageNotFoundError, distribution, version
from importlib.resources import files
from pathlib import Path

from haynes_studio.store import canonical_json

PROFILE_ID = "fsrcnn-x2-opencv-cpu-v1"
IMAGE_REPOSITORY = "ghcr.io/thaynes43/haynes-studio-upscaling"
REPOSITORY = "Saafke/FSRCNN_Tensorflow"
REVISION = "6a4812c4ef1c4f5947d79beafa32a05a6eb4a94d"
GRAPH_NAME = "FSRCNN_x2.pb"
GRAPH_BYTES = 38_973
GRAPH_BLOB = "2509b0e19b8a45ebce2ba50128e2fcb43ce8589c"
GRAPH_SHA256 = "366b33f0084c7b3f2bf6724f0a2c77bca94fcec9d7b6d72389d330073b380d5c"
WHEELS = {
    "opencv-contrib-python-headless": (
        "4.14.0.94", "opencv_contrib_python_headless-4.14.0.94-cp37-abi3-manylinux_2_28_x86_64.whl",
        "3ee9718fc1eb2d4439c72ec6ad65831ff6d0802ff6eacab834905d67686f2a38",
    ),
    "pillow": (
        "13.0.0", "pillow-13.0.0-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl",
        "42d63be3af4f9b951b199b0a9d23365d37ab14687e6d77b74940432c8515c4ca",
    ),
    "numpy": (
        "2.4.6", "numpy-2.4.6-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl",
        "90f9849678c75fe7afa2d348ac842c168b0a4d3d61919687216dfc547976d853",
    ),
}
MAX_INPUT = 4 * 1024**2
MAX_OUTPUT = 8 * 1024**2
MAX_LONG_EDGE = 1280
MAX_PIXELS = 921_600
TARGETS = ((1080, 1920), (1920, 1080))
STARTUP_SECONDS = 30
REQUEST_SECONDS = 5
CLIP_SECONDS = 300
THREADS = 2
PROVIDER = "opencv-dnn-cpu-fp32"
SETTINGS = {
    "default": "",
    "compact-allocator": (
        "glibc.malloc.arena_max=1:glibc.malloc.trim_threshold=131072:glibc.malloc.mmap_threshold=131072"
    ),
}
THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "OPENCV_FOR_THREADS_NUM": str(THREADS), "OPENCV_OPENCL_RUNTIME": "disabled",
    "OPENCV_LOG_LEVEL": "SILENT",
}
RESOURCES = json.loads(files(__package__).joinpath("resources.json").read_text(encoding="utf-8"))

REQUEST_INVALID = "adapter.request_invalid"
PIN_MISMATCH = "adapter.pin_mismatch"
TIMEOUT = "adapter.timeout"
RESPONSE_INVALID = "adapter.response_invalid"
COMMAND_FAILED = "adapter.command_failed"
NOT_FOUND = "adapter.not_found"
BUSY = "adapter.busy"


class UpscaleError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def digest_path(path: Path) -> str:
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def cpu_facts(cv2) -> dict:
    cpu_models = {
        line.partition(":")[2].strip()
        for line in Path("/proc/cpuinfo").read_text().splitlines()
        if line.partition(":")[0].strip() == "model name"
    }
    features = cv2.getCPUFeaturesLine()
    if len(cpu_models) != 1 or not features:
        raise UpscaleError(PIN_MISMATCH)
    return {
        "model": cpu_models.pop(), "opencv_features": features,
        "disabled_features": os.environ.get("OPENCV_CPU_DISABLE", ""),
    }


def native_hashes(cv2) -> dict:
    # cv2's module filename is its Python bootstrap. The cv2 wheel has one extension.
    cv2_binary, = Path(cv2.__file__).parent.glob("cv2*.so")
    return {
        "opencv": digest_path(cv2_binary),
        "pillow": digest_path(Path(import_module("PIL._imaging").__file__)),
        "numpy": digest_path(Path(import_module("numpy._core._multiarray_umath").__file__)),
    }


def runtime_identity() -> bytes:
    cv2 = import_module("cv2")
    try:
        # The production and contrib wheels both install the cv2 namespace.
        for name in ("opencv-python", "opencv-python-headless", "opencv-contrib-python"):
            try:
                distribution(name)
            except PackageNotFoundError:
                continue
            raise UpscaleError(PIN_MISMATCH)
        if (cv2.__version__ != "4.14.0"
                or any(version(name) != pin[0] for name, pin in WHEELS.items())
                or os.environ.get("OPENCV_CPU_DISABLE", "")
                or any(os.environ.get(key) != value for key, value in THREAD_ENV.items())):
            raise UpscaleError(PIN_MISMATCH)
        return canonical_json({"cpu": cpu_facts(cv2), "native_sha256": native_hashes(cv2)})
    except (OSError, ValueError, PackageNotFoundError) as error:
        raise UpscaleError(PIN_MISMATCH) from error


@dataclass(frozen=True)
class Profile:
    image_digest: str
    app_build: str
    identity: bytes
    graph_bytes: int = GRAPH_BYTES
    graph_sha256: str = GRAPH_SHA256
    graph_blob: str = GRAPH_BLOB
    settings: str = "default"

    @classmethod
    def installed(cls) -> Profile:
        image = os.environ.get("STUDIO_UPSCALING_IMAGE", "")
        build = os.environ.get("STUDIO_UPSCALING_REVISION", "")
        if (not re.fullmatch(re.escape(IMAGE_REPOSITORY) + r"@sha256:[a-f0-9]{64}", image)
                or image.endswith("sha256:" + "0" * 64)
                or not re.fullmatch(r"[a-f0-9]{40}", build)
                or os.environ.get("GLIBC_TUNABLES", "")):
            raise UpscaleError(PIN_MISMATCH)
        return cls(image.split("@", 1)[1], build, runtime_identity())

    def document(self) -> dict:
        adapter = {name: digest_path(Path(__file__).with_name(name)) for name in (
            "backend.py", "files.py", "opencv.py", "pixels.py", "profile.py", "service.py",
        )}
        adapter["delivery_profile.py"] = digest_path(Path(__file__).parent.parent / "render/delivery_profile.py")
        return {
            "profile_id": PROFILE_ID, "image_digest": self.image_digest, "app_build": self.app_build,
            "model": {"repository": REPOSITORY, "revision": REVISION, "path": f"models/{GRAPH_NAME}",
                      "bytes": self.graph_bytes, "sha256": self.graph_sha256, "git_blob": self.graph_blob},
            "wheels": {name: {"version": v, "filename": filename, "sha256": h}
                       for name, (v, filename, h) in WHEELS.items()},
            **json.loads(self.identity),
            "adapter_sha256": adapter,
            "runtime": {"provider": PROVIDER, "backend": "DNN_BACKEND_OPENCV", "target": "DNN_TARGET_CPU",
                        "tensor": "FP32 1x1xHxW luma", "opencv_threads": THREADS, "pool_env": THREAD_ENV,
                        "opencl": False, "allocator": self.settings, "glibc_tunables": SETTINGS[self.settings]},
            "resize": {"algorithm": "fsrcnn", "scale": 2, "input": "RGB8 to BGR8",
                       "output": "BGR8 to RGB8", "chroma": "OpenCV YCrCb linear",
                       "tiles": "whole-frame", "overlap_px": 0, "fit": "exact-aspect center crop upstream",
                       "plate_comparison_fit": "centered cover after inference, one-shot comparison only",
                       "final_resize": "Pillow Lanczos", "targets": [list(size) for size in TARGETS]},
            "png": {"mode": "RGB8", "compress_level": 1, "optimize": False, "metadata": False},
            "limits": {"input_bytes": MAX_INPUT, "output_bytes": MAX_OUTPUT, "input_pixels": MAX_PIXELS,
                       "input_long_edge": MAX_LONG_EDGE, "startup_seconds": STARTUP_SECONDS,
                       "request_seconds": REQUEST_SECONDS, "clip_seconds": CLIP_SECONDS, "in_flight": 1},
            "memory": RESOURCES,
        }

    def manifest(self) -> bytes:
        return canonical_json(self.document())

    def verify(self, weights: Path) -> tuple[str, bytes]:
        from .files import read_file, open_directory

        expected = self.manifest()
        digest = sha256(expected).hexdigest()
        try:
            with open_directory(weights) as directory:
                manifest = read_file(directory, "profile.json", len(expected), PIN_MISMATCH)
                pin = read_file(directory, "profile.sha256", 65, PIN_MISMATCH)
                model = read_file(directory, GRAPH_NAME, self.graph_bytes, PIN_MISMATCH)
        except FileNotFoundError as error:
            raise UpscaleError(NOT_FOUND) from error
        except OSError as error:
            raise UpscaleError(PIN_MISMATCH) from error
        blob = sha1(b"blob " + str(len(model)).encode() + b"\0" + model, usedforsecurity=False).hexdigest()
        if (manifest != expected or pin != (digest + "\n").encode("ascii")
                or len(model) != self.graph_bytes or sha256(model).hexdigest() != self.graph_sha256
                or blob != self.graph_blob):
            raise UpscaleError(PIN_MISMATCH)
        return digest, model
