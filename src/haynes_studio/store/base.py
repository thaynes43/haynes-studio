"""The store interface (contract section 8, D39): blobs by content hash, and the
ledger of completed stages.

Two adapters share the blob interface: ``local`` (the CLI and tests,
:class:`~haynes_studio.store.local.LocalStore`) and ``nfs`` (the installed product,
story 434, not built here). In the product the ledger is a Postgres row; the local
adapter keeps it as a create-only JSON file. Nothing in either interface deletes,
truncates, renames or overwrites (D17).
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import BinaryIO

from haynes_studio.store.records import Blob, StageRecord

Source = bytes | bytearray | memoryview | os.PathLike[str] | BinaryIO
"""What :meth:`Store.publish` streams: bytes, a local file path (a ``pathlib.Path``,
never a plain ``str``) or a binary file object opened for reading."""

PRESENT = "present"
MISSING = "missing"
MISMATCH = "mismatch"  # a file is there, but not those bytes (or not a regular file)


class Store(ABC):
    """Content-addressed, create-only blob storage."""

    @abstractmethod
    def publish(self, source: Source, *, scope: str, media_type: str,
                expected_sha256: str | None = None) -> Blob:
        """Publish one blob atomically and create-only (section 8, steps 1 to 4) under
        ``scope`` (``"library"`` or a production ID). Same bytes again succeed;
        ``store.collision`` if other bytes hold the path; ``store.hash_mismatch`` if
        ``expected_sha256`` is given and differs."""

    @abstractmethod
    def verify(self, locator: str, sha256: str) -> str:
        """:data:`PRESENT`, :data:`MISSING` or :data:`MISMATCH` for the blob at
        ``locator`` against ``sha256`` (re-hashed). ``store.locator_invalid`` for a
        locator outside the layout."""

    @abstractmethod
    def open(self, locator: str) -> BinaryIO:
        """The blob's bytes, read-only. ``store.blob_missing`` if absent."""


class StageLedger(ABC):
    """Completion records: readers trust only stages that have one."""

    @abstractmethod
    def complete_stage(self, record: StageRecord) -> StageRecord:
        """Record a stage as complete, create-only. The same record again succeeds; a
        different record for that stage is ``store.collision`` and changes nothing.
        Every blob it lists must already be published."""

    @abstractmethod
    def stage_record(self, production_id: str, run_id: str, stage: str) -> StageRecord | None:
        """The completed stage's record, or ``None`` if the stage has not completed."""
