"""Store error codes and the error that carries one.

Contract codes (section 15): ``store.locator_invalid`` (invalid), ``store.collision``
(failed stage), ``id.malformed`` and ``id.type_mismatch`` (invalid). The other codes
are **proposals** of story 379, not yet in the rule index.
"""

from __future__ import annotations

from haynes_studio.errors import INVALID, Violation

FAILED = "failed"  # the contract's "failed stage" status

LOCATOR_INVALID = "store.locator_invalid"  # contract
COLLISION = "store.collision"  # contract
ID_MALFORMED = "id.malformed"  # contract
ID_TYPE_MISMATCH = "id.type_mismatch"  # contract
# Proposals (story 379):
HASH_MISMATCH = "store.hash_mismatch"  # bytes are not the hash they should be
BLOB_MISSING = "store.blob_missing"  # no file at a locator a record or a story needs
RECORD_INVALID = "store.record_invalid"  # a stage name, output set or record file is malformed
MEDIA_TYPE_UNSUPPORTED = "store.media_type_unsupported"  # no extension for the media type

STATUS = {
    LOCATOR_INVALID: INVALID,
    COLLISION: FAILED,
    ID_MALFORMED: INVALID,
    ID_TYPE_MISMATCH: INVALID,
    HASH_MISMATCH: FAILED,
    BLOB_MISSING: FAILED,
    RECORD_INVALID: INVALID,
    MEDIA_TYPE_UNSUPPORTED: INVALID,
}


class StoreError(Exception):
    """A store operation refused or failed with a rule code. ``locator`` (or a record
    path) names the file concerned, when there is one. Nothing is overwritten or
    removed when this is raised; a staging file the attempt made stays for
    ``store doctor`` to report (D17)."""

    def __init__(self, code: str, message: str, *, locator: str | None = None):
        self.code = code
        self.status = STATUS.get(code, INVALID)
        self.locator = locator
        self.message = message
        where = f" ({locator})" if locator else ""
        super().__init__(f"{code}{where}: {message}")

    def violation(self, path: str = "") -> Violation:
        return Violation(self.code, path, self.message, self.status)
