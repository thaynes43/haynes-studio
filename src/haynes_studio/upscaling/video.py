"""Read one frame from a verified, immutable Studio delivery blob."""

from contextlib import ExitStack, contextmanager
from fractions import Fraction
from hashlib import sha256
import os
from pathlib import Path, PurePosixPath
import re
import stat

import numpy as np
from PIL import Image

from haynes_studio.store import StoreError, parse_locator
from haynes_studio.timebase import DELIVERY_FPS

from .files import READ, open_directory
from .pixels import fits
from .profile import (
    FRAME_OUT_OF_RANGE, MAX_VIDEO_BYTES, PIN_MISMATCH, REQUEST_INVALID, VIDEO_CAPTURE_OPTIONS, VIDEO_THREADS,
    UpscaleError,
)


def frame_selector(index: str | None, timestamp: str | None) -> int:
    if index is not None and timestamp is None and re.fullmatch(r"[0-9]{1,10}", index):
        return int(index)
    if index is None and timestamp is not None and re.fullmatch(r"[0-9]{1,10}(?:\.[0-9]{1,9})?", timestamp):
        return int(Fraction(timestamp) * DELIVERY_FPS)
    raise UpscaleError(REQUEST_INVALID)


def _stamp(facts):
    return facts.st_mode, facts.st_nlink, facts.st_size, facts.st_mtime_ns, facts.st_ctime_ns


@contextmanager
def _verified_blob(store: Path, relative: str):
    try:
        locator = parse_locator(relative)
        if locator.ext != "mp4":
            raise UpscaleError(REQUEST_INVALID)
        *folders, filename = PurePosixPath(locator.text).parts
        with ExitStack() as held:
            directory = held.enter_context(open_directory(store))
            for folder in folders:
                directory = held.enter_context(open_directory(folder, dir_fd=directory))
            source = held.enter_context(os.fdopen(os.open(filename, READ, dir_fd=directory), "rb"))
            facts = os.fstat(source.fileno())
            if (not stat.S_ISREG(facts.st_mode) or facts.st_nlink != 1
                    or not 0 < facts.st_size <= MAX_VIDEO_BYTES):
                raise UpscaleError(REQUEST_INVALID)
            digest = sha256()
            remaining = facts.st_size
            while remaining and (chunk := source.read(min(1024**2, remaining))):
                digest.update(chunk)
                remaining -= len(chunk)
            if (remaining or source.read(1) or digest.hexdigest() != locator.sha256
                    or _stamp(os.fstat(source.fileno())) != _stamp(facts)):
                raise UpscaleError(PIN_MISMATCH)
            source.seek(0)
            header = source.read(12)
            if len(header) != 12 or header[4:8] != b"ftyp" or header[8:12] == b"qt  ":
                raise UpscaleError(REQUEST_INVALID)
            # FFmpeg reopens this descriptor, so name replacement cannot change
            # the file being decoded. The backing store is mounted read-only.
            yield f"/proc/self/fd/{source.fileno()}", locator.sha256, facts.st_size
            if _stamp(os.fstat(source.fileno())) != _stamp(facts):
                raise UpscaleError(PIN_MISMATCH)
    except (OSError, StoreError) as error:
        raise UpscaleError(REQUEST_INVALID) from error


def read_frame(store: Path, relative: str, index: int, target: tuple[int, int], *,
               master_frames: int | None = None) -> tuple[Image.Image, dict]:
    with _verified_blob(store, relative) as (descriptor_path, digest, size_bytes):
        image, frames = _decode_frame(descriptor_path, index, target, master_frames)
    return image, {"sha256": digest, "bytes": size_bytes, "size": list(image.size),
                   "fps": DELIVERY_FPS, "frame_count": frames, "frame_index": index}


def _decode_frame(descriptor_path, index, target, master_frames):
    import cv2

    # The one-shot command uses a single local decoder. Prevent protocol or
    # demuxer fallback and keep native diagnostics out of the comparison log.
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = VIDEO_CAPTURE_OPTIONS
    os.environ["OPENCV_FFMPEG_LOGLEVEL"] = "-8"
    capture = cv2.VideoCapture()
    try:
        if not capture.open(descriptor_path, cv2.CAP_FFMPEG, [
            cv2.CAP_PROP_N_THREADS, VIDEO_THREADS, cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_NONE,
        ]):
            raise UpscaleError(REQUEST_INVALID)
        size = (capture.get(cv2.CAP_PROP_FRAME_WIDTH), capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if (capture.get(cv2.CAP_PROP_FPS) != DELIVERY_FPS or capture.get(cv2.CAP_PROP_ORIENTATION_META) != 0
                or frames <= 0):
            raise UpscaleError(REQUEST_INVALID)
        if master_frames is None:
            if not fits(size, target):
                raise UpscaleError(REQUEST_INVALID)
        elif size != target or frames != master_frames:
            raise UpscaleError(REQUEST_INVALID)
        if not 0 <= index < frames:
            raise UpscaleError(FRAME_OUT_OF_RANGE)
        if index and not capture.set(cv2.CAP_PROP_POS_FRAMES, index):
            raise UpscaleError(REQUEST_INVALID)
        ok, bgr = capture.read()
        if (not ok or bgr.dtype != np.uint8 or bgr.shape != (size[1], size[0], 3)
                or capture.get(cv2.CAP_PROP_POS_FRAMES) != index + 1 or capture.get(cv2.CAP_PROP_PTS) != index):
            raise UpscaleError(REQUEST_INVALID)
        return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)), frames
    except (cv2.error, OverflowError, ValueError) as error:
        raise UpscaleError(REQUEST_INVALID) from error
    finally:
        capture.release()
