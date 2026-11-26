"""Durable FIFO, claim fencing and immutable run inputs.

The lane row serializes enqueue order and claiming. A claim locks only the
head, even if later rows are free. Every worker write locks and fences the
run before reading or writing an attempt. No transaction spans a Wan call.
"""

import hashlib
import json
from datetime import UTC, timedelta
from uuid import uuid4

import sqlalchemy as sa

from haynes_studio.build.run import advance, new_run, update
from haynes_studio.canonical.ids import Minter
from haynes_studio.store import blob_locator, canonical_json

from .problems import NotFound, StaleRevision
from .queue_controls import is_paused
from .schema import run_check_overrides, run_lane, run_wan_attempts, runs

ACTIVE = ("queued", "running", "held")
PENDING = ("reserved", "sent")
LEASE = timedelta(seconds=90)
BACKOFF = timedelta(seconds=15)
CHECK_OVERRIDABLE = "layered.decal_gate"
STATUS = runs.c.document["status"].astext
ATTEMPTS = run_wan_attempts.c


class QueueConflict(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class IdempotencyMismatch(Exception):
    pass


def database_time(conn):
    return conn.scalar(sa.select(sa.func.clock_timestamp()))


def timestamp(now):
    return now.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def actor_key(actor):
    identity = {k: v for k, v in actor.items() if k in ("kind", "iss", "sub", "key_id")}
    return hashlib.sha256(canonical_json(identity)).hexdigest()


def lookup_idempotency(conn, story_id, actor, key, story_revision):
    row = conn.execute(sa.select(runs).where(
        runs.c.story_id == story_id, runs.c.idempotency_actor == actor_key(actor),
        runs.c.idempotency_key == key,
    )).mappings().one_or_none()
    if row is not None and row["document"]["snapshot"]["story_revision"] != story_revision:
        raise IdempotencyMismatch
    return row


def enqueue(conn, *, snapshot, snapshot_sha256, library, actor, key, estimate, answers=None):
    story = snapshot["story"]
    production_id = story["production_id"]
    position = conn.scalar(sa.select(run_lane.c.next_position).with_for_update())
    conn.execute(run_lane.update().values(next_position=position + 1))
    number = conn.scalar(sa.select(sa.func.max(runs.c.number)).where(
        runs.c.production_id == production_id,
    )) or 0
    run = new_run(run_id=Minter().mint("run"), story_id=story["id"], number=number + 1,
                  snapshot={"sha256": snapshot_sha256, "story_revision": story["revision"],
                            "board_count": len(story["boards"]),
                            "locator": blob_locator(production_id, snapshot_sha256, "application/json")},
                  queued_by=actor, queued_at=timestamp(database_time(conn)), phase="all",
                  idempotency_key=key, reason="queued through Studio API")
    run["estimate"] = estimate["estimate"]
    if answers is not None:
        run["answers"] = answers
    return conn.execute(runs.insert().values(
        id=run["id"], story_id=story["id"], production_id=production_id,
        position=position, number=run["number"], idempotency_actor=actor_key(actor),
        idempotency_key=key, snapshot=snapshot, frozen_library=library,
        estimate_methods=estimate["methods"], document=run,
    ).returning(runs)).mappings().one()


def get(conn, run_id, *, lock=False, snapshot_pin_only=False):
    if snapshot_pin_only:
        stmt = sa.select(runs.c.production_id, runs.c.document["snapshot"].label("snapshot_pin"),
                         sa.func.jsonb_typeof(runs.c.snapshot).label("snapshot_type"))
    else:
        stmt = sa.select(runs)
    stmt = stmt.where(runs.c.id == run_id)
    if lock:
        stmt = stmt.with_for_update()
    row = conn.execute(stmt).mappings().one_or_none()
    if row is None:
        raise NotFound
    return row


def list_story(conn, story_id, cursor, limit):
    stmt = sa.select(runs).where(runs.c.story_id == story_id)
    if cursor is not None:
        after = conn.scalar(sa.select(runs.c.position).where(
            runs.c.id == cursor, runs.c.story_id == story_id,
        ))
        if after is None:
            raise NotFound
        stmt = stmt.where(runs.c.position > after)
    return conn.execute(stmt.order_by(runs.c.position).limit(limit)).mappings().all()


def ahead(conn, position=None):
    stmt = sa.select(runs.c.document).where(STATUS.in_(ACTIVE))
    if position is not None:
        stmt = stmt.where(runs.c.position < position)
    return conn.scalars(stmt)


def worker_present(conn, *, now=None):
    now = database_time(conn) if now is None else now
    seen = conn.scalar(sa.select(run_lane.c.worker_seen_at))
    if seen is not None and seen > now - LEASE:
        return True
    return conn.scalar(sa.select(sa.exists().where(runs.c.claim_until > now)))


def _attempts(conn, run_id):
    return conn.execute(sa.select(run_wan_attempts).where(ATTEMPTS.run_id == run_id)
                        .order_by(ATTEMPTS.created_at, ATTEMPTS.job_id)).mappings().all()


def _unsettled(conn, run_id):
    return conn.execute(sa.select(run_wan_attempts).where(
        ATTEMPTS.run_id == run_id, ATTEMPTS.state.in_(PENDING),
    )).mappings().one_or_none()


def _summary(attempt):
    return {key: attempt[key] for key in ("job_id", "kind", "attempt", "state")}


def view(conn, row, *, detail=True):
    doc = {**row["document"], "revision": row["revision"], "estimate_methods": row["estimate_methods"],
           "cancel_requested": row["cancel_requested"]}
    if detail:
        doc["wan_attempts"] = [_summary(attempt) for attempt in _attempts(conn, row["id"])]
        doc["check_overrides"] = list(conn.scalars(sa.select(run_check_overrides.c.document)
            .where(run_check_overrides.c.run_id == row["id"]).order_by(run_check_overrides.c.artifact)))
    return doc


def _save(conn, row, *, visible=True, **values):
    if visible:
        values["revision"] = runs.c.revision + 1
    return conn.execute(runs.update().where(runs.c.id == row["id"]).values(**values)
                        .returning(runs)).mappings().one()


def _clear_claim():
    return {"worker_id": None, "claim_until": None}


def claim(conn, worker_id, *, reconcile_paused=False):
    lane = conn.execute(sa.select(run_lane).with_for_update(skip_locked=True)).mappings().one_or_none()
    if lane is None:
        return None
    now = database_time(conn)
    if lane["worker_seen_at"] is None or lane["worker_seen_at"] <= now - BACKOFF:
        conn.execute(run_lane.update().values(worker_seen_at=now))
    paused = is_paused(conn, "run")
    if paused and not reconcile_paused:
        return None
    head = sa.select(sa.func.min(runs.c.position)).where(STATUS.in_(ACTIVE)).scalar_subquery()
    row = conn.execute(sa.select(runs).where(runs.c.position == head, STATUS.in_(ACTIVE))
                       .with_for_update(skip_locked=True)).mappings().one_or_none()
    if row is None:
        return None
    if ((row["claim_until"] is not None and row["claim_until"] > now) or
            (row["retry_at"] is not None and row["retry_at"] > now)):
        return None
    actor = {"kind": "worker", "worker_id": worker_id}
    doc = row["document"]
    attempt = _unsettled(conn, row["id"])
    if paused and (doc["status"] == "queued" or attempt is None or attempt["state"] != "sent"):
        return None
    if doc["status"] == "running":
        doc = advance(doc, "held", at=timestamp(now), by=actor,
                      reason="Previous claim expired. Reconcile recorded Wan work.")
    if doc["status"] == "queued":
        doc = advance(doc, "running", at=timestamp(now), by=actor, error=None, reason="Worker claimed run")
    row = _save(conn, row, document=doc, retry_at=None, worker_id=worker_id,
                fence=runs.c.fence + 1, claim_until=now + LEASE)
    earlier_runs = list(conn.scalars(sa.select(runs.c.id).where(
        runs.c.production_id == row["production_id"], runs.c.number < row["number"],
    ).order_by(runs.c.number.desc())))
    result = {"run": view(conn, row, detail=False), "snapshot": row["snapshot"],
              "library": row["frozen_library"], "fence": row["fence"], "earlier_runs": earlier_runs,
              "claim_until": row["claim_until"], "actor": actor,
              "pending": None if attempt is None else dict(attempt)}
    if paused:
        result["reconcile_only"] = True
    return result


def lock_claim(conn, run_id, worker_id, fence, *, wan_dispatch=False):
    if wan_dispatch:
        # Match the lane-before-run order used by claims. This lock serializes
        # dispatch authorization with pause, and ends before the Wan call.
        conn.execute(sa.select(run_lane.c.id).with_for_update(read=True)).scalar_one()
    row = get(conn, run_id, lock=True)
    now = database_time(conn)
    if (row["worker_id"] != worker_id or row["fence"] != fence or
            row["claim_until"] is None or row["claim_until"] <= now):
        raise QueueConflict("work.fence_lost", "This worker no longer owns the run")
    if wan_dispatch and not row["cancel_requested"]:
        _require_open_lane(conn)
    return row, now


def heartbeat(conn, row, now, progress):
    doc = row["document"]
    if progress is not None:
        progress = {**progress, "percent": max(doc["progress"]["percent"], progress["percent"])}
    if progress is not None and progress != doc["progress"]:
        row = _save(conn, row, document=update(doc, progress=progress), claim_until=now + LEASE)
    else:
        row = _save(conn, row, visible=False, claim_until=now + LEASE)
    return {"claim_until": row["claim_until"], "cancel_requested": row["cancel_requested"]}


def resume(conn, row, now, actor):
    if row["cancel_requested"]:
        raise QueueConflict("run.stopping", "The run was cancelled")
    pending = _unsettled(conn, row["id"])
    if pending is not None and pending["state"] == "sent":
        raise QueueConflict("wan.unsettled", "Reconcile the recorded Wan job before resuming")
    if row["document"]["status"] == "held":
        doc = advance(row["document"], "running", at=timestamp(now), by=actor, error=None,
                      reason="Worker reconciled recorded Wan work")
        row = _save(conn, row, document=doc)
    return view(conn, row, detail=False)


def wan_request_hash(request):
    # Wan product v1 uses sorted JSON with Python's default separators/ASCII escaping.
    return hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()


def _require_open_lane(conn):
    if is_paused(conn, "run"):
        raise QueueConflict("work.lane_paused", "The run lane is paused for new Wan work")


def reserve_attempt(conn, row, now, kind, request, *, check_pause=False):
    # The tracker URL labels Wan's ledger. It is not an inference input.
    clip_key = wan_request_hash({key: value for key, value in request.items() if key != "story"})
    latest = conn.execute(sa.select(run_wan_attempts).where(
        ATTEMPTS.run_id == row["id"], ATTEMPTS.clip_key == clip_key,
    ).order_by(ATTEMPTS.attempt.desc()).limit(1)).mappings().one_or_none()
    if latest is not None and latest["state"] in (*PENDING, "succeeded", "failed"):
        if check_pause and latest["state"] == "reserved":
            _require_open_lane(conn)
        return latest
    if latest is not None:
        request = latest["request"]
    if row["document"]["status"] != "running" or row["cancel_requested"] or row["publishing"]:
        raise QueueConflict("run.stopping", "The run cannot start another Wan job")
    if _unsettled(conn, row["id"]) is not None:
        raise QueueConflict("wan.unsettled", "Reconcile the recorded Wan job first")
    if check_pause:
        _require_open_lane(conn)
    attempt = conn.execute(run_wan_attempts.insert().values(
        job_id=uuid4().hex, run_id=row["id"], clip_key=clip_key, kind=kind, request=request,
        request_sha256=wan_request_hash(request), created_at=now, state="reserved",
        attempt=1 if latest is None else latest["attempt"] + 1,
    ).returning(run_wan_attempts)).mappings().one()
    _save(conn, row)
    return attempt


def _admission_backoff(row, now):
    refusals = min(row["admission_refusals"] + 1, 3)
    return {"admission_refusals": refusals,
            "retry_at": now + timedelta(seconds=60 * 2 ** (refusals - 1))}


def attempt_action(conn, row, now, job_id, state, outcome=None):
    attempt = conn.execute(sa.select(run_wan_attempts).where(
        ATTEMPTS.run_id == row["id"], ATTEMPTS.job_id == job_id,
    )).mappings().one_or_none()
    if attempt is None:
        raise NotFound
    if state != "sent" and attempt["state"] == state and attempt["outcome"] == outcome:
        # Retrying a lost outcome acknowledgement does not change the record.
        return attempt
    if state == "sent":
        expected = "reserved"
        if (row["document"]["status"] != "running" or row["cancel_requested"] or row["publishing"]):
            raise QueueConflict("run.stopping", "The run cannot submit another Wan job")
    else:
        expected = "sent"
    if attempt["state"] != expected:
        raise QueueConflict("wan.attempt_state", "The recorded Wan attempt cannot take this action")
    attempt = conn.execute(run_wan_attempts.update().where(ATTEMPTS.job_id == job_id)
                           .values(state=state, outcome=outcome)
                           .returning(run_wan_attempts)).mappings().one()
    if state == "busy":
        _save(conn, row, **_admission_backoff(row, now))
    elif state in ("succeeded", "restart_failed"):
        _save(conn, row, admission_refusals=0)
    else:
        _save(conn, row)
    return attempt


def cancel(conn, row, revision, actor):
    if revision != row["revision"]:
        raise StaleRevision(row["revision"])
    if row["document"]["status"] == "cancelled" or row["cancel_requested"]:
        return row
    if row["document"]["status"] not in ACTIVE or row["publishing"]:
        raise QueueConflict("run.transition", "The run cannot be cancelled after it finishes or starts publishing")
    pending = _unsettled(conn, row["id"])
    if pending is not None and pending["state"] == "sent":
        return _save(conn, row, cancel_requested=True, retry_at=None)
    if pending is not None:
        _settle(conn, pending, "cancelled")
    now = database_time(conn)
    doc = advance(row["document"], "cancelled", at=timestamp(now), by=actor,
                  reason="Cancelled by a Studio user or scoped agent", error=None,
                  progress={"percent": 100, "stage": "cancelled"})
    return _save(conn, row, document=doc, cancel_requested=True, retry_at=None, **_clear_claim())


def publish(conn, row):
    if row["document"]["status"] != "running" or row["cancel_requested"]:
        raise QueueConflict("run.stopping", "The run cannot start publication")
    if _unsettled(conn, row["id"]) is not None:
        raise QueueConflict("wan.unsettled", "Reconcile the recorded Wan job before publishing")
    if not row["publishing"]:
        _save(conn, row, publishing=True)


def _settle(conn, pending, state):
    conn.execute(run_wan_attempts.update().where(ATTEMPTS.job_id == pending["job_id"])
                 .values(state=state))


def finish(conn, row, now, actor, target, reason, fields, *, wait_reason=None,
           wan_job_id=None, admission_busy=False):
    pending = _unsettled(conn, row["id"])
    if wan_job_id is not None and (pending is None or pending["job_id"] != wan_job_id):
        raise QueueConflict("wan.attempt_state", "The outcome must settle the recorded Wan attempt")
    sent = pending is not None and pending["state"] == "sent"
    if target == "cancelled" and not row["cancel_requested"]:
        raise QueueConflict("run.transition", "No cancellation is pending")
    if target == "succeeded" and (not row["publishing"] or row["cancel_requested"]):
        raise QueueConflict("run.transition", "The run requires a fenced, verified delivery to succeed")
    if row["cancel_requested"] and (not sent or wan_job_id is not None):
        target, reason, wait_reason = "cancelled", "Cancelled after reconciling Wan work", None
        fields = {**fields, "error": None, "progress": {"percent": 100, "stage": "cancelled"}}
    if sent and wan_job_id is None and target != "held":
        raise QueueConflict("wan.unsettled", "Reconcile the recorded Wan job before releasing the run")
    if pending is not None and target in ("cancelled", "failed"):
        _settle(conn, pending, target)
    original = row["document"]
    if original["status"] == target:
        doc = update(original, **fields, wait_reason=wait_reason)
    else:
        doc = advance(original, target, at=timestamp(now), by=actor, reason=reason,
                      **fields, wait_reason=wait_reason)
    defer = {"retry_at": None}
    if target in ("held", "queued"):
        defer["retry_at"] = max(now + BACKOFF, row["retry_at"] or now)
        if admission_busy and not row["cancel_requested"]:
            defer.update(_admission_backoff(row, now))
    return _save(conn, row, document=doc, **defer, **_clear_claim())


def record_override(conn, row, revision, *, artifact, reason, actor):
    if row["revision"] != revision:
        raise StaleRevision(row["revision"])
    doc = row["document"]
    checks = [*(doc["checks"] or []), *(check for stage in doc["stages"]
                                        for check in (stage.get("checks") or []))]
    if doc["status"] not in ("failed", "succeeded") or not any(
        check["check"] == CHECK_OVERRIDABLE and check.get("artifact") == artifact and
        check["result"] == "fail" for check in checks
    ):
        raise QueueConflict("check.not_overridable", "This artifact has no failed, overridable decal check")
    exists = conn.scalar(sa.select(sa.exists().where(
        run_check_overrides.c.run_id == row["id"], run_check_overrides.c.artifact == artifact,
    )))
    if exists:
        raise QueueConflict("check.override_exists", "This artifact already has an override")
    override = {"check": CHECK_OVERRIDABLE, "artifact": artifact, "reason": reason,
                "by": actor, "at": timestamp(database_time(conn))}
    conn.execute(run_check_overrides.insert().values(run_id=row["id"], artifact=artifact, document=override))
    _save(conn, row)
    return override
