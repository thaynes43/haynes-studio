"""Media checks and the phone proxy (contract sections 3 and 8; story 381), on PyAV.

:func:`inspect` checks one MP4 against a delivery profile and returns every problem it
finds, each naming what was expected and what was there; it never raises for a bad or
unreadable file. It decodes every video and audio frame, so "decodable" and the frame
count are measured, not read from the container's header:

| Check | Expected |
|---|---|
| ``container`` | a readable file; MP4: an ``ftyp`` box first, not a QuickTime (``qt  ``) brand |
| ``streams`` | exactly one video and one audio stream, nothing else |
| ``video_codec``, ``pixel_format`` | H.264, ``yuv420p`` (proposal: what phones play; the PoC's masters) |
| ``frame_size`` | the profile's width x height |
| ``frame_rate`` | 24 fps, and decoded frame *i* at *i* / 24 s within half a frame (proposal) |
| ``frame_count`` | decoded frames equal the expected count (TIME-11) |
| ``duration`` | the video stream lasts expected / 24 s, within half a frame (TIME-11) |
| ``audio_codec``, ``audio_rate`` | AAC at 48 000 Hz (the mix rate, section 3) |
| ``audio_duration`` | expected x 2000 samples, both as recorded and as decoded, within a tolerance (one AAC frame of 1024 samples for a master, proposal; 0 for the proxy, whose length is exact) |
| ``audio_continuity`` | each decoded audio frame starts where the samples before it end, from 0, within one AAC frame (no hole, no late start) |
| ``decode`` | every packet decodes, and the decoder marks no video frame corrupt |
| ``bytes`` | under a limit, when the caller gives one (the proxy, P-10) |

H.264 has no checksum: damage the decoder cannot see (about half of single-packet
corruptions in a test) decodes without error. The SHA-256, not the decode, proves the
bytes are the ones the build made.

The audio tolerance is a proposal: TIME-11 makes the mix exactly ``frames x 2000``
samples, but AAC in MP4 records the stream's length at the encoder's granularity, and
the PoC cut its masters with ``-t`` at 4 decimals (a 1087-frame PoC-style master's
audio stream is 32 samples short).

:func:`make_proxy` encodes the phone proxy from a checked master: H.264 at the
profile's size, a capped bit rate so the size bound holds for any picture, AAC with
exactly ``frames x 2000`` samples, ``+faststart``. Decoders, the scaler and x264 are
given ``threads`` threads (2 in session pods and tests). PyAV's audio resampler and its
AAC encoder each build a libavfilter graph whose thread pool starts one thread per CPU;
no filter in those graphs is slice-threaded, so the pool stays idle. Measured in a
session pod: a 60 s proxy took 6.4 s and 10.2 s of CPU (1.6 cores), and the pool's
threads used none.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

import av
import numpy as np
from av.video.reformatter import VideoReformatter

from haynes_studio.delivery.model import (
    AAC,
    AUDIO_RATE,
    AUDIO_SAMPLES_PER_FRAME,
    FPS,
    H264,
)

PIXEL_FORMAT = "yuv420p"
AAC_FRAME = 1024  # samples in one AAC frame: the audio duration tolerance (proposal)
HALF_FRAME = Fraction(1, 2 * FPS)
FRAME = Fraction(1, FPS)
QUICKTIME_BRAND = b"qt  "

# The proxy encoder (proposal, story 381). The bit rate is capped (x264 VBV), so the
# proxy's size has an upper bound whatever the picture: video at most
# (maxrate x seconds + bufsize) / 8 bytes, audio about bitrate x seconds / 8. For 60 s
# that is 18 750 000 + 625 000 + 960 000 bytes, about 20.3 MB, under P-10's 25 000 000
# with room for the container. The CRF keeps simple pictures far below the cap.
PROXY_VIDEO_OPTIONS = {
    "preset": "veryfast",
    "crf": "23",
    "maxrate": "2500k",
    "bufsize": "5000k",
    "g": str(2 * FPS),  # a key frame every 2 s, for seeking on a phone
    "profile": "high",
}
PROXY_VIDEO_MAXRATE = 2_500_000  # bits per second
PROXY_VIDEO_BUFSIZE = 5_000_000  # bits
PROXY_AUDIO_BITRATE = 128_000  # bits per second, AAC-LC stereo
PROXY_AUDIO_LAYOUT = "stereo"


@dataclass(frozen=True, slots=True)
class Problem:
    """One failed check: ``check`` is a name from the table above."""

    check: str
    expected: str
    actual: str

    def __str__(self) -> str:
        return f"{self.check}: expected {self.expected}, got {self.actual}"


@dataclass(frozen=True, slots=True)
class MediaReport:
    """What :func:`inspect` measured, and every problem. ``frames`` is the number of
    video frames decoded; ``audio_samples`` the audio stream's recorded length and
    ``decoded_audio_samples`` the samples decoded, both at the stream's own rate."""

    brand: str | None
    video_codec: str | None
    audio_codec: str | None
    width: int | None
    height: int | None
    pixel_format: str | None
    frames: int
    audio_rate: int | None
    audio_samples: int | None
    decoded_audio_samples: int
    problems: tuple[Problem, ...]

    @property
    def ok(self) -> bool:
        return not self.problems


def _brand(path: str | os.PathLike[str]) -> bytes | None:
    """The major brand of a file whose first box is ``ftyp``, else ``None``."""
    with open(path, "rb") as handle:
        head = handle.read(12)
    if len(head) == 12 and head[4:8] == b"ftyp":
        return head[8:12]
    return None


def _brand_text(brand: bytes | None) -> str | None:
    return None if brand is None else brand.decode("latin-1")


def _seconds(value: Fraction) -> str:
    return f"{float(value):.4f} s"


def inspect(path: str | os.PathLike[str], *, width: int, height: int, expected_frames: int,
            threads: int = 2, max_bytes: int | None = None,
            audio_tolerance: int = AAC_FRAME) -> MediaReport:
    """Check the MP4 at ``path`` against a delivery profile: ``width`` x ``height`` at
    24 fps, ``expected_frames`` frames, H.264 and AAC with ``expected_frames x 2000``
    samples (within ``audio_tolerance``), and (when given) strictly fewer than
    ``max_bytes`` bytes. Every problem is reported; nothing is raised for a bad or
    unreadable file."""
    if isinstance(expected_frames, bool) or not isinstance(expected_frames, int) \
            or expected_frames < 1:
        raise ValueError(f"expected_frames must be a positive integer, got {expected_frames!r}")
    problems: list[Problem] = []
    found: dict[str, Any] = {"brand": None, "video_codec": None, "audio_codec": None,
                             "width": None, "height": None, "pixel_format": None,
                             "frames": 0, "audio_rate": None, "audio_samples": None,
                             "decoded_audio_samples": 0}
    try:
        size = os.stat(path).st_size
        brand = _brand(path)
    except OSError as error:
        problems.append(Problem("container", "a readable file", type(error).__name__))
        return _report(found, problems)
    if max_bytes is not None and size >= max_bytes:
        problems.append(Problem("bytes", f"under {max_bytes} bytes", f"{size} bytes"))
    found["brand"] = _brand_text(brand)
    if brand is None or brand == QUICKTIME_BRAND:
        problems.append(Problem("container", "MP4 (an ftyp box first, not QuickTime)",
                                "QuickTime" if brand == QUICKTIME_BRAND else "no ftyp box first"))
        return _report(found, problems)
    try:
        container = av.open(os.fspath(path), "r")
    except (av.FFmpegError, OSError, ValueError) as error:
        problems.append(Problem("decode", "a readable MP4", type(error).__name__))
        return _report(found, problems)
    with container:
        _check(container, problems, found, width=width, height=height,
               expected_frames=expected_frames, threads=threads,
               audio_tolerance=audio_tolerance)
    return _report(found, problems)


def _report(found: dict[str, Any], problems: list[Problem]) -> MediaReport:
    return MediaReport(problems=tuple(problems), **found)


def _check(container: Any, problems: list[Problem], found: dict[str, Any], *, width: int,
           height: int, expected_frames: int, threads: int, audio_tolerance: int) -> None:
    videos, audios = list(container.streams.video), list(container.streams.audio)
    others = len(container.streams) - len(videos) - len(audios)
    if (len(videos), len(audios), others) != (1, 1, 0):
        problems.append(Problem("streams", "one video and one audio stream",
                                f"{len(videos)} video, {len(audios)} audio, {others} other"))
    video = videos[0] if videos and videos[0].codec_context is not None else None
    audio = audios[0] if audios and audios[0].codec_context is not None else None
    if videos and video is None:
        problems.append(Problem("video_codec", H264, "a codec with no decoder"))
    if audios and audio is None:
        problems.append(Problem("audio_codec", AAC, "a codec with no decoder"))
    expected_samples = expected_frames * AUDIO_SAMPLES_PER_FRAME
    if video is not None:
        _video_header(video, problems, found, width, height, Fraction(expected_frames, FPS))
    if audio is not None:
        _audio_header(audio, problems, found, expected_samples, audio_tolerance)
    if video is None:
        return
    for stream in (video, audio):
        if stream is not None:
            stream.thread_type = "AUTO"
            stream.codec_context.thread_count = threads
    late: tuple[int, Fraction | None] | None = None
    corrupt: int | None = None
    gap: tuple[int, int | None] | None = None  # (samples decoded so far, the frame's start)
    decoded = 0
    try:
        for packet in container.demux(*(s for s in (video, audio) if s is not None)):
            for frame in packet.decode():
                if packet.stream is audio:
                    start = None if frame.pts is None else frame.pts * frame.time_base * AUDIO_RATE
                    if gap is None and (start is None or abs(start - decoded) >= AAC_FRAME):
                        gap = (decoded, None if start is None else int(start))
                    decoded += frame.samples
                    continue
                index = found["frames"]
                found["frames"] += 1
                if corrupt is None and frame.is_corrupt:
                    corrupt = index
                if late is None:
                    at = None if frame.pts is None else frame.pts * frame.time_base
                    if at is None or abs(at - index * FRAME) >= HALF_FRAME:
                        late = (index, at)
    except (av.FFmpegError, ValueError) as error:
        problems.append(Problem("decode", "every packet decodes",
                                f"{type(error).__name__} after {found['frames']} frames"))
    found["decoded_audio_samples"] = decoded
    if corrupt is not None:
        problems.append(Problem("decode", "every frame decodes undamaged",
                                f"frame {corrupt} marked corrupt by the decoder"))
    if late is not None:
        index, at = late
        problems.append(Problem("frame_rate", f"frame {index} at {_seconds(index * FRAME)}",
                                "no timestamp" if at is None else _seconds(at)))
    if found["frames"] != expected_frames:
        problems.append(Problem("frame_count", f"{expected_frames} frames",
                                f"{found['frames']} decoded"))
    if audio is not None and audio.codec_context.sample_rate == AUDIO_RATE:
        _decoded_audio(problems, decoded, gap, expected_samples, audio_tolerance)


def _decoded_audio(problems: list[Problem], decoded: int, gap: tuple[int, int | None] | None,
                   expected: int, tolerance: int) -> None:
    """The audio as decoded: continuous from 0 (each frame starts where the samples
    before it end, within one AAC frame), and ``expected`` samples long within the
    tolerance. The decoder returns whole AAC frames, so up to one frame of the
    encoder's end padding comes on top."""
    if gap is not None:
        at, start = gap
        problems.append(Problem("audio_continuity", f"audio continuous from 0: a frame at "
                                f"sample {at}", "no timestamp" if start is None
                                else f"a frame at sample {start}"))
    if not expected - tolerance <= decoded < expected + tolerance + AAC_FRAME:
        problems.append(Problem("audio_duration", f"{expected} samples decoded (within "
                                f"{tolerance}, plus one AAC frame of padding)",
                                f"{decoded} samples decoded"))


def _video_header(video: Any, problems: list[Problem], found: dict[str, Any], width: int,
                  height: int, expected_length: Fraction) -> None:
    context = video.codec_context
    found.update(video_codec=context.name, width=context.width, height=context.height,
                 pixel_format=context.pix_fmt)
    if context.name != H264:
        problems.append(Problem("video_codec", H264, str(context.name)))
    if context.pix_fmt != PIXEL_FORMAT:
        problems.append(Problem("pixel_format", PIXEL_FORMAT, str(context.pix_fmt)))
    if (context.width, context.height) != (width, height):
        problems.append(Problem("frame_size", f"{width}x{height}",
                                f"{context.width}x{context.height}"))
    rate = video.average_rate
    if rate is None or Fraction(rate) != FPS:
        problems.append(Problem("frame_rate", f"{FPS} fps",
                                "unknown" if rate is None else f"{float(rate):g} fps"))
    if video.duration is None or video.time_base is None:
        problems.append(Problem("duration", _seconds(expected_length), "no recorded duration"))
    else:
        length = video.duration * video.time_base
        if abs(length - expected_length) >= HALF_FRAME:
            problems.append(Problem("duration", _seconds(expected_length), _seconds(length)))


def _audio_header(audio: Any, problems: list[Problem], found: dict[str, Any], expected: int,
                  tolerance: int) -> None:
    context = audio.codec_context
    found.update(audio_codec=context.name, audio_rate=context.sample_rate)
    if context.name != AAC:
        problems.append(Problem("audio_codec", AAC, str(context.name)))
    if context.sample_rate != AUDIO_RATE:
        problems.append(Problem("audio_rate", f"{AUDIO_RATE} Hz", f"{context.sample_rate} Hz"))
    if audio.duration is None or audio.time_base is None:
        problems.append(Problem("audio_duration", f"{expected} samples", "no recorded duration"))
        return
    samples = audio.duration * audio.time_base * AUDIO_RATE
    found["audio_samples"] = int(samples)
    if abs(samples - expected) > tolerance:
        problems.append(Problem("audio_duration", f"{expected} samples (within {tolerance})",
                                f"{float(samples):.0f} samples"))


def make_proxy(source: str | os.PathLike[str], dest: str | os.PathLike[str], *, width: int,
               height: int, frames: int, threads: int = 2) -> None:
    """Encode the phone proxy of a checked master at ``source`` into a new file
    ``dest``: H.264 ``width`` x ``height`` at 24 fps with the first ``frames`` frames,
    and AAC stereo at 48 000 Hz with exactly ``frames x 2000`` samples (trimmed, or
    padded with silence). ``dest`` must not exist."""
    total = frames * AUDIO_SAMPLES_PER_FRAME
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # never an existing file
    os.close(fd)
    with av.open(os.fspath(source), "r") as master, \
            av.open(os.fspath(dest), "w", format="mp4",
                    options={"movflags": "+faststart"}) as proxy:
        video_in, audio_in = master.streams.video[0], master.streams.audio[0]
        for stream in (video_in, audio_in):
            stream.thread_type = "AUTO"
            stream.codec_context.thread_count = threads
        video = proxy.add_stream("libx264", rate=FPS, options=dict(PROXY_VIDEO_OPTIONS))
        video.width, video.height, video.pix_fmt = width, height, PIXEL_FORMAT
        video.codec_context.thread_count = threads
        audio = proxy.add_stream(AAC, rate=AUDIO_RATE, layout=PROXY_AUDIO_LAYOUT)
        audio.bit_rate = PROXY_AUDIO_BITRATE
        audio.codec_context.thread_count = 1
        resampler = av.AudioResampler(format="fltp", layout=PROXY_AUDIO_LAYOUT, rate=AUDIO_RATE)
        sink = _AudioSink(proxy, audio, total)
        scaler = VideoReformatter()  # one scaler, held to ``threads`` (the default is all CPUs)
        written = 0
        for packet in master.demux(video_in, audio_in):
            for frame in packet.decode():
                if packet.stream is audio_in:
                    for part in resampler.resample(frame):
                        sink.add(part.to_ndarray())
                elif written < frames:
                    picture = scaler.reformat(frame, width=width, height=height,
                                              format=PIXEL_FORMAT, interpolation="AREA",
                                              threads=threads)
                    picture.pts, picture.time_base = written, FRAME
                    written += 1
                    for out in video.encode(picture):
                        proxy.mux(out)
        for part in resampler.resample(None):
            sink.add(part.to_ndarray())
        for out in video.encode(None):
            proxy.mux(out)
        sink.finish()


class _AudioSink:
    """Feeds the AAC encoder 1024-sample frames, and exactly ``total`` samples."""

    def __init__(self, container: Any, stream: Any, total: int):
        self._container, self._stream, self._total = container, stream, total
        self._pending = np.zeros((2, 0), dtype=np.float32)
        self._sent = 0

    def add(self, samples: np.ndarray) -> None:
        room = self._total - self._sent - self._pending.shape[1]
        if room > 0:
            self._pending = np.concatenate([self._pending, samples[:, :room]], axis=1)
        while self._pending.shape[1] >= AAC_FRAME:
            self._send(self._pending[:, :AAC_FRAME])
            self._pending = self._pending[:, AAC_FRAME:]

    def finish(self) -> None:
        short = self._total - self._sent - self._pending.shape[1]
        if short > 0:
            silence = np.zeros((2, short), dtype=np.float32)
            self._pending = np.concatenate([self._pending, silence], axis=1)
        while self._pending.shape[1]:
            self._send(self._pending[:, :AAC_FRAME])
            self._pending = self._pending[:, AAC_FRAME:]
        for out in self._stream.encode(None):
            self._container.mux(out)

    def _send(self, samples: np.ndarray) -> None:
        frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(samples), format="fltp",
                                           layout=PROXY_AUDIO_LAYOUT)
        frame.sample_rate, frame.pts = AUDIO_RATE, self._sent
        frame.time_base = Fraction(1, AUDIO_RATE)
        self._sent += samples.shape[1]
        for out in self._stream.encode(frame):
            self._container.mux(out)


__all__ = [
    "AAC_FRAME", "MediaReport", "PIXEL_FORMAT", "PROXY_AUDIO_BITRATE", "PROXY_VIDEO_BUFSIZE",
    "PROXY_VIDEO_MAXRATE", "PROXY_VIDEO_OPTIONS", "Problem", "inspect", "make_proxy",
]
