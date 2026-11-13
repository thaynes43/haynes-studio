"""How a chain of whole-frame clips becomes a board's frames (story 427): pure maths.

A chain is the clips of one whole-frame clip artifact, in order. Every clip after the
first starts on the previous clip's last frame (E0: ``s1-wf-x1`` started from
``s1-wf-a-last.png``), so its first frame is a duplicate and is dropped; the chain is
then one run of distinct source frames on the source clock. TIME-8 maps the board
onto it: board frame ``n`` shows source frame ``floor(n * fs / 24)``, a board of ``F``
frames needs ``floor((F - 1) * fs / 24) + 1`` of them, and the rest are trimmed and
recorded. Fewer is ``time.source_short``; nothing is held or padded (P-05).

The requested lengths come from :func:`haynes_studio.render.clock.i2v_clip_lengths`;
this module only reads what the clips delivered.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from haynes_studio.render.clock import source_frame, source_frames_needed
from haynes_studio.timebase import DELIVERY_FPS
from haynes_studio.wholeframe.errors import SOURCE_SHORT, WholeFrameError


@dataclass(frozen=True)
class ClipUse:
    """What one clip of a chain gives a board."""

    index: int
    delivered: int  # frames the clip holds
    dropped: int  # 1 for a chained clip: its first frame repeats the previous clip's last
    offered: int  # distinct frames it adds to the chain: delivered - dropped
    used: int  # of those, frames inside the board's span (source frame < needed)
    trimmed: int  # offered - used: frames after the board's last needed source frame

    def to_document(self) -> dict[str, int]:
        return {"index": self.index, "delivered": self.delivered, "dropped": self.dropped,
                "offered": self.offered, "used": self.used, "trimmed": self.trimmed}


@dataclass(frozen=True)
class Assembly:
    """A board's frames from a chain: the TIME-8 span and each clip's share of it."""

    frames: int  # board frames, F
    source_fps: int
    fps: int
    needed: int  # TIME-8 source frames needed
    available: int  # distinct frames the chain holds
    clips: tuple[ClipUse, ...]

    @property
    def trimmed(self) -> int:
        """Source frames after the board's span, trimmed (TIME-8: trimmed and recorded)."""
        return self.available - self.needed

    def locate(self, source_index: int) -> tuple[int, int]:
        """``(clip, frame within that clip)`` of a source frame of the chain."""
        start = 0
        for clip in self.clips:
            if source_index < start + clip.offered:
                return clip.index, source_index - start + clip.dropped
            start += clip.offered
        raise IndexError(source_index)

    def picks(self) -> Iterator[tuple[int, int]]:
        """For board frames 0 to F-1 in order: the clip and the frame within it shown."""
        for n in range(self.frames):
            yield self.locate(source_frame(n, self.source_fps, self.fps))

    def to_document(self) -> dict[str, Any]:
        return {"frames": self.frames, "source_fps": self.source_fps, "fps": self.fps,
                "needed": self.needed, "available": self.available, "trimmed": self.trimmed,
                "clips": [clip.to_document() for clip in self.clips]}


def assemble(frames: int, delivered: Sequence[int], *, source_fps: int,
             fps: int = DELIVERY_FPS) -> Assembly:
    """The assembly of a board of ``frames`` frames from clips that delivered
    ``delivered`` frames each, in chain order. ``time.source_short`` when a clip is
    empty or the chain holds fewer distinct frames than TIME-8 needs."""
    needed = source_frames_needed(frames, source_fps, fps)
    if not delivered:
        raise WholeFrameError(SOURCE_SHORT, "no clip: the board's picture has no source")
    uses, start = [], 0
    for index, count in enumerate(delivered):
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise WholeFrameError(SOURCE_SHORT, f"clip {index} delivered {count!r} frames")
        dropped = 1 if index else 0
        offered = count - dropped
        used = max(0, min(offered, needed - start))
        uses.append(ClipUse(index=index, delivered=count, dropped=dropped, offered=offered,
                            used=used, trimmed=offered - used))
        start += offered
    if start < needed:
        raise WholeFrameError(SOURCE_SHORT, f"the chain holds {start} source frames; a board of "
                              f"{frames} frames needs {needed} (TIME-8)")
    return Assembly(frames=frames, source_fps=source_fps, fps=fps, needed=needed,
                    available=start, clips=tuple(uses))
