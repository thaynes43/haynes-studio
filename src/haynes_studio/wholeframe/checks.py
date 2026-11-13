"""The whole-frame adapter's pre-build check of one board (story 427).

:func:`check_board` lists every reason the adapter would refuse a board, as
violations with JSON Pointers into the board, before any clip is asked for. The
build's pre-build check (story 406) can run it at ``queue_run``; the renderer and the
clip stage refuse the same things again, so nothing depends on it having run.
"""

from __future__ import annotations

from haynes_studio.canonical.model import Board, SoundCue
from haynes_studio.errors import Violation
from haynes_studio.render.clock import (
    I2V_CLIP_FRAMES,
    I2V_MAX_CLIPS,
    i2v_clip_lengths,
    source_frames_needed,
)
from haynes_studio.wholeframe.errors import (
    CHAIN_LIMIT,
    METHOD_UNAVAILABLE,
    PHOTO_ABSENT,
    STATUS,
    UNSUPPORTED,
)


def _violation(code: str, path: str, message: str) -> Violation:
    return Violation(code, path, message, STATUS[code])


def check_board(board: Board, *, frames: int | None, source_fps: int = 24,
                clip_frames: int = I2V_CLIP_FRAMES, max_clips: int = I2V_MAX_CLIPS) -> list[Violation]:
    """Why this adapter cannot build ``board``; empty when it can. ``frames`` is the
    board's frame count (TIME-3, TIME-4), or ``None`` for an untimed board, whose
    chain is checked once it is timed."""
    out: list[Violation] = []
    layer, motion = board.method.layer, board.method.motion
    if (layer, motion) == ("whole_frame", "s2v"):
        out.append(_violation(METHOD_UNAVAILABLE, "/method", "whole-frame speech-to-video has "
                              "no adapter (contract section 5)"))
    elif (layer, motion) != ("whole_frame", "i2v"):
        out.append(_violation(UNSUPPORTED, "/method", f"{layer}+{motion} is not a whole-frame I2V "
                              "board"))
    if board.photo.current_version_id is None:
        out.append(_violation(PHOTO_ABSENT, "/photo/current_version_id", "a whole-frame board "
                              "starts on its current photo version"))
    for index, cue in enumerate(board.cues):
        if not isinstance(cue, SoundCue):  # sound cues are the mix's, not the picture's
            out.append(_violation(UNSUPPORTED, f"/cues/{index}", f"a whole-frame board draws no "
                                  f"{cue.type} cue"))
    if frames is not None:
        needed = source_frames_needed(frames, source_fps)
        try:
            i2v_clip_lengths(needed, clip_frames, max_clips)
        except ValueError as error:
            out.append(_violation(CHAIN_LIMIT, "", str(error)))
    return out
