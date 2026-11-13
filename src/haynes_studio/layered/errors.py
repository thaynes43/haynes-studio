"""Layered adapter codes (story 426).

Contract codes: ``time.source_short`` (TIME-8: a timed clip shorter than its board, or
a stored clip or keyed artifact that is missing or short, fails the stage; one that
does not decode is ``layered.clip_invalid``),
``method.unavailable`` (whole-frame + speech-to-video) and ``motion.clip_absent`` (a
cast still without a loop; story 457's code). The ``layered.*`` codes are **proposals**
of story 426, not yet in the rule index.

:class:`LayeredError` is a :class:`~haynes_studio.render.errors.CacheError`, so a build
that stops on cache errors stops on these too. Nothing is deleted, evicted,
overwritten, held or padded when one is raised.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from haynes_studio.errors import INVALID
from haynes_studio.render.errors import CacheError
from haynes_studio.store.errors import FAILED

UNAVAILABLE = "unavailable"

SOURCE_SHORT = "time.source_short"  # contract (TIME-8, P-05)
METHOD_UNAVAILABLE = "method.unavailable"  # contract: whole-frame + S2V
CLIP_ABSENT = "motion.clip_absent"  # story 457: a cast still with no loop
# Proposals (story 426):
UNSUPPORTED = "layered.unsupported"  # an input, profile or cue the adapter does not draw
CLIP_INVALID = "layered.clip_invalid"  # a source's answer or a stored artifact is not as asked
DECAL_WEAK = "layered.decal_weak"  # a decal track below the record's floor (the decal gate)
LAYOUT_INVALID = "layered.layout_invalid"  # a preset that cannot place a slot
DRIVE_INVALID = "layered.drive_invalid"  # takes that cannot make an exact drive track

STATUS = {
    SOURCE_SHORT: FAILED,
    METHOD_UNAVAILABLE: UNAVAILABLE,
    CLIP_ABSENT: INVALID,
    UNSUPPORTED: INVALID,
    CLIP_INVALID: FAILED,
    DECAL_WEAK: FAILED,
    LAYOUT_INVALID: INVALID,
    DRIVE_INVALID: INVALID,
}


class LayeredError(CacheError):
    """A layered refusal or failure with one of the codes above. ``check`` holds the
    check result of a failed gate (the decal gate), else None."""

    def __init__(self, code: str, message: str, *, where: str | None = None,
                 check: Mapping[str, Any] | None = None):
        super().__init__(code, message, where=where)
        self.status = STATUS.get(code, INVALID)
        self.check = check
