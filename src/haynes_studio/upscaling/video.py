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

from haynes_studio.canonical.ids import is_id
from haynes_studio.store import StoreError, parse_locator
from haynes_studio.timebase import DELIVERY_FPS

from .files import READ, open_directory
from .mp4 import first_presentation_time
from .pixels import fits
from .profile import (
    DELIVERY_ID_REQUIRED, FRAME_OUT_OF_RANGE, MAX_VIDEO_BYTES, NONZERO_START_TIMESTAMP, PIN_MISMATCH,
    REQUEST_INVALID, VIDEO_CAPTURE_OPTIONS, VIDEO_THREADS, UpscaleError,
)


def frame_selector(index: str | None, timestamp: str | None) -> int:
    if index is not None and timestamp is None and re.fullmatch(r"[0-9]{1,10}", index):
        return int(index)
    if index is None and timestamp is not None and re.fullmatch(r"[0-9]{1,10}(?:\.[0-9]{1,9})?", timestamp):
        return int(Fraction(timestamp) * DELIVERY_FPS)
    raise UpscaleError(REQUEST_INVALID)


def require_delivery_id(master: str | None, delivery_id: str | None) -> None:
    if master is not None and delivery_id is None:
        raise UpscaleError(DELIVERY_ID_REQUIRED)
    if delivery_id is not None and (master is None or not is_id(delivery_id, "dlv")):
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
            yield source, locator.sha256, facts.st_size
            if _stamp(os.fstat(source.fileno())) != _stamp(facts):
                raise UpscaleError(PIN_MISMATCH)
    except (OSError, StoreError) as error:
        raise UpscaleError(REQUEST_INVALID) from error


def read_frame(store: Path, relative: str, index: int, target: tuple[int, int], *,
               master_frames: int | None = None) -> tuple[Image.Image, dict]:
    facts = {}
    image = _read_video(store, relative, index, target, master_frames, facts, pixels=True)
    return image, facts


def probe_frames(store: Path, proxy: str, index: int, target: tuple[int, int], *,
                 master: str | None = None, delivery_id: str | None = None) -> dict:
    source = {"resolved": False}
    report = {"passed": False, "source": source}
    if master is not None:
        report["reference"] = {"resolved": False}
    try:
        require_delivery_id(master, delivery_id)
        _read_video(store, proxy, index, target, None, source, pixels=False)
        source["resolved"] = True
        if master is not None:
            reference = report["reference"]
            report["delivery_id"] = delivery_id
            _read_video(store, master, index, target, source["frame_count"], reference, pixels=False)
            reference["resolved"] = True
    except UpscaleError as error:
        report["code"] = error.code
    else:
        report["passed"] = True
    return report


def _read_video(store, relative, index, target, master_frames, facts, *, pixels):
    with _verified_blob(store, relative) as (source, digest, size_bytes):
        facts.update(sha256=digest, bytes=size_bytes, fps=DELIVERY_FPS, frame_index=index)
        first_timestamp = first_presentation_time(source, size_bytes)
        facts["first_timestamp_seconds"] = float(first_timestamp)
        return _decode_frame(f"/proc/self/fd/{source.fileno()}", index, target, master_frames, facts,
                             first_timestamp=first_timestamp, pixels=pixels)


def _decode_frame(descriptor_path, index, target, master_frames, facts, *, first_timestamp, pixels):
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
        size = (int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        facts.update(size=list(size), frame_count=frames)
        if (capture.get(cv2.CAP_PROP_FPS) != DELIVERY_FPS or capture.get(cv2.CAP_PROP_ORIENTATION_META) != 0
                or frames <= 0):
            raise UpscaleError(REQUEST_INVALID)
        if master_frames is None:
            if not fits(size, target):
                raise UpscaleError(REQUEST_INVALID)
        elif size != target or frames != master_frames:
            raise UpscaleError(REQUEST_INVALID)
        if first_timestamp != 0:
            raise UpscaleError(NONZERO_START_TIMESTAMP)

        if not 0 <= index < frames:
            raise UpscaleError(FRAME_OUT_OF_RANGE)
        if index and not capture.set(cv2.CAP_PROP_POS_FRAMES, index):
            raise UpscaleError(REQUEST_INVALID)
        ok, bgr = capture.read()
        if (not ok or bgr.dtype != np.uint8 or bgr.shape != (size[1], size[0], 3)
                or capture.get(cv2.CAP_PROP_POS_FRAMES) != index + 1):
            raise UpscaleError(REQUEST_INVALID)
        if capture.get(cv2.CAP_PROP_PTS) != index:
            raise UpscaleError(REQUEST_INVALID)
        if pixels:
            return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    except (cv2.error, OverflowError, ValueError) as error:
        raise UpscaleError(REQUEST_INVALID) from error
    finally:
        capture.release()
