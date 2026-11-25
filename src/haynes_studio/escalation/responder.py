"""Restrict the package's exact agent identity at Studio's API boundary."""

from datetime import timedelta

import sqlalchemy as sa

from haynes_studio.db import runs
from haynes_studio.db.schema import agent_grants, agent_keys
from haynes_studio.db.schema import runs as run_table

from . import storage
from .lifecycle import OUTCOMES, EscalationError, require_live
from .package import RESPONDER_PREFIX, digest


def is_responder(key_id):
    return key_id is not None and key_id.startswith(RESPONDER_PREFIX)


def _refuse():
    return EscalationError("responder_scope", "The package does not permit this responder operation", 403)


def _require_key(conn, row, key_id, now):
    if key_id != row["responder_key_id"]:
        raise _refuse()
    if now >= row["expires_at"]:
        raise EscalationError("expired", "The package has expired")
    key = conn.execute(sa.select(agent_keys.c.expires_at, agent_keys.c.revoked_at).where(
        agent_keys.c.id == key_id,
    )).one_or_none()
    grants = set(conn.execute(sa.select(agent_grants.c.production_id, agent_grants.c.scope).where(
        agent_grants.c.key_id == key_id, agent_grants.c.active,
    )))
    expected = {(row["production_id"], scope) for scope in storage.document(row)["responder_key"]["scopes"]}
    if key is None or key.revoked_at is not None or key.expires_at != row["expires_at"] or grants != expected:
        raise _refuse()


def _active_package(conn, key_id):
    row = storage.get_by_key(conn, key_id)
    if row is None:
        raise _refuse()
    now = runs.database_time(conn)
    require_live(conn, row, now)
    _require_key(conn, row, key_id, now)
    transitions = storage.history(conn, row["id"])
    latest = transitions[-1]
    if latest["state"] != "requested":
        raise _refuse()
    doc = storage.document(row)
    if now >= latest["occurred_at"] + timedelta(seconds=doc["usage_cap"]["seconds"]):
        raise EscalationError("budget_elapsed", "The responder's execution window has ended")
    return doc, transitions


def require_route(conn, key_id, operation, parameters):
    """All ordinary authenticated routes default to refusal for a responder."""
    # Callback validates its path, key, expiry and idempotency in its own
    # transaction. In particular, a retry can follow the terminal event.
    if operation == "report_escalation":
        return
    doc, _ = _active_package(conn, key_id)
    allowed = doc["allowed_actions"]
    if operation == "get_me":
        return  # Existing MCP identity handshake.
    if operation == "get_story" and parameters["id"] == doc["story_id"]:
        if "studio_get_story_summary" in allowed:
            return
    if operation == "queue_run" and parameters["id"] == doc["story_id"]:
        if "studio_queue_run" in allowed:
            return
    if operation in ("get_board", "update_board") and parameters["id"] in doc["board_ids"]:
        action = "studio_get_board" if operation == "get_board" else "studio_patch_board"
        if action in allowed:
            return
    if operation == "get_escalation_check" and parameters["run_id"] == doc["run_id"]:
        if any(ref["record_sha256"] == parameters["record_sha256"] for ref in doc["failure"]["results"]):
            return
    if operation == "get_media" and any(
        ref["sha256"] == parameters["sha256"] for ref in doc["artifacts"]
    ):
        return
    raise _refuse()


def require_patch(conn, key_id, story_id, board_id, fields):
    """Hold the lifecycle lock through the normal fenced draft write."""
    storage.lock(conn)
    doc, transitions = _active_package(conn, key_id)
    if (story_id != doc["story_id"] or board_id not in doc["board_ids"]
            or "studio_patch_board" not in doc["allowed_actions"]):
        raise _refuse()
    if set(fields) - {*doc["patch_fields"], "acknowledge_person_edit"}:
        raise _refuse()
    if ("acknowledge_person_edit" in fields
            and board_id not in transitions[1]["detail"]["acknowledged_board_ids"]):
        raise _refuse()


def _queued_by_responder(story_id, actor):
    return sa.select(run_table).where(
        run_table.c.story_id == story_id, run_table.c.idempotency_actor == runs.actor_key(actor),
    )


def require_queue(conn, actor, story_id, idempotency_key):
    storage.lock(conn)
    doc, _ = _active_package(conn, actor["key_id"])
    if story_id != doc["story_id"] or "studio_queue_run" not in doc["allowed_actions"]:
        raise _refuse()
    keys = set(conn.scalars(_queued_by_responder(story_id, actor)
                           .with_only_columns(run_table.c.idempotency_key)))
    if idempotency_key not in keys and len(keys) >= doc["usage_cap"]["queued_runs"]:
        raise EscalationError("run_cap", "The responder already queued its allowed run")


def report(conn, production_id, package_id, *, actor, idempotency_key, report):
    storage.lock(conn)
    now = runs.database_time(conn)
    row = storage.get_package(conn, package_id, production_id)
    key_id = actor.get("key_id") if actor["kind"] == "agent" else None
    _require_key(conn, row, key_id, now)
    transitions = storage.history(conn, package_id)
    latest = transitions[-1]
    receipt = {"idempotency_sha256": digest(idempotency_key), "report": report}
    if latest["state"] in OUTCOMES:
        if latest["detail"] != receipt:
            raise EscalationError("callback_conflict", "The package already has a different callback")
        return storage.view(conn, row, now)
    if latest["state"] != "requested":
        raise EscalationError("state", "Only a requested package can receive a callback")
    doc = storage.document(row)
    if not set(report["changed_board_ids"]).issubset(doc["board_ids"]):
        raise EscalationError("changed_ids", "Report only this package's board IDs", 422)
    if report["queued_run_ids"]:
        queued = set(conn.scalars(_queued_by_responder(doc["story_id"], actor)
                                  .with_only_columns(run_table.c.id)))
        if not set(report["queued_run_ids"]).issubset(queued):
            raise EscalationError("changed_ids", "Report only the run queued with this package", 422)
    storage.append_event(conn, package_id, len(transitions) + 1, report["outcome"], now, actor, receipt)
    return storage.view(conn, row, now)
