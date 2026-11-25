"""Read the first presentation time in a Studio MP4's unfragmented video track."""

from dataclasses import dataclass
from fractions import Fraction
from struct import Struct

from .profile import REQUEST_INVALID, UpscaleError


@dataclass(frozen=True)
class _Box:
    kind: bytes
    start: int
    end: int


def _read(source, box, offset, fmt):
    fields = Struct(">" + fmt)
    if box.start + offset + fields.size > box.end:
        raise UpscaleError(REQUEST_INVALID)
    source.seek(box.start + offset)
    data = source.read(fields.size)
    if len(data) != fields.size:
        raise UpscaleError(REQUEST_INVALID)
    return fields.unpack(data)


def _children(source, box):
    offset = 0
    while box.start + offset < box.end:
        size, kind = _read(source, box, offset, "I4s")
        header_size = 8
        if size == 1:
            size, = _read(source, box, offset + 8, "Q")
            header_size = 16
        elif size == 0:
            size = box.end - box.start - offset
        if size < header_size or box.start + offset + size > box.end:
            raise UpscaleError(REQUEST_INVALID)
        yield _Box(kind, box.start + offset + header_size, box.start + offset + size)
        offset += size


def _child(source, box, kind, *, optional=False):
    for entry in _children(source, box):
        if entry.kind == kind:
            return entry
    if not optional:
        raise UpscaleError(REQUEST_INVALID)
    return None


def _version(source, box):
    version, = _read(source, box, 0, "B")
    if version not in (0, 1):
        raise UpscaleError(REQUEST_INVALID)
    return version


def _timescale(source, box):
    timescale, = _read(source, box, 20 if _version(source, box) else 12, "I")
    if timescale == 0:
        raise UpscaleError(REQUEST_INVALID)
    return timescale


def _rows(source, box, fmt):
    count, = _read(source, box, 4, "I")
    size = Struct(">" + fmt).size
    if 8 + count * size != box.end - box.start:
        raise UpscaleError(REQUEST_INVALID)
    for index in range(count):
        yield _read(source, box, 8 + index * size, fmt)


def _first_video_edit(source, track):
    edits = _child(source, track, b"edts", optional=True)
    if edits is None:
        return 0, None, None
    table = _child(source, edits, b"elst")
    movie_start = 0
    for duration, media_start, rate in _rows(source, table, "Qqi" if _version(source, table) else "Iii"):
        if media_start == -1:
            movie_start += duration
        elif media_start >= 0 and duration and rate == 1 << 16:
            return movie_start, media_start, duration
        else:
            raise UpscaleError(REQUEST_INVALID)
    raise UpscaleError(REQUEST_INVALID)


def _first_sample(source, table, media_start):
    timing = _child(source, table, b"stts")
    composition = _child(source, table, b"ctts", optional=True)
    offsets = None if composition is None else _rows(
        source, composition, "Ii" if _version(source, composition) else "II",
    )
    dts = remaining = shift = 0
    earliest = None
    for count, delta in _rows(source, timing, "II"):
        if count == 0 or delta == 0:
            raise UpscaleError(REQUEST_INVALID)
        while count:
            if remaining == 0:
                remaining, shift = (count, 0) if offsets is None else next(offsets, (0, 0))
                if remaining == 0:
                    raise UpscaleError(REQUEST_INVALID)
            run = min(count, remaining)
            pts = dts + shift
            # An edit can trim leading samples. Find the first sample in this
            # run whose presentation time is inside the edit.
            skipped = 0 if media_start is None else max(0, -((pts - media_start) // delta))
            if skipped < run:
                candidate = pts + skipped * delta
                earliest = candidate if earliest is None else min(earliest, candidate)
            dts += run * delta
            remaining -= run
            count -= run
    if earliest is None or remaining or (offsets is not None and next(offsets, None) is not None):
        raise UpscaleError(REQUEST_INVALID)
    return earliest


def first_presentation_time(source, size: int) -> Fraction:
    """Read the exact MP4 time before the decoder rounds or rebases it."""
    movie = _child(source, _Box(b"", 0, size), b"moov")
    if _child(source, movie, b"mvex", optional=True) is not None:
        raise UpscaleError(REQUEST_INVALID)
    video = []
    for track in _children(source, movie):
        if track.kind == b"trak":
            media = _child(source, track, b"mdia")
            handler = _child(source, media, b"hdlr")
            if _read(source, handler, 8, "4s") == (b"vide",):
                video.append((track, media))
    if len(video) != 1:
        raise UpscaleError(REQUEST_INVALID)
    track, media = video[0]
    media_scale = _timescale(source, _child(source, media, b"mdhd"))
    sample_table = _child(source, _child(source, media, b"minf"), b"stbl")
    movie_start, media_start, duration = _first_video_edit(source, track)
    first_pts = _first_sample(source, sample_table, media_start)
    if media_start is None:
        return Fraction(first_pts, media_scale)
    movie_scale = _timescale(source, _child(source, movie, b"mvhd"))
    first_in_edit = Fraction(first_pts - media_start, media_scale)
    if first_in_edit >= Fraction(duration, movie_scale):
        raise UpscaleError(REQUEST_INVALID)
    return Fraction(movie_start, movie_scale) + first_in_edit
