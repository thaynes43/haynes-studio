"""The delivery conversion profile (TIME-7, TIME-8 and TIME-11).

Generated picture is converted on the board clock before segment encoding. The
profile is recorded by hash in the segment key and by value in run provenance.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, __version__ as pillow_version

from haynes_studio.render.clock import S2V_SOURCE_FPS
from haynes_studio.store import canonical_json
from haynes_studio.timebase import DELIVERY_FPS, MIX_RATE, SAMPLES_PER_FRAME, SAMPLES_PER_MS

VERSION = "studio.delivery-conversion/v1"
LANCZOS = "lanczos"


@dataclass(frozen=True)
class DeliveryUpscalerProfile:
    """A pinned resize backend. An installed model can supply its implementation
    here, along with its own version and tool and weight digests."""

    name: str
    version: int
    tool: str
    tool_sha256: str
    model_sha256: str | None
    resize: Callable[[Image.Image, tuple[int, int]], Image.Image]

    def scale(self, image: Image.Image, size: tuple[int, int]) -> Image.Image:
        """Scale a generated frame to the board size, keeping its exact aspect."""
        return self.resize(image, size) if needs_scaling(image.size, size) else image


def needs_scaling(source: tuple[int, int], target: tuple[int, int]) -> bool:
    sw, sh = source
    tw, th = target
    if sw * th != sh * tw:
        raise ValueError(f"{sw}x{sh} and {tw}x{th} have different aspects")
    return source != target


def _lanczos(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return image.resize(size, Image.Resampling.LANCZOS)


def fit_set_plate(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Still plates keep the compositor's centred cover fit with Lanczos."""
    return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS)


@cache
def _baseline() -> DeliveryUpscalerProfile:
    # Hash the loaded native Pillow core that performs the resampling.
    with Path(Image.core.__file__).open("rb") as core:
        tool_sha256 = hashlib.file_digest(core, "sha256").hexdigest()
    return DeliveryUpscalerProfile(
        name=LANCZOS, version=1, tool=f"Pillow {pillow_version}", tool_sha256=tool_sha256,
        model_sha256=None, resize=_lanczos,
    )


def _document() -> dict[str, Any]:
    upscaler = _baseline()
    return {
        "version": VERSION,
        "timing": {
            "delivery_fps": DELIVERY_FPS, "s2v_source_fps": S2V_SOURCE_FPS,
            "source_selection": "floor(n * source_fps / delivery_fps)",
            "extra_source_frames": "trim", "short_source": "fail",
            "mix_rate_hz": MIX_RATE, "mix_samples_per_frame": SAMPLES_PER_FRAME,
            "mix_samples_per_ms": SAMPLES_PER_MS,
        },
        "scaling": {
            "target": "segment frame size", "same_size": "identity",
            "aspect_mismatch": "fail", "set_plate_fit": "centred Lanczos cover",
            "upscaler": {
                "name": upscaler.name, "version": upscaler.version, "tool": upscaler.tool,
                "tool_sha256": upscaler.tool_sha256, "model_sha256": upscaler.model_sha256,
            },
        },
    }


@cache
def delivery_profile_sha256() -> str:
    return hashlib.sha256(canonical_json(_document())).hexdigest()


def delivery_profile_record() -> dict[str, Any]:
    return {**_document(), "sha256": delivery_profile_sha256()}


def resolve_delivery_upscaler(profile_sha256: str | None) -> DeliveryUpscalerProfile:
    """Resolve the backend named by the profile hash. An old segment key without
    a profile used this same Lanczos baseline."""
    if profile_sha256 is not None and profile_sha256 != delivery_profile_sha256():
        raise ValueError(f"unknown delivery conversion profile {profile_sha256!r}")
    return _baseline()
