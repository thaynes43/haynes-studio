"""The layered adapter's pre-build check of one board (story 426).

:func:`check_board` lists every reason the adapter would refuse a board, as violations
with JSON Pointers into the board (the set's into the story), before any clip is asked
for. Story 406 runs it at ``queue_run``; the plan, the stages and the renderer refuse
the same things again, so nothing depends on it having run.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from haynes_studio.canonical.model import Board, CameraCue, MoveCue, Story
from haynes_studio.errors import Violation
from haynes_studio.layered import compose
from haynes_studio.layered.errors import (
    LAYOUT_INVALID,
    METHOD_UNAVAILABLE,
    STATUS,
    UNSUPPORTED,
    LayeredError,
)


def _violation(code: str, path: str, message: str) -> Violation:
    return Violation(code, path, message, STATUS[code])


def check_board(story: Story, board: Board, *, motion: Any | None = None) -> list[Violation]:
    """Why this adapter cannot build ``board``; empty when it can. ``motion`` is the
    board's ``BoardMotion`` from :func:`~.pin.pin_board`; its problems are reported as
    they are (``motion.clip_absent`` and story 457's other codes)."""
    out: list[Violation] = []
    layer, mode = board.method.layer, board.method.motion
    if (layer, mode) == ("whole_frame", "s2v"):
        out.append(_violation(METHOD_UNAVAILABLE, "/method", "whole-frame speech-to-video has no "
                              "adapter (contract section 5)"))
    elif layer != "layered" or mode not in ("s2v", "i2v"):
        out.append(_violation(UNSUPPORTED, "/method", f"{layer}+{mode} is not a layered board"))
        return out
    if not board.cast:
        out.append(_violation(UNSUPPORTED, "/cast", "a layered board has at least one cast member "
                              "(method.layered_needs_cast)"))
    if story.set is None or (story.set.asset_version_id is None
                             and story.set.motion_asset_version_id is None):
        out.append(_violation(UNSUPPORTED, "/set", "a layered board draws on the story's set plate "
                              "or set loop"))
    layout: Mapping[str, Any] | None = story.layouts.get(board.layout.preset)
    if layout is None:
        out.append(_violation(LAYOUT_INVALID, "/layout/preset", f"preset {board.layout.preset!r} "
                              "is not in the story"))
    else:
        for index, entry in enumerate(board.cast):
            try:
                compose.slot_of(layout, entry.slot)
            except LayeredError as error:
                out.append(_violation(error.code, f"/cast/{index}", error.message))
    slots = {entry.slot for entry in board.cast}
    cameras = 0
    for index, cue in enumerate(board.cues):
        if isinstance(cue, MoveCue) and cue.slot not in slots:
            out.append(_violation(UNSUPPORTED, f"/cues/{index}", f"a move of slot {cue.slot!r}, "
                                  "which is not on the board"))
        elif isinstance(cue, CameraCue):
            cameras += 1
            if cue.easing not in compose.EASINGS:
                out.append(_violation(UNSUPPORTED, f"/cues/{index}", f"easing {cue.easing!r} is "
                                      "not drawn"))
            if cameras > 1:
                out.append(_violation(UNSUPPORTED, f"/cues/{index}", "one camera cue per board, "
                                      "as legacy (proposal)"))
    if motion is not None:
        out.extend(motion.problems)
    return out


__all__ = ["check_board"]
