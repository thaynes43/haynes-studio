"""Audio in and out for the mixer (story 841), on the locked PyAV build and numpy.

Every filter runs in a libavfilter graph held to two threads (contract section 14), in
process: the pod has no system ffmpeg, and the legacy mixer's filters (``aresample``
through ``av.AudioResampler``, ``volume``, ``alimiter`` and the R128 meter of
``loudnorm``) are the same libavfilter code. Samples are ``float32`` arrays shaped
``(samples, channels)``. Nothing here reads a file by name: every input is bytes.
"""

from __future__ import annotations

import io
import math
import wave
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

import av
import numpy as np
from av.filter import Graph

from haynes_studio.mix.errors import INPUT_INVALID, MixError
from haynes_studio.timebase import MIX_RATE

THREADS = 2  # contract section 14: filters and coders at two threads
CHUNK = 4096  # samples pushed into a graph per frame
FULL_SCALE_24 = 8_388_607  # largest positive 24-bit PCM code
METER_FLUSH = 9_600  # two 100 ms meter steps of silence, so the true peak sees the end
STEREO = "stereo"
_LAYOUTS = {1: "mono", 2: STEREO}


def filter_build() -> str:
    """The filter build the mixer's version names: PyAV's version, libavfilter's and
    libswresample's (resampler, limiter and loudness meter live there)."""
    f = av.library_versions["libavfilter"]
    s = av.library_versions["libswresample"]
    return (f"pyav-{av.__version__}/libavfilter-{f[0]}.{f[1]}.{f[2]}"
            f"/libswresample-{s[0]}.{s[1]}.{s[2]}")


def _frames(samples: np.ndarray, rate: int) -> Iterable[av.AudioFrame]:
    """``samples`` (n, channels) as packed ``flt`` frames of :data:`CHUNK` samples."""
    channels = samples.shape[1]
    layout = _LAYOUTS[channels]
    data = np.ascontiguousarray(samples, dtype=np.float32)
    for start in range(0, data.shape[0], CHUNK):
        part = data[start:start + CHUNK]
        frame = av.AudioFrame.from_ndarray(part.reshape(1, -1), format="flt", layout=layout)
        frame.sample_rate, frame.pts, frame.time_base = rate, start, Fraction(1, rate)
        yield frame


def _as_array(frame: av.AudioFrame) -> np.ndarray:
    """A pulled ``flt`` (packed) frame as (n, channels) float32."""
    channels = len(frame.layout.channels)
    return frame.to_ndarray().reshape(-1, channels).astype(np.float32, copy=False)


def _drain(graph: Graph, out: list[np.ndarray], last: list[Any]) -> None:
    while True:
        try:
            frame = graph.pull()
        except (av.BlockingIOError, av.EOFError):
            return
        out.append(_as_array(frame))
        if frame.metadata:  # a meter's reading: keep the latest one
            last[:] = [frame]


def run_filters(samples: np.ndarray, rate: int, chain: Sequence[tuple[str, str]], *,
                where: str) -> tuple[np.ndarray, av.AudioFrame | None]:
    """Run ``samples`` at ``rate`` through the filter ``chain`` (name, arguments), and
    return the output as packed ``flt`` (n, channels), with the last frame pulled
    that carried metadata (a meter's latest reading). The graph is held to
    :data:`THREADS` threads. A filter that refuses its arguments or its input is
    ``mix.input_invalid``."""
    if samples.ndim != 2 or samples.shape[1] not in _LAYOUTS:
        raise MixError(INPUT_INVALID, f"audio is mono or stereo, got shape {samples.shape}",
                       where=where)
    out: list[np.ndarray] = []
    last: list[Any] = []
    try:
        graph = Graph()
        graph.threads = THREADS
        node = graph.add_abuffer(format="flt", sample_rate=rate,
                                 layout=_LAYOUTS[samples.shape[1]], time_base=Fraction(1, rate))
        for name, args in (*chain, ("aformat", "sample_fmts=flt")):
            step = graph.add(name, args)
            node.link_to(step)
            node = step
        sink = graph.add("abuffersink")
        node.link_to(sink)
        graph.configure()
        for frame in _frames(samples, rate):
            graph.push(frame)
            _drain(graph, out, last)
        graph.push(None)
        _drain(graph, out, last)
    except (av.FFmpegError, ValueError) as error:
        raise MixError(INPUT_INVALID, f"the filters {[name for name, _ in chain]} refused: "
                       f"{type(error).__name__}", where=where) from None
    channels = samples.shape[1] if not out else out[0].shape[1]
    result = np.concatenate(out) if out else np.zeros((0, channels), np.float32)
    return result, (last[0] if last else None)


def to_mix_rate(samples: np.ndarray, rate: int, *, where: str) -> np.ndarray:
    """``samples`` at ``rate`` as 48 000 Hz stereo: libswresample, as the legacy
    ``read_audio`` (``av.AudioResampler(format='fltp', layout='stereo', rate=48000)``)."""
    if rate == MIX_RATE and samples.shape[1] == 2:
        return np.ascontiguousarray(samples, dtype=np.float32)
    out, _ = run_filters(samples, rate, (("aresample", str(MIX_RATE)),
                                         ("aformat", "channel_layouts=stereo")), where=where)
    return out


def decode_audio(data: bytes, *, where: str) -> np.ndarray:
    """The first audio stream of ``data`` (any container PyAV reads: WAV, MP4) as
    48 000 Hz stereo float32, every frame decoded."""
    try:
        with av.open(io.BytesIO(data), "r") as container:
            if not container.streams.audio:
                raise MixError(INPUT_INVALID, "no audio stream", where=where)
            stream = container.streams.audio[0]
            stream.codec_context.thread_count = THREADS
            graph = Graph()
            graph.threads = THREADS
            source = graph.add_abuffer(template=stream)
            chain = [graph.add("aresample", str(MIX_RATE)),
                     graph.add("aformat", "sample_fmts=flt:channel_layouts=stereo")]
            sink = graph.add("abuffersink")
            node = source
            for step in (*chain, sink):
                node.link_to(step)
                node = step
            graph.configure()
            out: list[np.ndarray] = []
            last: list[Any] = []
            for frame in container.decode(stream):
                graph.push(frame)
                _drain(graph, out, last)
            graph.push(None)
            _drain(graph, out, last)
    except (av.FFmpegError, ValueError, IndexError) as error:
        raise MixError(INPUT_INVALID, f"cannot decode audio: {type(error).__name__}",
                       where=where) from None
    return np.concatenate(out) if out else np.zeros((0, 2), np.float32)


@dataclass(frozen=True)
class Pcm:
    """A PCM WAV read with :mod:`wave`: its rate, channels, sample width and samples
    as float32 (n, channels) on the -1..1 scale of its width."""

    rate: int
    channels: int
    width: int
    samples: np.ndarray


def read_pcm(data: bytes, *, where: str) -> Pcm:
    """A 16-bit or 24-bit PCM WAV (a voice track, the mix)."""
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            rate, channels, width, count = (w.getframerate(), w.getnchannels(),
                                            w.getsampwidth(), w.getnframes())
            raw = w.readframes(count)
    except (wave.Error, EOFError) as error:
        raise MixError(INPUT_INVALID, f"not a PCM WAV: {error}", where=where) from None
    if len(raw) != count * width * channels:
        raise MixError(INPUT_INVALID, f"the WAV holds {len(raw)} bytes of samples, its header "
                       f"says {count * width * channels}", where=where)
    if width == 2:
        ints = np.frombuffer(raw, dtype="<i2").astype(np.int32)
        scale = 32768.0
    elif width == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        ints = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        ints = np.where(ints >= 1 << 23, ints - (1 << 24), ints)
        scale = 8388608.0
    else:
        raise MixError(INPUT_INVALID, f"PCM is 16 or 24 bits, got {8 * width}", where=where)
    samples = (ints.astype(np.float32) / np.float32(scale)).reshape(-1, channels)
    return Pcm(rate=rate, channels=channels, width=width, samples=samples)


def quantize_24(samples: np.ndarray) -> np.ndarray:
    """Float samples to 24-bit codes: rounded to nearest, clipped to full scale."""
    codes = np.rint(samples.astype(np.float64) * FULL_SCALE_24)
    return np.clip(codes, -FULL_SCALE_24 - 1, FULL_SCALE_24).astype(np.int32)


def write_wav24(samples: np.ndarray, rate: int = MIX_RATE) -> bytes:
    """48 000 Hz stereo float samples as a 24-bit PCM WAV (the legacy soundtrack's
    ``pcm_s24le``). The same samples always give the same bytes."""
    codes = quantize_24(samples).astype("<i4")
    packed = codes.reshape(-1).view(np.uint8).reshape(-1, 4)[:, :3].tobytes()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(samples.shape[1])
        w.setsampwidth(3)
        w.setframerate(rate)
        w.writeframes(packed)
    return buffer.getvalue()


@dataclass(frozen=True)
class Loudness:
    """R128 integrated loudness (LUFS) and true peak (dBTP) of a programme; ``None``
    where the programme is silent (no gated block, or a zero peak)."""

    integrated_lufs: float | None
    true_peak_dbtp: float | None


def _reading(samples: np.ndarray, name: str, where: str) -> float:
    _, last = run_filters(samples, MIX_RATE, (("ebur128", "metadata=1:peak=true"),),
                          where=where)
    try:
        return float(dict(last.metadata)[name]) if last is not None else float("nan")
    except (KeyError, ValueError):
        raise MixError(INPUT_INVALID, "the loudness meter gave no reading", where=where) from None


def measure(samples: np.ndarray, *, where: str) -> Loudness:
    """Integrated loudness and true peak of 48 000 Hz stereo ``samples``, by
    libavfilter's ``ebur128`` meter (ITU-R BS.1770, gated; true peak by 4x
    oversampling). Legacy read the same quantities from ``loudnorm``'s first pass
    (``input_i``, ``input_tp``).

    The meter reports on the frame that crosses each 100 ms step, so its last reading
    covers the programme up to its last whole step: exactly the gated blocks BS.1770
    counts, which is the integrated loudness read here. The true peak is read from a
    second pass with :data:`METER_FLUSH` samples of silence after the programme, so it
    covers every sample to the end (silence adds no peak)."""
    if samples.shape[0] == 0:
        return Loudness(None, None)
    integrated = _reading(samples, "lavfi.r128.I", where)
    flushed = np.concatenate([samples, np.zeros((METER_FLUSH, samples.shape[1]), np.float32)])
    peak = _reading(flushed, "lavfi.r128.true_peak", where)
    lufs = integrated if math.isfinite(integrated) and integrated > -70.0 else None
    dbtp = 20 * math.log10(peak) if peak > 0 and math.isfinite(peak) else None
    return Loudness(lufs, dbtp)

