"""Record bounded technical failures and advance their append-only lifecycle."""

import re
from datetime import UTC, timedelta
from functools import cache

import sqlalchemy as sa

from haynes_studio.canonical.ids import is_id
from haynes_studio.db import runs
from haynes_studio.schemas import validator_for
from haynes_studio.store import canonical_json
from haynes_studio.store.layout import is_sha256

from . import storage
from .package import VALID_FOR, deduplication_id, digest, make_package
from .settings import Settings
from .transport import Transport

ACTIVE = frozenset({"proposed", "authorized", "requested"})
OUTCOMES = frozenset({"done", "failed", "escalate"})
SYSTEM = {"kind": "system", "component": "escalation"}
TECHNICAL_CHECKS = {
    "build.check_failed": frozenset({
        "layered.decal_gate", "mix.length", "mix.loudness", "mix.true_peak", "mix.clipping",
        "master.loudness", "master.true_peak", "master.clipping", "master.transcript",
    }),
    "layered.decal_weak": frozenset({"layered.decal_gate"}),
    "mix.check_failed": frozenset({
        "mix.length", "mix.loudness", "mix.true_peak", "mix.clipping",
        "master.loudness", "master.true_peak", "master.clipping",
    }),
}


@cache
def _run_check_validator():
    return validator_for("studio.run.v1.schema.json").evolve(schema={
        "$ref": "https://haynes-studio.invalid/schemas/studio.run.v1.schema.json#/$defs/check",
    })


class EscalationError(Exception):
    def __init__(self, code, message, status=409):
        self.code = "escalation." + code
        self.status = status
        super().__init__(message)


def _counts(conn, production_id, settings, now):
    start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    event, pkg = storage.events, storage.packages
    production, total = conn.execute(sa.select(
        sa.func.count().filter(pkg.c.production_id == production_id), sa.func.count(),
    ).select_from(event.join(pkg, pkg.c.id == event.c.package_id)).where(
        event.c.state == "authorized", event.c.occurred_at >= start,
        event.c.occurred_at < start + timedelta(days=1),
    )).one()
    return {"utc_day": start.date().isoformat(), "production": production, "total": total,
            "production_limit": settings.per_production_per_day, "total_limit": settings.total_per_day}


def _authorize(conn, package_id, now, actor, counts, acknowledged_boards):
    storage.append_event(conn, package_id, 2, "authorized", now, actor, {
        "cap_counts_before": counts, "acknowledged_board_ids": acknowledged_boards,
    })


def record_failure(conn, run, *, actor, attempt, error_code, board_id, result, settings: Settings):
    """Accept one completed evaluation from the fenced run worker.

    The producer uses a stable ordinal per run, check and board and only
    supplies completed evaluations. Replays and repeated copies within one
    evaluation cannot advance the count.
    """
    check = result.get("check")
    if (not isinstance(check, str) or check not in TECHNICAL_CHECKS.get(error_code, ())
            or result.get("result") != "fail" or "override" in result):
        return None
    if run["document"]["status"] != "running" or run["cancel_requested"]:
        return None
    frozen_boards = {board["id"] for board in run["snapshot"]["story"]["boards"]}
    if ((board_id is not None and (not is_id(board_id, "brd") or board_id not in frozen_boards))
            or (check == "layered.decal_gate" and board_id is None)
            or result.get("board_id", board_id) != board_id):
        raise EscalationError("board", "The check does not name a board in this run's snapshot", 422)
    artifact = result.get("artifact")
    key = result.get("key")
    if (not _run_check_validator().is_valid(result) or not is_sha256(artifact)
            or not isinstance(key, str) or not key.startswith("sha256:") or not is_sha256(key[7:])):
        raise EscalationError("check_evidence", "The failed check needs its artifact and recorded input key", 422)
    input_sha256 = key[7:]
    run_id = run["id"]
    package_id = deduplication_id(run_id, check, board_id, input_sha256, artifact)
    storage.lock(conn)
    now = runs.database_time(conn)
    if run["claim_until"] <= now:
        raise runs.QueueConflict("work.fence_lost", "This worker no longer owns the run")
    if storage.overridden(conn, run_id, check, artifact):
        return None

    recorded = {"run_id": run_id, "attempt": attempt, "board_id": board_id,
                "error_code": error_code, "check": result}
    record_sha256 = digest(recorded)
    evaluation_id = digest([run_id, check, board_id, attempt])
    existing = conn.scalar(sa.select(storage.failures.c.record_sha256).where(
        storage.failures.c.evaluation_id == evaluation_id))
    if existing is not None:
        if existing != record_sha256:
            raise EscalationError("evaluation_conflict", "The evaluation already has different evidence")
        return None
    if conn.scalar(sa.select(storage.packages.c.id).where(storage.packages.c.id == package_id)):
        return None

    conn.execute(storage.failures.insert().values(
        record_sha256=record_sha256, evaluation_id=evaluation_id, failure_id=package_id,
        run_id=run_id, recorded_at=now, actor=actor, result=canonical_json(recorded),
    ))
    matched = list(conn.scalars(sa.select(storage.failures.c.record_sha256).where(
        storage.failures.c.failure_id == package_id,
    ).order_by(storage.failures.c.recorded_at, storage.failures.c.record_sha256).limit(2)))
    if len(matched) < 2:
        return None

    doc, encoded, sha256 = make_package(run, package_id, board_id, check, input_sha256, artifact,
                                        matched, now)
    conn.execute(storage.packages.insert().values(
        id=package_id, run_id=run_id, production_id=run["production_id"],
        responder_key_id=doc["responder_key"]["id"],
        expires_at=now + VALID_FOR, sha256=sha256, canonical_json=encoded,
    ))
    counts = None
    reason = "person_authorization"
    if settings.authorization == "automatic":
        counts = _counts(conn, run["production_id"], settings, now)
        if counts["production"] >= counts["production_limit"] or counts["total"] >= counts["total_limit"]:
            reason = "automatic_cap_reached"
        else:
            reason = "automatic_authorization"
    detail = {"reason": reason}
    if reason == "automatic_cap_reached":
        detail["cap_counts"] = counts
    storage.append_event(conn, package_id, 1, "proposed", now, SYSTEM, detail)
    if reason == "automatic_authorization":
        _authorize(conn, package_id, now, SYSTEM, counts, [])
    return package_id


def require_live(conn, row, now):
    if now >= row["expires_at"]:
        raise EscalationError("expired", "The package has expired")
    doc = storage.document(row)
    if storage.overridden(conn, row["run_id"], doc["failure"]["check"], doc["artifacts"][0]["sha256"]):
        raise EscalationError("override", "A person overrode the failed check")


def decide(conn, production_id, package_id, decision, *, actor, settings, acknowledged_boards=()):
    if actor["kind"] != "human":
        raise EscalationError("person_required", "A signed-in person must make this decision", 403)
    storage.lock(conn)
    now = runs.database_time(conn)
    row = storage.get_package(conn, package_id, production_id)
    transitions = storage.history(conn, row["id"])
    state = transitions[-1]["state"]
    if decision == "authorize" and state == "proposed":
        require_live(conn, row, now)
        boards = sorted(set(acknowledged_boards))
        if not set(boards).issubset(storage.document(row)["board_ids"]):
            raise EscalationError("board", "Only this package's boards can be acknowledged", 422)
        _authorize(conn, row["id"], now, actor, _counts(conn, production_id, settings, now), boards)
    elif (decision == "decline" and state == "proposed") or (decision == "cancel" and state in ACTIVE):
        target = "declined" if decision == "decline" else "cancelled"
        storage.append_event(conn, row["id"], len(transitions) + 1, target, now, actor, {})
    else:
        raise EscalationError("state", "The package cannot take this decision in its current state")
    return storage.view(conn, row, now)


def request_with_transport(conn, production_id, package_id, transport: Transport):
    """Exercise the authorized handoff with the in-process test transport.

    The v1 application wires no dispatcher. A future external transport must
    use remote deduplication and reconcile ambiguous replies before recording
    a receipt. This transaction is only for the bounded in-process transport.
    """
    storage.lock(conn)
    now = runs.database_time(conn)
    row = storage.get_package(conn, package_id, production_id)
    require_live(conn, row, now)
    transitions = storage.history(conn, package_id)
    if transitions[-1]["state"] != "authorized":
        raise EscalationError("state", "Only an authorized package can be requested once")
    external_id = transport.request(row["canonical_json"], sha256=row["sha256"],
                                    deduplication_id=package_id)
    if not isinstance(external_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", external_id) is None:
        raise EscalationError("request_receipt", "The transport returned an invalid request ID")
    if conn.scalar(sa.select(storage.events.c.package_id).where(storage.events.c.external_request_id == external_id)):
        raise EscalationError("request_receipt", "The external request ID is already assigned")
    storage.append_event(conn, package_id, len(transitions) + 1, "requested", now,
                         {"kind": "transport"}, {}, external_request_id=external_id)
    return storage.view(conn, row, now)
