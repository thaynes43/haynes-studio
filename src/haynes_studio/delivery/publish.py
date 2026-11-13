"""Delivering a finished master (contract section 8, story 381): check it, make and
check the phone proxy, publish both through the store, and complete one stage whose
record lists the master, the proxy and the delivery document.

    delivery = deliver(Path("job/final.mp4"), store=LocalStore(root),
                       production_id=prd, run_id=run, expected_frames=1087)

Order is the guarantee. Nothing is written to the store until the master and the
proxy have passed every check (:func:`haynes_studio.delivery.media.inspect`). Then the
master and the proxy are published (create-only, by content hash, re-hashed in
place), then the delivery document as a JSON blob, then the stage's completion record
(``stage`` ``delivery``), which re-hashes all three. Readers trust only a completed
stage (:func:`read_delivery`), so a delivery is either complete and verified, or
absent; a crash before the record leaves only orphan blobs and staging leftovers,
which no reader trusts and ``store doctor`` lists (D17: nothing is removed).

- **Idempotent.** A run has one delivery. Delivering the same master again (same
  bytes, frame count and media kind) returns the completed delivery unchanged and
  writes nothing. Another master for a delivered run is ``store.collision``.
- **Concurrent.** Two deliveries of one run race to the record's create-only link;
  the loser finds the winner's record and returns it if it holds the same master,
  else ``store.collision``. The finished record is never changed.

Nothing here deletes, replaces or renames a store file. The proxy is encoded in a
private scratch folder outside the store (in ``workdir``, else the system's temporary
folder), which is removed when the delivery returns (proposal).
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from haynes_studio.canonical.ids import Minter, is_id
from haynes_studio.canonical.validate import READ, WRITE
from haynes_studio.delivery.errors import (
    MASTER_CHANGED,
    MASTER_INVALID,
    NOT_VERIFIED,
    PROXY_INVALID,
    RECORD_INVALID,
    DeliveryError,
)
from haynes_studio.delivery.media import inspect, make_proxy
from haynes_studio.delivery.model import (
    AAC,
    DELIVERY_SCHEMA,
    FPS,
    H264,
    LOCAL,
    MASTER_SIZES,
    MP4,
    NFS,
    PROXY_SIZES,
    Delivery,
    media_kind_of,
    proxy_byte_limit,
)
from haynes_studio.delivery.validate import validate_delivery
from haynes_studio.jsonio import parse_strict
from haynes_studio.stages import completed_stage
from haynes_studio.store import (
    COLLISION,
    PRESENT,
    Blob,
    LocalStore,
    StageLedger,
    StageRecord,
    Store,
    StoreError,
    canonical_json,
)
from haynes_studio.store.layout import check_production_id, check_run_id

STAGE = "delivery"
MASTER, PROXY, RECORD = "master", "proxy", "delivery"  # the stage's output names
JSON = "application/json"
RECORD_MAX_BYTES = 1 << 20  # a delivery document is about 1.5 KB

_CHUNK = 1 << 20


def deliver(master: os.PathLike[str], *, store: Store, production_id: str, run_id: str,
            expected_frames: int, media_kind: str = "short",
            ledger: StageLedger | None = None, delivery_id: str | None = None,
            now: datetime | None = None, threads: int = 2,
            workdir: os.PathLike[str] | None = None) -> Delivery:
    """Deliver the finished master at ``master`` for run ``run_id``: the master must be
    ``media_kind``'s frame size at 24 fps with exactly ``expected_frames`` frames (the
    sum of the run's board frames, TIME-11). Returns the completed delivery.

    ``ledger`` defaults to ``store`` (the local adapter keeps both). ``delivery_id`` and
    ``now`` are minted and read from the clock unless given. Encoders and decoders use
    at most ``threads`` threads."""
    ledger = _ledger(store, ledger)
    check_production_id(production_id)
    check_run_id(run_id)
    adapter = _adapter(store)
    if media_kind not in MASTER_SIZES:
        raise ValueError(f"media_kind must be one of {', '.join(MASTER_SIZES)}, got {media_kind!r}")
    if isinstance(expected_frames, bool) or not isinstance(expected_frames, int) \
            or expected_frames < 1:
        raise ValueError(f"expected_frames must be a positive integer, got {expected_frames!r}")
    if delivery_id is not None and not is_id(delivery_id, "dlv"):
        raise ValueError(f"delivery_id must be a dlv_ ID, got {delivery_id!r}")
    if not isinstance(master, os.PathLike):
        raise TypeError("pass the master as a pathlib.Path")
    if isinstance(threads, bool) or not isinstance(threads, int) or threads < 1:
        raise ValueError(f"threads must be a positive integer, got {threads!r}")
    created_at = _timestamp(now)

    # O_NONBLOCK: a FIFO in the master's place cannot hang the open.
    fd = os.open(master, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise DeliveryError(MASTER_INVALID, "the master is not a regular file; nothing "
                                "was published")
    except BaseException:
        os.close(fd)
        raise
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(fd)
        sha256, _ = _hash(handle)
        existing = read_delivery(store, production_id=production_id, run_id=run_id,
                                 ledger=ledger)
        if existing is not None:
            return _same(existing, sha256, expected_frames, media_kind)
        # Decode the inode this process holds open, never the name again.
        source = f"/proc/self/fd/{fd}"
        width, height = MASTER_SIZES[media_kind]
        report = inspect(source, width=width, height=height, expected_frames=expected_frames,
                         threads=threads)
        if not report.ok:
            raise DeliveryError(MASTER_INVALID, f"the master is not a {media_kind} master of "
                                f"{expected_frames} frames; nothing was published",
                                report.problems)
        with tempfile.TemporaryDirectory(prefix="studio-delivery-", dir=workdir) as scratch:
            proxy_path = Path(scratch) / "proxy.mp4"
            proxy_width, proxy_height = PROXY_SIZES[media_kind]
            make_proxy(source, proxy_path, width=proxy_width, height=proxy_height,
                       frames=expected_frames, threads=threads)
            limit = proxy_byte_limit(expected_frames)
            proxy_report = inspect(proxy_path, width=proxy_width, height=proxy_height,
                                   expected_frames=expected_frames, threads=threads,
                                   max_bytes=limit)
            if not proxy_report.ok:
                raise DeliveryError(PROXY_INVALID, "the proxy made from the master failed its "
                                    "checks; nothing was published", proxy_report.problems)
            _unchanged(before, os.fstat(fd))
            handle.seek(0)
            master_blob = store.publish(handle, scope=production_id, media_type=MP4,
                                        expected_sha256=sha256)
            with open(proxy_path, "rb") as proxy_handle:
                proxy_sha256, _ = _hash(proxy_handle)
                proxy_handle.seek(0)
                proxy_blob = store.publish(proxy_handle, scope=production_id, media_type=MP4,
                                           expected_sha256=proxy_sha256)
    for name, blob in ((MASTER, master_blob), (PROXY, proxy_blob)):
        if store.verify(blob.locator, blob.sha256) != PRESENT:
            raise DeliveryError(NOT_VERIFIED, f"the published {name} did not re-hash to "
                                f"{blob.sha256} at {blob.locator}")
    document = {
        "schema": DELIVERY_SCHEMA,
        "id": delivery_id or Minter().mint("dlv"),
        "run_id": run_id,
        "created_at": created_at,
        "store": {"adapter": adapter, "writable": True},
        "master": _media(master_blob, width, height, report.frames),
        "proxy": _media(proxy_blob, proxy_width, proxy_height, proxy_report.frames),
        "verification": {"decoded_frames": report.frames, "expected_frames": expected_frames,
                         "sha256_verified": True, "proxy_under_bytes": limit},
        "legacy": None,
    }
    problems = validate_delivery(document, context=WRITE)
    if problems:  # a bug here, not a bad master: every input was checked above
        raise AssertionError("; ".join(str(problem) for problem in problems))
    record_blob = store.publish(canonical_json(document), scope=production_id, media_type=JSON)
    record = StageRecord(production_id=production_id, run_id=run_id, stage=STAGE,
                         blobs={MASTER: master_blob, PROXY: proxy_blob, RECORD: record_blob})
    try:
        ledger.complete_stage(record)
    except StoreError as error:
        if error.code != COLLISION:
            raise
        # Another delivery of this run completed first: the same master returns it.
        winner = read_delivery(store, production_id=production_id, run_id=run_id,
                               ledger=ledger)
        if winner is None:
            raise
        return _same(winner, sha256, expected_frames, media_kind)
    return Delivery.from_document(document)


def read_delivery(store: Store, *, production_id: str, run_id: str,
                  ledger: StageLedger | None = None) -> Delivery | None:
    """The run's completed delivery, or ``None`` if it has none. Every file the stage
    lists is re-hashed (``store.blob_missing`` or ``store.hash_mismatch`` if one is not
    as recorded), and the delivery document must validate and name exactly the
    stage's master and proxy (``delivery.record_invalid``)."""
    ledger = _ledger(store, ledger)
    record = completed_stage(ledger, production_id=production_id, run_id=run_id, stage=STAGE,
                             store=None if ledger is store else store)
    if record is None:
        return None
    if set(record.blobs) != {MASTER, PROXY, RECORD} or record.blobs[RECORD].media_type != JSON:
        raise DeliveryError(RECORD_INVALID, f"stage {STAGE!r} of {run_id} lists "
                            f"{sorted(record.blobs)}, not a master, a proxy and a delivery")
    with store.open(record.blobs[RECORD].locator) as handle:
        data = handle.read(RECORD_MAX_BYTES + 1)
    try:
        document = parse_strict(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise DeliveryError(RECORD_INVALID, f"the delivery document of {run_id} is not strict "
                            f"JSON ({type(error).__name__})") from None
    problems = validate_delivery(document, context=READ)
    if problems:
        raise DeliveryError(RECORD_INVALID, f"the delivery document of {run_id} is invalid: "
                            + "; ".join(str(problem) for problem in problems))
    delivery = Delivery.from_document(document)
    for name, media in ((MASTER, delivery.master), (PROXY, delivery.proxy)):
        blob = record.blobs[name]
        if media is None or (media.sha256, media.bytes, media.locator) != \
                (blob.sha256, blob.bytes, blob.locator):
            raise DeliveryError(RECORD_INVALID, f"the delivery document of {run_id} names "
                                f"another {name} than its stage record")
    if delivery.run_id != run_id:
        raise DeliveryError(RECORD_INVALID, f"the delivery document of {run_id} names run "
                            f"{delivery.run_id}")
    return delivery


def _ledger(store: Store, ledger: StageLedger | None) -> StageLedger:
    if ledger is not None:
        return ledger
    if not isinstance(store, StageLedger):
        raise TypeError("this store keeps no stage records; pass a ledger")
    return store


def _adapter(store: Store) -> str:
    """The delivery's ``store.adapter``: ``local`` for the local store; another store
    names itself in an ``adapter`` attribute (proposal: the NFS store of story 434)."""
    adapter = LOCAL if isinstance(store, LocalStore) else getattr(store, "adapter", None)
    if adapter not in (LOCAL, NFS):
        raise TypeError(f"a delivery is published to the {LOCAL} or {NFS} store, not "
                        f"{type(store).__name__}")
    return adapter


def _hash(handle: BinaryIO) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    while chunk := handle.read(_CHUNK):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def _unchanged(before: os.stat_result, after: os.stat_result) -> None:
    """The master's size, times and inode are as they were when it was hashed."""
    keys = ("st_ino", "st_dev", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, key) != getattr(after, key) for key in keys):
        raise DeliveryError(MASTER_CHANGED, "the master file changed while it was checked; "
                            "nothing was published")


def _same(existing: Delivery, sha256: str, expected_frames: int, media_kind: str) -> Delivery:
    """The completed delivery, if it is this master at this frame count and kind."""
    if existing.master.sha256 != sha256:
        raise DeliveryError(COLLISION, f"run {existing.run_id} is already delivered with "
                            f"another master ({existing.master.sha256}); nothing was changed")
    if existing.verification.expected_frames != expected_frames or \
            media_kind_of(existing.master.width, existing.master.height) != media_kind:
        raise DeliveryError(COLLISION, f"run {existing.run_id} is already delivered as a "
                            f"{media_kind_of(existing.master.width, existing.master.height)} "
                            f"of {existing.verification.expected_frames} frames; nothing was "
                            "changed")
    return existing


def _media(blob: Blob, width: int, height: int, frames: int) -> dict:
    return {"sha256": blob.sha256, "bytes": blob.bytes, "media_type": MP4, "width": width,
            "height": height, "fps": FPS, "frames": frames, "video_codec": H264,
            "audio_codec": AAC, "locator": blob.locator, "legacy_path": None}


def _timestamp(now: datetime | None) -> str:
    """ISO 8601 UTC to the second (proposal), from ``now`` or the clock."""
    now = datetime.now(UTC) if now is None else now
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = ["MASTER", "PROXY", "RECORD", "STAGE", "deliver", "read_delivery"]
