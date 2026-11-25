"""Source decoding, straight-alpha decontamination and PNG checks."""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from struct import unpack_from

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt

from .profile import (
    ALPHA_THRESHOLD, BACKING_DISTANCE, DIM, FAINT_MAX, INTERIOR_DISTANCE, OPAQUE,
    PNG_COMPRESSION, REQUEST_INVALID, RESPONSE_INVALID, UNMIX_FLOOR, MatteError,
)

MAX_SOURCE_BYTES = 20 * 1024**2
MODES = {"cutout": "RGBA", "mask": "L"}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def decode_source(data: bytes, source: dict) -> Image.Image:
    if len(data) != source["bytes"] or sha256(data).hexdigest() != source["sha256"]:
        raise MatteError(REQUEST_INVALID)
    if source["media_type"] == "image/png" and (
        not data.startswith(PNG_SIGNATURE) or data[8:16] != b"\x00\x00\x00\x0dIHDR"
        or data[24:26] != b"\x08\x02"
    ):
        # Pillow exposes RGB16 PNGs as RGB after narrowing the samples.
        # IHDR must declare 8-bit truecolour before decoding.
        raise MatteError(REQUEST_INVALID)
    formats = {"image/jpeg": "JPEG", "image/png": "PNG"}
    try:
        with Image.open(BytesIO(data), formats=[formats[source["media_type"]]]) as image:
            if (image.mode != "RGB" or getattr(image, "n_frames", 1) != 1
                    or image.size != (source["width"], source["height"])
                    or "icc_profile" in image.info or "transparency" in image.info
                    or image.getexif().get(274, 1) != 1):
                raise MatteError(REQUEST_INVALID)
            image.load()
            return image.copy()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Warning) as error:
        raise MatteError(REQUEST_INVALID) from error


def linear_srgb(byte_values: np.ndarray) -> np.ndarray:
    values = byte_values / 255
    return np.where(values <= 0.04045, values / 12.92, ((values + 0.055) / 1.055) ** 2.4)


def srgb_bytes(linear: np.ndarray) -> np.ndarray:
    linear = np.clip(linear, 0, 1)
    values = np.where(linear <= 0.0031308, linear * 12.92, 1.055 * linear**(1 / 2.4) - 0.055)
    return np.floor(values * 255 + 0.5).astype(np.uint8)


def _remove_backing(rgb: np.ndarray, alpha: np.ndarray, backing: list[int]) -> None:
    foreground = alpha >= ALPHA_THRESHOLD
    near_edge = distance_transform_edt(foreground) <= INTERIOR_DISTANCE
    fractional = (alpha > 0) & (alpha < OPAQUE) & near_edge

    low = fractional & (alpha <= FAINT_MAX)
    distances_squared = np.square(rgb[low].astype(np.int32) - backing).sum(axis=1)
    alpha[low] = np.where(distances_squared <= BACKING_DISTANCE**2, 0, alpha[low])

    unmix = fractional & (alpha > 0)
    coverage = np.maximum(alpha[unmix], UNMIX_FLOOR)[:, None] / 255
    colour = linear_srgb(rgb[unmix])
    background = linear_srgb(np.asarray(backing))
    rgb[unmix] = srgb_bytes((colour - (1 - coverage) * background) / coverage)


def matte_pixels(image: Image.Image, continuous: np.ndarray, backing: list[int] | None) -> np.ndarray:
    if (continuous.shape != (DIM, DIM) or continuous.dtype != np.float32
            or not np.isfinite(continuous).all()):
        raise MatteError(RESPONSE_INVALID)
    resized = Image.fromarray(continuous).resize(image.size, Image.Resampling.BILINEAR)
    alpha = np.floor(np.clip(np.asarray(resized), 0, 1).astype(np.float64) * 255 + 0.5)
    alpha = alpha.astype(np.uint8)
    rgb = np.array(image)
    if backing is not None and np.any(alpha < ALPHA_THRESHOLD):
        _remove_backing(rgb, alpha, backing)
    rgb[alpha == 0] = 0
    return np.dstack((rgb, alpha))


def measure_shape(alpha: np.ndarray, target: int | None) -> dict:
    foreground = alpha >= ALPHA_THRESHOLD
    rows = np.flatnonzero(foreground.any(axis=1))
    if not rows.size or foreground.all():
        raise MatteError(RESPONSE_INVALID)
    columns = np.flatnonzero(foreground.any(axis=0))
    top, bottom = int(rows[0]), int(rows[-1]) + 1
    height = bottom - top
    return {
        "bbox_xyxy": [int(columns[0]), top, int(columns[-1]) + 1, bottom],
        "bbox_height_px": height,
        "foreground_area_px": int(foreground.sum()),
        "alpha_threshold": ALPHA_THRESHOLD,
        "scale": {"numerator": target, "denominator": height} if target is not None else {
            "numerator": 1, "denominator": 1,
        },
    }


def encode_png(pixels: np.ndarray) -> bytes:
    with BytesIO() as buffer:
        Image.fromarray(pixels).save(buffer, "PNG", compress_level=PNG_COMPRESSION, optimize=False)
        return buffer.getvalue()


def describe_png(data: bytes, mode: str, size: tuple[int, int]) -> tuple[dict, np.ndarray]:
    _check_png_chunks(data)
    try:
        with Image.open(BytesIO(data), formats=["PNG"]) as image:
            if image.mode != mode or image.size != size or getattr(image, "n_frames", 1) != 1 or image.info:
                raise MatteError(RESPONSE_INVALID)
            pixels = np.array(image)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Warning) as error:
        raise MatteError(RESPONSE_INVALID) from error
    return ({
        "sha256": sha256(data).hexdigest(), "bytes": len(data), "media_type": "image/png",
        "width": size[0], "height": size[1],
    }, pixels)


def _check_png_chunks(data: bytes) -> None:
    if not data.startswith(PNG_SIGNATURE):
        raise MatteError(RESPONSE_INVALID)
    offset = len(PNG_SIGNATURE)
    while offset + 12 <= len(data):
        length, kind = unpack_from(">I4s", data, offset)
        offset += 12 + length  # length, type, data, CRC
        if kind == b"IEND" and length == 0 and offset == len(data):
            return
        if kind not in (b"IHDR", b"IDAT"):
            break
    raise MatteError(RESPONSE_INVALID)
