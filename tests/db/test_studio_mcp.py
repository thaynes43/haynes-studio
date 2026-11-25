"""Studio MCP and key provisioning on disposable PostgreSQL."""

import asyncio
import json
import secrets
import string
import sys
from datetime import UTC, datetime
from stat import S_IMODE

import httpx
import pytest
import sqlalchemy as sa

from haynes_studio.api import key_admin
from haynes_studio.api.transport import access_log
from haynes_studio.canonical import to_document
from haynes_studio.canonical.ids import Minter
from haynes_studio.db import identity
from haynes_studio.db.catalog import record_asset_version, record_delivery
from haynes_studio.db.engine import connect_engine
from haynes_studio.db.schema import agent_grants, agent_keys, boards
from haynes_studio.mcp.server import create_app
from haynes_studio.store.layout import blob_locator
from tests.canonical.fixtures import example
from tests.library.fixtures import winter_menu
from tests.mcp.client import API_URL, MCP_URL, call, connect, fail
from tests.support.synthetic import write_sine_wav

from .test_studio_api import (
    bearer, client, engine, key_admin_db, new_production, owner_engine, register_agent,
    runtime_db, runtime_role, service, sign_in,
)

pytestmark = pytest.mark.db
EXPIRES = "2099-01-01T00:00:00+00:00"


@pytest.fixture
def admin(studio_db, capsys, monkeypatch):
    monkeypatch.setenv("STUDIO_MIGRATION_DATABASE_URL", studio_db.url)
    monkeypatch.setenv("STUDIO_DATABASE_SCHEMA", studio_db.schema)

    def command(*args, expect=0):
        assert key_admin.run(args) == expect
        output = capsys.readouterr()
        if expect:
            assert not output.out
            return output.err.strip()
        assert len(output.out.splitlines()) == 1 and not output.err
        return json.loads(output.out)

    return command


def issue(admin, path, production, *scopes):
    result = admin("create", "--out", str(path), "--production", production,
                   *(value for scope in scopes for value in ("--scope", scope)))
    assert set(result) == {"key_id"}
    return {**result, "key": path.read_text().strip()}


def test_key_provisioning_hashes_expiry_and_revocation(admin, service, owner_engine, runtime_db,
                                                     monkeypatch, tmp_path, caplog):
    app, _, issuer = service
    browser = client(app)
    csrf = sign_in(browser, issuer)
    first, second = new_production(browser, csrf), new_production(browser, csrf)
    caplog.set_level("INFO", logger=access_log.name)
    path = tmp_path / "new-key"
    create = ("create", "--out", str(path), "--production", first)
    result = admin(*create, "--production", second, "--production", first,
                   "--scope", "read", "--scope", "draft:write", "--expires-at", EXPIRES)
    assert set(result) == {"key_id"} and S_IMODE(path.stat().st_mode) == 0o600
    key_id, secret = result["key_id"], path.read_text().strip()
    with owner_engine.connect() as conn:
        row = conn.execute(sa.select(agent_keys).where(agent_keys.c.id == key_id)).one()
        assert row.digest == identity.digest(secret)
        assert row.expires_at.isoformat() == EXPIRES and row.revoked_at is None
    listed = next(key for key in admin("list")["keys"] if key["key_id"] == key_id)
    assert listed == {"key_id": key_id, "expires_at": EXPIRES, "revoked_at": None,
                      "production_scopes": {prod: ["draft:write", "read"] for prod in (first, second)}}
    assert admin(*create, "--scope", "go_live:approve", expect=1) == (
        "key_admin.invalid_scope"
    )
    assert admin(*create[:3], "--production", Minter().mint("prd"), "--scope", "read", expect=1) == (
        "key_admin.production_not_found"
    )
    assert admin(*create, "--scope", "read",
                 "--expires-at", "2000-01-01T00:00:00Z", expect=1) == "key_admin.expiry_in_past"
    assert admin(*create, "--scope", "read",
                 "--expires-at", "2000-01-01", expect=1) == "key_admin.invalid_expiry"
    agent = client(app)
    bearer = {"Authorization": "Bearer " + secret}
    assert agent.get("/v1/me", headers=bearer).json()["production_scopes"] == listed["production_scopes"]
    revoked = admin("revoke", key_id)
    assert revoked["revoked_at"] and admin("revoke", key_id) == revoked
    assert agent.get("/v1/me", headers=bearer).status_code == 401
    assert admin("revoke", Minter().mint("key"), expect=1) == "key_admin.key_not_found"

    monkeypatch.setenv("STUDIO_MIGRATION_DATABASE_URL", runtime_db.url)
    assert admin("list", expect=1) == "key_admin.privileges_required"
    monkeypatch.delenv("STUDIO_MIGRATION_DATABASE_URL")
    monkeypatch.setenv("STUDIO_DATABASE_URL", runtime_db.url)
    assert admin("list", expect=1) == "key_admin.migration_dsn_required"

    events = [json.loads(record.getMessage()) for record in caplog.records if record.name == access_log.name]
    actions = [event for event in events if "action" in event]
    assert [(action["action"], action["status"]) for action in actions] == [
        ("agent_keys.create", 201), ("agent_keys.list", 200),
        ("agent_keys.create", 422), ("agent_keys.create", 404), ("agent_keys.create", 422),
        ("agent_keys.create", 422), ("agent_keys.revoke", 200), ("agent_keys.revoke", 200),
        ("agent_keys.revoke", 404), ("agent_keys.list", 403), ("agent_keys.list", 422),
    ]
    assert actions[0]["key_id"] == key_id and actions[0]["principal_id"]
    assert secret not in caplog.text and row.digest not in caplog.text


def test_create_refuses_redirected_output_and_exclusive_file_conflict(
    admin, service, owner_engine, tmp_path, caplog, monkeypatch,
):
    api, _, issuer = service
    browser = client(api)
    production = new_production(browser, sign_in(browser, issuer))
    secret = secrets.token_urlsafe(32)
    args = ("create", "--production", production, "--scope", "read")
    caplog.set_level("INFO", logger=access_log.name)
    monkeypatch.setattr(key_admin.secrets, "token_urlsafe", lambda _: secret)
    with monkeypatch.context() as patch:
        def unexpected_connection(*_):
            pytest.fail("Redirected create attempted a database connection")

        patch.setattr(key_admin, "connect_engine", unexpected_connection)
        assert admin(*args, expect=1) == "key_admin.output_required: use --out PATH when stdout is not a terminal"
    path = tmp_path / "existing"
    path.write_text("preserve me")
    assert admin(*args, "--out", str(path), expect=1) == "key_admin.output_exists"
    assert path.read_text() == "preserve me"
    with owner_engine.connect() as conn:
        assert conn.scalar(sa.select(agent_keys.c.id).where(agent_keys.c.digest == identity.digest(secret))) is None
        assert conn.scalar(sa.select(sa.func.count()).select_from(agent_grants).where(
            agent_grants.c.production_id == production,
        )) == 0
    assert secret not in caplog.text

    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    result = admin(*args)
    assert result["key"] == secret
    with owner_engine.connect() as conn:
        assert conn.scalar(sa.select(agent_keys.c.digest).where(agent_keys.c.id == result["key_id"])) == identity.digest(secret)
    assert secret not in caplog.text


def test_register_file_is_idempotent_and_replaces_grants_with_the_documented_role(
    admin, service, owner_engine, key_admin_db, tmp_path, caplog, monkeypatch,
):
    api, _, issuer = service
    browser = client(api)
    csrf = sign_in(browser, issuer)
    first, second = new_production(browser, csrf), new_production(browser, csrf)
    secret = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(48))
    path = tmp_path / "mounted"
    path.write_bytes(secret.encode("ascii") + b"\r\n")
    monkeypatch.setenv("STUDIO_MIGRATION_DATABASE_URL", key_admin_db.url)
    caplog.set_level("INFO", logger=access_log.name)
    command = ("register", "--key-file", str(path))
    original = ("--production", first, "--production", second, "--scope", "read", "--scope", "draft:write",
                "--expires-at", EXPIRES)
    result = admin(*command, *original)
    assert set(result) == {"key_id"}
    key_id = result["key_id"]
    assert admin(*command, *original, "--production", first, "--scope", "read") == result
    assert admin(*command, *original[:-2], expect=1) == "key_admin.grants_conflict"
    reduced = ("--production", second, "--scope", "read")
    assert admin(*command, *reduced, expect=1) == "key_admin.grants_conflict"
    agent = client(api)
    assert agent.get("/v1/me", headers=bearer(secret)).json()["production_scopes"] == {
        first: ["draft:write", "read"], second: ["draft:write", "read"],
    }
    assert admin(*command, *reduced, "--replace-grants") == result
    assert agent.get("/v1/me", headers=bearer(secret)).json()["production_scopes"] == {second: ["read"]}
    with owner_engine.connect() as conn:
        row = conn.execute(sa.select(agent_keys).where(agent_keys.c.id == key_id)).one()
        assert row.digest == identity.digest(secret) and row.expires_at is None
    assert next(item for item in admin("list")["keys"] if item["key_id"] == key_id)["production_scopes"] == {
        second: ["read"],
    }
    assert admin(*command, *original, "--replace-grants") == result
    assert agent.get("/v1/me", headers=bearer(secret)).json()["production_scopes"] == {
        first: ["draft:write", "read"], second: ["draft:write", "read"],
    }
    revoked = admin("revoke", key_id)
    assert admin(*command, *reduced, "--replace-grants") == result
    assert admin("revoke", key_id) == revoked
    assert agent.get("/v1/me", headers=bearer(secret)).status_code == 401
    actions = [json.loads(record.getMessage()) for record in caplog.records
               if record.name == access_log.name and '"action":"agent_keys.register"' in record.getMessage()]
    assert [event["status"] for event in actions] == [201, 200, 409, 409, 200, 200, 200]
    assert secret not in caplog.text and row.digest not in caplog.text

    engine = connect_engine(key_admin_db.url, key_admin_db.schema)
    try:
        with engine.connect() as conn:
            assert conn.execute(sa.text("""
                SELECT current_user != pg_get_userbyid(relowner),
                       NOT has_table_privilege(oid, 'DELETE'),
                       NOT has_column_privilege(oid, 'digest', 'UPDATE'),
                       NOT has_table_privilege('worker_tokens', 'SELECT')
                FROM pg_class WHERE oid = 'agent_keys'::regclass
            """)).one() == (True, True, True, True)
    finally:
        engine.dispose()


@pytest.mark.parametrize("invalid_key", [b"A" * 42, b"A" * 47, b"_" * 48, b"A" * 129, b"A" * 48 + b"\n\n",
                                        b"A" * 47 + b"\xff"])
def test_register_rejects_invalid_file(admin, tmp_path, caplog, invalid_key):
    path = tmp_path / "invalid-key"
    path.write_bytes(invalid_key)
    caplog.set_level("INFO", logger=access_log.name)
    assert admin("register", "--key-file", str(path), "--production", Minter().mint("prd"),
                 "--scope", "read", expect=1) == "key_admin.invalid_key_file"
    assert invalid_key.decode("ascii", errors="ignore").strip() not in caplog.text


def test_parser_does_not_echo_a_key_supplied_as_an_argument(capsys):
    secret = secrets.token_urlsafe(32)
    with pytest.raises(SystemExit) as error:
        key_admin.run(("register", "--production", Minter().mint("prd"), "--scope", "read", secret))
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert not captured.out and secret not in captured.err


def test_sdk_edits_scoped_drafts_through_the_api(admin, service, owner_engine, tmp_path, caplog):
    api, store, issuer = service
    browser = client(api)
    csrf = sign_in(browser, issuer)
    production, other = new_production(browser, csrf), new_production(browser, csrf)
    writer = issue(admin, tmp_path / "writer", production, "read", "draft:write")
    reader = issue(admin, tmp_path / "reader", production, "read")
    outsider = issue(admin, tmp_path / "outsider", other, "read", "draft:write")
    caplog.set_level("INFO", logger=access_log.name)
    clip = store.publish(write_sine_wav(tmp_path / "fixture.wav"), scope=production, media_type="audio/wav")
    sound = next(doc for doc in winter_menu().library.documents() if doc["kind"] == "sound")
    minter = Minter()
    version = {
        **sound, "id": minter.mint("asv"), "asset_id": minter.mint("ast"), "number": 1,
        "scope": {"production_id": production}, "legacy": None,
        "provenance": {**sound["provenance"], "source_key": None}, "content": to_document(clip),
    }
    with owner_engine.begin() as conn:
        record_asset_version(conn, version)

    async def scenario():
        mcp = create_app(API_URL, api_transport=httpx.ASGITransport(app=api))
        list_tools = {"jsonrpc": "2.0", "method": "tools/list", "id": 1}
        async with mcp.router.lifespan_context(mcp):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mcp)) as http:
                for headers in ({}, {"Authorization": "Bearer " + secrets.token_urlsafe(32)}):
                    response = await http.post(MCP_URL, json=list_tools, headers=headers)
                    assert response.status_code == 401
                    assert response.json()["error"]["code"] == "auth.required"
            async with connect(mcp, "Bearer " + writer["key"]) as session:
                tools = {item.name for item in (await session.list_tools()).tools}
                assert "studio_patch_board" in tools and "studio_get_media" not in tools
                assert "go_live:approve" not in tools and "studio_queue_run" not in tools
                listed = await call(session, "studio_list_productions")
                assert [item["id"] for item in listed["items"]] == [production]
                detail = await call(session, "studio_get_production", production_id=production)
                assert detail["name"].startswith("Fixture production ")
                assert detail["media_types"][0]["kind"] == "short"
                draft = await call(session, "studio_create_story", production_id=production, kind="short",
                                   fields={"title": "Fixture short"})
                story_id = draft["id"]
                delivery = example("valid/delivery.json")
                for part in ("master", "proxy"):
                    media = delivery[part]
                    media["locator"] = blob_locator(production, media["sha256"], media["media_type"])
                with owner_engine.begin() as conn:
                    record_delivery(conn, story_id, delivery)
                delivered = await call(session, "studio_get_delivery", run_id=delivery["run_id"])
                assert delivered["id"] == delivery["id"] and delivered["run_id"] == delivery["run_id"]
                for part in ("master", "proxy"):
                    assert delivered[part] == {
                        field: delivery[part][field] for field in ("sha256", "bytes", "frames", "media_type")
                    }
                first = await call(session, "studio_add_board", story_id=story_id, revision=1, fields={})
                second = await call(session, "studio_add_board", story_id=story_id, revision=2, fields={})
                board_id = first["id"]
                matches = await call(session, "studio_search_assets", production=production, kind="sound")
                assert [item["id"] for item in matches["items"] if item["scope"]["production_id"] == production] == [
                    version["id"],
                ]
                asset = await call(session, "studio_get_asset", asset_id=version["asset_id"])
                assert asset["asset"]["id"] == version["asset_id"] and asset["asset"]["revision"] == 1
                assert [item["id"] for item in asset["versions"]] == [version["id"]]
                assert "content" not in asset["versions"][0] and asset["next_cursor"] is None
                patch = {"board_id": board_id, "revision": first["revision"], "patch": {
                    "notes": [{"text": "Hold on the reaction"}],
                    "cues": [{"type": "sound", "asset_version_id": version["id"], "anchor": {"at_ms": 0},
                              "trim_ms": [0, 250], "level_rms_dbfs": -22}],
                }}
                updated = await call(session, "studio_patch_board", **patch)
                assert updated["revision"] == 2 and updated["story_id"] == story_id
                board = await call(session, "studio_get_board", board_id=board_id)
                assert board["notes"][0]["text"] == "Hold on the reaction"
                assert board["notes"][0]["id"].startswith("nte_")
                assert board["cues"][0]["id"].startswith("cue_")
                assert board["cues"][0]["asset_version_id"] == version["id"]
                stale = await fail(session, "studio_patch_board", **patch)
                assert (stale["code"], stale["status"], stale["current_revision"]) == ("conflict.revision", "conflict", 2)
                assert stale["request_id"].startswith("req-")
                summary = await call(session, "studio_get_story_summary", story_id=story_id, limit=1)
                assert summary["revision"] == 4 and summary["board_order"] == [board_id]
                timing = await call(session, "studio_get_story_timing", story_id=story_id, limit=1)
                assert timing["story_revision"] == summary["revision"] and timing["fps"] == 24
                assert [item["board_id"] for item in timing["boards"]] == [board_id]
                assert timing["next_cursor"] == summary["next_cursor"]
                last_timing = await call(session, "studio_get_story_timing", story_id=story_id,
                                         cursor=timing["next_cursor"])
                assert [item["board_id"] for item in last_timing["boards"]] == [second["id"]]
                assert last_timing["next_cursor"] is None
                page = await call(session, "studio_get_story_summary", story_id=story_id, cursor=summary["next_cursor"])
                assert page["board_order"] == [second["id"]]
                order = await call(session, "studio_reorder_boards", story_id=story_id,
                                   revision=4, board_order=[second["id"], board_id])
                assert order["revision"] == 5
                assert (await fail(session, "studio_get_story_summary", story_id=story_id,
                                   cursor=summary["next_cursor"]))["current_revision"] == 5
                removed = await call(session, "studio_remove_board", board_id=second["id"], revision=1)
                assert removed["tombstone"] and removed["revision"] == 2
                assert (await fail(session, "studio_get_board", board_id=second["id"]))["http_status"] == 404
                assert (await call(session, "studio_get_story_summary", story_id=story_id))["revision"] == 6
                story_patch = {"story_id": story_id, "revision": 6, "patch": {"title": "Edited fixture"}}
                edited = await call(session, "studio_patch_story", **story_patch)
                assert edited["title"] == "Edited fixture" and edited["revision"] == 7
                assert (await fail(session, "studio_patch_story", **story_patch))["current_revision"] == 7
                stories = await call(session, "studio_list_stories", production_id=production, kind="short",
                                     publication="unpublished", approved=False)
                assert [(item["id"], item["title"], item["revision"]) for item in stories["items"]] == [
                    (story_id, "Edited fixture", 7),
                ]
                published = await call(session, "studio_list_stories", production_id=production, kind="short",
                                       publication="published")
                assert published["items"] == []
                assert (await fail(session, "go_live:approve"))["code"] == "tool.not_found"
                assert (await fail(session, "studio_get_media", sha256=clip.sha256))["code"] == "tool.not_found"
            async with connect(mcp, "Bearer " + reader["key"]) as session:
                assert (await call(session, "studio_get_board", board_id=board_id))["revision"] == 2
                forbidden = await fail(session, "studio_patch_board", board_id=board_id, revision=2, patch={})
                assert (forbidden["status"], forbidden["code"]) == ("forbidden", "auth.forbidden")
                admin("revoke", reader["key_id"])
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mcp)) as http:
                    response = await http.post(MCP_URL, json=list_tools, headers={
                        "Authorization": "Bearer " + reader["key"],
                        "Accept": "application/json, text/event-stream",
                    })
                    assert response.status_code == 401
            async with connect(mcp, "Bearer " + outsider["key"]) as session:
                assert (await fail(session, "studio_get_board", board_id=board_id))["status"] == "forbidden"
                denied = await fail(session, "studio_patch_board", board_id=board_id, revision=2, patch={})
                assert (denied["status"], denied["code"]) == ("forbidden", "auth.forbidden")
                assert (await fail(session, "studio_get_delivery", run_id=delivery["run_id"]))["status"] == "forbidden"
                assert (await fail(session, "studio_get_asset", asset_id=version["asset_id"]))["status"] == "not_found"
            return second["id"]

    second_id = asyncio.run(scenario())
    with owner_engine.connect() as conn:
        assert conn.scalar(sa.select(boards.c.tombstone).where(boards.c.id == second_id)) is True
    assert all(entry["key"] not in caplog.text for entry in (writer, reader, outsider))


def test_expired_key_and_concurrent_clients_stay_production_scoped(
    admin, service, owner_engine, tmp_path, caplog,
):
    api, _, issuer = service
    browser = client(api)
    csrf = sign_in(browser, issuer)
    first, second = new_production(browser, csrf), new_production(browser, csrf)
    initial = issue(admin, tmp_path / "initial", first, "read")
    external = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(128))
    mounted = tmp_path / "external"
    mounted.write_text(external)
    admin("register", "--key-file", str(mounted), "--production", second, "--scope", "read")
    _, expired = register_agent(owner_engine, {first: ["read"]}, expires_at=datetime(2000, 1, 1, tzinfo=UTC))
    caplog.set_level("INFO", logger=access_log.name)

    async def scenario():
        mcp = create_app(API_URL, api_transport=httpx.ASGITransport(app=api))

        async def check_scope(session, allowed, denied):
            listing = await call(session, "studio_list_productions")
            assert [item["id"] for item in listing["items"]] == [allowed]
            assert (await call(session, "studio_get_production", production_id=allowed))["id"] == allowed
            error = await fail(session, "studio_get_production", production_id=denied)
            assert (error["http_status"], error["code"]) == (403, "auth.forbidden")

        async with mcp.router.lifespan_context(mcp):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mcp)) as http:
                response = await http.post(MCP_URL, headers=expired, json={
                    "jsonrpc": "2.0", "method": "tools/list", "id": 1,
                })
                assert response.status_code == 401
                assert response.json()["error"]["code"] == "auth.required"
            async with (connect(mcp, "Bearer " + initial["key"]) as left,
                        connect(mcp, "Bearer " + external) as right):
                await asyncio.gather(check_scope(left, first, second), check_scope(right, second, first))

    asyncio.run(scenario())
    assert all(key not in caplog.text for key in (initial["key"], external, expired["Authorization"].split()[1]))
