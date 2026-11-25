"""Append and read approval events in the caller's database transaction."""

import sqlalchemy as sa

from haynes_studio.canonical.ids import Minter
from haynes_studio.db.problems import NotFound
from haynes_studio.db.schema import go_live_approvals as approvals, go_live_withdrawals as withdrawals
from haynes_studio.db.schema import runs, stories

_active = approvals.outerjoin(withdrawals, withdrawals.c.approval_id == approvals.c.id)


def active_id(run_id):
    return (sa.select(approvals.c.id).select_from(_active)
            .where(approvals.c.run_id == run_id, withdrawals.c.approval_id.is_(None))
            .order_by(approvals.c.id).limit(1))


def story_approved():
    return sa.exists(sa.select(1).select_from(_active.join(runs, runs.c.id == approvals.c.run_id))
                     .where(runs.c.story_id == stories.c.id, withdrawals.c.approval_id.is_(None))
                     .correlate(stories))


def story_status_query():
    finished_at = runs.c.document["finished_at"].astext
    finished_run = (sa.select(sa.func.jsonb_build_object(
        "id", runs.c.id, "status", runs.c.document["status"].astext,
        "finished_at", finished_at, "active_approval_id", active_id(runs.c.id).scalar_subquery(),
    )).where(runs.c.story_id == stories.c.id, finished_at.is_not(None))
        .order_by(sa.cast(finished_at, sa.DateTime(timezone=True)).desc(), runs.c.position.desc())
        .limit(1).correlate(stories).scalar_subquery())
    return sa.select(stories.c.id, stories.c.published, story_approved().label("approved"),
                     finished_run.label("latest_finished_run"))


def _view(document, withdrawal):
    return {**document, "derived": {"state": "withdrawn" if withdrawal is not None else "active",
                                    "withdrawal": withdrawal, "publication_ids": []}}


def record_approval(conn, run, master_sha256, approver, display_name, auth_time, approved_at, checks):
    document = {
        "schema": "studio.go-live-approval/v1", "id": Minter().mint("apr"),
        "run_id": run["id"], "run_snapshot_sha256": run["snapshot"]["sha256"],
        "delivery_id": run["delivery_id"], "master_sha256": master_sha256,
        "approver": approver, "approver_display_name": display_name,
        "auth_time": auth_time, "approved_at": approved_at,
        "release_checks": checks,
    }
    conn.execute(approvals.insert().values(
        id=document["id"], run_id=run["id"], delivery_id=run["delivery_id"], document=document,
    ))
    return _view(document, None)


def get(conn, approval_id):
    result = conn.scalar(sa.select(approvals.c.document).where(approvals.c.id == approval_id))
    if result is None:
        raise NotFound
    return result


def history(conn, run_id):
    approved_at = sa.cast(approvals.c.document["approved_at"].astext, sa.DateTime(timezone=True))
    rows = conn.execute(sa.select(approvals.c.document, withdrawals.c.document).select_from(_active)
                        .where(approvals.c.run_id == run_id)
                        .order_by(approved_at.desc(), approvals.c.id.desc()))
    return [_view(document, withdrawal) for document, withdrawal in rows]


def record_withdrawal(conn, approval, by, auth_time, withdrawn_at):
    document = {
        "schema": "studio.go-live-withdrawal/v1", "approval_id": approval["id"],
        "withdrawn_by": by, "auth_time": auth_time, "withdrawn_at": withdrawn_at,
    }
    conn.execute(withdrawals.insert().values(approval_id=approval["id"], document=document))
    return _view(approval, document)
