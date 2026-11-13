"""Segment encoding and decoding (story 380), through PyAV at two threads.

A segment is one board's picture: H.264 in MP4, video only, constant frame rate, every
packet's decode time equal to its presentation time (no B-frames), first frame an IDR.
That is what lets :mod:`haynes_studio.render.splice` join segments by stream copy, as
the legacy layered film did with ffmpeg's concat demuxer.

What a segment key assumes about the encoder: the settings below, the thread count and
mode, and the encoder build (the PyAV and libavcodec versions, which pin the bundled
x264) are key inputs, so another build or setting never reuses a segment. Encoded bytes
may still differ between builds and are never compared; decoded frames are, and H.264
decoding is exact.

x264 runs **sliced** threads (each frame cut into one slice per thread), which give the
same bytes for the same frames every time. Its default frame threading, as the legacy
``ffmpeg -threads 2`` used, does not: in this pod 25 encodes of one synthetic segment
gave three different outputs. A full render must reproduce a cached segment exactly,
so the cache uses sliced threads (**proposal**).
"""

from __future__ import annotations

import io
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, BinaryIO

import av
import numpy as np

from haynes_studio.render.errors import (
    FRAME_COUNT,
    FRAME_INVALID,
    SPLICE_INCOMPATIBLE,
    CacheError,
)

THREADS = 2  # contract section 14: encoders at two threads


def encoder_build() -> str:
    """The encoder build a segment key names: PyAV's version and libavcodec's."""
    major, minor, micro = av.library_versions["libavcodec"]
    return f"pyav-{av.__version__}/libavcodec-{major}.{minor}.{micro}"


@dataclass(frozen=True)
class EncoderSettings:
    """Segment encoder settings (**proposal**: the legacy per-shot settings, libx264
    ``fast`` at CRF 18 in yuv420p on two threads, plus sliced threads, no B-frames and
    a two-second keyframe interval)."""

    codec: str = "libx264"
    pix_fmt: str = "yuv420p"
    crf: int = 18
    preset: str = "fast"
    gop: int = 48
    threads: int = THREADS

    def options(self) -> dict[str, str]:
        return {"crf": str(self.crf), "preset": self.preset, "g": str(self.gop), "bf": "0",
                "threads": str(self.threads),
                "x264-params": f"threads={self.threads}:sliced-threads=1:bframes=0"}

    def key_inputs(self) -> dict[str, Any]:
        """The settings as a segment key input, with the encoder build."""
        return {"codec": self.codec, "pix_fmt": self.pix_fmt, "crf": self.crf,
                "preset": self.preset, "gop": self.gop, "bframes": 0, "threads": self.threads,
                "threading": "sliced", "container": "mp4", "build": encoder_build()}


def _check_frame(frame: Any, index: int, width: int, height: int) -> np.ndarray:
    if not isinstance(frame, np.ndarray) or frame.dtype != np.uint8 or frame.shape != (height, width, 3):
        shape = getattr(frame, "shape", None)
        raise CacheError(FRAME_INVALID, f"frame {index} is not uint8 RGB {height}x{width}x3 "
                         f"(got {type(frame).__name__} {shape})")
    return np.ascontiguousarray(frame)


def encode_segment(frames: Iterable[np.ndarray], *, frames_expected: int, width: int, height: int,
                   fps: int, settings: EncoderSettings) -> bytes:
    """Encode exactly ``frames_expected`` RGB frames (board clock order) as one
    segment. More or fewer frames is ``render.frame_count``; a frame of another shape
    or type is ``render.frame_invalid``."""
    buffer = io.BytesIO()
    count = 0
    with av.open(buffer, mode="w", format="mp4") as container:
        stream = container.add_stream(settings.codec, rate=fps)
        stream.width, stream.height, stream.pix_fmt = width, height, settings.pix_fmt
        stream.codec_context.time_base = Fraction(1, fps)
        stream.codec_context.thread_count = settings.threads
        stream.options = settings.options()
        for frame in frames:
            if count >= frames_expected:
                raise CacheError(FRAME_COUNT, f"the renderer gave more than {frames_expected} frames")
            video = av.VideoFrame.from_ndarray(_check_frame(frame, count, width, height), format="rgb24")
            video.pts = count
            for packet in stream.encode(video):
                container.mux(packet)
            count += 1
        if count != frames_expected:
            raise CacheError(FRAME_COUNT, f"the renderer gave {count} frames, the board has {frames_expected}")
        for packet in stream.encode():
            container.mux(packet)
    return buffer.getvalue()


def as_source(data: bytes | BinaryIO) -> BinaryIO:
    return io.BytesIO(data) if isinstance(data, bytes | bytearray | memoryview) else data


def decode_frames(data: bytes | BinaryIO) -> Iterator[np.ndarray]:
    """Every frame of a video, decoded to RGB at two threads, in order."""
    with av.open(as_source(data)) as container:
        stream = container.streams.video[0]
        stream.codec_context.thread_count = THREADS
        for frame in container.decode(stream):
            yield frame.to_ndarray(format="rgb24")


@dataclass(frozen=True)
class SegmentInfo:
    """What a splice needs to know about one segment, read from its packets."""

    frames: int
    width: int
    height: int
    pix_fmt: str
    codec: str
    extradata: bytes
    time_base: Fraction


def stream_params(stream: Any) -> dict[str, Any]:
    context = stream.codec_context
    return {"width": context.width, "height": context.height, "pix_fmt": context.pix_fmt,
            "codec": context.name, "extradata": bytes(context.extradata or b"")}


def check_segment_stream(container: Any, *, fps: int, where: str) -> tuple[Any, int]:
    """The one video stream of a segment and its frame tick (in its time base), or
    ``splice.incompatible``: a segment has exactly one stream, a video stream whose
    time base divides one frame into whole ticks."""
    if len(container.streams) != 1 or len(container.streams.video) != 1:
        raise CacheError(SPLICE_INCOMPATIBLE, "a segment has exactly one stream, a video one",
                         where=where)
    stream = container.streams.video[0]
    tick = Fraction(1, fps) / stream.time_base
    if tick.denominator != 1:
        raise CacheError(SPLICE_INCOMPATIBLE, f"time base {stream.time_base} does not divide a "
                         f"frame at {fps} fps", where=where)
    return stream, int(tick)


def probe_segment(data: bytes | BinaryIO, *, fps: int, where: str = "segment") -> SegmentInfo:
    """Count a segment's packets and check its timing: packet *i* is presented and
    decoded at frame *i* (constant frame rate, no reordering)."""
    with av.open(as_source(data)) as container:
        stream, tick = check_segment_stream(container, fps=fps, where=where)
        count = 0
        for packet in container.demux(stream):
            if packet.size == 0:
                continue
            if packet.pts != count * tick or packet.dts != packet.pts:
                raise CacheError(SPLICE_INCOMPATIBLE, f"packet {count} is not at frame {count} "
                                 "(constant frame rate, no B-frames)", where=where)
            count += 1
        params: Mapping[str, Any] = stream_params(stream)
        return SegmentInfo(frames=count, time_base=stream.time_base, **params)
