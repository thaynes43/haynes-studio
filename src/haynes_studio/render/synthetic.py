"""A deterministic synthetic renderer for tests (story 380).

It draws a pattern from the segment key's inputs only, so any change to an input
changes the picture and nothing else can:

- the background colour comes from the key (every input feeds it);
- a band of bars spells the board frame number in binary, and a second band 12 bits of
  the key, both readable after lossy encoding (:func:`read_code`), so a test can tell
  which board and which board frame a decoded film frame shows;
- a square bounces with the first looping layer's phase (TIME-8a), and a few dots fall
  where the board's procedural stream puts them (P-06).

No film frame or offset is ever an input. Frames are small numpy arrays; this is a
test fixture, not a compositor.
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np

from haynes_studio.render.base import SegmentRenderer, SegmentRequest
from haynes_studio.render.clock import loop_frame, stream_random

BITS = 12  # bars per band: board frames up to 4095, 12 bits of the key
SQUARE = 48
DOTS = 4
LOOP_LENGTH = 24  # the synthetic square's ping-pong loop, in frames


def fingerprint(key: str) -> int:
    """The 12 key bits the second band shows."""
    return int(key.removeprefix("sha256:")[:3], 16)


def _bars(frame: np.ndarray, value: int, top: int, height: int) -> None:
    width = frame.shape[1] // BITS
    for bit in range(BITS):
        on = (value >> (BITS - 1 - bit)) & 1
        frame[top:top + height, bit * width:(bit + 1) * width] = 255 if on else 0


def read_code(frame: np.ndarray) -> tuple[int, int]:
    """``(board frame, key fingerprint)`` read back from a drawn (and possibly lossy
    re-decoded) frame: the mean of each bar's middle, thresholded at half."""
    height = frame.shape[0] // 8
    width = frame.shape[1] // BITS
    values = []
    for band in range(2):
        value, top = 0, band * height
        for bit in range(BITS):
            patch = frame[top + height // 4:top + 3 * height // 4,
                          bit * width + width // 4:(bit + 1) * width - width // 4]
            value = (value << 1) | int(patch.mean() > 127)
        values.append(value)
    return values[0], values[1]


class SyntheticRenderer(SegmentRenderer):
    """Draws a key-derived pattern (see the module docstring)."""

    compositor = "studio.render.synthetic/1"

    def render(self, request: SegmentRequest) -> Iterator[np.ndarray]:
        width, height, frames = request.width, request.height, request.frames
        if frames >= 1 << BITS:
            raise ValueError(f"the synthetic renderer draws at most {(1 << BITS) - 1} frames")
        digest = bytes.fromhex(request.key.removeprefix("sha256:"))
        background = np.array(list(digest[:3]), dtype=np.uint8) // 2 + 64
        band = height // 8
        phases = [layer["phase"] for layer in request.inputs.get("layers", ())
                  if layer.get("phase") is not None]
        phase = phases[0] if phases else 0
        stream = request.inputs.get("procedural_stream", 0)
        span_x, span_y = width - SQUARE, height - 2 * band - SQUARE
        for n in range(frames):
            frame = np.empty((height, width, 3), dtype=np.uint8)
            frame[:] = background
            _bars(frame, n, 0, band)
            _bars(frame, fingerprint(request.key), band, band)
            step = loop_frame(n, phase, LOOP_LENGTH)
            x = step * span_x // (LOOP_LENGTH - 1)
            frame[2 * band + span_y // 2:2 * band + span_y // 2 + SQUARE, x:x + SQUARE] = list(digest[3:6])
            for dot in range(DOTS):
                draw = stream_random(stream, n * DOTS + dot)
                dx, dy = draw % (width - 8), 2 * band + (draw >> 20) % (height - 2 * band - 8)
                frame[dy:dy + 8, dx:dx + 8] = 255
            yield frame
