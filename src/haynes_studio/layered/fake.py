"""A fake speech-to-video source with small disposable clips (story 426), for tests and
dry runs. Nothing here calls a service.

Frame 0 of a clip is the start image (at the profile's size), as the engine's is; frame
*n* is drawn by ``draw(n, start)`` (default: the start image with a square that moves
with *n*, so every frame differs), and carries a small mark in its top-left corner, in a
green shade of the request's key, so another request gives another clip (a key-green
mark, which the keyer removes). Like the E0 engine it may deliver more frames than
requested (``extra``, E0: 154 asked, 158 returned). Faults for tests: ``deliver`` sets
the frame count, ``start_sha256`` and ``drive_sha256`` report other inputs, ``seed``
another seed, ``size`` another size, ``data`` other bytes.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import PIL.Image

from haynes_studio.layered.source import S2VClip, S2VRequest, S2VSource
from haynes_studio.render.encode import EncoderSettings, encode_segment

ENGINE = "fake-s2v/1"
FILES = {"fake-s2v.safetensors": "0" * 64}

Draw = Callable[[int, np.ndarray], np.ndarray]


def moving_square(n: int, start: np.ndarray) -> np.ndarray:
    frame = start.copy()
    height, width = frame.shape[:2]
    size = max(2, width // 10)
    x = (n * 3) % max(1, width - size)
    frame[height - size:height, x:x + size] = (250, 250, 250)
    return frame


@dataclass
class FakeS2VSource(S2VSource):
    """Deterministic synthetic clips (see the module docstring). ``calls`` lists every
    request, so a test can tell that a second build asked for nothing."""

    draw: Draw = moving_square
    extra: int = 0
    deliver: int | None = None
    start_sha256: str | None = None
    drive_sha256: str | None = None
    seed: int | None = None
    size: tuple[int, int] | None = None
    data: bytes | None = None
    name: str = "studio.layered.fake-s2v/1"
    calls: list[S2VRequest] = field(default_factory=list)

    def generate(self, request: S2VRequest) -> S2VClip:
        self.calls.append(request)
        width, height = self.size or tuple(request.profile["size"])
        with PIL.Image.open(io.BytesIO(request.start_image)) as image:
            start = np.asarray(image.convert("RGB").resize((width, height), PIL.Image.Resampling.BICUBIC))
        count = request.frames + self.extra if self.deliver is None else self.deliver

        shade = 150 + int(hashlib.sha256(request.key.encode()).hexdigest()[:2], 16) % 100

        def frames():
            for n in range(count):
                if n == 0:
                    yield start
                    continue
                frame = np.array(self.draw(n, start), dtype=np.uint8)
                frame[:4, :4] = (30, shade, 40)
                yield frame
        data = self.data if self.data is not None else encode_segment(
            frames(), frames_expected=count, width=width, height=height,
            fps=request.profile["source_fps"], settings=EncoderSettings())
        return S2VClip(
            data=data, seed=request.seed if self.seed is None else self.seed,
            frames_requested=request.frames,
            start_image_sha256=self.start_sha256 or request.start_image_sha256,
            drive_track_sha256=self.drive_sha256 or request.drive_track_sha256,
            engine=ENGINE, engine_job_id="fake-" + hashlib.sha256(request.key.encode()).hexdigest()[:12],
            files_sha256=dict(FILES), extra={"render_s": 0})


__all__ = ["ENGINE", "FILES", "FakeS2VSource", "moving_square"]
