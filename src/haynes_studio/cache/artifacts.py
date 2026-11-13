"""The artifact cache on the store (story 380): one completed stage per cache key.

A cached artifact is a completed stage (story 379) named ``<kind>-<key hex>`` with two
outputs: the artifact itself, under its kind's name, and ``inputs``, the key document as
canonical JSON, whose SHA-256 is the key itself. A miss makes the artifact and commits
the stage (blobs first, then the record); a hit reads a completed record, which the
local ledger re-hashes, and checks that it is that key's entry. The cache never deletes,
evicts or overwrites anything (D17).

Where a stage is found (**proposal**): a stage record lives under a run
(``records/<run_id>/<stage>.json``), so the cache commits under the current run and
looks for a key in the current run first, then in the earlier runs it is given, newest
first. :class:`StageFinder` is the seam: the product's Postgres ledger (story 434) can
answer "a completed stage of this name in this production" with one query instead.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from haynes_studio.cache.errors import ENTRY_INVALID, CacheError
from haynes_studio.cache.keys import CacheKey
from haynes_studio.stages import StageOutput, commit_stage, completed_stage
from haynes_studio.store import Blob, StageLedger, StageRecord, Store
from haynes_studio.store.layout import check_production_id, check_run_id

INPUTS = "inputs"
JSON = "application/json"


def stage_name(key: CacheKey) -> str:
    """The stage a key's artifact is recorded as: ``<kind>-<64 hex digits>``."""
    return f"{key.kind}-{key.hex}"


class StageFinder(Protocol):
    """Finds a completed stage of a production by name, in whatever run made it."""

    def find(self, stage: str) -> StageRecord | None: ...


@dataclass(frozen=True)
class RunSearch:
    """A :class:`StageFinder` over named runs of one production, in the order given:
    each lookup reads the ledger's record of that stage in each run (the local ledger
    re-hashes every blob it names) until one is complete."""

    ledger: StageLedger
    production_id: str
    run_ids: tuple[str, ...]
    store: Store | None = None  # for a ledger that cannot see the blobs

    def find(self, stage: str) -> StageRecord | None:
        for run_id in self.run_ids:
            record = completed_stage(self.ledger, production_id=self.production_id,
                                     run_id=run_id, stage=stage, store=self.store)
            if record is not None:
                return record
        return None


@dataclass(frozen=True)
class CachedArtifact:
    """An artifact the cache holds: its key, the completed record and the artifact's
    blob. ``hit`` is false when this call made it."""

    key: CacheKey
    record: StageRecord
    blob: Blob
    hit: bool

    @property
    def sha256(self) -> str:
        return self.blob.sha256


@dataclass
class CacheStats:
    """What one cache did: keys found, keys made."""

    hits: list[str] = field(default_factory=list)
    made: list[str] = field(default_factory=list)


class ArtifactCache:
    """Cached artifacts of one production, committed under ``run_id``. Lookups search
    ``run_id`` and then ``earlier_runs`` (newest first), unless ``finder`` is given."""

    def __init__(self, store: Store, *, production_id: str, run_id: str,
                 earlier_runs: Sequence[str] = (), ledger: StageLedger | None = None,
                 finder: StageFinder | None = None):
        if ledger is None:
            if not isinstance(store, StageLedger):
                raise TypeError("this store keeps no stage records; pass a ledger")
            ledger = store
        self.store = store
        self.ledger = ledger
        self.production_id = check_production_id(production_id)
        self.run_id = check_run_id(run_id)
        runs = (run_id, *(check_run_id(run) for run in earlier_runs if run != run_id))
        self.finder = finder or RunSearch(ledger, production_id, runs)
        self.stats = CacheStats()

    def lookup(self, key: CacheKey, media_type: str) -> CachedArtifact | None:
        """The completed entry for ``key``, checked, or ``None``. A completed stage of
        that name that is not ``key``'s entry (other outputs, another media type, an
        ``inputs`` blob that is not the key document) is ``cache.entry_invalid``."""
        stage = stage_name(key)
        record = self.finder.find(stage)
        if record is None:
            return None
        blobs = dict(record.blobs)
        inputs, artifact = blobs.get(INPUTS), blobs.get(key.kind)
        if set(blobs) != {INPUTS, key.kind} or artifact is None or inputs is None:
            raise CacheError(ENTRY_INVALID, f"outputs {sorted(blobs)} are not "
                             f"{sorted({INPUTS, key.kind})}", where=stage)
        if inputs.sha256 != key.hex or inputs.media_type != JSON:
            raise CacheError(ENTRY_INVALID, "its inputs are not the key's document", where=stage)
        if artifact.media_type != media_type:
            raise CacheError(ENTRY_INVALID, f"its {key.kind} is {artifact.media_type}, not "
                             f"{media_type}", where=stage)
        self.stats.hits.append(key.value)
        return CachedArtifact(key=key, record=record, blob=artifact, hit=True)

    def commit(self, key: CacheKey, data: bytes, media_type: str) -> CachedArtifact:
        """Publish ``data`` and the key document, then record the stage (create-only;
        the same outputs again succeed, other bytes are ``store.collision``)."""
        record = commit_stage(self.store, ledger=self.ledger, production_id=self.production_id,
                              run_id=self.run_id, stage=stage_name(key), outputs={
                                  key.kind: StageOutput(data, media_type),
                                  INPUTS: StageOutput(key.canonical, JSON, expected_sha256=key.hex)})
        self.stats.made.append(key.value)
        return CachedArtifact(key=key, record=record, blob=record.blobs[key.kind], hit=False)

    def get_or_make(self, key: CacheKey, make: Callable[[], bytes], media_type: str) -> CachedArtifact:
        """The cached artifact for ``key``; on a miss, ``make()`` it and commit it."""
        found = self.lookup(key, media_type)
        return found if found is not None else self.commit(key, make(), media_type)
