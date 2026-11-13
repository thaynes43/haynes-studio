"""The splice (story 380): the film picture from its ordered segments, by stream copy.

Each segment's packets are copied into one MP4, shifted by the frames before it
(``F[k]``, TIME-7), without decoding or re-encoding, so the film decodes to exactly
the segments' frames in order: a film spliced from cached segments decodes to the same
frames as one spliced from freshly rendered ones. Legacy did the same with ffmpeg's
concat demuxer and ``-c copy`` (``poc/layered_film.py``).

TIME-11 conservation is checked twice: each segment must hold exactly its board's
frames, and the written film must hold their sum. Segments must share one codec, frame
size, pixel format and parameter set (``splice.incompatible`` otherwise); a segment key
names the encoder settings and build, so cached segments of one film agree.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, BinaryIO

import av

from haynes_studio.render.encode import (
    as_source,
    stream_params,
    check_segment_stream,
    probe_segment,
)
from haynes_studio.render.errors import CONSERVATION, SPLICE_INCOMPATIBLE, CacheError
from haynes_studio.timebase import DELIVERY_FPS


@dataclass(frozen=True)
class SpliceInput:
    """One segment to splice: its bytes and the frames its board has."""

    source: bytes | BinaryIO
    frames: int
    label: str = "segment"


def splice(segments: Sequence[SpliceInput], *, fps: int = DELIVERY_FPS) -> bytes:
    """The film picture: every segment's packets in order, each segment shifted by the
    frames before it. Raises ``time.conservation`` when a segment does not hold its
    board's frames or the film does not hold their sum, and ``splice.incompatible``
    when segments cannot share one stream."""
    if not segments:
        raise CacheError(CONSERVATION, "a film has at least one segment")
    buffer = io.BytesIO()
    reference: dict[str, Any] | None = None
    offset = 0
    with av.open(buffer, mode="w", format="mp4") as film:
        out_stream = None
        for index, segment in enumerate(segments):
            where = f"{segment.label} {index}"
            with av.open(as_source(segment.source)) as container:
                stream, tick = check_segment_stream(container, fps=fps, where=where)
                params = stream_params(stream)
                if reference is None:
                    reference = params
                    out_stream = film.add_stream_from_template(stream)
                    out_stream.time_base = stream.time_base
                elif params != reference:
                    differs = sorted(name for name in params if params[name] != reference[name])
                    raise CacheError(SPLICE_INCOMPATIBLE, f"differs from the first segment in "
                                     f"{', '.join(differs)}", where=where)
                count = 0
                for packet in container.demux(stream):
                    if packet.size == 0:
                        continue
                    if packet.pts != count * tick or packet.dts != packet.pts:
                        raise CacheError(SPLICE_INCOMPATIBLE, f"packet {count} is not at frame "
                                         f"{count} (constant frame rate, no B-frames)", where=where)
                    packet.pts = packet.dts = (offset + count) * tick
                    packet.stream = out_stream
                    film.mux(packet)
                    count += 1
                if count != segment.frames:
                    raise CacheError(CONSERVATION, f"holds {count} frames, its board has "
                                     f"{segment.frames} (TIME-11)", where=where)
                offset += count
    data = buffer.getvalue()
    written = probe_segment(data, fps=fps, where="film picture").frames
    if written != offset:
        raise CacheError(CONSERVATION, f"the film holds {written} frames, its boards {offset} "
                         "(TIME-11)", where="film picture")
    return data
