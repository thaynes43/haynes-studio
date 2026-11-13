"""The whole-frame image-to-video adapter (story 427, contract sections 3 to 5).

- :mod:`.chain`: how a chain of clips becomes a board's frames (TIME-8), pure maths.
- :mod:`.source`: the :class:`~.source.ClipSource` interface, :func:`~.source.chain_seed`
  and :func:`~.source.last_frame_png`.
- :mod:`.fake`: :class:`~.fake.FakeClipSource`, small disposable clips for tests.
- :mod:`.clips`: :class:`~.clips.WholeFrameClips`, the clips as one cached artifact.
- :mod:`.renderer`: :class:`~.renderer.WholeFrameRenderer`, the segment renderer.
- :mod:`.checks`: :func:`~.checks.check_board`, the pre-build refusals.
- :mod:`.errors`: the codes.

The length policy itself is :func:`haynes_studio.render.clock.i2v_clip_lengths`.
Reference: ``docs/reference/whole-frame-adapter.md``.
"""

from __future__ import annotations

from haynes_studio.wholeframe.chain import Assembly, ClipUse, assemble
from haynes_studio.wholeframe.checks import check_board
from haynes_studio.wholeframe.clips import ADAPTER, SCHEMA, WholeFrameClips, production_reader
from haynes_studio.wholeframe.errors import WholeFrameError
from haynes_studio.wholeframe.renderer import COMPOSITOR, WholeFrameRenderer, fit_rule
from haynes_studio.wholeframe.source import (
    ClipRequest,
    ClipSource,
    ClipSpec,
    SourceClip,
    chain_seed,
    last_frame_png,
)

__all__ = [
    "ADAPTER", "Assembly", "COMPOSITOR", "ClipRequest", "ClipSource", "ClipSpec", "ClipUse",
    "SCHEMA", "SourceClip", "WholeFrameClips", "WholeFrameError", "WholeFrameRenderer",
    "assemble", "chain_seed", "check_board", "fit_rule", "last_frame_png", "production_reader",
]
