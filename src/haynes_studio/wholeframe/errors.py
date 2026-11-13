"""Whole-frame adapter codes (story 427).

Contract codes (section 15): ``method.unavailable`` (whole-frame + speech-to-video,
refused at Build), ``photo.absent`` (no current photo version, invalid at queue) and
``time.source_short`` (TIME-8: a missing or short clip fails the stage). The
``wholeframe.*`` codes are **proposals** of story 427, not yet in the rule index.

:class:`WholeFrameError` is a :class:`~haynes_studio.render.errors.CacheError`, so a
build that already stops on cache errors stops on these too. Nothing is deleted,
evicted, overwritten, held or padded when one is raised.
"""

from __future__ import annotations

from haynes_studio.errors import INVALID
from haynes_studio.render.errors import CacheError
from haynes_studio.store.errors import FAILED

UNAVAILABLE = "unavailable"

METHOD_UNAVAILABLE = "method.unavailable"  # contract: whole-frame + S2V
PHOTO_ABSENT = "photo.absent"  # contract: a whole-frame board with no current photo
SOURCE_SHORT = "time.source_short"  # contract: a clip is missing, short or undecodable
# Proposals (story 427):
UNSUPPORTED = "wholeframe.unsupported"  # an input or cue the adapter does not draw
CHAIN_LIMIT = "wholeframe.chain_limit"  # a board needs more chained clips than the limit
CLIP_INVALID = "wholeframe.clip_invalid"  # a clip source's answer is not what was asked

STATUS = {
    METHOD_UNAVAILABLE: UNAVAILABLE,
    PHOTO_ABSENT: INVALID,
    SOURCE_SHORT: FAILED,
    UNSUPPORTED: INVALID,
    CHAIN_LIMIT: INVALID,
    CLIP_INVALID: FAILED,
}


class WholeFrameError(CacheError):
    """A whole-frame refusal or failure with one of the codes above."""

    def __init__(self, code: str, message: str, *, where: str | None = None):
        super().__init__(code, message, where=where)
        self.status = STATUS.get(code, INVALID)
