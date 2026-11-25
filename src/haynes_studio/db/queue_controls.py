"""Append-only pause and resume decisions serialized with lane claims."""

import sqlalchemy as sa

from .schema import media_job_lanes, queue_lane_events, run_lane

LANES = ("run", "voice", "image")


def _latest(conn, lane):
    return conn.execute(sa.select(queue_lane_events).where(
        queue_lane_events.c.lane == lane,
    ).order_by(queue_lane_events.c.sequence.desc()).limit(1)).mappings().one_or_none()


def is_paused(conn, lane):
    decision = _latest(conn, lane)
    return decision is not None and decision["paused"]


def _status(lane, decision):
    if decision is None:
        return {"lane": lane, "paused": False, "changed_at": None, "changed_by": None}
    return {key: decision[key] for key in ("lane", "paused", "changed_at", "changed_by")}


def status(conn):
    return [_status(lane, _latest(conn, lane)) for lane in LANES]


def set_paused(conn, lane, paused, by, clock):
    # These are the same row locks held during claim acquisition. Enqueueing uses
    # the locks for FIFO allocation and does not consult the pause state.
    lock = (sa.select(run_lane.c.id) if lane == "run" else
            sa.select(media_job_lanes.c.lane).where(media_job_lanes.c.lane == lane))
    conn.execute(lock.with_for_update()).scalar_one()
    latest = _latest(conn, lane)
    current = _status(lane, latest)
    if current["paused"] == paused:
        return current
    decision = conn.execute(queue_lane_events.insert().values(
        lane=lane, sequence=1 if latest is None else latest["sequence"] + 1,
        paused=paused, changed_by=by, changed_at=clock(conn),
    ).returning(queue_lane_events)).mappings().one()
    return _status(lane, decision)
