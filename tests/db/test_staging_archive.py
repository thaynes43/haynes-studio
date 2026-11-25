"""Archive HTTP and MCP contracts against a disposable PostgreSQL database."""

import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from types import SimpleNamespace

import httpx
import psycopg
import pytest
import sqlalchemy as sa

from haynes_studio.api.archive_routes import MAX_TEXT_BYTES
from haynes_studio.api.transport import access_log
from haynes_studio.canonical.ids import Minter
from haynes_studio.db import drafts, identity
from haynes_studio.db.migrate import migrate
from haynes_studio.db.schema import archive_records, archive_versions, worker_tokens
from haynes_studio.mcp.server import create_app
from haynes_studio.queue.worker_tokens import worker_bearer
from tests.formats.fixtures import doll_short
from tests.mcp.client import API_URL, MCP_URL, call, connect, fail

from .test_studio_api import (
    bearer, client, engine, new_production, new_story, owner_engine, register_agent,
    runtime_db, runtime_role, service, sign_in,
)

pytestmark = pytest.mark.db
ORIGINAL = {"origin": "original"}
SCOPES = ["archive:read", "archive:write", "draft:write"]


@pytest.fixture
def studio(service, owner_engine):
    api, _, issuer = service
    browser = client(api)
    csrf = sign_in(browser, issuer)
    production = new_production(browser, csrf)
    other = new_production(browser, csrf)
    story = new_story(browser, csrf, production)
    other_story = new_story(browser, csrf, other)
    key, headers = register_agent(owner_engine, {production: [*SCOPES, "read"]})
    mcp = create_app(API_URL, api_transport=httpx.ASGITransport(app=api))
    return SimpleNamespace(api=api, browser=browser, csrf=csrf, production=production, story=story,
                           other=other, other_story=other_story, key=key, headers=headers, mcp=mcp)


def create_path(production):
    return f"/v1/productions/{production}/archive-records"


def version_path(version):
    return f"/v1/archive-versions/{version}"


def record_path(record):
    return f"/v1/archive-records/{record}"


def story_path(studio):
    return f"/v1/stories/{studio.story}"


def board_path(board):
    return f"/v1/boards/{board}"


def entry(kind="brief", text="The imaginary hat inspector takes notes.\r\n", **fields):
    return {"kind": kind, "title": "Hat Inspector", "text": text, "provenance": ORIGINAL, **fields}


def draft(studio, marker, *keys):
    return {
        "schema": "studio.agent-draft/v1", "production_id": studio.production, "story_id": studio.story,
        "model": "fixture-writer", "session": "fixture-session", "set": None,
        "boards": [{"key": key, "fields": {
            "title": f"{marker} {key}", "lines": [],
            "timing": {"lead_ms": None, "tail_ms": None, "hold_ms": 1000},
            "voice": None, "cast": [], "layout": {"preset": "default", "foreground": True},
            "method": {"layer": "whole_frame", "motion": "i2v"}, "cues": [], "notes": [],
        }} for key in keys],
    }


def post(studio, path, body, idem, *, headers=None):
    return client(studio.api).post(path, json=body, headers={
        **(headers or studio.headers), "Idempotency-Key": idem,
    })


def stage(studio, document, idem="storyboard", *, kind="storyboard"):
    response = post(studio, create_path(studio.production), entry(kind, json.dumps(document)), idem)
    assert response.status_code == 201, response.json()
    return response.json()


def revise(studio, record, previous, document, idem="revised"):
    response = post(studio, record_path(record) + "/versions", {
        "text": json.dumps(document), "provenance": ORIGINAL, "revises_version_id": previous,
    }, idem)
    assert response.status_code == 201, response.json()
    return response.json()["id"]


def apply(studio, version, revision, *, headers=None, story_id=None, person=False):
    http = studio.browser if person else client(studio.api)
    auth = studio.csrf if person else headers or studio.headers
    return http.post(version_path(version) + "/apply", json={"story_id": story_id or studio.story},
                     headers={**auth, "If-Match": str(revision)})


def test_frontier_staging_and_pinned_shepherd_read(studio, owner_engine, caplog):
    caplog.set_level("INFO")
    _, read_headers = register_agent(owner_engine, {studio.production: ["archive:read"]})
    recipe = studio.browser.post("/v1/formats", json=doll_short(), headers=studio.csrf)
    assert recipe.status_code == 201, recipe.json()
    format_id = recipe.json()["id"]
    original_text = "Inspector Tâve checks the very small hats.\r\n"
    edited_text = "Inspector Tâve counts seventeen hats.\r\n"
    storyboard_text = json.dumps(draft(studio, "Original draft", "opening", "middle", "closing"))
    create_args = {"production_id": studio.production, "idempotency_key": "opening-script",
                   **entry("script", original_text, format_version_id=format_id)}

    async def scenario():
        async with studio.mcp.router.lifespan_context(studio.mcp), connect(
            studio.mcp, studio.headers["Authorization"],
        ) as frontier, connect(studio.mcp, read_headers["Authorization"]) as shepherd:
            brief = await call(frontier, "studio_create_archive_record", production_id=studio.production,
                               idempotency_key="brief", **entry())
            script = await call(frontier, "studio_create_archive_record", **create_args)
            first = script["version"]
            assert first["written_by"] == {"kind": "agent", "key_id": studio.key}
            assert first["number"] == 1 and first["revises_version_id"] is None
            assert first["format_version_id"] == format_id
            append_args = {"record_id": script["id"], "revises_version_id": first["id"],
                           "text": edited_text, "provenance": ORIGINAL, "idempotency_key": "edit"}
            second = await call(frontier, "studio_add_archive_version", **append_args)
            assert second["number"] == 2 and second["revises_version_id"] == first["id"]

            assert await call(frontier, "studio_create_archive_record", **create_args) == script
            assert await call(frontier, "studio_add_archive_version", **append_args) == second
            mismatch = await fail(frontier, "studio_add_archive_version", **{**append_args, "text": "Other edit"})
            assert mismatch["code"] == "idempotency.mismatch" and mismatch["http_status"] == 422
            stale = await fail(frontier, "studio_add_archive_version", **{**append_args, "idempotency_key": "stale"})
            assert (stale["http_status"], stale["code"], stale["existing_entity_id"]) == (
                409, "archive.stale_version", second["id"],
            )

            history = await call(frontier, "studio_get_archive_record", record_id=script["id"], limit=1)
            assert history["head_version_id"] == second["id"] == history["next_cursor"]
            assert history["versions"] == [second] and "text" not in second
            history = await call(frontier, "studio_get_archive_record", record_id=script["id"],
                                 cursor=history["next_cursor"])
            assert history["versions"] == [first] and history["next_cursor"] is None
            listing = await call(shepherd, "studio_list_archive_records", production_id=studio.production)
            assert {record["id"] for record in listing["items"]} == {brief["id"], script["id"]}
            pinned = await call(shepherd, "studio_get_archive_version", version_id=first["id"])
            data = original_text.encode("utf-8")
            assert pinned["text"].encode("utf-8") == data
            assert pinned["bytes"] == len(data) and pinned["sha256"] == hashlib.sha256(data).hexdigest()

            staged = await call(frontier, "studio_create_archive_record", production_id=studio.production,
                                idempotency_key="board", **entry("storyboard", storyboard_text))
            version_id = staged["version"]["id"]
            initial = await call(frontier, "studio_apply_archive_storyboard", version_id=version_id,
                                 story_id=studio.story, revision=1)
            ids = {item["key"]: item["board_id"] for item in initial["boards"]}
            assert [item["reason"] for item in initial["boards"]] == ["created"] * 3

            changed = studio.browser.patch(board_path(ids["opening"]), json={"title": "Person's own opening"},
                                           headers={**studio.csrf, "If-Match": '"1"'})
            assert changed.status_code == 200
            # This key created the unstamped board itself. Even that doesn't make it eligible.
            unstamped = await call(frontier, "studio_add_board", story_id=studio.story, revision=5, fields={})
            protected = {id_: studio.browser.get(board_path(id_)).json()
                         for id_ in (ids["opening"], unstamped["id"])}
            assert "draft_application" not in protected[unstamped["id"]]

            updated = json.dumps(draft(studio, "Revised draft", "opening", "middle", "closing", "unbound"))
            revised = await call(frontier, "studio_add_archive_version", record_id=staged["id"],
                                 revises_version_id=version_id, text=updated, provenance=ORIGINAL,
                                 idempotency_key="board-edit")
            apply_args = {"version_id": revised["id"], "story_id": studio.story, "revision": 6}
            stale = await fail(frontier, "studio_apply_archive_storyboard", **{**apply_args, "revision": 5})
            assert (stale["code"], stale["current_revision"]) == ("conflict.revision", 6)
            applied = await call(frontier, "studio_apply_archive_storyboard", **apply_args)
            assert applied["revision"] == 8
            assert {(item["board_id"], item["reason"]) for item in applied["boards"]} == {
                (ids["opening"], "edited_by_person"), (unstamped["id"], "unstamped_board"),
                (ids["middle"], "updated"), (ids["closing"], "updated"), (None, "unbound_board_key"),
            }
            for key in ("middle", "closing"):
                board = studio.browser.get(board_path(ids[key])).json()
                assert board["title"] == f"Revised draft {key}"
                assert board["draft_application"]["archive_version_id"] == revised["id"]
                assert board["draft_application"]["draft_sha256"] == revised["sha256"]
            for id_, before in protected.items():
                assert studio.browser.get(board_path(id_)).json() == before
            assert studio.browser.get(story_path(studio)).json()["board_order"] == [
                ids["opening"], ids["middle"], ids["closing"], unstamped["id"],
            ]
            replay = await call(frontier, "studio_apply_archive_storyboard", **{**apply_args, "revision": 8})
            assert replay["revision"] == 8
            assert [item["reason"] for item in replay["boards"]].count("already_applied") == 2
            for tool, arguments in (
                ("studio_create_archive_record", create_args),
                ("studio_add_archive_version", append_args),
                ("studio_apply_archive_storyboard", {**apply_args, "revision": 8}),
            ):
                assert (await fail(shepherd, tool, **arguments))["http_status"] == 403
            return script, first, revised

    script, first, revised = asyncio.run(scenario())
    audit = [json.loads(record.getMessage()) for record in caplog.records if record.name == access_log.name]
    assert any(event.get("action") == "archive.read" and event["sha256"] == first["sha256"]
               and event["record_id"] == script["id"] and event["bytes"] == first["bytes"]
               and event["kind"] == "script" for event in audit)
    assert any(event.get("action") == "archive.applied" and event["version_id"] == revised["id"]
               and event["story_id"] == studio.story for event in audit)
    for value in (original_text.rstrip(), edited_text.rstrip(), "Original draft opening", "Revised draft middle",
                  script["title"], "opening-script"):
        assert value not in caplog.text


def test_scopes_and_production_confinement_for_every_api_operation_and_tool(studio, owner_engine):
    _, foreign = register_agent(owner_engine, {studio.other: SCOPES})
    _, read = register_agent(owner_engine, {studio.production: ["archive:read"]})
    _, write = register_agent(owner_engine, {studio.production: ["archive:write"]})
    _, draft_write = register_agent(owner_engine, {studio.production: ["draft:write", "archive:write"]})
    _, revoked = register_agent(owner_engine, {studio.production: SCOPES}, revoked_at=datetime.now(UTC))
    _, elsewhere = register_agent(owner_engine, {studio.other: ["archive:read"],
                                                 studio.production: ["draft:write"]})
    worker = worker_bearer("W" * 48)
    with owner_engine.begin() as conn:
        conn.execute(worker_tokens.insert().values(digest=identity.digest(worker), worker_id="fixture-render"))
    worker_headers = bearer(worker)
    body = entry("storyboard", json.dumps(draft(studio, "Fixture", "board")))
    root = create_path(studio.production)
    created = post(studio, root, body, "setup")
    assert created.status_code == 201, created.json()
    archive = created.json()
    record, version = archive["id"], archive["head_version_id"]
    append = {"text": body["text"], "provenance": ORIGINAL, "revises_version_id": version}
    apply = {"story_id": studio.story}
    operations = [
        ("studio_create_archive_record", "POST", root, body, read, {"production_id": studio.production, **body}),
        ("studio_add_archive_version", "POST", record_path(record) + "/versions", append, read,
         {"record_id": record, **append}),
        ("studio_list_archive_records", "GET", root, None, write, {"production_id": studio.production}),
        ("studio_get_archive_record", "GET", record_path(record), None, write, {"record_id": record}),
        ("studio_get_archive_version", "GET", version_path(version), None, write, {"version_id": version}),
        ("studio_apply_archive_storyboard", "POST", version_path(version) + "/apply", apply, draft_write,
         {"version_id": version, "story_id": studio.story, "revision": 1}),
    ]
    # A caller that cannot see a record or version gets 404, as for an unknown ID. A
    # caller that can see it but lacks the scope for the operation gets 403.
    hidden_from_foreign = {"studio_get_archive_record", "studio_get_archive_version",
                           "studio_add_archive_version", "studio_apply_archive_storyboard"}
    hidden_without_scope = {"studio_get_archive_record", "studio_get_archive_version",
                            "studio_apply_archive_storyboard"}
    http = client(studio.api)
    for tool, method, path, payload, no_scope, arguments in operations:
        outside = 404 if tool in hidden_from_foreign else 403
        denied = 404 if tool in hidden_without_scope else 403
        for headers, status in ((foreign, outside), (no_scope, denied), (revoked, 401), (worker_headers, 401)):
            response = http.request(method, path, json=payload, headers={
                **headers, "Idempotency-Key": "refused", "If-Match": '"1"',
            })
            assert response.status_code == status, (tool, response.json())
    # `elsewhere` may draft here but cannot read this archive: the version is hidden.
    # `read` can read it but may not draft: refused, not hidden.
    for headers, status in ((elsewhere, 404), (read, 403)):
        assert http.post(version_path(version) + "/apply", json=apply,
                         headers={**headers, "If-Match": '"1"'}).status_code == status
    unknown_record, unknown_version = Minter().mint("arc"), Minter().mint("arv")
    for headers in (foreign, studio.headers):
        assert http.post(record_path(unknown_record) + "/versions", json=append, headers={
            **headers, "Idempotency-Key": "unknown"}).status_code == 404
        assert http.post(version_path(unknown_version) + "/apply", json=apply,
                         headers={**headers, "If-Match": '"1"'}).status_code == 404
    assert http.get(version_path(version), headers=read).json()["text"] == body["text"]
    assert http.post(version_path(version) + "/apply", json={"story_id": studio.other_story},
                     headers={**studio.headers, "If-Match": '"1"'}).status_code == 404

    async def scenario():
        async with studio.mcp.router.lifespan_context(studio.mcp), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=studio.mcp),
        ) as http:
            for tool, _, _, _, no_scope, arguments in operations:
                outside = 404 if tool in hidden_from_foreign else 403
                denied = 404 if tool in hidden_without_scope else 403
                if tool in {"studio_create_archive_record", "studio_add_archive_version"}:
                    arguments = {**arguments, "idempotency_key": "refused"}
                for headers, status in ((foreign, outside), (no_scope, denied)):
                    async with connect(studio.mcp, headers["Authorization"]) as session:
                        assert (await fail(session, tool, **arguments))["http_status"] == status
                for headers in (revoked, worker_headers):
                    response = await http.post(MCP_URL, headers={
                        **headers, "Accept": "application/json, text/event-stream",
                    }, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                             "params": {"name": tool, "arguments": arguments}})
                    assert response.status_code == 401
            for headers, status in ((elsewhere, 404), (read, 403)):
                async with connect(studio.mcp, headers["Authorization"]) as session:
                    error = await fail(session, "studio_apply_archive_storyboard", version_id=version,
                                       story_id=studio.story, revision=1)
                    assert error["http_status"] == status

    asyncio.run(scenario())
    assert studio.browser.get(story_path(studio)).json()["board_order"] == []
    assert studio.browser.get(record_path(record)).json()["versions"] == [archive["version"]]
    assert len(studio.browser.get(root).json()["items"]) == 1


@pytest.mark.parametrize("kind", ["record", "version"])
def test_archive_reads_hide_foreign_ids_like_unknown_ids(studio, owner_engine, kind):
    _, foreign = register_agent(owner_engine, {studio.other: ["archive:read"]})
    archive = stage(studio, draft(studio, "First", "one"))
    if kind == "record":
        path, prefix, saved = record_path, "arc", archive["id"]
    else:
        path, prefix, saved = version_path, "arv", archive["head_version_id"]
    unknown = Minter().mint(prefix)
    http = client(studio.api)
    for id_ in (saved, unknown):
        response = http.get(path(id_), headers=foreign)
        assert (response.status_code, response.json()["error"]["code"]) == (404, "not_found")

    async def scenario():
        async with studio.mcp.router.lifespan_context(studio.mcp), connect(
            studio.mcp, foreign["Authorization"],
        ) as session:
            for id_ in (saved, unknown):
                error = await fail(session, f"studio_get_archive_{kind}", **{f"{kind}_id": id_})
                assert (error["http_status"], error["code"]) == (404, "not_found")

    asyncio.run(scenario())


def test_apply_requires_archive_ancestry_and_skips_same_version(studio):
    archive = stage(studio, draft(studio, "First", "one", "two"))
    first = archive["head_version_id"]
    second = revise(studio, archive["id"], first, draft(studio, "Second", "one", "two"))
    other = stage(studio, draft(studio, "Other record", "one", "two"), "other-record")["head_version_id"]

    created = apply(studio, first, 1)
    assert created.status_code == 200, created.json()
    assert [item["reason"] for item in created.json()["boards"]] == ["created"] * 2
    revised = apply(studio, second, created.json()["revision"])
    assert revised.status_code == 200, revised.json()
    receipt = revised.json()
    assert [item["reason"] for item in receipt["boards"]] == ["updated"] * 2
    ids = [item["board_id"] for item in receipt["boards"]]
    before = [studio.browser.get(board_path(id_)).json() for id_ in ids]
    assert [board["title"] for board in before] == ["Second one", "Second two"]

    for attempted, outcome, reason in (
        (first, "conflict", "archive.version_not_descendant"),
        (other, "conflict", "archive.version_not_descendant"),
        (second, "skipped", "already_applied"),
    ):
        response = apply(studio, attempted, receipt["revision"])
        assert response.status_code == 200, response.json()
        assert response.json()["revision"] == receipt["revision"]
        assert [item["board_id"] for item in response.json()["boards"]] == ids
        assert [(item["outcome"], item["reason"], item.get("stamped_version_id"))
                for item in response.json()["boards"]] == [
            (outcome, reason, second if outcome == "conflict" else None),
        ] * 2
        assert [studio.browser.get(board_path(id_)).json() for id_ in ids] == before

    third = revise(studio, archive["id"], second, draft(studio, "Third", "one", "two"), "third")
    fourth = revise(studio, archive["id"], third, draft(studio, "Fourth", "one", "two"), "fourth")
    response = apply(studio, fourth, receipt["revision"])
    assert response.status_code == 200, response.json()
    assert [item["reason"] for item in response.json()["boards"]] == ["updated"] * 2
    assert [studio.browser.get(board_path(id_)).json()["title"] for id_ in ids] == ["Fourth one", "Fourth two"]


def test_archive_apply_can_update_plain_draft_by_same_agent(studio):
    document = draft(studio, "First", "one")
    fields = {**document["boards"][0]["fields"], "draft_application": {
        "board_key": "one", "draft_sha256": "a" * 64, "model": document["model"], "session": document["session"],
    }}
    del fields["voice"]  # The ordinary board endpoint infers the silent-board voice object.
    created = client(studio.api).post(story_path(studio) + "/boards", json=fields,
                                     headers={**studio.headers, "If-Match": "1"})
    assert created.status_code == 201, created.json()
    board = created.json()
    assert "archive_version_id" not in board["draft_application"]
    version = stage(studio, draft(studio, "Second", "one"))["head_version_id"]
    response = apply(studio, version, 2)
    assert response.status_code == 200, response.json()
    assert response.json()["boards"] == [
        {"key": "one", "board_id": board["id"], "outcome": "applied", "reason": "updated"},
    ]


@pytest.mark.parametrize("isolate_redraft_guard", [False, True], ids=["per-board", "mutation"])
def test_apply_refuses_another_agents_board(studio, owner_engine, monkeypatch, isolate_redraft_guard):
    archive = stage(studio, draft(studio, "First", "one"))
    first = archive["head_version_id"]
    created = apply(studio, first, 1).json()
    board_id = created["boards"][0]["board_id"]
    before = studio.browser.get(board_path(board_id)).json()
    second = revise(studio, archive["id"], first, draft(studio, "Second", "one"))
    _, other = register_agent(owner_engine, {studio.production: SCOPES})
    if isolate_redraft_guard:
        # Exercise the mutation's own stamp-author check independently of the
        # two archive prechecks, which would otherwise refuse the same write.
        monkeypatch.setattr(drafts, "check_archive_board", lambda held, by: None)
    response = apply(studio, second, created["revision"], headers=other)
    if isolate_redraft_guard:
        assert response.status_code == 409, response.json()
        assert response.json()["error"]["code"] == "draft.protected"
    else:
        assert response.status_code == 200, response.json()
        assert response.json()["boards"] == [
            {"key": "one", "board_id": board_id, "outcome": "conflict", "reason": "draft.protected"},
        ]
    assert studio.browser.get(board_path(board_id)).json() == before
    assert studio.browser.get(story_path(studio)).json()["revision"] == created["revision"]


@pytest.mark.parametrize("append", [False, True], ids=["create", "append"])
def test_storyboard_write_refuses_another_production(studio, append):
    foreign = draft(studio, "Foreign", "one")
    foreign.update(production_id=studio.other, story_id=studio.other_story)
    root = create_path(studio.production)
    if append:
        archive = stage(studio, draft(studio, "First", "one"))
        path = record_path(archive["id"])
        response = post(studio, path + "/versions", {
            "text": json.dumps(foreign), "provenance": ORIGINAL, "revises_version_id": archive["head_version_id"],
        }, "foreign")
    else:
        response = post(studio, root, entry("storyboard", json.dumps(foreign)), "foreign")
    assert response.status_code == 422, response.json()
    assert response.json()["error"]["code"] == "archive.production_mismatch"
    if append:
        assert studio.browser.get(path).json()["versions"] == [archive["version"]]
    else:
        assert studio.browser.get(root).json()["items"] == []


def test_apply_refuses_non_storyboard_kind(studio):
    # The text is deliberately a valid draft so the kind check is decisive.
    archive = stage(studio, draft(studio, "Brief", "one"), kind="brief")
    response = apply(studio, archive["head_version_id"], 1)
    assert response.status_code == 422, response.json()
    assert response.json()["error"]["code"] == "archive.not_storyboard"
    assert studio.browser.get(story_path(studio)).json()["board_order"] == []


def test_apply_refuses_another_story_in_same_production(studio):
    response = studio.browser.post(f"/v1/productions/{studio.production}/media-types/short/stories",
                                   json={"title": "Alternate story"}, headers=studio.csrf)
    assert response.status_code == 201, response.json()
    alternate = response.json()["id"]
    archive = stage(studio, draft(studio, "First", "one"))
    response = apply(studio, archive["head_version_id"], 1, story_id=alternate)
    assert response.status_code == 422, response.json()
    assert response.json()["error"]["code"] == "archive.story_mismatch"
    for story_id in (studio.story, alternate):
        assert studio.browser.get(f"/v1/stories/{story_id}").json()["board_order"] == []


def test_apply_refuses_changed_set_pins(studio):
    document = draft(studio, "First", "one")
    document["set"] = {"asset_version_id": Minter().mint("asv")}
    archive = stage(studio, document)
    response = apply(studio, archive["head_version_id"], 1)
    assert response.status_code == 422, response.json()
    assert response.json()["error"]["code"] == "draft.set_changed"
    assert studio.browser.get(story_path(studio)).json()["board_order"] == []


def test_validation_and_human_apply_are_atomic(studio, owner_engine, caplog):
    caplog.set_level("INFO")
    root = create_path(studio.production)
    bad_board = draft(studio, "Safe", "one", "two")
    bad_board["boards"][1]["fields"]["lines"] = [{"speaker": "a", "text": "The hats are ours.",
                                                  "gap_before_ms": 0}]
    invalid = post(studio, root, entry("storyboard", json.dumps(bad_board)), "bad-board")
    assert invalid.status_code == 422 and invalid.json()["error"]["path"] == "/text"
    escaped = json.dumps(draft(studio, "password=fictional987", "one")).replace("=", r"\u003d")
    for message in (entry(text="password=fictional987"), entry("storyboard", escaped)):
        response = post(studio, root, message, "bad-secret")
        assert response.status_code == 422 and response.json()["error"]["code"] == "archive.credentials"
        assert "fictional987" not in response.text
    assert "fictional987" not in caplog.text
    missing_format = post(studio, root, entry(format_version_id=Minter().mint("fmv")), "bad-format")
    assert missing_format.status_code == 422 and missing_format.json()["error"]["code"] == "ref.unknown"
    too_big = post(studio, root, entry(text="é" * (MAX_TEXT_BYTES // 2 + 1)), "too-big")
    assert too_big.status_code == 413 and too_big.json()["error"]["code"] == "archive.too_large"
    http = client(studio.api)
    headers = {**studio.headers, "Content-Type": "application/json", "Idempotency-Key": "bad-utf8"}
    for bad in (b'{"text":"\xff"}', b'{"text":"\\ud800"}', b'{"text":"\\u0000"}'):
        assert http.post(root, content=bad, headers=headers).status_code == 422
    bad_provenance = entry(provenance={"origin": "adapted", "source_locator": {
        "label": "I am the private source passage", "sha256": "a" * 64,
    }})
    assert post(studio, root, bad_provenance, "bad-locator").status_code == 422
    assert studio.browser.get(root).json()["items"] == []

    payload = draft(studio, "Artist draft", "one", "two")
    payload["boards"][1]["fields"]["layout"]["preset"] = "MissingLayout"
    adapted = {"origin": "adapted", "source_locator": {"label": "fixtureScene-12", "sha256": "a" * 64}}
    body = entry("storyboard", json.dumps(payload), provenance=adapted)
    human = {**studio.csrf, "Idempotency-Key": "human"}
    created = studio.browser.post(root, json=body, headers=human)
    assert created.status_code == 201, created.json()
    archive = created.json()
    version = archive["version"]
    assert version["written_by"]["kind"] == "human"
    assert studio.browser.get(version_path(version["id"])).json()["provenance"] == version["provenance"]
    path = story_path(studio)
    apply = {"story_id": studio.story}
    apply_path = version_path(version["id"]) + "/apply"
    # The draft is valid in isolation, but one proposal fails against the target story.
    actual = studio.browser.post(apply_path, json=apply, headers={**studio.csrf, "If-Match": '"1"'})
    assert actual.status_code == 422 and "MissingLayout" not in actual.text
    assert studio.browser.get(path).json()["board_order"] == []
    assert studio.browser.get(path).json()["revision"] == 1
    del payload["boards"][1]
    next_version = studio.browser.post(record_path(archive["id"]) + "/versions", headers=human, json={
        "text": json.dumps(payload), "provenance": adapted, "revises_version_id": version["id"],
    }).json()
    applied = studio.browser.post(version_path(next_version["id"]) + "/apply", json=apply,
                                  headers={**studio.csrf, "If-Match": '"1"'})
    assert applied.status_code == 200, applied.json()
    board_id = applied.json()["boards"][0]["board_id"]
    board = studio.browser.get(board_path(board_id)).json()
    assert board["drafted_by"] == version["written_by"]
    stamp = board["draft_application"]
    assert stamp["archive_version_id"] == next_version["id"]
    assert (stamp["person_edit"], stamp["person_edit_revision"]) == ("content", board["revision"])
    assert {"model", "session"}.isdisjoint(stamp)
    third = revise(studio, archive["id"], next_version["id"], draft(studio, "Agent edit", "one"))
    refusal = http.post(version_path(third) + "/apply", json=apply,
                        headers={**studio.headers, "If-Match": '"2"'})
    assert refusal.status_code == 200, refusal.json()
    assert refusal.json()["boards"] == [
        {"key": "one", "board_id": board_id, "outcome": "conflict", "reason": "edited_by_person"},
    ]
    assert studio.browser.get(board_path(board_id)).json() == board
    with owner_engine.connect() as conn:
        assert conn.scalar(sa.select(sa.func.count()).select_from(archive_versions).where(
            archive_versions.c.record_id == archive["id"],
        )) == 3


def test_human_archive_revision_is_a_person_edit(studio):
    archive = stage(studio, draft(studio, "Agent draft", "one"))
    first = archive["head_version_id"]
    created = apply(studio, first, 1).json()
    second = revise(studio, archive["id"], first, draft(studio, "Person applies", "one"))
    result = apply(studio, second, created["revision"], person=True)
    assert result.status_code == 200, result.json()
    receipt = result.json()
    assert receipt["boards"][0]["reason"] == "updated"
    board_id = created["boards"][0]["board_id"]
    board = studio.browser.get(board_path(board_id)).json()
    assert board["drafted_by"] == {"kind": "agent", "key_id": studio.key}
    stamp = board["draft_application"]
    assert stamp["archive_version_id"] == second
    assert (stamp["person_edit"], stamp["person_edit_revision"]) == ("content", board["revision"])
    assert {"model", "session"}.isdisjoint(stamp)
    replay = apply(studio, second, receipt["revision"], person=True)
    assert replay.json()["boards"][0]["reason"] == "already_applied"
    assert replay.json()["revision"] == receipt["revision"]
    third = revise(studio, archive["id"], second, draft(studio, "Later person apply", "one"), "third")
    later = apply(studio, third, receipt["revision"], person=True)
    assert later.status_code == 200, later.json()
    assert later.json()["boards"] == [
        {"key": "one", "board_id": board_id, "outcome": "conflict", "reason": "edited_by_person"},
    ]
    assert later.json()["revision"] == receipt["revision"]
    assert studio.browser.get(board_path(board_id)).json() == board
    protected = client(studio.api).patch(board_path(board_id), json={"title": "Agent edit"},
                                         headers={**studio.headers, "If-Match": str(board["revision"])})
    assert (protected.status_code, protected.json()["error"]["code"]) == (409, "draft.protected")


def test_adapted_source_locator_is_keyed_per_production(studio, owner_engine):
    passage_hash = hashlib.sha256(b"A synthetic source line.").hexdigest()

    def provenance(label):
        return {"origin": "adapted", "source_locator": {"label": label, "sha256": passage_hash}}

    root = create_path(studio.production)
    for label in ("a-line-of-prose", "source--12", "source:12", "A" * 39 + "-1"):
        rejected = post(studio, root, entry(provenance=provenance(label)), "bad-label")
        assert rejected.status_code == 422, rejected.json()
        assert rejected.json()["error"]["path"].endswith("/source_locator/label")

    label = "A" * 38 + "-1"
    adapted = provenance(label)
    body = entry(provenance=adapted)
    created = post(studio, root, body, "original")
    assert created.status_code == 201, created.json()
    first = created.json()["version"]
    locator = first["provenance"]["source_locator"]
    assert set(locator) == {"label", "hmac_sha256"}
    assert locator["label"] == label
    assert len(bytes.fromhex(locator["hmac_sha256"])) == 32
    assert locator["hmac_sha256"] != passage_hash
    assert passage_hash not in created.text
    assert post(studio, root, body, "original").json()["version"] == first
    appended = post(studio, record_path(first["record_id"]) + "/versions", {
        "text": "Revised text", "provenance": adapted, "revises_version_id": first["id"],
    }, "revision")
    assert appended.status_code == 201, appended.json()
    assert appended.json()["provenance"]["source_locator"] == locator
    _, foreign = register_agent(owner_engine, {studio.other: ["archive:write"]})
    other = post(studio, create_path(studio.other), body, "original", headers=foreign)
    assert other.status_code == 201, other.json()
    assert other.json()["version"]["provenance"]["source_locator"]["hmac_sha256"] != locator["hmac_sha256"]

    async def scenario():
        async with studio.mcp.router.lifespan_context(studio.mcp), connect(
            studio.mcp, studio.headers["Authorization"],
        ) as session:
            pinned = await call(session, "studio_get_archive_version", version_id=first["id"])
            assert pinned["provenance"]["source_locator"] == locator
            assert passage_hash not in json.dumps(pinned)

    asyncio.run(scenario())


def test_version_read_and_apply_reject_text_hash_mismatch(studio, owner_engine):
    archive = stage(studio, draft(studio, "Before", "one"))
    version_id = archive["head_version_id"]
    # Corrupt bytes without changing the byte count or invalidating the draft.
    with owner_engine.begin() as conn:
        conn.execute(archive_versions.update().where(archive_versions.c.id == version_id).values(
            text=sa.func.replace(archive_versions.c.text, "Before", "Edited"),
        ))

    exact = client(studio.api).get(version_path(version_id), headers=studio.headers)
    attempted = apply(studio, version_id, 1)
    for response in (exact, attempted):
        assert (response.status_code, response.json()["error"]["code"]) == (500, "archive.text_hash_mismatch")
        assert "Edited" not in response.text
    assert studio.browser.get(story_path(studio)).json()["board_order"] == []

    async def scenario():
        async with studio.mcp.router.lifespan_context(studio.mcp), connect(
            studio.mcp, studio.headers["Authorization"],
        ) as session:
            error = await fail(session, "studio_get_archive_version", version_id=version_id)
            assert (error["http_status"], error["code"]) == (500, "archive.text_hash_mismatch")

    asyncio.run(scenario())


def test_mcp_can_stage_and_read_full_byte_limit(studio):
    text = "é\r\n" * (MAX_TEXT_BYTES // 4)
    assert len(text.encode("utf-8")) == MAX_TEXT_BYTES

    async def scenario():
        async with studio.mcp.router.lifespan_context(studio.mcp), connect(
            studio.mcp, studio.headers["Authorization"],
        ) as session:
            created = await call(session, "studio_create_archive_record", production_id=studio.production,
                                 idempotency_key="full-sized", **entry(text=text))
            pinned = await call(session, "studio_get_archive_version", version_id=created["head_version_id"])
            assert pinned["bytes"] == MAX_TEXT_BYTES and pinned["text"] == text
            refused = await fail(session, "studio_add_archive_version", record_id=created["id"],
                                 revises_version_id=pinned["id"], idempotency_key="too-long",
                                 text=text + "x", provenance=ORIGINAL)
            assert refused["http_status"] == 413 and refused["code"] == "archive.too_large"
            appended = await call(session, "studio_add_archive_version", record_id=created["id"],
                                  revises_version_id=pinned["id"], idempotency_key="full-revision",
                                  text=text[::-1], provenance=ORIGINAL)
            assert appended["bytes"] == MAX_TEXT_BYTES

    asyncio.run(scenario())


def test_concurrent_append_cannot_fork_chain(studio):
    created = post(studio, create_path(studio.production), entry(), "original").json()
    first = created["head_version_id"]
    start = Barrier(2)

    def append(index):
        start.wait(timeout=10)
        return post(studio, record_path(created["id"]) + "/versions", {
            "text": f"Fixture edition {index}", "provenance": ORIGINAL, "revises_version_id": first,
        }, f"edition-{index}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = sorted(pool.map(append, (1, 2)), key=lambda reply: reply.status_code)
    assert [reply.status_code for reply in replies] == [201, 409]
    second = replies[0].json()
    assert replies[1].json()["error"]["existing_entity_id"] == second["id"]
    record = studio.browser.get(record_path(created["id"])).json()
    assert record["versions"] == [second, created["version"]]


def test_archive_runtime_cannot_change_or_delete_rows(engine):
    statements = (
        "UPDATE archive_versions SET text = text WHERE false",
        "DELETE FROM archive_versions WHERE false",
        "UPDATE archive_records SET title = title WHERE false",
        "DELETE FROM archive_records WHERE false",
    )
    for statement in statements:
        with engine.begin() as conn, pytest.raises(sa.exc.ProgrammingError) as denied:
            conn.exec_driver_sql(statement)
        assert isinstance(denied.value.orig, psycopg.errors.InsufficientPrivilege)


def test_archive_runtime_cannot_insert_a_version_that_skips_its_parent_number(studio, engine):
    response = post(studio, create_path(studio.production), entry(), "root-for-gap")
    assert response.status_code == 201, response.json()
    record = response.json()
    text = "An archive version that skips number two."
    data = text.encode("utf-8")
    with pytest.raises(sa.exc.IntegrityError) as rejected, engine.begin() as conn:
        conn.execute(archive_versions.insert().values(
            id=Minter().mint("arv"), record_id=record["id"], number=3, revises_version_id=record["version"]["id"],
            text=text, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), provenance=ORIGINAL,
            written_by={"kind": "agent"}, written_at=sa.func.clock_timestamp(),
            request_key_sha256=hashlib.sha256(record["id"].encode()).hexdigest(),
            request_sha256=hashlib.sha256(data).hexdigest(),
        ))
    assert rejected.value.orig.diag.constraint_name == "archive_versions_contiguous_parent_fkey"


def test_archive_record_requires_a_root_version_at_commit(studio, engine):
    with pytest.raises(sa.exc.IntegrityError) as rejected, engine.begin() as conn:
        conn.execute(archive_records.insert().values(
            id=Minter().mint("arc"), production_id=studio.production, kind="brief", title="Missing first version",
        ))
    assert rejected.value.orig.diag.constraint_name == "archive_records_root_version_fkey"


def test_archive_migration_downgrades_and_upgrades_cleanly(owner_engine, runtime_role):
    # Name the revision: "-1" would only undo whatever migration is newest.
    migrate(owner_engine, "downgrade", "0009_release_packages")
    try:
        with owner_engine.connect() as conn:
            inspector = sa.inspect(conn)
            assert not inspector.has_table("archive_records")
            assert not inspector.has_table("archive_versions")
            assert inspector.has_table("candidate_feedback")
    finally:
        migrate(owner_engine, runtime_role=runtime_role[0])
    with owner_engine.connect() as conn:
        inspector = sa.inspect(conn)
        assert inspector.has_table("archive_records")
        assert inspector.has_table("archive_versions")
