"""Provision a worker from a mounted secret with the documented database grants."""

import json
import secrets
import string
from datetime import UTC, datetime

import psycopg
import pytest
import sqlalchemy as sa
from psycopg import sql

from haynes_studio.api import key_admin
from haynes_studio.api.transport import access_log
from haynes_studio.db.engine import connect_engine
from haynes_studio.db.identity import digest, get_worker_lane
from haynes_studio.db.migrate import migrate
from haynes_studio.db.schema import worker_lane_grants, worker_tokens
from haynes_studio.queue.worker_tokens import worker_bearer
from tests.support.database import new_schema_name

from .test_studio_api import (
    bearer, client, documented_role, engine, new_production, owner_engine, runtime_db,
    runtime_role, service, sign_in,
)
from .test_studio_mcp import admin

pytestmark = pytest.mark.db
CLAIM = "/internal/v1/work/claim"


@pytest.fixture(scope="module")
def worker_admin_db(studio_db, owner_engine):
    yield from documented_role(studio_db, "studio_worker_token_admin", "worker_token_admin")


def _secret(length):
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(length))


def test_worker_register_rotate_and_revoke_under_documented_grants(
    admin, studio_db, worker_admin_db, runtime_db, service, owner_engine, tmp_path, monkeypatch, caplog,
):
    app, _, issuer = service
    api = client(app)
    signed_in = client(app)
    production = new_production(signed_in, sign_in(signed_in, issuer))
    token_file = tmp_path / "worker-secret"
    # Test even accidental reuse of the mounted value by the agent provisioner.
    first = _secret(48)
    token_file.write_text(first + "\n", encoding="ascii")
    admin("register", "--key-file", str(token_file), "--production", production, "--scope", "read")

    caplog.set_level("INFO", logger=access_log.name)
    command = ("worker-token", "register", "--token-file", str(token_file), "--worker-id")
    worker_id = "fixture-render"
    result = {"worker_id": worker_id}
    assert admin(*command, worker_id, expect=1) == "key_admin.worker_lane_required"
    monkeypatch.setenv("STUDIO_MIGRATION_DATABASE_URL", worker_admin_db.url)
    assert admin(*command, worker_id, "--lane", "run", expect=1) == "key_admin.privileges_required"
    monkeypatch.setenv("STUDIO_MIGRATION_DATABASE_URL", studio_db.url)
    assert admin(*command, worker_id, "--lane", "run") == result
    monkeypatch.setenv("STUDIO_MIGRATION_DATABASE_URL", worker_admin_db.url)
    assert admin(*command, worker_id) == admin(*command, worker_id) == result
    assert admin(*command, "another-render", "--replace", expect=1) == "key_admin.worker_token_conflict"
    original = "worker_" + first
    assert api.get("/v1/me", headers=bearer(first)).status_code == 200
    assert api.post(CLAIM, headers=bearer(first)).status_code == 401
    assert api.get("/v1/me", headers=bearer(original)).status_code == 401
    assert api.post(CLAIM, headers=bearer(original)).status_code == 204
    assert api.post(CLAIM).status_code == signed_in.post(CLAIM).status_code == 401
    with owner_engine.connect() as conn:
        row = conn.execute(sa.select(worker_tokens).where(worker_tokens.c.worker_id == worker_id)).one()
        assert row.digest == digest(original) and row.expires_at is None and row.revoked_at is None

    second = _secret(121)
    token_file.write_text(second, encoding="ascii")
    assert admin(*command, worker_id, expect=1) == "key_admin.worker_id_conflict"
    assert admin(*command, worker_id, "--replace", "--lane", "image",
                 expect=1) == "key_admin.worker_lane_conflict"
    assert api.post(CLAIM, headers=bearer(original)).status_code == 204
    assert admin(*command, worker_id, "--replace") == result
    replacement = "worker_" + second
    assert api.post(CLAIM, headers=bearer(original)).status_code == 401
    assert api.post(CLAIM, headers=bearer(replacement)).status_code == 204
    assert api.post(CLAIM, headers=bearer(replacement), json={"lane": "image"}).status_code == 403
    assert api.get("/v1/me", headers=bearer(replacement)).status_code == 401
    history = [item for item in admin("worker-token", "list")["workers"] if item["worker_id"] == worker_id]
    assert len(history) == 2 and history[0]["revoked_at"]
    assert history[1] == {**result, "lane": "run", "expires_at": None, "revoked_at": None}
    assert history[0]["lane"] == "run"
    revoked = admin("worker-token", "revoke", worker_id)
    assert revoked["revoked_at"] and admin("worker-token", "revoke", worker_id) == revoked
    assert admin("worker-token", "revoke", "unknown-worker", expect=1) == "key_admin.worker_not_found"
    assert admin(*command, worker_id, "--replace", expect=1) == "key_admin.worker_token_revoked"
    assert api.post(CLAIM, headers=bearer(replacement)).status_code == 401

    provisioner = connect_engine(worker_admin_db.url, worker_admin_db.schema)
    try:
        with provisioner.connect() as conn:
            assert conn.execute(sa.text("""
                SELECT current_user != pg_get_userbyid(relowner),
                       NOT has_table_privilege(oid, 'DELETE'),
                       NOT has_column_privilege(oid, 'digest', 'UPDATE'),
                       NOT has_column_privilege(oid, 'expires_at', 'INSERT'),
                       NOT has_column_privilege('agent_keys', 'digest', 'SELECT')
                FROM pg_class WHERE oid = 'worker_tokens'::regclass
            """)).one() == (True, True, True, True, True)
    finally:
        provisioner.dispose()
    monkeypatch.setenv("STUDIO_MIGRATION_DATABASE_URL", runtime_db.url)
    assert admin(*command, worker_id, "--replace", expect=1) == "key_admin.privileges_required"
    assert admin("worker-token", "list", expect=1) == "key_admin.privileges_required"
    assert admin("worker-token", "revoke", worker_id, expect=1) == "key_admin.privileges_required"
    for secret in (first, second, original, replacement, digest(original), digest(replacement)):
        assert secret not in caplog.text and secret not in json.dumps(history)


def test_lane_migration_retains_existing_tokens_on_upgrade_and_downgrade(studio_db, runtime_role):
    schema = new_schema_name()
    with psycopg.connect(studio_db.url) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    migration = connect_engine(studio_db.url, schema)
    installed = {"studio-worker": "run", "studio-image-worker": "image", "studio-voice-worker": "voice"}
    tokens = {worker_id: worker_bearer(_secret(64)) for worker_id in (*installed, "legacy-unknown")}
    rows = [{"digest": digest(secret), "worker_id": worker_id, "revoked_at": None}
            for worker_id, secret in tokens.items()]
    revoked = worker_bearer(_secret(64))
    rows.append({"digest": digest(revoked), "worker_id": "studio-worker", "revoked_at": datetime.now(UTC)})
    try:
        migrate(migration, target="head-1", runtime_role=runtime_role[0])
        with migration.begin() as conn:
            conn.execute(worker_tokens.insert(), rows)
            prior = list(conn.execute(sa.select(worker_tokens).order_by(worker_tokens.c.digest)))

        migrate(migration, runtime_role=runtime_role[0])
        with migration.begin() as conn:
            assert dict(conn.execute(sa.select(worker_lane_grants)).tuples().all()) == installed
            assert list(conn.execute(sa.select(worker_tokens).order_by(worker_tokens.c.digest))) == prior
            assert get_worker_lane(conn, revoked) is None
            for worker_id, secret in tokens.items():
                assert get_worker_lane(conn, secret) == (worker_id, installed.get(worker_id))
            conn.exec_driver_sql(f'SET LOCAL ROLE "{runtime_role[0]}"')
            assert conn.execute(sa.text("""
                SELECT has_table_privilege('worker_lane_grants', 'SELECT'),
                       has_column_privilege('worker_lane_grants', 'lane', 'UPDATE'),
                       has_column_privilege('worker_lane_grants', 'lane', 'INSERT'),
                       has_table_privilege('worker_lane_grants', 'DELETE')
            """)).one() == (True, False, False, False)

        migrate(migration, direction="downgrade", target="0010_staging_archive")
        with migration.connect() as conn:
            assert not sa.inspect(conn).has_table("worker_lane_grants", schema=schema)
            assert list(conn.execute(sa.select(worker_tokens).order_by(worker_tokens.c.digest))) == prior
    finally:
        migration.dispose()
        with psycopg.connect(studio_db.url) as admin:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_worker_revoke_keeps_working_with_pre_lane_admin_grants(
    admin, studio_db, worker_admin_db, owner_engine, service, tmp_path, monkeypatch,
):
    # This is the installed registration shape: no --lane for a seeded ID.
    worker_id = "studio-voice-worker"
    secret = _secret(64)
    token_file = tmp_path / "worker-secret"
    token_file.write_text(secret, encoding="ascii")
    assert admin("worker-token", "register", "--worker-id", worker_id,
                 "--token-file", str(token_file)) == {"worker_id": worker_id}
    api = client(service[0])
    auth = bearer(worker_bearer(secret))
    assert api.post(CLAIM, headers=auth, json={"lane": "voice"}).status_code == 204

    role = sql.Identifier(f"{studio_db.schema}_worker_token_admin")
    privileges = sql.SQL("SELECT (worker_id, lane) ON {}.worker_lane_grants").format(
        sql.Identifier(studio_db.schema),
    )
    with psycopg.connect(studio_db.url) as conn:
        conn.execute(sql.SQL("REVOKE {} FROM {}").format(privileges, role))
    try:
        monkeypatch.setenv("STUDIO_MIGRATION_DATABASE_URL", worker_admin_db.url)
        assert admin("worker-token", "list", expect=1) == "key_admin.privileges_required"
        assert admin("worker-token", "revoke", worker_id)["revoked_at"]
        assert api.post(CLAIM, headers=auth, json={"lane": "voice"}).status_code == 401
    finally:
        with psycopg.connect(studio_db.url) as conn:
            conn.execute(sql.SQL("GRANT {} TO {}").format(privileges, role))


@pytest.mark.parametrize("invalid", [b"A" * 47, b"A" * 122, b"_" * 48, b"A" * 48 + b"\n\n", b"A" * 47 + b"\xff"])
def test_worker_register_rejects_invalid_file(admin, tmp_path, invalid):
    token_file = tmp_path / "worker-secret"
    token_file.write_bytes(invalid)
    assert admin("worker-token", "register", "--worker-id", "fixture-render", "--token-file", str(token_file),
                 expect=1) == "key_admin.invalid_worker_token_file"


def test_worker_register_requires_a_file_even_with_runtime_token_in_env(monkeypatch, capsys):
    secret = _secret(48)
    monkeypatch.setenv("STUDIO_WORKER_TOKEN", secret)
    with pytest.raises(SystemExit) as error:
        key_admin.run(("worker-token", "register", "--worker-id", "fixture-render", secret))
    assert error.value.code == 2
    output = capsys.readouterr()
    assert not output.out and secret not in output.err
