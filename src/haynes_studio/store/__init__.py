"""The studio store (contract section 8, D39; story 379): media by content hash,
create-only atomic publication and stage completion records.

- :mod:`.layout`: the D39 layout, locators (``store.locator_invalid``), record paths.
- :mod:`.base`: the :class:`Store` and :class:`StageLedger` interfaces.
- :mod:`.local`: the ``local`` adapter (CLI and tests) and its read-only doctor.
- :mod:`.records`: :class:`Blob`, :class:`StageRecord` and canonical JSON.
- :mod:`.errors`: :class:`StoreError` and the error codes.

Nothing here deletes, purges, truncates or renames (D17). Reference:
``docs/reference/store-and-stages.md``.
"""

from __future__ import annotations

from haynes_studio.store.base import MISMATCH, MISSING, PRESENT, StageLedger, Store
from haynes_studio.store.errors import (
    BLOB_MISSING,
    COLLISION,
    HASH_MISMATCH,
    LOCATOR_INVALID,
    MEDIA_TYPE_UNSUPPORTED,
    RECORD_INVALID,
    StoreError,
)
from haynes_studio.store.layout import (
    EXTENSIONS,
    LIBRARY,
    Locator,
    blob_locator,
    is_locator,
    is_sha256,
    parse_locator,
    record_path,
)
from haynes_studio.store.local import DoctorReport, LocalStore
from haynes_studio.store.records import Blob, StageRecord, canonical_json

__all__ = [
    "BLOB_MISSING", "Blob", "COLLISION", "DoctorReport", "EXTENSIONS", "HASH_MISMATCH",
    "LIBRARY", "LOCATOR_INVALID", "LocalStore", "Locator", "MEDIA_TYPE_UNSUPPORTED",
    "MISMATCH", "MISSING", "PRESENT", "RECORD_INVALID", "StageLedger", "StageRecord",
    "Store", "StoreError", "blob_locator", "canonical_json", "is_locator", "is_sha256",
    "parse_locator", "record_path",
]
