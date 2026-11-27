"""Identity and verification for the two-model offline CPU profile."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from functools import cache
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path

from haynes_studio.jsonio import parse_strict
from haynes_studio.store import canonical_json

# The v1 wire schemas pin this selector. The immutable manifest identifies the
# serving revision, and its digest binds each receipt to that revision.
PROFILE_ID = "grounding-dino-tiny-sam2.1-tiny-cpu-v1"
SERVING_PROFILE_ID = "grounding-dino-tiny-sam2.1-tiny-cpu-v2"
FALLBACK_ID = "owlv2-base-sam2.1-tiny-cpu-v1"
IMAGE = "ghcr.io/thaynes43/haynes-studio-segmentation"
SCRATCH = Path("/segmentation")
WEIGHTS = Path("/opt/studio-models")
LOCK = Path("/opt/studio/segmentation-runtime.txt")
STARTUP_SECONDS = 60
REQUEST_SECONDS = 60
MAX_SOURCE_BYTES = 8 * 1024**2
MAX_PIXELS = 2_073_600
MAX_SIDE = 1920
MAX_SHORT_SIDE = 1080
RUNTIME_PINS = {
    "torch": ("2.14.1+cpu", "5a6363570c753812540a05eb82380e329469cbe668643e88111414c12627711f"),
    "torchvision": ("0.29.1+cpu", "ef220d4b21878c58947851beb7337382897159105f012f0c9c07bf7e84174d7e"),
    "transformers": ("5.24.1", "505b39d3e45a3715f3acb81b858eb245ce1a462373b7f99e26f0dcd41ed4cd0f"),
    "safetensors": ("0.8.0", "fd6f3f93c9a0a7cc2788ee63fb763353d4bd2e89b0751bc78fcf7dda00bea774"),
    "pillow": ("13.0.0", "42d63be3af4f9b951b199b0a9d23365d37ab14687e6d77b74940432c8515c4ca"),
}
RESOURCES = json.loads(files(__package__).joinpath("resources.json").read_text(encoding="utf-8"))
WEIGHT_LOAD = RESOURCES["serving"]["weight_load"]
MODEL_DIRS = ("dino", "sam")

DETECTOR_FLOOR = 0.35
TEXT_FLOOR = 0.25
NMS_IOU = 0.50
SCORE_LEAD = 0.10
MIN_MODEL_PIXELS = 16
MASK_FLOOR = 0.80
MASK_SCORE_GAP = 0.05
MASK_AGREEMENT = 0.85
BOTTOM_COVERAGE = 0.10
GRAY = 128
MAX_TOKENS = 256
PNG_COMPRESSION = 6
FOREGROUND_QUERY = "table. lectern. chair back."

THREAD_ENV = {
    "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1", "TOKENIZERS_PARALLELISM": "false",
    "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_XET": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
    "CUDA_VISIBLE_DEVICES": "",
}


class SegmentationError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@cache
def _model_files() -> tuple[dict, ...]:
    source = files("haynes_studio").joinpath("model_licences.json").read_bytes()
    record = json.loads(source)["proposals"]["segmentation"]
    selected = next(profile for profile in record["profiles"] if profile["key"] == PROFILE_ID)
    models = {model["key"]: model for model in record["models"]}
    entries = []
    for directory, key in zip(MODEL_DIRS, selected["models"], strict=True):
        model = models[key]
        weight = model["weight"]
        entries.append({
            "directory": directory,
            "repository": model["repository"],
            "revision": model["source_revision"],
            "files": [
                {"name": weight["name"], "size_bytes": weight["size_bytes"], "sha256": weight["published_sha256"]},
                *model["auxiliary"],
            ],
        })
    if sum(item["size_bytes"] for model in entries for item in model["files"]) != selected["download_bytes"]:
        raise SegmentationError("profile_unavailable")
    return tuple(entries)


def parameters() -> dict:
    return {
        "dtype": "float32", "execution": "eager", "batch": 1,
        "threads": {"intra_op": 2, "inter_op": 1, **THREAD_ENV}, "in_flight": 1,
        "weight_load": WEIGHT_LOAD, "startup_seconds": STARTUP_SECONDS, "request_seconds": REQUEST_SECONDS,
        "detector": {
            "short_edge": 800, "long_edge": 1333, "padding": "batch_max_bottom_right",
            "custom_kernels": False, "max_tokens": MAX_TOKENS, "score_floor": DETECTOR_FLOOR,
            "text_floor": TEXT_FLOOR, "nms_iou": NMS_IOU, "score_lead": SCORE_LEAD,
            "min_model_pixels": MIN_MODEL_PIXELS, "foreground_query": FOREGROUND_QUERY,
        },
        "segmenter": {
            "size": [1024, 1024], "padding": "none", "resize_logits": "bilinear",
            "logit_threshold": 0, "score_floor": MASK_FLOOR, "score_gap": MASK_SCORE_GAP,
            "mask_agreement_iou": MASK_AGREEMENT, "bottom_coverage": BOTTOM_COVERAGE,
        },
        "cutout": {"gray_srgb": GRAY, "restrict_to_nonzero_alpha": True},
        "png": {"mode": "L", "metadata": False, "compression": PNG_COMPRESSION},
    }


@dataclass(frozen=True)
class Profile:
    image_digest: str
    revision: str
    lock_sha256: str
    libraries: tuple[tuple[str, str], ...]

    @classmethod
    def installed(cls) -> Profile:
        image = os.environ.get("STUDIO_SEGMENTATION_IMAGE", "")
        revision = os.environ.get("STUDIO_SEGMENTATION_REVISION", "")
        if (not re.fullmatch(re.escape(IMAGE) + r"@sha256:[a-f0-9]{64}", image)
                or image.endswith("sha256:" + "0" * 64) or not re.fullmatch(r"[a-f0-9]{40}", revision)):
            raise SegmentationError("profile_unavailable")
        try:
            requirements = LOCK.read_bytes()
            libraries = tuple((name, version(name)) for name in (*RUNTIME_PINS, "numpy", "tokenizers"))
            for name, installed_version in libraries:
                if name in RUNTIME_PINS:
                    pinned, wheel_hash = RUNTIME_PINS[name]
                    if installed_version != pinned or wheel_hash.encode() not in requirements:
                        raise SegmentationError("profile_unavailable")
        except (OSError, ValueError) as error:
            raise SegmentationError("profile_unavailable") from error
        return cls(image.split("@", 1)[1], revision, digest(requirements), libraries)

    @classmethod
    def from_manifest(cls, document: dict) -> Profile:
        """Reconstruct the exact serving pin without importing models or reading weights."""
        try:
            runtime = document["runtime"]
            libraries = runtime["libraries"]
            profile = cls(document["image_digest"], document["app_build"], runtime["lock_sha256"],
                          tuple(sorted(libraries.items())))
            if (not re.fullmatch(r"sha256:[a-f0-9]{64}", profile.image_digest)
                    or not re.fullmatch(r"[a-f0-9]{40}", profile.revision)
                    or not re.fullmatch(r"[a-f0-9]{64}", profile.lock_sha256)
                    or any(not isinstance(value, str) or not value for value in libraries.values())
                    or profile.manifest() != canonical_json(document)):
                raise ValueError
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise SegmentationError("profile_unavailable") from error
        return profile

    @classmethod
    def configured(cls) -> Profile | None:
        path = os.getenv("STUDIO_SEGMENTATION_MANIFEST")
        pin = os.getenv("STUDIO_SEGMENTATION_PROFILE_SHA256")
        if path is None and pin is None:
            return None
        try:
            with Path(path).open("rb") as manifest:
                data = manifest.read(64 * 1024 + 1)
            if len(data) > 64 * 1024 or digest(data) != pin:
                raise ValueError
            profile = cls.from_manifest(parse_strict(data.decode("utf-8")))
            if profile.manifest() != data:
                raise ValueError
        except (OSError, TypeError, ValueError, RecursionError) as error:
            raise SegmentationError("profile_unavailable") from error
        return profile

    def model_files(self) -> tuple[dict, ...]:
        return _model_files()

    def runtime(self) -> dict:
        return {"lock_sha256": self.lock_sha256, "libraries": dict(self.libraries)}

    def manifest(self) -> bytes:
        return canonical_json({
            "schema": "studio.segmentation-profile/v1", "profile": SERVING_PROFILE_ID,
            "image_digest": self.image_digest, "app_build": self.revision,
            "models": self.model_files(), "runtime": self.runtime(), "device": "cpu",
            "parameters": parameters(), "resources": RESOURCES,
        })

    def provenance(self, executed: list[str], applied: dict) -> dict:
        manifest_hash = digest(self.manifest())
        return {
            "profile": {"id": PROFILE_ID, "sha256": manifest_hash}, "image_digest": self.image_digest,
            "runtime": self.runtime(), "device": "cpu",
            "models": [
                {
                    "repository": model["repository"], "revision": model["revision"],
                    "file": model["files"][0]["name"], "weight_sha256": model["files"][0]["sha256"],
                    "config_manifest_sha256": digest(canonical_json(model["files"][1:])),
                }
                for model in self.model_files() if model["directory"] in executed
            ],
            "parameters": {**parameters(), **applied},
        }

    def verify(self, root: Path) -> str:
        expected = self.manifest()
        pin = digest(expected)
        try:
            entries = {"profile.json", "profile.sha256", *MODEL_DIRS}
            if not stat.S_ISDIR(root.lstat().st_mode) or entries != set(os.listdir(root)):
                raise SegmentationError("profile_unavailable")
            for name, data in (("profile.json", expected), ("profile.sha256", (pin + "\n").encode())):
                hash_file(root / name, len(data), digest(data))
            for model in self.model_files():
                directory = root / model["directory"]
                if not stat.S_ISDIR(directory.lstat().st_mode):
                    raise SegmentationError("profile_unavailable")
                if set(os.listdir(directory)) != {entry["name"] for entry in model["files"]}:
                    raise SegmentationError("profile_unavailable")
                for entry in model["files"]:
                    hash_file(directory / entry["name"], entry["size_bytes"], entry["sha256"])
        except OSError as error:
            raise SegmentationError("profile_unavailable") from error
        return pin


def hash_file(path: Path, size: int, expected: str) -> None:
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as source:
        facts = os.fstat(source.fileno())
        if not stat.S_ISREG(facts.st_mode) or facts.st_nlink != 1 or facts.st_size != size:
            raise SegmentationError("profile_unavailable")
        hashed = hashlib.sha256()
        count = 0
        while block := source.read(min(1024**2, size - count + 1)):
            count += len(block)
            if count > size:
                raise SegmentationError("profile_unavailable")
            hashed.update(block)
        if count != size or hashed.hexdigest() != expected:
            raise SegmentationError("profile_unavailable")
