"""Administer Studio credentials and import finished productions."""

import argparse
import json
import logging
import os
import re
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from haynes_studio.agent_tokens import MAX_AGENT_TOKEN_LENGTH, valid_agent_token
from haynes_studio.canonical.ids import Minter, is_id
from haynes_studio.db.engine import connect_engine
from haynes_studio.db.identity import AGENT_SCOPES, digest
from haynes_studio.db.schema import agent_grants, agent_keys, productions, worker_tokens
from haynes_studio.queue.worker_tokens import MAX_SECRET_LENGTH, worker_bearer

from .transport import access_log


class AdminProblem(Exception):
    def __init__(self, code: str, status: int):
        super().__init__(code)
        self.status = status


class AdminParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        # argparse can include a mistakenly supplied key in its error message.
        self.print_usage(sys.stderr)
        self.exit(2, "key_admin.invalid_arguments: see --help for accepted options\n")


def _admin_role(conn, *, worker: bool) -> str:
    role, can_administer = conn.execute(sa.text("""
        SELECT current_user, COALESCE(has_schema_privilege(current_schema(), 'USAGE'), false)
            AND bool_and(COALESCE(has_column_privilege(to_regclass(table_name), column_name, privilege), false))
        FROM (VALUES
            (false, 'productions', 'SELECT', ARRAY['id']),
            (false, 'agent_keys', 'SELECT', ARRAY['id', 'digest', 'expires_at', 'revoked_at']),
            (false, 'agent_keys', 'INSERT', ARRAY['id', 'digest', 'expires_at']),
            (false, 'agent_keys', 'UPDATE', ARRAY['expires_at', 'revoked_at']),
            (false, 'agent_grants', 'SELECT', ARRAY['key_id', 'production_id', 'scope', 'active']),
            (false, 'agent_grants', 'INSERT', ARRAY['key_id', 'production_id', 'scope']),
            (false, 'agent_grants', 'UPDATE', ARRAY['active']),
            (true, 'worker_tokens', 'SELECT', ARRAY['digest', 'worker_id', 'expires_at', 'revoked_at']),
            (true, 'worker_tokens', 'INSERT', ARRAY['digest', 'worker_id']),
            (true, 'worker_tokens', 'UPDATE', ARRAY['revoked_at'])
        ) AS required(worker, table_name, privilege, columns)
        CROSS JOIN LATERAL unnest(columns) AS fields(column_name)
        WHERE worker = :worker
    """), {"worker": worker}).one()
    if not can_administer:
        raise AdminProblem("key_admin.privileges_required", 403)
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


def _provision(conn, secret_digest: str, production_ids: list[str], scopes: list[str],
               expires_at: datetime | None, *, register: bool, replace_grants: bool) -> tuple[str, bool]:
    production_ids, scopes = sorted(set(production_ids)), sorted(set(scopes))
    if not all(is_id(item, "prd") for item in production_ids):
        raise AdminProblem("key_admin.invalid_production", 422)
    if not set(scopes) <= AGENT_SCOPES:
        raise AdminProblem("key_admin.invalid_scope", 422)

    new_key = insert(agent_keys).values(
        id=Minter().mint("key"), digest=secret_digest, expires_at=expires_at,
    ).on_conflict_do_nothing(index_elements=[agent_keys.c.digest]).returning(agent_keys.c.id)
    key_id = conn.scalar(new_key)
    grants = {(production_id, scope) for production_id in production_ids for scope in scopes}
    created = key_id is not None
    if not created:
        if not register:
            raise AdminProblem("key_admin.key_conflict", 409)
        # A registration or revocation of the same key must finish before we compare grants.
        key_id, current_expiry, revoked_at = conn.execute(sa.select(
            agent_keys.c.id, agent_keys.c.expires_at, agent_keys.c.revoked_at,
        ).where(agent_keys.c.digest == secret_digest).with_for_update()).one()
        if revoked_at is not None:
            raise AdminProblem("key_admin.key_revoked", 409)
        current_grants = set(conn.execute(sa.select(agent_grants.c.production_id, agent_grants.c.scope).where(
            agent_grants.c.key_id == key_id, agent_grants.c.active,
        )))
        if current_grants == grants and current_expiry == expires_at:
            return key_id, False
        if not replace_grants:
            raise AdminProblem("key_admin.grants_conflict", 409)

    existing = set(conn.scalars(sa.select(productions.c.id).where(productions.c.id.in_(production_ids))))
    if existing != set(production_ids):
        raise AdminProblem("key_admin.production_not_found", 404)
    if expires_at is not None and expires_at <= conn.scalar(sa.select(sa.func.now())):
        raise AdminProblem("key_admin.expiry_in_past", 422)

    if not created:
        conn.execute(agent_keys.update().where(agent_keys.c.id == key_id).values(expires_at=expires_at))
        conn.execute(agent_grants.update().where(
            agent_grants.c.key_id == key_id, agent_grants.c.active,
        ).values(active=False))
    grant = insert(agent_grants).on_conflict_do_update(
        index_elements=[agent_grants.c.key_id, agent_grants.c.production_id, agent_grants.c.scope],
        set_={"active": True},
    )
    conn.execute(grant, [
        {"key_id": key_id, "production_id": production_id, "scope": scope}
        for production_id, scope in sorted(grants)
    ])
    return key_id, created


def _read_secret_file(path: Path, max_length: int, error_code: str) -> str:
    with path.open("rb") as key_file:
        raw = key_file.read(max_length + 3)
    raw = raw.removesuffix(b"\r\n") if raw.endswith(b"\r\n") else raw.removesuffix(b"\n")
    if not raw.isascii():
        raise AdminProblem(error_code, 422)
    return raw.decode("ascii")


def _read_key(path: Path) -> str:
    secret = _read_secret_file(path, MAX_AGENT_TOKEN_LENGTH, "key_admin.invalid_key_file")
    if not valid_agent_token(secret):
        raise AdminProblem("key_admin.invalid_key_file", 422)
    return secret


def _write_key(path: Path, secret: str) -> None:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise AdminProblem("key_admin.output_exists", 409) from None
    try:
        with os.fdopen(fd, "w", encoding="ascii") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(secret + "\n")
    except OSError:
        path.unlink(missing_ok=True)
        raise


def _isoformat(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


def _list(conn) -> dict:
    rows = conn.execute(sa.select(
        agent_keys.c.id, agent_keys.c.expires_at, agent_keys.c.revoked_at,
        agent_grants.c.production_id, agent_grants.c.scope,
    ).select_from(agent_keys.outerjoin(agent_grants, sa.and_(
        agent_keys.c.id == agent_grants.c.key_id, agent_grants.c.active,
    ))).order_by(
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


def _worker_digest(path: Path, worker_id: str) -> str:
    code = "key_admin.invalid_worker_token_file"
    secret = _read_secret_file(path, MAX_SECRET_LENGTH, code)
    try:
        token = worker_bearer(secret)
    except ValueError:
        raise AdminProblem(code, 422) from None
    if worker_id in (secret, token):
        raise AdminProblem("key_admin.invalid_worker_id", 422)
    return digest(token)


def _worker_admin(conn, options, secret_digest: str | None) -> tuple[dict, int]:
    columns = worker_tokens.c
    if options.worker_action == "list":
        rows = conn.execute(sa.select(columns.worker_id, columns.expires_at, columns.revoked_at)
                            .order_by(columns.worker_id, columns.revoked_at, columns.expires_at))
        return {"workers": [{"worker_id": worker_id, "expires_at": _isoformat(expires_at),
                             "revoked_at": _isoformat(revoked_at)}
                            for worker_id, expires_at, revoked_at in rows]}, 200

    worker_id = options.worker_id
    # The digest is unique in PostgreSQL. Serialize changes within the schema
    # as worker IDs can have multiple historical rows and have no unique index.
    conn.execute(sa.select(sa.func.pg_advisory_xact_lock(
        sa.func.hashtext("studio.worker_token_admin"), sa.func.hashtext(sa.func.current_schema()),
    )))
    by_worker = columns.worker_id == worker_id
    revoke = worker_tokens.update().where(by_worker, columns.revoked_at.is_(None)).values(revoked_at=sa.func.now())
    if options.worker_action == "revoke":
        conn.execute(revoke)
        revoked_at = conn.scalar(sa.select(sa.func.max(columns.revoked_at)).where(by_worker))
        if revoked_at is None:
            raise AdminProblem("key_admin.worker_not_found", 404)
        return {"worker_id": worker_id, "revoked_at": _isoformat(revoked_at)}, 200

    row = conn.execute(sa.select(columns.worker_id, columns.revoked_at).where(
        columns.digest == secret_digest,
    )).one_or_none()
    if row is not None:
        if row.worker_id != worker_id:
            raise AdminProblem("key_admin.worker_token_conflict", 409)
        if row.revoked_at is not None:
            raise AdminProblem("key_admin.worker_token_revoked", 409)
        return {"worker_id": worker_id}, 200
    if conn.scalar(sa.select(sa.select(columns.worker_id).where(by_worker).exists())):
        if not options.replace:
            raise AdminProblem("key_admin.worker_id_conflict", 409)
        conn.execute(revoke)
    conn.execute(worker_tokens.insert().values(digest=secret_digest, worker_id=worker_id))
    return {"worker_id": worker_id}, 201


def run(argv=None) -> int:
    from haynes_studio.importer import production

    parser = AdminParser(description=__doc__)
    tasks = parser.add_subparsers(dest="action", required=True)
    production.add_arguments(tasks.add_parser(
        "import-production", help="Import a verified finished production archive",
    ))
    create = tasks.add_parser("create", help="Generate a new key")
    create.add_argument("--out", type=Path, metavar="PATH", help="Write the key to a new private file")
    register = tasks.add_parser("register", help="Register a key supplied in a file")
    register.add_argument("--key-file", type=Path, required=True, metavar="PATH")
    register.add_argument("--replace-grants", action="store_true", help="Replace existing grants and expiry")
    for provision in (create, register):
        provision.add_argument("--production", required=True, action="append", metavar="PRODUCTION_ID",
                               help="Grant access to this production ID. Repeat for more productions.")
        provision.add_argument("--scope", required=True, action="append", metavar="SCOPE",
                               help=f"Grant one of {', '.join(sorted(AGENT_SCOPES))}. Repeat for more scopes.")
        provision.add_argument("--expires-at", help="Optional future ISO 8601 timestamp with a timezone")
    tasks.add_parser("list", help="List key IDs, scopes, expiry and revocation")
    revoke = tasks.add_parser("revoke", help="Revoke a key by ID")
    revoke.add_argument("key_id")
    worker = tasks.add_parser("worker-token", help="Administer queue worker tokens")
    worker_tasks = worker.add_subparsers(dest="worker_action", required=True)
    worker_register = worker_tasks.add_parser("register", help="Register a worker token supplied in a file")
    worker_register.add_argument("--worker-id", required=True)
    worker_register.add_argument("--token-file", type=Path, required=True, metavar="PATH")
    worker_register.add_argument("--replace", action="store_true", help="Revoke prior tokens for this worker ID")
    worker_tasks.add_parser("list", help="List worker IDs, expiry and revocation")
    worker_revoke = worker_tasks.add_parser("revoke", help="Revoke tokens by worker ID")
    worker_revoke.add_argument("worker_id")
    options = parser.parse_args(argv)

    if options.action == "import-production":
        return production.run(options)

    worker_mode = options.action == "worker-token"
    key_id = getattr(options, "key_id", None)
    key_id = key_id if is_id(key_id, "key") else None
    audit = {
        "action": (f"worker_tokens.{options.worker_action}" if worker_mode else f"agent_keys.{options.action}"),
        "request_id": f"key-admin-{uuid4().hex}",
        "principal_kind": "database_role", "principal_id": None, "key_id": key_id, "status": 500,
    }
    engine = None
    try:
        if options.action == "create" and options.out is None and not sys.stdout.isatty():
            raise AdminProblem("key_admin.output_required", 422)
        secret = None
        if options.action == "create":
            secret = secrets.token_urlsafe(32)
        elif options.action == "register":
            secret = _read_key(options.key_file)
        worker_digest = None
        if worker_mode and options.worker_action != "list":
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,62}", options.worker_id):
                raise AdminProblem("key_admin.invalid_worker_id", 422)
            if options.worker_action == "register":
                worker_digest = _worker_digest(options.token_file, options.worker_id)
        dsn = os.getenv("STUDIO_MIGRATION_DATABASE_URL")
        if not dsn:
            raise AdminProblem("key_admin.migration_dsn_required", 422)
        engine = connect_engine(dsn, os.getenv("STUDIO_DATABASE_SCHEMA", "studio"))
        status = 200
        with engine.begin() as conn:
            audit["principal_id"] = _admin_role(conn, worker=worker_mode)
            if worker_mode:
                result, status = _worker_admin(conn, options, worker_digest)
            elif secret is not None:
                key_id, created = _provision(
                    conn, digest(secret), options.production, options.scope, _expiry(options.expires_at),
                    register=options.action == "register", replace_grants=getattr(options, "replace_grants", False),
                )
                result = {"key_id": key_id}
                status = 201 if created else 200
                if options.action == "create":
                    if options.out is None:
                        result["key"] = secret
                    elif os.path.lexists(options.out):
                        raise AdminProblem("key_admin.output_exists", 409)
            elif options.action == "list":
                result = _list(conn)
            else:
                result = _revoke(conn, options.key_id)
        audit["key_id"] = key_id
        if worker_mode and "worker_id" in result:
            audit["worker_id"] = result["worker_id"]
        if options.action == "create" and options.out is not None:
            try:
                _write_key(options.out, secret)
            except (AdminProblem, OSError):
                # A concurrent file creation or write failure after commit leaves
                # the freshly provisioned key undistributed. Revoke it by ID.
                with engine.begin() as conn:
                    _revoke(conn, key_id)
                raise
        audit["status"] = status
    except (AdminProblem, SQLAlchemyError, ValueError, OSError) as error:
        if isinstance(error, AdminProblem):
            audit["status"] = error.status
            code = str(error)
        else:
            code = "key_admin.failed"
        audit["code"] = code
        message = f"{code}: use --out PATH when stdout is not a terminal" if code == "key_admin.output_required" else code
        print(message, file=sys.stderr)
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
