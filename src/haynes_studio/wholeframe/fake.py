"""A fake clip source with small disposable clips (story 427), for tests and dry runs.

It makes each clip as a live source would, in chain order: clip 0 from the photo,
clip *k* from :func:`~.source.last_frame_png` of clip *k - 1*, whose decoded pixels are
its frame 0, so the chain boundary really repeats a frame. Every other frame is drawn
in memory and carries two bands of bars (the layout
:func:`haynes_studio.render.synthetic.read_code` reads after lossy encoding):

- band 0: the frame's index within its clip;
- band 1: :func:`marker` of the clip index and seed.

Clips are H.264 at the profile's ``size`` and ``source_fps``, encoded at two threads.
Nothing here calls a service. Faults for tests: ``deliver`` makes clip *i* hold that
many frames, ``omit`` leaves clip *i* out of the answer, ``start_sha256`` reports
another start image for clip *i*.
"""

from __future__ import annotations

import io
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field

import numpy as np
import PIL.Image

from haynes_studio.render.encode import EncoderSettings, encode_segment
from haynes_studio.wholeframe.source import (
    ClipRequest,
    ClipSource,
    SourceClip,
    last_frame_png,
    sha256_hex,
)

BITS = 12  # bars per band, as render.synthetic
ENGINE = "fake-i2v/1"
FILES = {"fake-i2v.safetensors": "0" * 64}


def marker(index: int, seed: int) -> int:
    """Band 1 of a fake frame: ``(index + 1) << 8 | seed & 0xFF`` (12 bits)."""
    return ((index + 1) << 8 | seed & 0xFF) & ((1 << BITS) - 1)


def _bars(frame: np.ndarray, value: int, band: int) -> None:
    height, width = frame.shape[0] // 8, frame.shape[1] // BITS
    top = band * height
    for bit in range(BITS):
        on = (value >> (BITS - 1 - bit)) & 1
        frame[top:top + height, bit * width:(bit + 1) * width] = 255 if on else 0


def draw(index: int, seed: int, number: int, width: int, height: int) -> np.ndarray:
    """Frame ``number`` of fake clip ``index``: a seed-and-index colour, the two bands
    and a square that moves with the frame number."""
    frame = np.empty((height, width, 3), dtype=np.uint8)
    frame[:] = (64 + (seed * 37 + index * 53) % 128, 96 + (index * 41) % 96, 160 - (seed % 64))
    _bars(frame, number, 0)
    _bars(frame, marker(index, seed), 1)
    size = max(2, width // 8)
    x = (number * 7) % max(1, width - size)
    frame[height // 2:height // 2 + size, x:x + size] = (250, 200, 40)
    return frame


@dataclass
class FakeClipSource(ClipSource):
    """Deterministic synthetic clips (see the module docstring). ``calls`` lists every
    request, so a test can tell that a second build asked for nothing."""

    deliver: Mapping[int, int] = field(default_factory=dict)
    omit: frozenset[int] = frozenset()
    start_sha256: Mapping[int, str] = field(default_factory=dict)
    name: str = "studio.wholeframe.fake/1"
    calls: list[ClipRequest] = field(default_factory=list)

    def generate(self, request: ClipRequest) -> list[SourceClip]:
        self.calls.append(request)
        width, height = request.profile["size"]
        fps = request.profile["source_fps"]
        clips, previous = [], None
        for spec in request.clips:
            start = request.photo_sha256
            first = None
            if previous is not None:
                png = last_frame_png(previous)
                start = sha256_hex(png)
                with PIL.Image.open(io.BytesIO(png)) as image:
                    first = np.asarray(image.convert("RGB"))
            count = self.deliver.get(spec.index, spec.frames)

            def frames(spec=spec, first=first, count=count) -> Iterator[np.ndarray]:
                for number in range(count):
                    yield first if number == 0 and first is not None else draw(
                        spec.index, spec.seed, number, width, height)
            data = encode_segment(frames(), frames_expected=count, width=width, height=height,
                                  fps=fps, settings=EncoderSettings())
            previous = data
            if spec.index in self.omit:
                continue
            clips.append(SourceClip(
                index=spec.index, data=data, seed=spec.seed, frames_requested=spec.frames,
                start_image_sha256=self.start_sha256.get(spec.index, start), engine=ENGINE,
                engine_job_id=f"fake-{sha256_hex(request.key.encode())[:12]}-{spec.index}",
                files_sha256=dict(FILES), extra={"render_s": 0}))
        return clips
