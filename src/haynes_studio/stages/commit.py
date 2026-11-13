"""Stage commit (contract section 8): a multi-file stage publishes all its blobs, then
one create-only completion record listing every hash. Readers trust only completed
stages.

Order is the whole guarantee. Every blob is published (``fsync``, ``link``, directory
``fsync``) before the record is written, so a record never names a missing blob; a
failure before the record leaves only orphan blobs and staging leftovers, which no
reader trusts and ``store doctor`` reports. A retried or concurrent commit of the same
outputs writes the same record bytes and succeeds; one with other outputs ends in
``store.collision`` and the finished record stays as it was.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from haynes_studio.store import (
    BLOB_MISSING,
    HASH_MISMATCH,
    LOCATOR_INVALID,
    MISSING,
    PRESENT,
    RECORD_INVALID,
    StageLedger,
    StageRecord,
    Store,
    StoreError,
)
from haynes_studio.store.base import Source, check_source
from haynes_studio.store.layout import (
    check_production_id,
    check_run_id,
    check_stage,
    extension,
    is_sha256,
)
from haynes_studio.store.records import check_name


@dataclass(frozen=True)
class StageOutput:
    """One file a stage produced: its bytes (bytes, a ``pathlib.Path`` or a binary
    file object), its validated media type and, when the producer knows it, the hash
    the bytes must have."""

    source: Source
    media_type: str
    expected_sha256: str | None = None


def commit_stage(store: Store, *, production_id: str, run_id: str, stage: str,
                 outputs: Mapping[str, StageOutput],
                 ledger: StageLedger | None = None) -> StageRecord:
    """Publish every output into the production's folder, in name order, then record
    the stage as complete. ``ledger`` defaults to ``store`` (the local adapter keeps
    both). IDs, the stage name, output names, media types, sources and expected
    hashes are checked before anything is written."""
    if ledger is None:
        if not isinstance(store, StageLedger):
            raise TypeError("this store keeps no stage records; pass a ledger")
        ledger = store
    check_production_id(production_id)
    check_run_id(run_id)
    check_stage(stage)
    if not outputs:
        raise StoreError(RECORD_INVALID, "a stage commits at least one output")
    for name, output in outputs.items():
        check_name(name)
        extension(output.media_type)
        check_source(output.source)
        if output.expected_sha256 is not None and not is_sha256(output.expected_sha256):
            raise StoreError(LOCATOR_INVALID, f"output {name!r}: expected_sha256 must be 64 "
                             f"lower-case hex digits, got {output.expected_sha256!r}")
    blobs = {name: store.publish(outputs[name].source, scope=production_id,
                                 media_type=outputs[name].media_type,
                                 expected_sha256=outputs[name].expected_sha256)
             for name in sorted(outputs)}
    return ledger.complete_stage(StageRecord(production_id=production_id, run_id=run_id,
                                             stage=stage, blobs=blobs))


def completed_stage(ledger: StageLedger, *, production_id: str, run_id: str, stage: str,
                    store: Store | None = None) -> StageRecord | None:
    """The stage's record if it completed, else ``None``: the only way a reader should
    find a stage's blobs. A :class:`~haynes_studio.store.LocalStore` ledger already
    re-hashes every blob the record lists (reading each in full). With ``store``, every
    blob is also re-hashed through the store, for a ledger that cannot see the blobs
    (``store.blob_missing`` or ``store.hash_mismatch`` if one is not as recorded)."""
    record = ledger.stage_record(production_id, run_id, stage)
    if record is None or store is None:
        return record
    for name, blob in record.blobs.items():
        state = store.verify(blob.locator, blob.sha256)
        if state != PRESENT:
            code = BLOB_MISSING if state == MISSING else HASH_MISMATCH
            raise StoreError(code, f"output {name!r} of the completed stage is {state}",
                             locator=blob.locator)
    return record
