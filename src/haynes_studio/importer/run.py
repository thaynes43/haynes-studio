"""The private input import itself (story 846): read each planned hash once, publish
it create-only, import it as its existing asset version, and report every row.

For each :class:`~haynes_studio.importer.plan.Item`, in plan order:

1. **Held already?** The store is asked (``Store.verify``, which re-hashes) for the
   hash at each locator the item needs. If every one is ``present``, nothing is read
   (a second import reads nothing it holds and writes nothing). If one is and another
   is not, the missing ones are copied from the store, not read again. A locator that
   holds *other* bytes stops the import (a damaged store is for a person, and
   ``store doctor``).
2. **Read** from the item's sources in order, through the read-only clients only
   (``LedgerReader.fetch_asset``; ``VolumeReader.fetch_job_output`` and
   ``fetch_upload``). Each refusal (``adapter.source_*``) is recorded and the next
   source tried; the first source whose bytes hash to the public SHA-256 (checked in
   the pod and again in the client) ends the reads. Any other failure (a timeout, a
   ``kubectl`` failure or denial, an unknown message, a changed pin) **stops the whole
   import**: nothing is retried, the remaining rows are reported as not read.
3. **Check the records first:** each library version with this hash is imported again
   (``import_version``, pure) with the bytes' measured content at its own locator,
   under its own source key and ID, before anything is published. It must return that
   same version (``created: false``); a record the bytes contradict
   (``idempotency.mismatch``) makes the item a ``mismatch`` and nothing is published.
4. **Publish** create-only into each scope (``Store.publish`` with the expected
   SHA-256), and check the store's blob is the expected hash, size and locator.

Bytes that do not hash to the public SHA-256 are never published or imported: the item
is ``mismatch``. A row is ``verified`` when the store holds its hash, ``absent`` when it
does not (``reason`` says why: refused reads, no readable locator, never delivered, or
not read because the import stopped), ``mismatch`` when a read returned other bytes or
the records contradict them.

After the items, the r4 story is resolved with the store's own answers: the library
resolver (``exists`` from ``Store.verify``) and the layered motion pins
(``layered.pin.pin_story``), which list what a layered build would still lack.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from haynes_studio.adapters.errors import SOURCE_HASH_MISMATCH, SOURCE_REFUSALS, AdapterError
from haynes_studio.adapters.wan_ledger import LedgerReader
from haynes_studio.adapters.wan_volume import VolumeReader, ledger_fetch_refusal
from haynes_studio.canonical.model import Principal
from haynes_studio.errors import ContractError, blocking
from haynes_studio.importer.plan import JOB_OUTPUT, LEDGER_ASSET, LIBRARY, Item, Plan, Source
from haynes_studio.jsonio import thaw
from haynes_studio.layered.pin import pin_story
from haynes_studio.library.library import Library, VersionRequest, import_version
from haynes_studio.library.model import Content, locator_for
from haynes_studio.library.resolve import resolve
from haynes_studio.store.base import MISMATCH as STORE_MISMATCH
from haynes_studio.store.base import PRESENT, Store
from haynes_studio.store.errors import StoreError

VERIFIED, ABSENT, MISMATCH = "verified", "absent", "mismatch"
STATUSES = (VERIFIED, ABSENT, MISMATCH)
# Dry run only: what a run would do with each item.
HELD, TO_READ, NOT_READ = "held", "to_read", "not_read"
REPORT_KIND = "private-input-import"
REPORT_VERSION = 1
STORY_URL = "https://work.haynesnetwork.com/work_packages/846"


@dataclass(frozen=True)
class Readers:
    """The read-only clients the import may call, each with the runner it was given."""

    ledger: LedgerReader
    volume: VolumeReader


class _Stop(Exception):
    def __init__(self, code: str, message: str, *, source: Source | None = None):
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.source = code, message, source

    def to_document(self, sha256: str) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "sha256": sha256,
                "source": None if self.source is None else self.source.to_document()}


@dataclass(frozen=True)
class Attempt:
    source: Source
    outcome: str  # "verified" or an adapter.source_* code
    seconds: float
    bytes: int = 0
    message: str = ""

    def to_document(self) -> dict[str, Any]:
        out = {"source": self.source.to_document(), "outcome": self.outcome,
               "seconds": round(self.seconds, 3), "bytes": self.bytes}
        if self.message:
            out["message"] = self.message
        return out


@dataclass
class ItemResult:
    item: Item
    status: str
    reason: str | None = None
    locators: tuple[str, ...] = ()
    read_from: dict[str, Any] | None = None  # a source, the store, or None: nothing read
    attempts: list[Attempt] = field(default_factory=list)
    versions: list[dict[str, Any]] = field(default_factory=list)
    bytes_read: int = 0  # from the Wan volume
    bytes_published: int = 0  # new blobs in the store

    def to_document(self) -> dict[str, Any]:
        return {"sha256": self.item.sha256, "media_type": self.item.media_type,
                "status": self.status, "reason": self.reason, "rows": list(self.item.rows),
                "locators": list(self.locators), "read_from": self.read_from,
                "attempts": [a.to_document() for a in self.attempts],
                "versions": self.versions, "bytes_read": self.bytes_read,
                "bytes_published": self.bytes_published}


@dataclass(frozen=True)
class ImportResult:
    report: dict[str, Any]
    library: Library

    @property
    def stopped(self) -> dict[str, Any] | None:
        return self.report["stopped"]

    @property
    def mismatched(self) -> bool:
        return self.report["totals"][MISMATCH] > 0


def _locator(item: Item, scope: str) -> str:
    return locator_for(item.sha256, item.media_type, None if scope == LIBRARY else scope)


def _held(store: Store, item: Item) -> dict[str, str]:
    """Each scope's locator and what the store holds there."""
    states = {}
    for scope in item.scopes:
        locator = _locator(item, scope)
        try:
            states[scope] = store.verify(locator, item.sha256)
        except (StoreError, OSError) as error:
            raise _Stop(getattr(error, "code", "store.blob_missing"),
                        f"the store could not be read at {locator}: {error}") from None
        if states[scope] == STORE_MISMATCH:
            raise _Stop("store.hash_mismatch", f"the store holds other bytes at {locator}; run "
                        "store doctor before importing again")
    return states


def _read(readers: Readers, item: Item, result: ItemResult, clock: Callable[[], float]) -> bytes | None:
    for source in item.sources:
        started = clock()
        try:
            if source.kind == LEDGER_ASSET:
                data = readers.ledger.fetch_asset(source.name, item.sha256, path=source.path or "").data
            elif source.kind == JOB_OUTPUT:
                data = readers.volume.fetch_job_output(source.name, item.sha256).data
            else:
                data = readers.volume.fetch_upload(item.sha256, "." + source.name.rsplit(".", 1)[1]).data
        except AdapterError as error:
            code = ledger_fetch_refusal(error) if source.kind == LEDGER_ASSET else \
                error.code if error.code in SOURCE_REFUSALS else None
            if code is None:
                raise _Stop(error.code, error.message, source=source) from None
            result.attempts.append(Attempt(source, code, clock() - started, message=error.message))
            continue
        result.attempts.append(Attempt(source, VERIFIED, clock() - started, len(data)))
        result.bytes_read += len(data)
        result.read_from = source.to_document()
        return data
    return None


def _request(library: Library, version_id: str, item: Item, size: int, locator: str) -> VersionRequest:
    """The existing version, again, with the bytes' measured content at its locator."""
    version = library.version(version_id)
    asset = library.asset(version.asset_id)
    content = Content(sha256=item.sha256, bytes=size, media_type=item.media_type, locator=locator,
                      width=version.content.width, height=version.content.height)
    provenance = {k: v for k, v in thaw(version.provenance).items()
                  if k not in ("created_at", "created_by")}
    return VersionRequest(
        kind=version.kind, name=asset.name, scope=asset.scope, capabilities=version.capabilities,
        content=content, provenance=provenance, licence=version.licence, state=version.state,
        labels=asset.labels, attributes=thaw(asset.attributes), legacy=thaw(version.legacy),
        voice=version.voice, motion=thaw(version.motion), version_id=version.id,
        asset_id=asset.id)


def _check_records(library: Library, item: Item, size: int, *, by: Principal,
                   now: str) -> list[dict[str, Any]]:
    """Import every version with this hash again; each must be returned unchanged.
    Raises ContractError when a record contradicts the bytes."""
    out = []
    for version_id in item.versions:
        version = library.version(version_id)
        outcome = import_version(library, _request(library, version_id, item, size,
                                                   version.content.locator), by=by, now=now)
        if outcome.created or outcome.version.id != version_id or outcome.library is not library:
            raise RuntimeError(f"importing {version_id} again made a new record; nothing is "
                               "published")  # cannot happen: same pin, same source key
        out.append({"version_id": version_id, "source_key": version.source_key,
                    "created": False})
    return out


def _publish(store: Store, item: Item, data: bytes, scopes: list[str]) -> int:
    published = 0
    for scope in scopes:
        locator = _locator(item, scope)
        try:
            blob = store.publish(data, scope=scope, media_type=item.media_type,
                                 expected_sha256=item.sha256)
        except (StoreError, OSError) as error:
            raise _Stop(getattr(error, "code", "store.collision"),
                        f"publishing to {locator} failed: {error}") from None
        if (blob.sha256, blob.bytes, blob.locator) != (item.sha256, len(data), locator):
            raise _Stop("store.hash_mismatch", f"the store answered another blob for {locator}")
        published += blob.bytes
    return published


def _one(item: Item, *, store: Store, library: Library, readers: Readers, by: Principal, now: str,
         clock: Callable[[], float]) -> ItemResult:
    result = ItemResult(item, ABSENT)
    states = _held(store, item)
    missing = [scope for scope in item.scopes if states[scope] != PRESENT]
    present = [scope for scope in item.scopes if states[scope] == PRESENT]
    data = None
    if missing and present:  # copy within the store, never read the source again
        locator = _locator(item, present[0])
        try:
            with store.open(locator) as handle:
                data = handle.read()
        except (StoreError, OSError) as error:
            raise _Stop(getattr(error, "code", "store.blob_missing"),
                        f"the store could not be read at {locator}: {error}") from None
        result.read_from = {"kind": "store", "locator": locator}
    elif missing:
        if not item.sources:
            result.reason = item.unread
            return result
        data = _read(readers, item, result, clock)
        if data is None:
            hashes = [a for a in result.attempts if a.outcome == SOURCE_HASH_MISMATCH]
            result.status = MISMATCH if hashes else ABSENT
            result.reason = "; ".join(sorted({a.outcome for a in result.attempts}))
            return result
    size = len(data) if data is not None else None
    if size is None:  # every scope holds it: measure from the store's answer
        size = _held_size(store, item)
    try:
        result.versions = _check_records(library, item, size, by=by, now=now)
    except ContractError as error:
        result.status = MISMATCH
        result.reason = ", ".join(sorted({v.rule for v in error.violations})) or str(error)
        return result
    if data is not None:
        result.bytes_published = _publish(store, item, data, missing)
    result.status = VERIFIED
    result.locators = tuple(_locator(item, scope) for scope in item.scopes)
    return result


def _held_size(store: Store, item: Item) -> int:
    locator = _locator(item, item.scopes[0])
    try:
        with store.open(locator) as handle:
            return handle.seek(0, 2)
    except (StoreError, OSError) as error:
        raise _Stop(getattr(error, "code", "store.blob_missing"),
                    f"the store could not be read at {locator}: {error}") from None


def _lacks(story: Mapping[str, Any], library: Library, store: Store) -> dict[str, Any]:
    """What a layered build of ``story`` would still lack, by the store's own answers."""
    def exists(locator: str, sha256: str) -> bool:
        return store.verify(locator, sha256) == PRESENT
    resolution = resolve(story, library, exists)
    motion = pin_story(story, library, store.verify)
    loops = [{"board_id": board_id, "rule": v.rule, "path": v.path, "message": v.message}
             for board_id, board in sorted(motion.boards.items()) for v in blocking(board.problems)]
    held = []
    for version in sorted(library.versions.values(), key=lambda v: v.id):
        if version.content is not None and not exists(version.content.locator,
                                                      version.content.sha256):
            held.append({"version_id": version.id, "kind": version.kind, "state": version.state,
                         "source_key": version.source_key, "locator": version.content.locator})
    return {"story": [{"rule": v.rule, "path": v.path, "message": v.message}
                      for v in blocking(resolution.problems)],
            "layered_loops": loops, "versions_not_held": held}


def _totals(plan: Plan, rows: list[dict[str, Any]], items: list[ItemResult]) -> dict[str, Any]:
    by_role: dict[str, dict[str, int]] = {}
    for row in rows:
        counts = by_role.setdefault(row["role"], {s: 0 for s in STATUSES})
        counts[row["status"]] += 1
    out: dict[str, Any] = {"rows": len(rows), "hashes": len(plan.items)}
    for status in STATUSES:
        out[status] = sum(1 for row in rows if row["status"] == status)
        out[f"hashes_{status}"] = sum(1 for item in items if item.status == status)
    out["hashes_read"] = sum(1 for item in items if item.bytes_read)
    out["bytes_read"] = sum(item.bytes_read for item in items)
    out["bytes_published"] = sum(item.bytes_published for item in items)
    out["by_role"] = dict(sorted(by_role.items()))
    return out


def run_import(plan: Plan, *, store: Store, library: Library, readers: Readers,
               story: Mapping[str, Any] | None, by: Principal, now: Callable[[], str],
               clock: Callable[[], float] = time.monotonic,
               authorized_by: str | None = None) -> ImportResult:
    """Import every planned item into ``store`` and check it against ``library``; the
    report accounts for every row of the plan. ``now`` gives UTC timestamps,
    ``clock`` seconds for durations (both injectable)."""
    started_at, started = now(), clock()
    results: list[ItemResult] = []
    stopped = None
    for index, item in enumerate(plan.items):
        try:
            results.append(_one(item, store=store, library=library, readers=readers, by=by,
                                now=started_at, clock=clock))
        except _Stop as stop:
            stopped = stop.to_document(item.sha256)
            for rest in plan.items[index:]:
                results.append(ItemResult(rest, ABSENT,
                                          reason=f"not_read: the import stopped at {stop.code}"))
            break
    by_hash = {result.item.sha256: result for result in results}
    rows = []
    for row in plan.rows:
        result = by_hash[row.sha256]
        rows.append({"key": row.key, "role": row.role, "sha256": row.sha256,
                     "status": result.status, "reason": result.reason,
                     "locators": list(result.locators),
                     "version_ids": [v["version_id"] for v in result.versions]})
    lacks = None
    if story is not None and stopped is None:
        lacks = _lacks(story, library, store)
    report = {
        "kind": REPORT_KIND, "version": REPORT_VERSION, "title": "The Winter Menu",
        "built_by": STORY_URL, "authorized_by": authorized_by, "dry_run": False,
        "production_id": plan.production_id, "started_at": started_at, "finished_at": now(),
        "elapsed_s": round(clock() - started, 3), "stopped": stopped,
        "totals": _totals(plan, rows, results), "rows": rows,
        "hashes": [result.to_document() for result in results], "lacks": lacks}
    return ImportResult(report=report, library=library)


def dry_run(plan: Plan, *, store: Store | None, now: Callable[[], str]) -> dict[str, Any]:
    """What a run would read, from where, and into which locators; nothing is read from
    the Wan volume and nothing is written. With a store, each item says whether the
    store already holds it (``Store.verify`` only reads)."""
    items = []
    for item in plan.items:
        held = None
        if store is not None:
            try:
                held = {scope: store.verify(_locator(item, scope), item.sha256) for scope in item.scopes}
            except (StoreError, OSError) as error:
                held = {"error": str(error)}
        if held is not None and held and all(state == PRESENT for state in held.values()):
            would = HELD
        else:
            would = TO_READ if item.sources else NOT_READ
        items.append({**item.to_document(), "would": would, "store": held,
                      "locators": [_locator(item, scope) for scope in item.scopes]})
    would = {item["sha256"]: item["would"] for item in items}
    rows = [{"key": r.key, "role": r.role, "sha256": r.sha256, "would": would[r.sha256],
             "unread": r.unread} for r in plan.rows]
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["would"]] = counts.get(row["would"], 0) + 1
    return {"kind": REPORT_KIND, "version": REPORT_VERSION, "title": "The Winter Menu",
            "built_by": STORY_URL, "dry_run": True, "production_id": plan.production_id,
            "at": now(), "totals": {"rows": len(rows), "hashes": len(items), **dict(sorted(counts.items())),
                                    "reads_at_most": sum(len(i["sources"]) for i in items
                                                         if i["would"] == TO_READ)},
            "rows": rows, "hashes": items}


__all__ = ["ABSENT", "HELD", "MISMATCH", "NOT_READ", "REPORT_KIND", "Readers", "ImportResult",
           "STATUSES", "TO_READ", "VERIFIED", "dry_run", "run_import"]
