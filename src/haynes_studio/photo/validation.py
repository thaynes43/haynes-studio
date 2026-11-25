"""Bounded decoding and metadata-free PNG encoding for board photos."""
from __future__ import annotations

import hashlib
import io
import re
import struct
from collections.abc import Iterable
from dataclasses import dataclass, field
from math import isqrt

from PIL import Image, ImageOps

from haynes_studio.errors import ContractError, Violation
from haynes_studio.photo_limits import MAX_UPLOAD_BYTES

PNG = "image/png"
IMAGE_TYPES = {PNG: "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}
MAX_SIDE = 4096
HEX_SHA256 = re.compile(r"[0-9a-f]{64}")
INVALID_IMAGE = "photo.image_invalid"
HASH_MISMATCH = "photo.hash_mismatch"
TOO_LARGE = "photo.too_large"


def error(rule: str, path: str, message: str, status: str = "invalid") -> ContractError:
    return ContractError("<photo>", [Violation(rule, path, message, status)])


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_hash(value: str, path: str) -> None:
    if not isinstance(value, str) or not HEX_SHA256.fullmatch(value):
        raise error(HASH_MISMATCH, path, "expected a lowercase SHA-256 digest")


def verify_bytes(data: bytes, expected: str, path: str) -> str:
    check_hash(expected, path)
    if not isinstance(data, bytes) or sha256(data) != expected:
        raise error(HASH_MISMATCH, path, "the supplied bytes have another SHA-256 digest")
    return expected


def text_is_encodable(value: str) -> bool:
    return "\x00" not in value and all(not 0xD800 <= ord(char) <= 0xDFFF for char in value)


def decode(data: bytes, media_type: str, path: str) -> Image.Image:
    if not isinstance(media_type, str) or media_type not in IMAGE_TYPES:
        raise error(INVALID_IMAGE, path, "expected PNG, JPEG or WebP")
    if not isinstance(data, bytes) or not data:
        raise error(INVALID_IMAGE, path, "expected non-empty image bytes")
    formats = [IMAGE_TYPES[media_type]]
    try:
        with Image.open(io.BytesIO(data), formats=formats) as header:
            if not all(0 < side <= MAX_SIDE for side in header.size):
                raise error(TOO_LARGE, path, "each image side can be at most 4096 pixels", "too_large")
            header.verify()
        with Image.open(io.BytesIO(data), formats=formats) as image:
            if getattr(image, "is_animated", False):
                raise error(INVALID_IMAGE, path, "expected a single still image")
            image.load()
            ImageOps.exif_transpose(image, in_place=True)
            if image.mode == "RGB" and not image.has_transparency_data:
                image.info.clear()
                return image
            rgba = image if image.mode == "RGBA" else image.convert("RGBA")
            if rgba is not image:
                image.close()
            clean = Image.new("RGB", rgba.size, "white")
            clean.paste(rgba, mask=rgba)
            return clean
    except ContractError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise error(TOO_LARGE, path, "each image side can be at most 4096 pixels", "too_large") from None
    except (OSError, ValueError, SyntaxError, struct.error, UserWarning,
            IndexError, TypeError, OverflowError):
        raise error(INVALID_IMAGE, path, "the image cannot be decoded as the declared type") from None


@dataclass(frozen=True)
class PhotoImage:
    png: bytes = field(repr=False)
    width: int
    height: int


def png_image(image: Image.Image) -> PhotoImage:
    out = io.BytesIO()
    image.save(out, format="PNG")
    return PhotoImage(out.getvalue(), image.width, image.height)


def reference_canvas(images: Iterable[Image.Image], count: int,
                     size: tuple[int, int]) -> PhotoImage:
    """Fit ordered references into the single image input of the pinned edit graph."""
    width, height = size
    columns = max(1, isqrt(count * width // height))
    rows = (count + columns - 1) // columns
    if columns > width or rows > height:
        raise error(TOO_LARGE, "/photo/input_asset_version_ids",
                    "too many references for the edit canvas", "too_large")
    canvas = Image.new("RGB", size, "white")
    for i, image in enumerate(images):
        col, row = i % columns, i // columns
        left, right = col * width // columns, (col + 1) * width // columns
        top, bottom = row * height // rows, (row + 1) * height // rows
        scale = min((right - left) / image.width, (bottom - top) / image.height)
        fitted = image.resize((max(1, round(image.width * scale)),
                               max(1, round(image.height * scale))), Image.Resampling.LANCZOS)
        canvas.paste(fitted, (left + (right - left - fitted.width) // 2,
                              top + (bottom - top - fitted.height) // 2))
    return png_image(canvas)
