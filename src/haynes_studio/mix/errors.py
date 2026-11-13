"""The sound and master error codes (story 841).

The contract's own codes are used where they fit: ``cue.out_of_range`` (TIME-10) and
``time.conservation`` (TIME-11). The rest are **proposals** of story 841, not yet in the
contract's rule index. The store's codes (``store.blob_missing``,
``store.hash_mismatch``) and the cache's (``cache.entry_invalid``,
``cache.key_input_invalid``) are raised as those modules raise them.
"""

from __future__ import annotations

from haynes_studio.errors import INVALID, Violation
from haynes_studio.store.errors import FAILED

CUE_OUT_OF_RANGE = "cue.out_of_range"  # TIME-10: a sound starts outside its board or the film
CONSERVATION = "time.conservation"  # TIME-11: mix length or master frames disagree
INPUT_INVALID = "mix.input_invalid"  # a track, sound or bed the mixer cannot use as keyed
MASTER_INVALID = "mix.master_invalid"  # the muxed master fails story 381's media checks
CHECK_FAILED = "mix.check_failed"  # a sound check did not pass

STATUS = {
    CUE_OUT_OF_RANGE: INVALID,
    CONSERVATION: FAILED,
    INPUT_INVALID: FAILED,
    MASTER_INVALID: FAILED,
    CHECK_FAILED: FAILED,
}


class MixError(Exception):
    """The mix or the master refused with a rule code. Nothing is published when this
    is raised before a commit, and nothing is ever deleted or overwritten (D17)."""

    def __init__(self, code: str, message: str, *, where: str | None = None):
        self.code = code
        self.status = STATUS.get(code, INVALID)
        self.where = where
        self.message = message
        suffix = f" ({where})" if where else ""
        super().__init__(f"{code}{suffix}: {message}")

    def violation(self, path: str = "") -> Violation:
        return Violation(self.code, path, self.message, self.status)
