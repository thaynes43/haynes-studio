"""Runs and their record on the store (contract section 8, D30; story 406).

A run is a record of what happened to one snapshot. Its states are ``queued`` (with
``wait_reason``), ``running``, then ``succeeded``, ``failed`` or ``cancelled``; ``held``
is a safety stop that resumes only after reconciliation. Terminal states never change,
and every status change appends a transition with its time, actor and reason.

**The record (proposal; the product's is a Postgres row, story 434).** The local store
keeps no mutable file, so each version of a run document is its own completed stage of
the run: ``run-0001`` (the queued run, with its snapshot blob), ``run-0002`` and so on,
each listing the run document as canonical JSON. A stage name is create-only, so two
writers that move one run from the same version race to the same name: one record
wins and the other is ``store.collision`` (a compare-and-set). Readers take the highest
completed version. Nothing is ever deleted or rewritten (D17).

Which runs a production has: the local adapter's ``records/`` folder lists them
(:func:`local_run_ids`, read-only), newest first by ULID; the product asks Postgres.
"""

from __future__ import annotations

import copy
import json
import os
import re
from collections.abc import Mapping
from typing import Any

from haynes_studio.build.errors import RUN_TRANSITION, RUN_UNKNOWN, BuildError
from haynes_studio.build.validate import validate_run
from haynes_studio.canonical.validate import WRITE
from haynes_studio.errors import blocking
from haynes_studio.stages import StageOutput, commit_stage, completed_stage
from haynes_studio.store import LocalStore, Store, canonical_json
from haynes_studio.store.layout import check_production_id, check_run_id

QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED, HELD = (
    "queued", "running", "succeeded", "failed", "cancelled", "held")
TERMINAL = frozenset({SUCCEEDED, FAILED, CANCELLED, "imported"})
ALLOWED: Mapping[str | None, frozenset[str]] = {
    None: frozenset({QUEUED}),
    QUEUED: frozenset({RUNNING, CANCELLED, HELD}),
    RUNNING: frozenset({SUCCEEDED, FAILED, CANCELLED, HELD}),
    HELD: frozenset({RUNNING, FAILED, CANCELLED}),  # after reconciliation only (story 410)
}
RUN_SCHEMA = "studio.run/v1"
JSON = "application/json"
RUN_OUTPUT, SNAPSHOT_OUTPUT = "run", "snapshot"
MAX_VERSIONS = 9999  # stage names run-0001 to run-9999 (proposal)
_STAGE = re.compile(r"^run-(\d{4})$")
_RUN_DIR = re.compile(r"^run_[0-7][0-9A-HJKMNP-TV-Z]{25}$")


def version_stage(number: int) -> str:
    """The stage that records version ``number`` of a run document."""
    if not 1 <= number <= MAX_VERSIONS:
        raise ValueError(f"a run has at most {MAX_VERSIONS} versions")
    return f"run-{number:04d}"


def new_run(*, run_id: str, story_id: str, number: int, snapshot: Mapping[str, Any],
            queued_by: Mapping[str, Any], queued_at: str, phase: str,
            idempotency_key: str | None = None, reason: str = "queued by the command line"
            ) -> dict[str, Any]:
    """A queued run of a snapshot (``snapshot``: sha256, story_revision, board_count,
    locator)."""
    return {
        "schema": RUN_SCHEMA, "id": run_id, "story_id": story_id, "number": number,
        "status": QUEUED, "wait_reason": None, "phase": phase, "snapshot": dict(snapshot),
        "queued_by": copy.deepcopy(dict(queued_by)), "queued_at": queued_at,
        "idempotency_key": idempotency_key,
        "estimate": None, "progress": {"percent": 0, "stage": None}, "stages": [],
        "outputs": None, "checks": None, "provenance": None, "delivery_id": None,
        "legacy": None, "started_at": None, "finished_at": None, "error": None,
        "transitions": [{"from": None, "to": QUEUED, "at": queued_at,
                         "by": copy.deepcopy(dict(queued_by)), "reason": reason}],
    }


def advance(run: Mapping[str, Any], to: str, *, at: str, by: Mapping[str, Any], reason: str,
            **fields: Any) -> dict[str, Any]:
    """The run moved to ``to``, with its transition recorded; ``fields`` replace other
    fields of the document. A terminal run, or a move the state machine does not
    allow, is ``run.transition`` and changes nothing."""
    status = run["status"]
    if status in TERMINAL:
        raise BuildError(RUN_TRANSITION, f"run {run['id']} is {status}; a terminal run never "
                         "changes")
    if to not in ALLOWED.get(status, frozenset()):
        raise BuildError(RUN_TRANSITION, f"run {run['id']} cannot move from {status} to {to}")
    out = copy.deepcopy(dict(run))
    out.update(copy.deepcopy(fields))
    out["status"] = to
    if to != QUEUED:
        out["wait_reason"] = None
    if to == RUNNING and out.get("started_at") is None:
        out["started_at"] = at
    if to in TERMINAL:
        out["finished_at"] = at
    out["transitions"] = [*run.get("transitions", []),
                          {"from": status, "to": to, "at": at, "by": copy.deepcopy(dict(by)),
                           "reason": reason}]
    return out


def update(run: Mapping[str, Any], **fields: Any) -> dict[str, Any]:
    """The run with ``fields`` replaced and its status unchanged (progress, stages); a
    terminal run is ``run.transition``."""
    if run["status"] in TERMINAL:
        raise BuildError(RUN_TRANSITION, f"run {run['id']} is {run['status']}; a terminal run "
                         "never changes")
    out = copy.deepcopy(dict(run))
    out.update(copy.deepcopy(fields))
    return out


class RunRecords:
    """Run documents of one production, each version a completed stage (see the module
    docstring)."""

    def __init__(self, store: Store, production_id: str):
        self.store = store
        self.production_id = check_production_id(production_id)
        self._versions: dict[str, int] = {}

    def _check(self, run: Mapping[str, Any]) -> bytes:
        problems = blocking(validate_run(run, context=WRITE))
        if problems:  # a bug in the build, never a user input
            raise AssertionError("; ".join(str(problem) for problem in problems))
        return canonical_json(dict(run))

    def create(self, run: Mapping[str, Any], snapshot: bytes) -> dict[str, Any]:
        """Record a new run (version 1) with its snapshot blob. The snapshot must be
        the bytes the run names (its sha256)."""
        run_id = check_run_id(run["id"])
        if self.latest(run_id) is not None:
            raise BuildError(RUN_TRANSITION, f"run {run_id} exists; a run ID is never reused")
        commit_stage(self.store, production_id=self.production_id, run_id=run_id,
                     stage=version_stage(1), outputs={
                         RUN_OUTPUT: StageOutput(self._check(run), JSON),
                         SNAPSHOT_OUTPUT: StageOutput(snapshot, JSON,
                                                      expected_sha256=run["snapshot"]["sha256"])})
        self._versions[run_id] = 1
        return dict(run)

    def write(self, run: Mapping[str, Any]) -> dict[str, Any]:
        """Record the next version of a run. The stored versions are counted again
        first: a run another writer moved since this one read it, or one whose stored
        status is terminal, is ``run.transition``; two writers of the same next version
        race to a create-only name, and the loser gets ``store.collision``."""
        run_id = check_run_id(run["id"])
        current = self._count(run_id)
        if current == 0:
            raise BuildError(RUN_UNKNOWN, f"no run {run_id} in {self.production_id}")
        known = self._versions.get(run_id)
        if known is not None and known != current:
            raise BuildError(RUN_TRANSITION, f"run {run_id} was moved by another writer "
                             f"(version {current}, this writer read {known})")
        stored = self._read(run_id, current)
        if stored["status"] in TERMINAL:
            raise BuildError(RUN_TRANSITION, f"run {run_id} is {stored['status']}; a terminal run "
                             "never changes")
        commit_stage(self.store, production_id=self.production_id, run_id=run_id,
                     stage=version_stage(current + 1),
                     outputs={RUN_OUTPUT: StageOutput(self._check(run), JSON)})
        self._versions[run_id] = current + 1
        return dict(run)

    def _count(self, run_id: str) -> int:
        number = 0
        while number < MAX_VERSIONS and completed_stage(
                self.store, production_id=self.production_id, run_id=run_id,
                stage=version_stage(number + 1)) is not None:
            number += 1
        return number

    def _read(self, run_id: str, number: int) -> dict[str, Any]:
        record = completed_stage(self.store, production_id=self.production_id, run_id=run_id,
                                 stage=version_stage(number))
        with self.store.open(record.blobs[RUN_OUTPUT].locator) as handle:
            return json.loads(handle.read())

    def latest(self, run_id: str) -> dict[str, Any] | None:
        """The run's newest recorded document, or ``None`` for an unknown run."""
        number = self._count(check_run_id(run_id))
        if number == 0:
            return None
        self._versions[run_id] = number
        return self._read(run_id, number)

    def history(self, run_id: str) -> list[dict[str, Any]]:
        """Every recorded version of the run, oldest first."""
        out = []
        for number in range(1, self._count(check_run_id(run_id)) + 1):
            record = completed_stage(self.store, production_id=self.production_id,
                                     run_id=run_id, stage=version_stage(number))
            with self.store.open(record.blobs[RUN_OUTPUT].locator) as handle:
                out.append(json.loads(handle.read()))
        return out

    def snapshot(self, run_id: str) -> bytes:
        """The run's snapshot blob (canonical JSON), re-hashed by the ledger."""
        record = completed_stage(self.store, production_id=self.production_id,
                                 run_id=check_run_id(run_id), stage=version_stage(1))
        if record is None:
            raise BuildError(RUN_UNKNOWN, f"no run {run_id} in {self.production_id}")
        with self.store.open(record.blobs[SNAPSHOT_OUTPUT].locator) as handle:
            return handle.read()


def local_run_ids(store: LocalStore, production_id: str) -> list[str]:
    """The runs a production has in a local store, newest first (ULIDs sort by time):
    the run folders under its ``records/``, read-only. Story 434's ledger answers this
    with a query."""
    check_production_id(production_id)
    folder = os.path.join(store.root, "productions", production_id, "records")
    try:
        names = [entry.name for entry in os.scandir(folder)
                 if _RUN_DIR.match(entry.name) and entry.is_dir(follow_symlinks=False)]
    except FileNotFoundError:
        return []
    return sorted(names, reverse=True)


__all__ = ["ALLOWED", "CANCELLED", "FAILED", "HELD", "QUEUED", "RUNNING", "RunRecords",
           "SUCCEEDED", "TERMINAL", "advance", "local_run_ids", "new_run", "update",
           "version_stage"]
