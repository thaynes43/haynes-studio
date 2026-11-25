"""Append-only PostgreSQL storage for the escalation contract."""

import json

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from haynes_studio.db.problems import NotFound
from haynes_studio.db.runs import timestamp
from haynes_studio.db.schema import metadata, run_check_overrides

failures = sa.Table(
    "escalation_check_failures", metadata,
    sa.Column("record_sha256", sa.String(64), primary_key=True),
    sa.Column("evaluation_id", sa.String(64), nullable=False),
    sa.Column("failure_id", sa.String(64), nullable=False),
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("actor", JSONB, nullable=False),
    sa.Column("result", sa.LargeBinary, nullable=False),
)
packages = sa.Table(
    "escalation_packages", metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column("production_id", sa.Text, nullable=False),
    sa.Column("responder_key_id", sa.Text, nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("sha256", sa.String(64), nullable=False),
    sa.Column("canonical_json", sa.LargeBinary, nullable=False),
)
events = sa.Table(
    "escalation_events", metadata,
    sa.Column("package_id", sa.String(64), primary_key=True),
    sa.Column("sequence", sa.Integer, primary_key=True),
    sa.Column("state", sa.Text, nullable=False),
    sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("actor", JSONB, nullable=False),
    sa.Column("detail", JSONB, nullable=False),
    sa.Column("external_request_id", sa.Text),
)


def lock(conn):
    # This schema's single transaction lock serializes all escalation writes,
    # including both dimensions of the cap. Runtime needs no UPDATE privileges.
    conn.execute(sa.select(sa.func.pg_advisory_xact_lock(
        sa.func.hashtext(sa.func.current_schema()), 445)))


def overridden(conn, run_id, check, artifact):
    return conn.scalar(sa.select(sa.exists().where(
        run_check_overrides.c.run_id == run_id,
        run_check_overrides.c.artifact == artifact,
        run_check_overrides.c.document["check"].astext == check,
    )))


def get_package(conn, package_id, production_id):
    row = conn.execute(sa.select(packages).where(
        packages.c.id == package_id, packages.c.production_id == production_id,
    )).mappings().one_or_none()
    if row is None:
        raise NotFound
    return row


def get_by_key(conn, key_id):
    return conn.execute(sa.select(packages).where(
        packages.c.responder_key_id == key_id,
    )).mappings().one_or_none()


def get_result(conn, run_id, record_sha256):
    row = conn.execute(sa.select(failures).where(
        failures.c.run_id == run_id, failures.c.record_sha256 == record_sha256,
    )).mappings().one_or_none()
    if row is None:
        raise NotFound
    return {"record_sha256": record_sha256, "recorded_at": timestamp(row["recorded_at"]),
            "actor": row["actor"], "result": json.loads(row["result"])}


def list_packages(conn, production_id, after, limit):
    return conn.execute(sa.select(packages).where(
        packages.c.production_id == production_id, packages.c.id > after,
    ).order_by(packages.c.id).limit(limit)).mappings().all()


def history(conn, package_id):
    return conn.execute(sa.select(events).where(
        events.c.package_id == package_id,
    ).order_by(events.c.sequence)).mappings().all()


def append_event(conn, package_id, sequence, state, now, actor, detail, *, external_request_id=None):
    conn.execute(events.insert().values(
        package_id=package_id, sequence=sequence, state=state, occurred_at=now,
        actor=actor, detail=detail, external_request_id=external_request_id,
    ))


def document(row):
    return json.loads(row["canonical_json"])


def view(conn, row, now):
    transitions = [{
        "sequence": event["sequence"], "state": event["state"], "at": timestamp(event["occurred_at"]),
        "by": event["actor"], "detail": event["detail"],
        **({"external_request_id": event["external_request_id"]} if event["external_request_id"] else {}),
    } for event in history(conn, row["id"])]
    return {"package": document(row), "sha256": row["sha256"], "state": transitions[-1]["state"],
            "expired": now >= row["expires_at"], "transitions": transitions}
