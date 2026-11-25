"""The single admitted still-matting profile and its immutable startup pins."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path

from haynes_studio.store import canonical_json

PROFILE_ID = "birefnet-lite-ort-cpu-v1"
MODEL = "onnx-community/BiRefNet_lite-ONNX"
SOURCE_REVISION = "de15b22ba131738a16dff04aab8bdf8dc32e3ac1"
GRAPH_NAME = "model.onnx"
GRAPH_BYTES = 224_005_088
GRAPH_SHA256 = "5600024376f572a557870a5eb0afb1e5961636bef4e1e22132025467d0f03333"
WHEEL_NAME = "onnxruntime-1.32.0-cp312-cp312-manylinux_2_28_x86_64.whl"
WHEEL_SHA256 = "99e1074c4b2197accd5073052a465361be17b89c093b8ffb6e6bd8f986c52df8"
RUNTIME_VERSION = "1.32.0"
PROVIDER = "CPUExecutionProvider"
IMAGE_REPOSITORY = "ghcr.io/thaynes43/haynes-studio-matting"
DIM = 1024
INPUT_NAME = "input_image"
OUTPUT_NAME = "output_image"
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)
ALPHA_THRESHOLD = 128
OPAQUE = 243
INTERIOR_DISTANCE = 4
FAINT_MAX = 20
BACKING_DISTANCE = 3
UNMIX_FLOOR = 21
PNG_COMPRESSION = 6
STARTUP_SECONDS = 120
REQUEST_SECONDS = 30
MEMORY_RESOURCES = json.loads(files(__package__).joinpath("resources.json").read_text(encoding="utf-8"))
MEMORY_LIMIT_BYTES = MEMORY_RESOURCES["limit_gib"] * 1024**3

REQUEST_INVALID = "adapter.request_invalid"
PIN_MISMATCH = "adapter.pin_mismatch"
TIMEOUT = "adapter.timeout"
RESPONSE_INVALID = "adapter.response_invalid"
COMMAND_FAILED = "adapter.command_failed"
NOT_FOUND = "adapter.not_found"
BUSY = "adapter.busy"


class MatteError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class SessionSettings:
    cpu_arena: bool = False
    memory_pattern: bool = True
    graph_optimization: str = "all"
    arena_growth: str = "default"
    shrink_cpu_arena: bool = False


@dataclass(frozen=True)
class Profile:
    image_digest: str
    app_build: str
    graph_bytes: int = GRAPH_BYTES
    graph_sha256: str = GRAPH_SHA256
    session: SessionSettings = SessionSettings()

    @classmethod
    def installed(cls) -> Profile:
        image = os.environ.get("STUDIO_MATTING_IMAGE", "")
        build = os.environ.get("STUDIO_MATTING_REVISION", "")
        if (not re.fullmatch(re.escape(IMAGE_REPOSITORY) + r"@sha256:[a-f0-9]{64}", image)
                or image.endswith("sha256:" + "0" * 64)):
            raise MatteError(PIN_MISMATCH)
        if not re.fullmatch(r"[a-f0-9]{40}", build):
            raise MatteError(PIN_MISMATCH)
        return cls(image.split("@", 1)[1], build)

    def provenance(self) -> dict:
        return {
            "model": MODEL,
            "source_revision": SOURCE_REVISION,
            "files_sha256": {GRAPH_NAME: self.graph_sha256},
            "runtime": {
                "name": "onnxruntime", "version": RUNTIME_VERSION,
                "wheel_sha256": WHEEL_SHA256,
            },
            "provider": PROVIDER,
            "image_digest": self.image_digest,
            "parameters": {
                "input": {
                    "name": INPUT_NAME, "dtype": "float32", "layout": "NCHW",
                    "shape": [1, 3, DIM, DIM], "resize": "bilinear",
                    "divisor": 255, "mean": list(MEAN), "std": list(STD),
                },
                "alpha": {
                    "name": OUTPUT_NAME, "shape": [1, 1, DIM, DIM],
                    "transform": "sigmoid", "resize": "bilinear",
                    "quantization": "floor(clamp(alpha,0,1)*255+0.5)",
                    "threshold": ALPHA_THRESHOLD, "opaque": OPAQUE,
                    "interior_distance_px": INTERIOR_DISTANCE, "faint_max": FAINT_MAX,
                    "backing_distance_srgb": BACKING_DISTANCE,
                    "unmix_alpha_floor": UNMIX_FLOOR, "unmix_space": "linear-srgb",
                },
                "png": {
                    "cutout_mode": "RGBA", "mask_mode": "L", "alpha": "straight",
                    "compression": PNG_COMPRESSION, "optimize": False, "metadata": False,
                },
                "libraries": {name: version(name) for name in ("numpy", "pillow", "scipy")},
                "session": {
                    "execution": "sequential", "intra_op_threads": 2,
                    "inter_op_threads": 1, "spinning": False, "in_flight": 1,
                    "startup_seconds": STARTUP_SECONDS, "request_seconds": REQUEST_SECONDS,
                    **asdict(self.session),
                },
            },
        }

    def manifest(self) -> bytes:
        return canonical_json({
            "profile_id": PROFILE_ID,
            "app_build": self.app_build,
            "graph_bytes": self.graph_bytes,
            "runtime_wheel": WHEEL_NAME,
            "memory": MEMORY_RESOURCES,
            **self.provenance(),
        })

    def verify(self, weights: Path) -> tuple[str, bytes]:
        expected = self.manifest()
        digest = hashlib.sha256(expected).hexdigest()
        try:
            with (weights / "profile.json").open("rb") as source:
                manifest = source.read(len(expected) + 1)
            with (weights / "profile.sha256").open("rb") as source:
                pin = source.read(66)
            if manifest != expected or pin != (digest + "\n").encode("ascii"):
                raise MatteError(PIN_MISMATCH)
            with (weights / GRAPH_NAME).open("rb") as source:
                model = source.read(self.graph_bytes + 1)
        except FileNotFoundError as error:
            raise MatteError(NOT_FOUND) from error
        except OSError as error:
            raise MatteError(COMMAND_FAILED) from error
        if len(model) != self.graph_bytes or hashlib.sha256(model).hexdigest() != self.graph_sha256:
            raise MatteError(PIN_MISMATCH)
        return digest, model
