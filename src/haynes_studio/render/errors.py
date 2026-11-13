"""Cache, render and splice error codes (story 380). They live in ``render`` so the
render package never imports the cache; :mod:`haynes_studio.cache.errors` re-exports
them.

TIME-11 says a frame mismatch fails the run but names no code; every code here is a
**proposal** of story 380, not yet in the contract's rule index.
"""

from __future__ import annotations

from haynes_studio.errors import INVALID, Violation
from haynes_studio.store.errors import FAILED

KEY_INPUT_INVALID = "cache.key_input_invalid"  # a key input is not a hash, int, text or JSON value
ENTRY_INVALID = "cache.entry_invalid"  # a completed stage at a key's name is not that key's entry
FRAME_COUNT = "render.frame_count"  # a renderer gave more or fewer frames than the board has
FRAME_INVALID = "render.frame_invalid"  # a frame is not uint8 RGB of the board's size
SPLICE_INCOMPATIBLE = "splice.incompatible"  # segments that cannot be joined by stream copy
CONSERVATION = "time.conservation"  # TIME-11: segment, board and film frames disagree

STATUS = {
    KEY_INPUT_INVALID: INVALID,
    ENTRY_INVALID: FAILED,
    FRAME_COUNT: FAILED,
    FRAME_INVALID: FAILED,
    SPLICE_INCOMPATIBLE: FAILED,
    CONSERVATION: FAILED,
}


class CacheError(Exception):
    """A key, cache, render or splice step refused with a rule code. Nothing is
    deleted, evicted or overwritten when this is raised (D17)."""

    def __init__(self, code: str, message: str, *, where: str | None = None):
        self.code = code
        self.status = STATUS.get(code, INVALID)
        self.where = where
        self.message = message
        suffix = f" ({where})" if where else ""
        super().__init__(f"{code}{suffix}: {message}")

    def violation(self, path: str = "") -> Violation:
        return Violation(self.code, path, self.message, self.status)
