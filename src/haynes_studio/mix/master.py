"""The master (story 841): the film picture and the mix in one MP4.

Legacy muxed with ``ffmpeg -c:v copy -c:a aac -b:a 192k -t <total> -movflags
+faststart`` (``poc/edit.py``, ``mux``). Here the picture's packets are copied as they
are (no decode, no re-encode, so the master decodes to exactly the film picture's
frames), and the mix, exactly ``frames x 2000`` samples, is encoded as AAC-LC stereo at
48 000 Hz and 192 kbit/s, with the MP4 movie timescale at 48 000 so the audio's
recorded length is exact. Before anything is returned the master is checked with
story 381's :func:`haynes_studio.delivery.media.inspect` at the picture's own size:
the frames, the audio length within one AAC frame (TIME-11), the codecs, continuity
and decoding. A master that fails is never returned, so it is never cached.
"""

from __future__ import annotations

import io
import os
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

import av
import numpy as np

from haynes_studio.delivery.media import AAC_FRAME, inspect
from haynes_studio.mix.audio import THREADS, read_pcm
from haynes_studio.mix.errors import CONSERVATION, MASTER_INVALID, MixError
from haynes_studio.render.encode import encoder_build, probe_segment
from haynes_studio.timebase import DELIVERY_FPS, MIX_RATE, SAMPLES_PER_FRAME

# Checks of story 381's inspect that say the master does not conserve time (TIME-11).
_TIME_CHECKS = {"frame_count", "duration", "audio_duration", "audio_continuity", "frame_rate"}


@dataclass(frozen=True)
class MuxSettings:
    """How the master is muxed (legacy values; the encoder build is a proposal, as for
    segments). :meth:`key_inputs` is the master key's ``mux`` input."""

    container: str = "mp4"
    video: str = "copy"
    audio_codec: str = "aac"
    audio_bitrate: int = 192_000
    audio_layout: str = "stereo"
    audio_rate: int = MIX_RATE
    faststart: bool = True
    # Proposal: the MP4 edit lists in samples, so the audio's recorded length is exactly
    # frames x 2000 (the muxer's default, 1000, rounds it down to a whole ms: 32 samples
    # short at 223 frames, as the PoC's 1087-frame masters were).
    movie_timescale: int = MIX_RATE
    threads: int = THREADS

    def key_inputs(self) -> dict[str, Any]:
        return {"container": self.container, "video": self.video, "audio": self.audio_codec,
                "audio_bitrate": self.audio_bitrate, "audio_layout": self.audio_layout,
                "audio_rate": self.audio_rate, "faststart": self.faststart,
                "movie_timescale": self.movie_timescale, "threads": self.threads,
                "build": encoder_build()}


MUX = MuxSettings()


@dataclass(frozen=True)
class MasterResult:
    """The master's bytes and what its check measured."""

    data: bytes
    frames: int
    width: int
    height: int
    audio_samples: int | None
    decoded_audio_samples: int


def _audio_packets(container: Any, stream: Any, samples: np.ndarray) -> list[Any]:
    """The mix encoded as AAC, in 1024-sample frames from sample 0."""
    planar = np.ascontiguousarray(samples.T, dtype=np.float32)
    packets = []
    for start in range(0, planar.shape[1], AAC_FRAME):
        frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(planar[:, start:start + AAC_FRAME]),
                                           format="fltp", layout=stream.layout.name)
        frame.sample_rate, frame.pts = MIX_RATE, start
        frame.time_base = Fraction(1, MIX_RATE)
        packets.extend(stream.encode(frame))
    packets.extend(stream.encode(None))
    return packets


def mux(picture: bytes, mix_wav: bytes, *, settings: MuxSettings = MUX,
        workdir: str | os.PathLike[str] | None = None) -> MasterResult:
    """Mux the film ``picture`` (H.264 MP4, video only) with ``mix_wav`` (48 000 Hz
    stereo PCM of exactly ``frames x 2000`` samples) and check the result. Raises
    ``time.conservation`` when the picture and the mix disagree on the film's length, or
    the master does not hold them; ``mix.master_invalid`` for any other failed check.
    ``workdir`` holds one scratch file while the master is checked (the system temporary
    folder by default); it is removed afterwards."""
    info = probe_segment(picture, fps=DELIVERY_FPS, where="film picture")
    pcm = read_pcm(mix_wav, where="mix")
    if (pcm.rate, pcm.channels) != (settings.audio_rate, 2):
        raise MixError(MASTER_INVALID, f"the mix is {pcm.rate} Hz with {pcm.channels} "
                       f"channels, the master takes {settings.audio_rate} Hz stereo", where="mix")
    expected = info.frames * SAMPLES_PER_FRAME
    if pcm.samples.shape[0] != expected:
        raise MixError(CONSERVATION, f"the mix has {pcm.samples.shape[0]} samples, the "
                       f"picture's {info.frames} frames need {expected} (TIME-11)", where="mix")
    options = {"movie_timescale": str(settings.movie_timescale)}
    if settings.faststart:
        options["movflags"] = "+faststart"
    # The mp4 muxer's faststart pass re-reads its output by name: one private file.
    with tempfile.TemporaryDirectory(prefix="studio-master-", dir=workdir) as scratch:
        path = os.path.join(scratch, "master.mp4")
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        with av.open(io.BytesIO(picture), "r") as source, \
                av.open(path, "w", format=settings.container, options=options) as out:
            _write(source, out, pcm.samples, settings)
        with open(path, "rb") as handle:
            data = handle.read()
        report = inspect(path, width=info.width, height=info.height,
                         expected_frames=info.frames, threads=settings.threads)
    if report.problems:
        code = (CONSERVATION if any(p.check in _TIME_CHECKS for p in report.problems)
                else MASTER_INVALID)
        raise MixError(code, "; ".join(str(p) for p in report.problems), where="master")
    return MasterResult(data=data, frames=report.frames, width=info.width, height=info.height,
                        audio_samples=report.audio_samples,
                        decoded_audio_samples=report.decoded_audio_samples)


def _write(source: Any, out: Any, samples: np.ndarray, settings: MuxSettings) -> None:
    """The picture's packets as they are, and the mix as AAC, interleaved by time."""
    video_in = source.streams.video[0]
    video = out.add_stream_from_template(video_in)
    video.time_base = video_in.time_base
    audio = out.add_stream(settings.audio_codec, rate=settings.audio_rate,
                           layout=settings.audio_layout)
    audio.bit_rate = settings.audio_bitrate
    audio.codec_context.thread_count = 1
    audio_packets = _audio_packets(out, audio, samples)
    video_packets = [packet for packet in source.demux(video_in) if packet.size]
    queue = sorted(
        [(Fraction(p.dts * video_in.time_base), 0, i, p) for i, p in enumerate(video_packets)]
        + [(Fraction(p.pts * p.time_base), 1, i, p) for i, p in enumerate(audio_packets)],
        key=lambda item: item[:3])
    for _, kind, _, packet in queue:
        packet.stream = video if kind == 0 else audio
        out.mux(packet)
