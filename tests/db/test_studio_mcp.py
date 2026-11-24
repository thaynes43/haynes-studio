"""Studio MCP and key provisioning on disposable PostgreSQL."""

import asyncio
import json
import secrets
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa

from haynes_studio.api import key_admin
from haynes_studio.api.transport import access_log
from haynes_studio.canonical import to_document
from haynes_studio.canonical.ids import Minter
from haynes_studio.db import identity
from haynes_studio.db.catalog import record_asset_version
from haynes_studio.db.schema import agent_keys, boards
from haynes_studio.mcp.server import create_app
from tests.library.fixtures import winter_menu
from tests.mcp.client import API_URL, MCP_URL, call, connect, fail
from tests.support.synthetic import write_sine_wav

from .test_studio_api import client, engine, new_production, owner_engine, runtime_db, service, sign_in

pytestmark = pytest.mark.db


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


def issue(admin, production, *scopes):
    return admin("create", "--production", production,
                 *(value for scope in scopes for value in ("--scope", scope)))


def test_key_provisioning_hashes_expiry_and_revocation(admin, service, owner_engine, runtime_db,
                                                     monkeypatch, caplog):
    app, _, issuer = service
    browser = client(app)
    csrf = sign_in(browser, issuer)
    first, second = new_production(browser, csrf), new_production(browser, csrf)
    caplog.set_level("INFO", logger=access_log.name)
    expiry = (datetime.now(UTC) + timedelta(hours=1)).replace(microsecond=0).isoformat()
    result = admin("create", "--production", first, "--production", second, "--production", first,
                   "--scope", "read", "--scope", "draft:write", "--expires-at", expiry)
    key_id, secret = result["key_id"], result["key"]
    with owner_engine.connect() as conn:
        row = conn.execute(sa.select(agent_keys).where(agent_keys.c.id == key_id)).one()
        assert row.digest == identity.digest(secret)
        assert row.expires_at.isoformat() == expiry and row.revoked_at is None
    listed = next(key for key in admin("list")["keys"] if key["key_id"] == key_id)
    assert listed == {"key_id": key_id, "expires_at": expiry, "revoked_at": None,
                      "production_scopes": {prod: ["draft:write", "read"] for prod in (first, second)}}
    assert admin("create", "--production", first, "--scope", "go_live:approve", expect=1) == (
        "key_admin.invalid_scope"
    )
    assert admin("create", "--production", Minter().mint("prd"), "--scope", "read", expect=1) == (
        "key_admin.production_not_found"
    )
    assert admin("create", "--production", first, "--scope", "read",
                 "--expires-at", "2000-01-01T00:00:00Z", expect=1) == "key_admin.expiry_in_past"
    assert admin("create", "--production", first, "--scope", "read",
                 "--expires-at", "2000-01-01", expect=1) == "key_admin.invalid_expiry"
    agent = client(app)
    bearer = {"Authorization": "Bearer " + secret}
    assert agent.get("/v1/me", headers=bearer).json()["production_scopes"] == listed["production_scopes"]
    revoked = admin("revoke", key_id)
    assert revoked["revoked_at"] and admin("revoke", key_id) == revoked
    assert agent.get("/v1/me", headers=bearer).status_code == 401
    assert admin("revoke", Minter().mint("key"), expect=1) == "key_admin.key_not_found"

    monkeypatch.setenv("STUDIO_MIGRATION_DATABASE_URL", runtime_db.url)
    assert admin("list", expect=1) == "key_admin.owner_required"
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


def test_sdk_edits_scoped_drafts_through_the_api(admin, service, owner_engine, tmp_path, caplog):
    api, store, issuer = service
    browser = client(api)
    csrf = sign_in(browser, issuer)
    production, other = new_production(browser, csrf), new_production(browser, csrf)
    writer = issue(admin, production, "read", "draft:write")
    reader = issue(admin, production, "read")
    outsider = issue(admin, other, "read", "draft:write")
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
                draft = await call(session, "studio_create_story", production_id=production, kind="short",
                                   fields={"title": "Fixture short"})
                story_id = draft["id"]
                first = await call(session, "studio_add_board", story_id=story_id, revision=1, fields={})
                second = await call(session, "studio_add_board", story_id=story_id, revision=2, fields={})
                board_id = first["id"]
                matches = await call(session, "studio_search_assets", production=production, kind="sound")
                assert [item["id"] for item in matches["items"] if item["scope"]["production_id"] == production] == [
                    version["id"],
                ]
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
            return second["id"]

    second_id = asyncio.run(scenario())
    with owner_engine.connect() as conn:
        assert conn.scalar(sa.select(boards.c.tombstone).where(boards.c.id == second_id)) is True
    assert all(entry["key"] not in caplog.text for entry in (writer, reader, outsider))
