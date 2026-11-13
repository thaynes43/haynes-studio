"""The renderer interface for one board's picture segment (story 380).

A renderer turns one segment key's inputs into the board's frames, in board-clock
order, frame 0 first. It is given the segment key document and nothing else about the
story: no film frame, no film offset, no neighbouring board (P-06). Input bytes the key
names by hash (stills, clips, keyed frames) are read through ``open_input``.

The cache, not the renderer, encodes the frames, publishes the segment and decides
whether to render at all; a real renderer (stories 426 and 427) plugs in here without
touching the cache.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, BinaryIO

import numpy as np


@dataclass(frozen=True)
class SegmentRequest:
    """One board's segment to render: its key, its key document and its frame size.
    ``frames``, ``width``, ``height`` and ``fps`` are read from the document."""

    key: str
    inputs: Mapping[str, Any] = field(repr=False)
    open_input: Callable[[str], BinaryIO] | None = field(default=None, repr=False, compare=False)

    @property
    def frames(self) -> int:
        return self.inputs["frames"]

    @property
    def width(self) -> int:
        return self.inputs["width"]

    @property
    def height(self) -> int:
        return self.inputs["height"]

    @property
    def fps(self) -> int:
        return self.inputs["fps"]

    def open(self, sha256: str) -> BinaryIO:
        """The bytes of an input the key names by hash."""
        if self.open_input is None:
            raise LookupError("this request carries no input reader")
        return self.open_input(sha256)


class SegmentRenderer(ABC):
    """Draws one board's segment. ``compositor`` is the digest the segment key names
    (contract section 4: "compositor digest"); two renderers that may draw differently
    must have different digests."""

    compositor: str

    @abstractmethod
    def render(self, request: SegmentRequest) -> Iterable[np.ndarray]:
        """Exactly ``request.frames`` frames, each ``uint8`` RGB of shape
        ``(height, width, 3)``, board frame 0 first."""
