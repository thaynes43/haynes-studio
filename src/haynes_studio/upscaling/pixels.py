"""Bounded, opaque PNG artifacts and the two fixed resize operations."""

from hashlib import sha256
from io import BytesIO
from struct import unpack_from
from zlib import crc32

from PIL import Image

from .profile import MAX_LONG_EDGE, MAX_PIXELS, REQUEST_INVALID, UpscaleError

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def fits(source: tuple[int, int], target: tuple[int, int]) -> bool:
    width, height = source
    tw, th = target
    return (0 < width <= MAX_LONG_EDGE and 0 < height <= MAX_LONG_EDGE and width * height <= MAX_PIXELS
            and width * th == height * tw and width < tw <= width * 2)


def describe(data: bytes, size: tuple[int, int]) -> dict:
    return {"sha256": sha256(data).hexdigest(), "bytes": len(data), "media_type": "image/png",
            "width": size[0], "height": size[1]}


def decode_png(data: bytes, size: tuple[int, int], code: str) -> Image.Image:
    # Validate the dimensions, RGB8 header and complete chunk stream before
    # handing the compressed bytes to Pillow. Reject alternate color metadata,
    # APNG, alpha, trailing bytes, and all other ancillary data.
    if (len(data) < 45 or not data.startswith(PNG_MAGIC)
            or unpack_from(">I4sIIBBBBB", data, 8) != (13, b"IHDR", *size, 8, 2, 0, 0, 0)):
        raise UpscaleError(code)
    view = memoryview(data)
    offset = len(PNG_MAGIC)
    seen_idat = False
    while offset + 12 <= len(data):
        length, tag = unpack_from(">I4s", data, offset)
        end = offset + length + 12
        if end > len(data) or crc32(view[offset + 4:end - 4]) != unpack_from(">I", data, end - 4)[0]:
            raise UpscaleError(code)
        if tag == b"IDAT":
            seen_idat = True
        elif tag == b"IEND" and seen_idat and length == 0 and end == len(data):
            break
        elif offset != len(PNG_MAGIC):
            raise UpscaleError(code)
        offset = end
    else:
        raise UpscaleError(code)
    try:
        with Image.open(BytesIO(data), formats=["PNG"]) as image:
            image.load()
            if image.mode != "RGB" or image.size != size:
                raise UpscaleError(code)
            return image.copy()
    except (OSError, SyntaxError, ValueError) as error:
        raise UpscaleError(code) from error


def encode_png(rgb: Image.Image) -> bytes:
    buffer = BytesIO()
    # Drop info inherited by Pillow from a private source still.
    rgb.info.clear()
    rgb.save(buffer, format="PNG", compress_level=1, optimize=False)
    return buffer.getvalue()


def lanczos(rgb: Image.Image, target: tuple[int, int]) -> Image.Image:
    if rgb.size == target:
        return rgb
    return rgb.resize(target, Image.Resampling.LANCZOS)


def crop_plate(rgb: Image.Image, target: tuple[int, int]) -> tuple[Image.Image, tuple[int, int, int, int]]:
    ax, ay = (9, 16) if target[0] < target[1] else (16, 9)
    width, height = rgb.size
    k = min(width // ax, height // ay)
    cw, ch = k * ax, k * ay
    if not fits((cw, ch), target):
        raise UpscaleError(REQUEST_INVALID)
    x, y = (width - cw) // 2, (height - ch) // 2
    box = (x, y, x + cw, y + ch)
    return rgb.crop(box), box
