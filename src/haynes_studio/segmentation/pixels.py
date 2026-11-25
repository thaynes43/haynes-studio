"""Source-image validation and binary, source-coordinate PNGs."""

from __future__ import annotations

from io import BytesIO
from struct import unpack_from

import numpy as np
from PIL import Image

from .profile import GRAY, MAX_SOURCE_BYTES, PNG_COMPRESSION, SegmentationError, digest

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def decode_source(data: bytes, source: dict) -> tuple[Image.Image, np.ndarray | None]:
    if not data or len(data) > MAX_SOURCE_BYTES or digest(data) != source["sha256"]:
        raise SegmentationError("invalid_input")
    try:
        with Image.open(BytesIO(data), formats=["PNG", "JPEG", "WEBP"]) as image:
            if (image.size != (source["width"], source["height"])
                    or getattr(image, "n_frames", 1) != 1 or getattr(image, "is_animated", False)
                    or image.getexif().get(274, 1) != 1):
                raise SegmentationError("invalid_input")
            image.load()
            if "A" in image.getbands() or "transparency" in image.info:
                rgba = image.convert("RGBA")
                alpha = np.asarray(rgba.getchannel("A")) != 0
                gray = Image.new("RGBA", image.size, (GRAY, GRAY, GRAY, 255))
                return Image.alpha_composite(gray, rgba).convert("RGB"), alpha
            return image.convert("RGB"), None
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Warning) as error:
        raise SegmentationError("invalid_input") from error


def tight_box(mask: np.ndarray) -> list[int] | None:
    rows = np.flatnonzero(mask.any(axis=1))
    if not rows.size:
        return None
    columns = np.flatnonzero(mask.any(axis=0))
    return [int(columns[0]), int(rows[0]), int(columns[-1]) + 1, int(rows[-1]) + 1]


def mask_iou(first: np.ndarray, second: np.ndarray) -> float:
    union = np.count_nonzero(first | second)
    return float(np.count_nonzero(first & second) / union) if union else 1.0


def encode_mask(mask: np.ndarray) -> bytes:
    with BytesIO() as buffer:
        Image.fromarray(mask.astype(np.uint8) * 255).save(
            buffer, "PNG", compress_level=PNG_COMPRESSION, optimize=False,
        )
        return buffer.getvalue()


def describe_mask(png: bytes, size: tuple[int, int]) -> tuple[dict, np.ndarray]:
    if (len(png) > MAX_SOURCE_BYTES or not png.startswith(PNG_SIGNATURE)
            or png[8:16] != b"\x00\x00\x00\x0dIHDR" or png[24:26] != b"\x08\x00"):
        raise SegmentationError("invalid_output")
    offset = len(PNG_SIGNATURE)
    while offset + 12 <= len(png):
        length, kind = unpack_from(">I4s", png, offset)
        offset += length + 12
        if kind == b"IEND" and length == 0 and offset == len(png):
            break
        if kind not in (b"IHDR", b"IDAT"):
            raise SegmentationError("invalid_output")
    else:
        raise SegmentationError("invalid_output")
    try:
        with Image.open(BytesIO(png), formats=["PNG"]) as image:
            if image.size != size or image.mode != "L" or image.info:
                raise SegmentationError("invalid_output")
            pixels = np.array(image)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Warning) as error:
        raise SegmentationError("invalid_output") from error
    mask = pixels == 255
    if np.any((pixels != 0) & ~mask) or not mask.any() or mask.all():
        raise SegmentationError("invalid_output")
    return {
        "sha256": digest(png), "bytes": len(png), "width": size[0], "height": size[1], "media_type": "image/png",
    }, mask
