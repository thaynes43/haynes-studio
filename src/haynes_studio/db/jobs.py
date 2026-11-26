"""Durable media jobs beside the run queue."""

from dataclasses import replace

import sqlalchemy as sa

from haynes_studio.canonical.ids import is_id
from haynes_studio.canonical.model import to_document
from haynes_studio.errors import ContractError, Violation
from haynes_studio.voice import jobs as transitions
from haynes_studio.voice.model import Job

from .problems import NotFound
from .queue_controls import is_paused
from .runs import LEASE, IdempotencyMismatch, QueueConflict, actor_key, database_time, timestamp
from .schema import media_job_lanes, media_jobs

STATUS = media_jobs.c.document["status"].astext
ACTIVE = ("queued", "running")
KIND_LANE = {"voice": "voice", "photo": "image", "asset_candidate": "image", "matte": "matte"}
MATTE_RELEASE_LIMIT = 3


def lock_lane(conn, lane, *, skip_locked=False):
    return conn.scalar(sa.select(media_job_lanes.c.next_position).where(
        media_job_lanes.c.lane == lane,
    ).with_for_update(skip_locked=skip_locked))


def lookup(conn, kind, target, by, key, signature):
    row = conn.execute(sa.select(media_jobs).where(
        media_jobs.c.kind == kind, media_jobs.c.idempotency_target == target,
        media_jobs.c.idempotency_actor == actor_key(to_document(by)),
        media_jobs.c.idempotency_key == key,
    )).mappings().one_or_none()
    if row is not None and row["request_signature"] != signature:
        raise IdempotencyMismatch
    return row


def enqueue(conn, job, *, position, production, story=None, board=None, inputs, key, signature):
    lane = KIND_LANE[job.kind]
    requester = to_document(job.created_by)
    conn.execute(media_job_lanes.update().where(media_job_lanes.c.lane == lane)
                 .values(next_position=position + 1))
    return conn.execute(media_jobs.insert().values(
        id=job.id, production_id=production, story_id=story, board_id=board, lane=lane,
        position=position, kind=job.kind, idempotency_target=board or "asset-jobs",
        idempotency_actor=actor_key(requester), idempotency_key=key,
        request_signature=signature, requester=requester, inputs=inputs, document=job.to_document(),
    ).returning(media_jobs)).mappings().one()


def prior_matte_versions(conn, input_signature):
    version_id = media_jobs.c.document["result_version_id"].astext
    return list(conn.scalars(sa.select(version_id).where(
        media_jobs.c.lane == "matte", STATUS == "succeeded",
        media_jobs.c.document["input_signature"].astext == input_signature,
    ).distinct()))


def job_document(row):
    """Project the immutable requester onto the public job document."""
    requester = row.get("requester")
    if isinstance(requester, dict):
        kind = requester.get("kind")
        if (kind == "human" and requester.keys() == {"kind", "iss", "sub"}
                and all(isinstance(requester[key], str) and requester[key] for key in ("iss", "sub"))):
            return {**row["document"], "created_by": requester}
        if kind == "agent" and requester.keys() == {"kind", "key_id"} and is_id(requester["key_id"], "key"):
            return {**row["document"], "created_by": requester}
    raise ContractError(row["id"], [Violation(
        "job.requester_invalid", "/created_by", "The stored job requester is missing or invalid",
    )])


def get(conn, job_id, *, lock=False, lane=None):
    stmt = sa.select(media_jobs).where(media_jobs.c.id == job_id)
    if lane is not None:
        stmt = stmt.where(media_jobs.c.lane == lane)
    if lock:
        stmt = stmt.with_for_update()
    row = conn.execute(stmt).mappings().one_or_none()
    if row is None:
        raise NotFound
    return row


def list_board(conn, board, after, limit):
    stmt = sa.select(media_jobs).where(media_jobs.c.board_id == board)
    if after is not None:
        stmt = stmt.where(media_jobs.c.id > after)
    return conn.execute(stmt.order_by(media_jobs.c.id).limit(limit)).mappings().all()


def active_for_story(conn, story):
    rows = conn.execute(sa.select(media_jobs.c.id, media_jobs.c.document, media_jobs.c.requester).where(
        media_jobs.c.story_id == story, STATUS.in_(ACTIVE),
    )).mappings()
    return [Job.from_document(job_document(row)) for row in rows]


def save(conn, row, **values):
    return conn.execute(media_jobs.update().where(media_jobs.c.id == row["id"])
                        .values(**values).returning(media_jobs)).mappings().one()


def finish(conn, row, job, **values):
    document = job.to_document()
    save(conn, row, document=document, worker_id=None, claim_until=None, **values)
    return document


def claim(conn, worker_id, lane, *, settle_only=False):
    if lock_lane(conn, lane, skip_locked=True) is None:
        return None
    settle_dispatch = settle_only or is_paused(conn, lane)
    head = sa.select(sa.func.min(media_jobs.c.position)).where(
        media_jobs.c.lane == lane, STATUS.in_(ACTIVE),
    ).scalar_subquery()
    row = conn.execute(sa.select(media_jobs).where(
        media_jobs.c.lane == lane, media_jobs.c.position == head, STATUS.in_(ACTIVE),
    ).with_for_update(skip_locked=True)).mappings().one_or_none()
    # A paused lane can retire an expired dispatch without starting work.
    if row is None or (settle_dispatch and not row["dispatched"]):
        return None
    now = database_time(conn)
    if row["claim_until"] is not None and row["claim_until"] > now:
        return None
    job = Job.from_document(job_document(row))
    if row["dispatched"]:
        # Engine submission is not idempotent. Expiry can only retire the job,
        # and the image adapter still waits for the shared engine queue to drain.
        finish(conn, row, transitions.fail(
            job, "work.dispatch_unconfirmed", "The worker claim expired after dispatch began",
            now=timestamp(now),
        ))
        return None
    if job.status == "queued":
        job = transitions.start(job, now=timestamp(now))
    return save(conn, row, document=job.to_document(), fence=media_jobs.c.fence + 1,
                worker_id=worker_id, claim_until=now + LEASE)


def lock_claim(conn, job_id, worker_id, fence, *, lane):
    row = get(conn, job_id, lock=True, lane=lane)
    now = database_time(conn)
    if (row["worker_id"] != worker_id or row["fence"] != fence or
            row["claim_until"] is None or row["claim_until"] <= now):
        raise QueueConflict("work.fence_lost", "This worker no longer owns the media job")
    return row, now


def heartbeat(conn, row, now):
    claim_until = now + LEASE
    save(conn, row, claim_until=claim_until)
    return {"claim_until": claim_until, "cancel_requested": False}


def dispatch(conn, row, now):
    if row["dispatched"]:
        raise QueueConflict("work.dispatched", "This job has already entered engine dispatch")
    save(conn, row, dispatched=True, claim_until=now + LEASE)


def release_matte(conn, row, now, *, reason=None):
    if row["dispatched"] and reason is None:
        raise QueueConflict("work.dispatched", "A dispatched matte job cannot be released")
    job = Job.from_document(job_document(row))
    updated_at = timestamp(now)
    if reason != "busy" and row["matte_releases"] >= MATTE_RELEASE_LIMIT:
        finish(conn, row, transitions.fail(job, "matting.sidecar_unavailable",
                                           "The matting sidecar repeatedly could not start the cutout",
                                           now=updated_at), dispatched=False)
        return
    # Keep the job's FIFO position and revoke the current fence's lease.
    queued = replace(job, status="queued", updated_at=updated_at)
    save(conn, row, document=queued.to_document(), worker_id=None, claim_until=None, dispatched=False,
         matte_releases=min(row["matte_releases"] + 1, MATTE_RELEASE_LIMIT))
