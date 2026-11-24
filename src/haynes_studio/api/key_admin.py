"""Provision or revoke scoped Studio agent keys using the migration identity."""

import argparse
import json
import logging
import os
import secrets
import sys
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from haynes_studio.canonical.ids import Minter, is_id
from haynes_studio.db.engine import connect_engine
from haynes_studio.db.identity import AGENT_SCOPES, digest
from haynes_studio.db.schema import agent_grants, agent_keys, productions

from .transport import access_log


class AdminProblem(Exception):
    def __init__(self, code: str, status: int):
        super().__init__(code)
        self.status = status


def _owner(conn) -> str:
    role, owns_credentials = conn.execute(sa.text("""
        SELECT current_user, (
            SELECT count(*) = 2 AND bool_and(pg_get_userbyid(c.relowner) = current_user)
            FROM pg_class c JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = current_schema() AND c.relname IN ('agent_keys', 'agent_grants')
        )
    """)).one()
    if not owns_credentials:
        raise AdminProblem("key_admin.owner_required", 403)
    return role


def _expiry(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        expires = datetime.fromisoformat(value)
        if expires.tzinfo is not None:
            return expires
    except ValueError:
        pass
    raise AdminProblem("key_admin.invalid_expiry", 422)


def _create(conn, key_id: str, production_ids: list[str], scopes: list[str],
            expires_at: datetime | None) -> dict:
    production_ids, scopes = sorted(set(production_ids)), sorted(set(scopes))
    if not all(is_id(item, "prd") for item in production_ids):
        raise AdminProblem("key_admin.invalid_production", 422)
    if not set(scopes) <= AGENT_SCOPES:
        raise AdminProblem("key_admin.invalid_scope", 422)
    existing = set(conn.scalars(sa.select(productions.c.id).where(productions.c.id.in_(production_ids))))
    if existing != set(production_ids):
        raise AdminProblem("key_admin.production_not_found", 404)
    if expires_at is not None and expires_at <= conn.scalar(sa.select(sa.func.now())):
        raise AdminProblem("key_admin.expiry_in_past", 422)
    secret = secrets.token_urlsafe(32)
    conn.execute(agent_keys.insert(), {"id": key_id, "digest": digest(secret), "expires_at": expires_at})
    conn.execute(agent_grants.insert(), [
        {"key_id": key_id, "production_id": production_id, "scope": scope}
        for production_id in production_ids for scope in scopes
    ])
    return {"key_id": key_id, "key": secret}


def _isoformat(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


def _list(conn) -> dict:
    rows = conn.execute(sa.select(
        agent_keys.c.id, agent_keys.c.expires_at, agent_keys.c.revoked_at,
        agent_grants.c.production_id, agent_grants.c.scope,
    ).select_from(agent_keys.outerjoin(agent_grants)).order_by(
        agent_keys.c.id, agent_grants.c.production_id, agent_grants.c.scope,
    ))
    keys = {}
    for row in rows:
        if row.id not in keys:
            keys[row.id] = {
                "key_id": row.id, "expires_at": _isoformat(row.expires_at),
                "revoked_at": _isoformat(row.revoked_at), "production_scopes": {},
            }
        if row.production_id is not None:
            keys[row.id]["production_scopes"].setdefault(row.production_id, []).append(row.scope)
    return {"keys": list(keys.values())}


def _revoke(conn, key_id: str) -> dict:
    if not is_id(key_id, "key"):
        raise AdminProblem("key_admin.invalid_key_id", 422)
    revoked_at = conn.scalar(agent_keys.update().where(
        agent_keys.c.id == key_id, agent_keys.c.revoked_at.is_(None),
    ).values(revoked_at=sa.func.now()).returning(agent_keys.c.revoked_at))
    if revoked_at is None:
        revoked_at = conn.scalar(sa.select(agent_keys.c.revoked_at).where(agent_keys.c.id == key_id))
    if revoked_at is None:
        raise AdminProblem("key_admin.key_not_found", 404)
    return {"key_id": key_id, "revoked_at": _isoformat(revoked_at)}


def run(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    tasks = parser.add_subparsers(dest="action", required=True)
    create = tasks.add_parser("create", help="Create a key and print its secret once")
    create.add_argument("--production", required=True, action="append", metavar="PRODUCTION_ID",
                        help="Grant access to this production ID. Repeat for more productions.")
    create.add_argument("--scope", required=True, action="append", metavar="SCOPE",
                        help=f"Grant one of {', '.join(sorted(AGENT_SCOPES))}. Repeat for more scopes.")
    create.add_argument("--expires-at", help="Optional future ISO 8601 timestamp with a timezone")
    tasks.add_parser("list", help="List key IDs, scopes, expiry and revocation")
    revoke = tasks.add_parser("revoke", help="Revoke a key by ID")
    revoke.add_argument("key_id")
    options = parser.parse_args(argv)

    key_id = getattr(options, "key_id", None)
    key_id = key_id if is_id(key_id, "key") else None
    audit = {
        "action": f"agent_keys.{options.action}", "request_id": f"key-admin-{uuid4().hex}",
        "principal_kind": "database_owner", "principal_id": None, "key_id": key_id, "status": 500,
    }
    engine = None
    try:
        dsn = os.getenv("STUDIO_MIGRATION_DATABASE_URL")
        if not dsn:
            raise AdminProblem("key_admin.migration_dsn_required", 422)
        engine = connect_engine(dsn, os.getenv("STUDIO_DATABASE_SCHEMA", "studio"))
        with engine.begin() as conn:
            audit["principal_id"] = _owner(conn)
            if options.action == "create":
                key_id = Minter().mint("key")
                result = _create(conn, key_id, options.production, options.scope, _expiry(options.expires_at))
            elif options.action == "list":
                result = _list(conn)
            else:
                result = _revoke(conn, options.key_id)
        audit["key_id"] = key_id
        audit["status"] = 201 if options.action == "create" else 200
    except (AdminProblem, SQLAlchemyError, ValueError, OSError) as error:
        if isinstance(error, AdminProblem):
            audit["status"] = error.status
            code = str(error)
        else:
            code = "key_admin.failed"
        audit["code"] = code
        print(code, file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()
        access_log.info("%s", json.dumps(audit, separators=(",", ":")))
    print(json.dumps(result, separators=(",", ":")))
    return 0


def main() -> int:
    handler = logging.StreamHandler()
    access_log.addHandler(handler)
    previous_level, previous_propagate = access_log.level, access_log.propagate
    access_log.setLevel(logging.INFO)
    access_log.propagate = False
    try:
        return run()
    finally:
        access_log.removeHandler(handler)
        access_log.setLevel(previous_level)
        access_log.propagate = previous_propagate


if __name__ == "__main__":
    raise SystemExit(main())
