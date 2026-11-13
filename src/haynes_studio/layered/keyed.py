"""Keyed frames as cached artifacts (story 426, contract section 4's "keyed and decal
frames", keyed by ``keyed_frames_key``).

One key (clip, still, key thresholds, protect boxes, decal box, decal version, keyer)
names one artifact: the clip's frames keyed to RGBA, with the lettering decal pasted
back first when the key names a decal box, every frame cropped to one box (the first
frame's doll plus 24 px, legacy ``DollClip``). It is **one lossless file with alpha**
(**proposal**): an animated PNG (APNG, ``image/png``, a media type the store already
knows), frames in order, each a full replacement of the canvas (dispose none, blend
source), and a ``tEXt`` chunk ``studio`` holding the record
(``studio.keyed-frames/v1``): the key, the frame count, the clip size, the crop box,
the decal box with every frame's tracking score and their summary, the keyer and the
tool builds. PNG because it is lossless with alpha and the store knows it; one file,
because the record and the frames can never part. Each frame is encoded by Pillow's
PNG encoder (no metadata, level 6), so the same frames give the same bytes in one
build. Cost: a frame is the doll's box in RGBA, deflated; a 121-frame doll clip at
576x1024 is in the order of the PoC's own keyed folder (121 PNG files), since the bytes
are the same PNG data.

The decal gate is not applied here: the floor (``decal_min_ecc``) is a record's, not a
key input, so the artifact keeps every score and the renderer gates it on every use,
cached or not, as legacy ``DollClip`` did (**proposal**). A weak track is therefore
cached but never drawn.

The cache rules hold: a miss makes and commits (blobs first, then the record); a hit
reads the completed record, re-hashed by the ledger; nothing is deleted, evicted or
overwritten. A missing clip, a clip that does not decode, or nothing left after keying
fails the stage and publishes nothing.
"""

from __future__ import annotations

import io
import struct
import zlib
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, BinaryIO

import cv2
import numpy as np
import PIL
import PIL.Image
import scipy

from haynes_studio.cache.artifacts import ArtifactCache, CachedArtifact
from haynes_studio.cache.keys import KEYED_FRAMES, CacheKey
from haynes_studio.jsonio import parse_strict, thaw
from haynes_studio.layered import keying
from haynes_studio.layered.errors import (
    CLIP_INVALID,
    SOURCE_SHORT,
    UNSUPPORTED,
    LayeredError,
)
from haynes_studio.render.encode import decode_frames
from haynes_studio.store import BLOB_MISSING, HASH_MISMATCH, StoreError

SCHEMA = "studio.keyed-frames/v1"  # proposal: the record inside the keyed artifact
PNG = "image/png"
TEXT_KEY = b"studio"
_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def tool_builds() -> dict[str, str]:
    """The library builds that draw keyed pixels (recorded, not key inputs)."""
    return {"numpy": np.__version__, "opencv": cv2.__version__, "pillow": PIL.__version__,
            "scipy": scipy.__version__}


# The APNG container ---------------------------------------------------------------------


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def _chunks(data: bytes) -> Iterator[tuple[bytes, bytes]]:
    if not data.startswith(_SIGNATURE):
        raise ValueError("not a PNG")
    at = len(_SIGNATURE)
    while at + 8 <= len(data):
        (length,) = struct.unpack(">I", data[at:at + 4])
        kind = data[at + 4:at + 8]
        body = data[at + 8:at + 8 + length]
        if len(body) != length:
            raise ValueError("a PNG chunk is cut short")
        yield kind, body
        at += 12 + length
        if kind == b"IEND":
            return
    raise ValueError("a PNG without IEND")


def _frame_png(rgba: np.ndarray) -> tuple[bytes, bytes]:
    """One RGBA frame's IHDR body and its IDAT payload, from Pillow's encoder."""
    buffer = io.BytesIO()
    PIL.Image.fromarray(np.ascontiguousarray(rgba), "RGBA").save(buffer, format="PNG")
    header, idat = b"", []
    for kind, body in _chunks(buffer.getvalue()):
        if kind == b"IHDR":
            header = body
        elif kind == b"IDAT":
            idat.append(body)
    return header, b"".join(idat)


def write_apng(frames: Sequence[bytes], header: bytes, record: Mapping[str, Any], fps: int) -> bytes:
    """An APNG of the frames' IDAT payloads (all of one IHDR), with ``record`` as the
    ``studio`` text chunk. Every frame replaces the whole canvas."""
    import json  # the record is ASCII JSON: tEXt is Latin-1
    width, height = struct.unpack(">II", header[:8])
    out = [_SIGNATURE, _chunk(b"IHDR", header),
           _chunk(b"acTL", struct.pack(">II", len(frames), 0)),
           _chunk(b"tEXt", TEXT_KEY + b"\0" + json.dumps(record, sort_keys=True, separators=(",", ":"),
                                                          ensure_ascii=True).encode("ascii"))]
    sequence = 0
    for index, payload in enumerate(frames):
        out.append(_chunk(b"fcTL", struct.pack(">IIIIIHHBB", sequence, width, height, 0, 0, 1, fps, 0, 0)))
        sequence += 1
        if index == 0:
            out.append(_chunk(b"IDAT", payload))
        else:
            out.append(_chunk(b"fdAT", struct.pack(">I", sequence) + payload))
            sequence += 1
    out.append(_chunk(b"IEND", b""))
    return b"".join(out)


def read_record(data: bytes) -> dict[str, Any]:
    """The ``studio.keyed-frames/v1`` record of a keyed artifact, read from its chunks
    without decoding a frame; anything else is ``layered.clip_invalid``."""
    try:
        for kind, body in _chunks(data):
            if kind == b"tEXt" and body.startswith(TEXT_KEY + b"\0"):
                record = parse_strict(body[len(TEXT_KEY) + 1:].decode("ascii"))
                break
            if kind in (b"IDAT", b"fcTL"):
                raise ValueError("no record before the frames")
        else:
            raise ValueError("no record")
    except (ValueError, UnicodeDecodeError) as error:
        raise LayeredError(CLIP_INVALID, f"not a keyed artifact: {error}") from error
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        raise LayeredError(CLIP_INVALID, f"a keyed artifact's record is not {SCHEMA}")
    return record


def frame_pngs(data: bytes, record: Mapping[str, Any]) -> list[bytes]:
    """Each frame of a keyed artifact as a standalone PNG, without decoding any:
    the artifact's own IHDR with the frame's one deflate stream. The layout must be
    the one :func:`write_apng` writes; a frame count or size other than the record's
    is ``time.source_short`` (fewer) or ``layered.clip_invalid``."""
    width, height = record["box"][2] - record["box"][0], record["box"][3] - record["box"][1]
    header, out, controls = None, [], 0
    try:
        for kind, body in _chunks(data):
            if kind == b"IHDR":
                header = body
            elif kind == b"fcTL":
                controls += 1
                _, w, h, x, y, _, _, dispose, blend = struct.unpack(">IIIIIHHBB", body)
                if (w, h, x, y, dispose, blend) != (width, height, 0, 0, 0, 0):
                    raise ValueError("a frame control is not a full-canvas replacing frame")
            elif kind in (b"IDAT", b"fdAT"):
                if len(out) != controls - 1:
                    raise ValueError("a frame without its control chunk")
                payload = body if kind == b"IDAT" else body[4:]
                out.append(_SIGNATURE + _chunk(b"IHDR", header or b"") + _chunk(b"IDAT", payload)
                           + _chunk(b"IEND", b""))
    except (ValueError, struct.error) as error:
        raise LayeredError(CLIP_INVALID, f"the keyed artifact is damaged: {error}") from error
    if header is None or struct.unpack(">II", header[:8]) != (width, height):
        raise LayeredError(CLIP_INVALID, "the keyed artifact is not the size its record names")
    if len(out) < record["frames"]:
        raise LayeredError(SOURCE_SHORT, f"the keyed artifact holds {len(out)} frames, its record "
                           f"says {record['frames']}")
    if len(out) > record["frames"] or controls != len(out):
        raise LayeredError(CLIP_INVALID, "the keyed artifact is not the frames its record names")
    return out


def decode_png(png: bytes) -> np.ndarray:
    """One keyed frame (:func:`frame_pngs`) as an RGBA array."""
    try:
        with PIL.Image.open(io.BytesIO(png)) as image:
            return np.asarray(image.convert("RGBA"))
    except Exception as error:  # Pillow raises its own error types for damaged files
        raise LayeredError(CLIP_INVALID, f"a keyed frame does not decode: {type(error).__name__}") from error


def read_frames(data: bytes, record: Mapping[str, Any]) -> Iterator[np.ndarray]:
    """The keyed artifact's RGBA frames in order (:func:`frame_pngs`, decoded)."""
    for png in frame_pngs(data, record):
        yield decode_png(png)


# The settings a key names -------------------------------------------------------------------


@dataclass(frozen=True)
class KeySettings:
    keyer: str
    lo: float
    hi: float
    protect: tuple[tuple[int, int, int, int], ...]
    decal_box: tuple[int, int, int, int] | None
    decal_version: str | None


def _box(value: Any, what: str) -> tuple[int, int, int, int]:
    if (not isinstance(value, list | tuple) or len(value) != 4
            or any(isinstance(v, bool) or not isinstance(v, int) for v in value)
            or not (0 <= value[0] < value[2] and 0 <= value[1] < value[3])):
        raise LayeredError(UNSUPPORTED, f"{what} {value!r} is not [x0, y0, x1, y1] in pixels")
    return tuple(value)  # type: ignore[return-value]


def check_settings(document: Mapping[str, Any]) -> KeySettings:
    """The key's settings, if this keyer serves them: a keyer and decal version of
    :mod:`.keying`, thresholds ``{lo, hi}`` with ``lo < hi``, boxes in pixels."""
    if document.get("keyer") not in keying.KEYERS:
        raise LayeredError(UNSUPPORTED, f"keyer {document.get('keyer')!r} is not one of "
                           f"{', '.join(keying.KEYERS)}", where="/keyer")
    thresholds = thaw(document.get("key_thresholds"))
    lo, hi = (thresholds.get("lo"), thresholds.get("hi")) if isinstance(thresholds, dict) else (None, None)
    if (not isinstance(thresholds, dict) or set(thresholds) != {"lo", "hi"}
            or any(isinstance(v, bool) or not isinstance(v, int | float) for v in (lo, hi))
            or not lo < hi):
        raise LayeredError(UNSUPPORTED, f"key thresholds {thresholds!r} are not {{lo, hi}} with "
                           "lo < hi", where="/key_thresholds")
    protect = tuple(_box(box, "a protect box") for box in document.get("protect_boxes") or ())
    decal_box, version = document.get("decal_box"), document.get("decal_version")
    if decal_box is None:
        if version is not None:
            raise LayeredError(UNSUPPORTED, "a decal version without a decal box", where="/decal_box")
        return KeySettings(document["keyer"], lo, hi, protect, None, None)
    if version not in keying.DECAL_VERSIONS:
        raise LayeredError(UNSUPPORTED, f"decal version {version!r} is not one of "
                           f"{', '.join(keying.DECAL_VERSIONS)}", where="/decal_version")
    return KeySettings(document["keyer"], lo, hi, protect, _box(decal_box, "the decal box"), version)


def read_verified(read: Callable[[str], BinaryIO], sha256: str, what: str) -> bytes:
    """Blob ``sha256`` through ``read``, re-hashed. A missing blob is
    ``time.source_short``; other bytes are ``store.hash_mismatch``."""
    import hashlib
    try:
        with read(sha256) as handle:
            data = handle.read()
    except StoreError as error:
        if error.code == BLOB_MISSING:
            raise LayeredError(SOURCE_SHORT, f"{what} is missing", where=sha256) from error
        raise
    if hashlib.sha256(data).hexdigest() != sha256:
        raise StoreError(HASH_MISMATCH, f"{what} {sha256} is not the bytes it is named by")
    return data


def _decoded(data: bytes) -> Iterator[np.ndarray]:
    try:
        yield from decode_frames(data)
    except Exception as error:  # PyAV raises its own error types for damaged media
        raise LayeredError(CLIP_INVALID, f"the clip does not decode: {type(error).__name__}") from error


def still_rgb(data: bytes, size: tuple[int, int]) -> np.ndarray:
    """The decal's still as RGB at the clip's size (``DollClip``: the still resized to
    the first frame's size, Pillow's default bicubic)."""
    try:
        with PIL.Image.open(io.BytesIO(data)) as image:
            still = image.convert("RGB")
    except Exception as error:
        raise LayeredError(CLIP_INVALID, f"the decal still does not decode: {type(error).__name__}") from error
    if still.size != size:
        still = still.resize(size, PIL.Image.Resampling.BICUBIC)
    return np.asarray(still)


def make_keyed(key: CacheKey, settings: KeySettings, clip: bytes, still: bytes | None,
               fps: int = 24) -> bytes:
    """The keyed artifact of ``clip`` (see the module docstring), one frame at a time."""
    frames = _decoded(clip)
    first = next(frames, None)
    if first is None:
        raise LayeredError(SOURCE_SHORT, "the clip holds no frame")
    height, width = first.shape[:2]

    def source() -> Iterator[np.ndarray]:
        yield first
        for frame in frames:
            if frame.shape != first.shape:
                raise LayeredError(CLIP_INVALID, "the clip changes size between frames")
            yield frame

    scores: list[float | None] = []
    if settings.decal_box is not None:
        x0, y0, x1, y1 = settings.decal_box
        if x1 > width or y1 > height:
            raise LayeredError(UNSUPPORTED, f"the decal box {list(settings.decal_box)} is outside "
                               f"the {width}x{height} clip", where="/decal_box")
        if still is None:
            raise LayeredError(SOURCE_SHORT, "the decal's still is missing")
        rgb = still_rgb(still, (width, height))

        def fixed() -> Iterator[np.ndarray]:
            for index, (frame, score) in enumerate(keying.decal_frames(rgb, source(), settings.decal_box)):
                if index:
                    scores.append(score)
                yield frame
        frames_in: Iterator[np.ndarray] = fixed()
    else:
        frames_in = source()
    box = None
    header = b""
    payloads: list[bytes] = []
    for frame in frames_in:
        rgba = keying.key(frame, settings.lo, settings.hi, settings.protect)
        if box is None:
            box = keying.alpha_box(rgba)
            if box is None:
                raise LayeredError(CLIP_INVALID, "nothing is left of the clip's first frame after "
                                   "keying")
        header, payload = _frame_png(rgba[box[1]:box[3], box[0]:box[2]])
        payloads.append(payload)
    assert box is not None
    decal = None
    if settings.decal_box is not None:
        decal = {"box": list(settings.decal_box), "version": settings.decal_version,
                 **keying.summarize(scores), "scores": scores}
    record = {"schema": SCHEMA, "key": key.value, "frames": len(payloads),
              "clip_size": [width, height], "box": list(box), "keyer": settings.keyer,
              "thresholds": {"lo": settings.lo, "hi": settings.hi},
              "protect_boxes": [list(b) for b in settings.protect], "decal": decal,
              "tools": tool_builds()}
    return write_apng(payloads, header, record, fps)


class KeyedFrames:
    """The keyed-frames stage on ``cache``: a ``content`` source for ``keyed_frames``
    keys. ``read_clip`` and ``read_still`` open a blob by hash (the clip as MP4, the
    decal's still as an image), from whatever scope holds it."""

    def __init__(self, cache: ArtifactCache, *, read_clip: Callable[[str], BinaryIO],
                 read_still: Callable[[str], BinaryIO]):
        self.cache = cache
        self.read_clip = read_clip
        self.read_still = read_still
        self.made: list[str] = []  # keys this stage keyed

    def __call__(self, key: CacheKey) -> str:
        return self.frames(key).sha256

    def frames(self, key: CacheKey) -> CachedArtifact:
        if key.kind != KEYED_FRAMES:
            raise LookupError(f"the keyed-frames stage makes no {key.kind} artifacts")
        settings = check_settings(key.document)
        found = self.cache.lookup(key, PNG)
        if found is not None:
            return found
        clip = read_verified(self.read_clip, key.document["clip"], "the clip")
        still = None
        if settings.decal_box is not None:
            still = read_verified(self.read_still, key.document["still"], "the decal's still")
        data = make_keyed(key, settings, clip, still)
        self.made.append(key.value)
        return self.cache.commit(key, data, PNG)


__all__ = ["PNG", "SCHEMA", "KeySettings", "KeyedFrames", "check_settings", "decode_png",
           "frame_pngs", "make_keyed", "read_frames", "read_record", "read_verified", "still_rgb", "tool_builds", "write_apng"]
