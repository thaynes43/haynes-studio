"""Apply original frozen boards through the SDK, MCP, API and disposable Postgres."""

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from stat import S_IMODE
from types import SimpleNamespace

import httpx
import pytest
import sqlalchemy as sa
from mcp import ClientSession, types
from PIL import Image

from haynes_studio.canonical import Board, to_document
from haynes_studio.canonical.ids import Minter
from haynes_studio.cli import main
from haynes_studio.db.catalog import record_asset_version
from haynes_studio.db.schema import boards
from haynes_studio.drafting import cli as draft_cli
from haynes_studio.drafting.apply import apply_draft, read_baseline
from haynes_studio.drafting.declaration import READ_TOKEN_HEADER
from haynes_studio.drafting.document import Draft
from haynes_studio.mcp.server import create_app
from tests.library.fixtures import winter_menu
from tests.mcp.client import API_URL, MCP_URL, call, connect, fail

from .test_studio_api import (
    client, engine, new_production, owner_engine, register_agent, runtime_db, runtime_role,
    service, sign_in,
)

pytestmark = pytest.mark.db
FIXTURES = Path(__file__).resolve().parents[1] / "drafting" / "fixtures"


@dataclass
class Prepared:
    mcp: object
    browser: object
    csrf: dict
    production: str
    story: str
    set_id: str
    cast_id: str
    key_id: str
    headers: dict
    other_key: dict

    def raw(self, filename):
        return ((FIXTURES / filename).read_bytes()
                .replace(b"prd_00000000000000000000000001", self.production.encode())
                .replace(b"sty_00000000000000000000000001", self.story.encode())
                .replace(b"asv_00000000000000000000000002", self.set_id.encode())
                .replace(b"asv_00000000000000000000000003", self.cast_id.encode()))

    def board(self, id_):
        return self.browser.get(f"/v1/boards/{id_}")

    def edit(self, id_, revision, **fields):
        return self.browser.patch(f"/v1/boards/{id_}", json=fields,
                                  headers={**self.csrf, "If-Match": str(revision)})

    def story_record(self):
        return self.browser.get(f"/v1/stories/{self.story}").json()

    def session(self, headers=None):
        return connect(self.mcp, (headers or self.headers)["Authorization"])


@pytest.fixture
def prepared(service, owner_engine, tmp_path):
    api, store, issuer = service
    browser = client(api)
    csrf = sign_in(browser, issuer)
    production, other = new_production(browser, csrf), new_production(browser, csrf)
    key_id, key = register_agent(owner_engine, {production: ["read", "draft:write"]})
    _, other_key = register_agent(owner_engine, {other: ["read", "draft:write"]})
    minter = Minter()
    versions = {}
    for kind, name in (("cast", "Pim Rattle"), ("set", "Lost-property counter"),
                       ("voice", "Fixture stock voice")):
        doc = next(v for v in winter_menu().library.documents() if v["kind"] == kind)
        content = None
        if kind != "voice":
            path = tmp_path / f"{kind}.png"
            Image.new("RGBA", (8, 8), (70, 20, len(kind), 255)).save(path)
            content = to_document(store.publish(path, scope=production, media_type="image/png"))
        versions[kind] = {
            **doc, "id": minter.mint("asv"), "asset_id": minter.mint("ast"), "number": 1,
            "name": name, "scope": {"production_id": production}, "labels": [],
            "legacy": None, "provenance": {**doc["provenance"], "source_key": None}, "content": content,
        }
    with owner_engine.begin() as conn:
        for version in versions.values():
            record_asset_version(conn, version)
    set_id, cast_id = versions["set"]["id"], versions["cast"]["id"]
    response = browser.post(f"/v1/productions/{production}/media-types/short/stories", headers=csrf, json={
        "title": "The Office of Lost Tuesdays",
        "cast": [{"slot": "a", "name": "Pim Rattle", "voice_version_id": versions["voice"]["id"]}],
        "set": {"asset_version_id": set_id, "motion_asset_version_id": None,
                "foreground_edge_px": None, "foreground_feather_px": None, "legacy_fire": None},
    })
    assert response.status_code == 201, response.json()
    mcp = create_app(API_URL, api_transport=httpx.ASGITransport(app=api))
    return Prepared(mcp, browser, csrf, production, response.json()["id"], set_id, cast_id,
                    key_id, key, other_key)


async def first_draft(prepared, session):
    draft = Draft.parse(prepared.raw("first.json"))
    result = await apply_draft(session, draft)
    assert result.ok, result.document()
    assert [row["reason"] for row in result.boards] == ["created"] * 3
    return result


@pytest.fixture
def draft_command(prepared, service, tmp_path, monkeypatch):
    @asynccontextmanager
    async def in_process_http(**kwargs):
        api, _, _ = service
        mcp = create_app(API_URL, api_transport=httpx.ASGITransport(app=api))
        async with mcp.router.lifespan_context(mcp):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mcp), **kwargs) as http:
                yield http

    monkeypatch.setattr(draft_cli, "httpx", SimpleNamespace(
        AsyncClient=in_process_http, URL=httpx.URL, InvalidURL=httpx.InvalidURL,
        HTTPError=httpx.HTTPError, HTTPStatusError=httpx.HTTPStatusError,
    ))
    monkeypatch.setenv("STUDIO_MCP_URL", MCP_URL)
    monkeypatch.delenv("STUDIO_AGENT_KEY", raising=False)
    key_file = tmp_path / "key"
    secret = prepared.headers["Authorization"].split()[1]
    key_file.write_text(secret + "\n")
    draft_file = tmp_path / "draft.json"
    draft_file.write_bytes(prepared.raw("first.json"))
    receipt_file = tmp_path / "receipt.json"
    args = ["draft", "apply", str(draft_file), "--story", prepared.story,
            "--out", str(receipt_file), "--key-file", str(key_file)]
    return args, draft_file, receipt_file, secret


def test_cli_first_draft_records_provenance_pins_and_usage(prepared, draft_command, capsys):
    args, draft_file, receipt_file, secret = draft_command
    assert main(args) == 0
    receipt = json.loads(receipt_file.read_text())
    assert S_IMODE(receipt_file.stat().st_mode) == 0o600
    assert receipt["production_id"] == prepared.production
    assert receipt["usage"] == {
        "model": "fixture-writer", "session": "fixture-session-first",
        "input_tokens": 175, "output_tokens": None, "cost_usd": None,
    }
    ids = [row["board_id"] for row in receipt["boards"]]
    assert prepared.story_record()["board_order"] == ids
    for row in receipt["boards"]:
        board = prepared.board(row["board_id"]).json()
        assert row["key_id"] == prepared.key_id
        assert board["drafted_by"] == {"kind": "agent", "key_id": prepared.key_id}
        assert board["draft_application"] == {
            "board_key": row["key"], "draft_sha256": Draft.parse(draft_file.read_bytes()).sha256,
            "model": "fixture-writer", "session": "fixture-session-first",
            "applied_at": row["applied_at"], "board_revision": 1, "applied_board_revision": 1,
        }
        assert board["notes"][0]["text"]
    arrival, _, aftermath = [prepared.board(id_).json() for id_ in ids]
    assert arrival["cast"][0]["asset_version_id"] == prepared.cast_id
    assert arrival["cues"][0]["anchor"]["after_line_id"] == arrival["lines"][0]["id"]
    assert aftermath["photo"]["input_asset_version_ids"] == [prepared.set_id]
    assert main(args) == 2
    assert json.loads(receipt_file.read_text()) == receipt
    output = capsys.readouterr()
    assert all(secret not in text for text in (output.out, output.err, receipt_file.read_text()))


@pytest.mark.parametrize("fault", ["cancelled_write", "unexpected_response", "ctrl_c"])
def test_cli_keeps_a_truthful_receipt_when_apply_is_interrupted(
    prepared, draft_command, monkeypatch, capsys, fault,
):
    args, _, path, secret = draft_command
    original = ClientSession.call_tool
    writes = 0

    async def call_tool(session, name, arguments=None, **kwargs):
        nonlocal writes
        if fault == "unexpected_response" and name == "studio_get_story_summary":
            return types.CallToolResult(content=[], structuredContent={})
        reply = await original(session, name, arguments, **kwargs)
        if fault == "cancelled_write" and name == "studio_add_board":
            assert not reply.isError
            writes += 1
            if writes == 2:
                raise asyncio.CancelledError
        return reply

    def ctrl_c(coroutine):
        coroutine.close()
        raise BaseExceptionGroup("fixture task-group interruption", [KeyboardInterrupt()])

    monkeypatch.setattr(ClientSession, "call_tool", call_tool)
    if fault == "ctrl_c":
        monkeypatch.setattr(draft_cli, "asyncio", SimpleNamespace(
            run=ctrl_c, CancelledError=asyncio.CancelledError,
        ))
    assert main(args) == 1
    receipt = json.loads(path.read_text())
    assert secret not in path.read_text()
    assert "Traceback" not in capsys.readouterr().err
    if fault == "cancelled_write":
        assert receipt["error"]["code"] == "draft.transport_failed"
        assert [row["outcome"] for row in receipt["boards"]] == ["applied", "uncertain", "skipped"]
        assert receipt["boards"][1]["reason"] == "draft.write_interrupted"
        assert set(receipt["baseline"]) == {"arrival"}
        committed = prepared.story_record()["board_order"]
        assert len(committed) == 2 and committed[0] == receipt["baseline"]["arrival"]["board_id"]
    else:
        expected = "draft.interrupted" if fault == "ctrl_c" else "draft.unexpected_failure"
        assert receipt["error"]["code"] == expected
        assert [row["outcome"] for row in receipt["boards"]] == ["skipped"] * 3
        assert prepared.story_record()["board_order"] == []


def test_redraft_preserves_person_edit_tombstone_and_added_board(prepared):
    async def scenario():
        async with prepared.mcp.router.lifespan_context(prepared.mcp), prepared.session() as session:
            initial = await first_draft(prepared, session)
            ids = {key: value.board_id for key, value in initial.baseline.items()}
            edited = prepared.edit(ids["paperwork"], 1, title="Person's receipt beat")
            assert edited.status_code == 200
            assert edited.json()["draft_application"]["person_edit"] == "content"
            removed = prepared.browser.delete(f"/v1/boards/{ids['aftermath']}",
                                               headers={**prepared.csrf, "If-Match": "1"})
            assert removed.status_code == 204
            revision = prepared.story_record()["revision"]
            added = prepared.browser.post(f"/v1/stories/{prepared.story}/boards", json={"title": "A person's new board"},
                                          headers={**prepared.csrf, "If-Match": str(revision)})
            assert added.status_code == 201
            added_id = added.json()["id"]
            redraft = Draft.parse(prepared.raw("redraft.json"))
            result = await apply_draft(session, redraft, read_baseline(initial.document(), redraft))
            assert {row["board_id"]: (row["outcome"], row["reason"]) for row in result.boards} == {
                ids["arrival"]: ("applied", "updated"), ids["paperwork"]: ("conflict", "edited_by_person"),
                ids["aftermath"]: ("conflict", "removed"), added_id: ("conflict", "untracked_board"),
            }
            assert result.document()["usage"]["cost_usd"] == 0
            assert prepared.story_record()["board_order"] == [ids["arrival"], ids["paperwork"], added_id]
            assert prepared.board(ids["aftermath"]).status_code == 404
            assert prepared.board(added_id).json() == added.json()
            assert prepared.board(ids["paperwork"]).json() == edited.json()
            arrival = prepared.board(ids["arrival"]).json()
            assert arrival["revision"] == 2 and arrival["draft_application"]["draft_sha256"] == redraft.sha256
            assert arrival["lines"][0]["text"].endswith("Next Week.")
            assert arrival["cues"][0]["anchor"]["after_line_id"] == arrival["lines"][0]["id"]
            retry = await apply_draft(session, redraft, read_baseline(result.document(), redraft))
            assert next(row for row in retry.boards if row["key"] == "arrival")["reason"] == "already_applied"
            assert prepared.board(ids["arrival"]).json() == arrival

            # Supplying the new board revision directly through MCP cannot restart
            # an agent rewrite against the earlier provenance of the person's board.
            blocked = await fail(session, "studio_patch_board", board_id=ids["paperwork"], revision=2, patch={
                "title": "Do not apply",
                "draft_application": {"board_key": "paperwork", "draft_sha256": redraft.sha256,
                                      "model": redraft.model, "session": redraft.session,
                                      "previous_draft_sha256": initial.draft.sha256,
                                      "story_revision": prepared.story_record()["revision"]},
            })
            assert blocked["code"] == "draft.protected"
    asyncio.run(scenario())


def test_reorder_protects_moved_boards_even_after_order_is_restored(prepared):
    async def scenario():
        async with prepared.mcp.router.lifespan_context(prepared.mcp), prepared.session() as session:
            initial = await first_draft(prepared, session)
            a, b, c = [row["board_id"] for row in initial.boards]
            for order in ([b, a, c], [a, b, c]):
                revision = prepared.story_record()["revision"]
                response = prepared.browser.put(f"/v1/stories/{prepared.story}/board-order",
                                                json={"board_order": order},
                                                headers={**prepared.csrf, "If-Match": str(revision)})
                assert response.status_code == 200
            redraft = Draft.parse(prepared.raw("redraft.json"))
            result = await apply_draft(session, redraft, initial.baseline)
            assert {row["board_id"]: row["reason"] for row in result.boards} == {
                a: "reordered", b: "reordered", c: "updated",
            }
            assert prepared.story_record()["board_order"] == [a, b, c]
    asyncio.run(scenario())


def test_plain_agent_board_writes_cannot_replace_a_person_edit(prepared):
    async def scenario():
        async with prepared.mcp.router.lifespan_context(prepared.mcp), prepared.session() as session:
            initial = await first_draft(prepared, session)
            a, b, c = [row["board_id"] for row in initial.boards]
            person = prepared.edit(b, 1, title="Person's board")
            assert person.status_code == 200
            revision = prepared.story_record()["revision"]
            api = prepared.browser
            cases = (
                ("PATCH", f"/v1/boards/{b}", 2, {"title": "Agent's replacement"}),
                ("PUT", f"/v1/stories/{prepared.story}/board-order", revision, {"board_order": [b, a, c]}),
                ("DELETE", f"/v1/boards/{b}", 2, None),
            )
            for method, path, rev, body in cases:
                response = api.request(method, path, json=body,
                                       headers={**prepared.headers, "If-Match": str(rev)})
                assert response.status_code == 409, response.json()
                error = response.json()["error"]
                assert (error["code"], error["board_id"], error["person_edit_revision"]) == (
                    "draft.protected", b, 2,
                )
            assert prepared.board(b).json() == person.json()
            assert prepared.story_record()["revision"] == revision
            assert prepared.story_record()["board_order"] == [a, b, c]

            # Moving other boards leaves the protected board's position and revision alone.
            await call(session, "studio_reorder_boards", story_id=prepared.story, revision=revision,
                       board_order=[c, b, a])
            assert prepared.board(b).json()["revision"] == 2
    asyncio.run(scenario())


def test_person_creations_and_edits_protect_boards_without_a_draft_stamp(prepared):
    async def scenario():
        async with prepared.mcp.router.lifespan_context(prepared.mcp), prepared.session() as session:
            api = prepared.browser
            story_path = f"/v1/stories/{prepared.story}"
            created = api.post(story_path + "/boards", json={"title": "Person's new board"},
                               headers={**prepared.csrf, "If-Match": "1"})
            assert created.status_code == 201
            a = created.json()["id"]
            b = (await call(session, "studio_add_board", story_id=prepared.story, revision=2,
                            fields={"title": "Agent's ordinary board"}))["id"]
            edited = prepared.edit(b, 1, title="Person's replacement")
            assert edited.status_code == 200
            for board_id, revision in ((a, 1), (b, 2)):
                blocked = await fail(session, "studio_patch_board", board_id=board_id, revision=revision,
                                     patch={"title": "Blocked"})
                assert (blocked["code"], blocked["board_id"], blocked["person_edit_revision"]) == (
                    "draft.protected", board_id, revision,
                )
                blocked = await fail(session, "studio_remove_board", board_id=board_id, revision=revision)
                assert blocked["code"] == "draft.protected"
            order = {"story_id": prepared.story, "revision": 4, "board_order": [b, a]}
            blocked = await fail(session, "studio_reorder_boards", **order)
            assert (blocked["code"], blocked["board_id"]) == ("draft.protected", b)
            assert prepared.story_record()["revision"] == 4

            reordered = api.put(story_path + "/board-order", json={"board_order": [b, a]},
                                headers={**prepared.csrf, "If-Match": "4"})
            assert reordered.status_code == 200
            read = await call(session, "studio_get_board", board_id=b)
            assert read["revision"] == read["person_edit_revision"] == 3
            assert read["person_edit"] == "reordered"
            written = await call(session, "studio_patch_board", board_id=b, revision=3, patch={
                "title": "Requested agent edit", "acknowledge_person_edit": {
                    "board_revision": 3, "read_token": read["read_token"],
                },
            })
            assert written["revision"] == 4
            assert written["person_edit_revision"] == 3
            history = written["person_edit_acknowledgments"]
            assert history[0]["key_id"] == prepared.key_id and history[0]["board_revision"] == 3
            board = prepared.board(b).json()
            assert "draft_application" not in board
            assert to_document(Board.from_document(board))["person_edit_acknowledgments"] == history
    asyncio.run(scenario())


def test_older_unstamped_board_needs_acknowledgment_for_patch_reorder_and_removal(prepared, owner_engine):
    api = prepared.browser
    story = f"/v1/stories/{prepared.story}"
    headers = prepared.headers
    old, own = (
        api.post(story + "/boards", json={"title": title},
                 headers={**headers, "If-Match": str(rev)}).json()
        for rev, title in enumerate(("Older board", "New board"), 1)
    )
    by = {"kind": "agent", "key_id": prepared.key_id}
    assert old["created_by"] == own["created_by"] == by
    assert "draft_application" not in old
    with owner_engine.begin() as conn:
        # Older rows carried a drafter but had no server-owned creation record.
        conn.execute(boards.update().where(boards.c.id == old["id"]).values(
            document=boards.c.document.op("-")("created_by"),
        ))
    path = f'/v1/boards/{old["id"]}'
    order_path = story + "/board-order"
    order = {"board_order": [own["id"], old["id"]]}
    assert "created_by" not in api.get(path).json()

    def acknowledgment():
        read = api.get(path, headers=headers)
        return {"board_revision": read.json()["revision"], "read_token": read.headers[READ_TOKEN_HEADER]}

    def attempt(method, url, revision, body, ack_body, success):
        write_headers = {**headers, "If-Match": str(revision)}
        refused = api.request(method, url, json=body, headers=write_headers)
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"]["board_id"] == old["id"]
        assert refused.json()["error"]["code"] == "draft.protected"
        allowed = api.request(method, url, json={**body, "acknowledge_person_edit": ack_body},
                              headers=write_headers)
        assert allowed.status_code == success, allowed.text

    attempt("PATCH", path, 1, {"title": "Approved update"}, acknowledgment(), 200)
    attempt("PUT", order_path, 4, order, {old["id"]: acknowledgment()}, 200)
    attempt("DELETE", path, 3, {}, acknowledgment(), 204)
    with owner_engine.connect() as conn:
        removed = conn.execute(sa.select(boards.c.document, boards.c.tombstone)
                               .where(boards.c.id == old["id"])).one()
    assert removed.tombstone
    assert "person_edit" not in removed.document
    assert [row["board_revision"] for row in removed.document["person_edit_acknowledgments"]] == [1, 2, 3]


def test_agent_fills_and_reorders_a_fresh_story_without_acknowledgment(prepared):
    api, headers = prepared.browser, prepared.headers
    story = f"/v1/stories/{prepared.story}"
    board_ids = []
    for revision in (1, 2):
        response = api.post(story + "/boards", json={}, headers={**headers, "If-Match": str(revision)})
        assert response.status_code == 201, response.text
        board_ids.append(response.json()["id"])
    reordered = api.put(story + "/board-order", json={"board_order": board_ids[::-1]},
                        headers={**headers, "If-Match": "3"})
    assert reordered.status_code == 200, reordered.text
    path = f"/v1/boards/{board_ids[0]}"
    draft = api.patch(path, json={"title": "A finished board"}, headers={**headers, "If-Match": "1"})
    assert draft.status_code == 200, draft.text
    assert draft.json()["title"] == "A finished board"
    assert api.delete(path, headers={**headers, "If-Match": "2"}).status_code == 204


def test_another_agent_cannot_write_an_unstamped_agent_board(prepared, owner_engine):
    api = prepared.browser
    created = api.post(f"/v1/stories/{prepared.story}/boards", json={},
                       headers={**prepared.headers, "If-Match": "1"})
    assert created.status_code == 201, created.text
    board = created.json()
    _, other = register_agent(owner_engine, {prepared.production: ["read", "draft:write"]})
    change = api.patch(f'/v1/boards/{board["id"]}', json={"title": "Unacknowledged edit"},
                       headers={**other, "If-Match": "1"})
    assert change.status_code == 409
    assert change.json()["error"]["code"] == "draft.protected"
    assert prepared.board(board["id"]).json() == board


def test_acknowledgment_requires_the_current_read_and_preserves_history(prepared, owner_engine):
    async def scenario():
        async with prepared.mcp.router.lifespan_context(prepared.mcp), prepared.session() as session:
            initial = await first_draft(prepared, session)
            a, b, c = [row["board_id"] for row in initial.boards]
            api = prepared.browser
            path = f"/v1/boards/{b}"
            assert prepared.edit(b, 1, title="First person edit").status_code == 200
            read = api.get(path, headers=prepared.headers)
            assert read.status_code == 200
            ack = {"board_revision": 2, "read_token": read.headers[READ_TOKEN_HEADER]}
            assert prepared.edit(b, 2, title="Second person edit").status_code == 200
            patch = {"title": "Agent's change", "acknowledge_person_edit": ack}
            headers = {**prepared.headers, "If-Match": "3"}
            stale = api.patch(path, json=patch, headers=headers)
            assert stale.status_code == 409
            assert stale.json()["error"]["path"] == "/acknowledge_person_edit/board_revision"
            guessed = api.patch(path, json={**patch, "acknowledge_person_edit": {
                **ack, "board_revision": 3,
            }}, headers=headers)
            assert guessed.status_code == 422
            assert guessed.json()["error"]["code"] == "draft.invalid_read_token"
            assert prepared.board(b).json()["title"] == "Second person edit"

            async def acknowledgment():
                board = await call(session, "studio_get_board", board_id=b)
                return {"board_revision": board["revision"], "read_token": board["read_token"]}

            written = await call(session, "studio_patch_board", board_id=b, revision=3,
                                 patch={**patch, "acknowledge_person_edit": await acknowledgment()})
            stamp = written["draft_application"]
            assert stamp["person_edit_revision"] == 3
            recorded, = stamp["person_edit_acknowledgments"]
            assert recorded == {"key_id": prepared.key_id, "board_revision": 3,
                                "acknowledged_at": prepared.board(b).json()["updated_at"]}
            args = {"story_id": prepared.story, "revision": prepared.story_record()["revision"],
                    "board_order": [b, a, c]}
            blocked = await fail(session, "studio_reorder_boards", **args)
            assert (blocked["code"], blocked["person_edit_revision"], blocked["current_revision"]) == (
                "draft.protected", 3, 4,
            )
            await call(session, "studio_reorder_boards", **args, acknowledge_person_edit={
                b: await acknowledgment(),
            })
            await call(session, "studio_remove_board", board_id=b, revision=5,
                       acknowledge_person_edit=await acknowledgment())
            with owner_engine.connect() as conn:
                tombstone, removed = conn.execute(
                    sa.select(boards.c.tombstone, boards.c.document).where(boards.c.id == b)
                ).one()
            assert tombstone and removed["revision"] == 6
            history = removed["draft_application"]["person_edit_acknowledgments"]
            assert history[0] == recorded
            assert [item["board_revision"] for item in history] == [3, 4, 5]
            assert history[-1]["acknowledged_at"] == removed["updated_at"]
    asyncio.run(scenario())


def test_another_agent_key_needs_its_own_read_to_redraft(prepared, owner_engine):
    new_key_id, new_headers = register_agent(owner_engine, {prepared.production: ["read", "draft:write"]})

    async def scenario():
        async with prepared.mcp.router.lifespan_context(prepared.mcp), prepared.session() as original:
            initial = await first_draft(prepared, original)
            a = initial.baseline["arrival"].board_id
            redraft = Draft.parse(prepared.raw("redraft.json"))
            patch = {"title": "Change keys", "draft_application": {
                "board_key": "arrival", "draft_sha256": redraft.sha256, "model": redraft.model,
                "session": redraft.session, "previous_draft_sha256": initial.draft.sha256,
                "story_revision": prepared.story_record()["revision"],
            }}
            original_read = await call(original, "studio_get_board", board_id=a)
            async with prepared.session(new_headers) as other:
                args = {"board_id": a, "revision": 1}
                blocked = await fail(other, "studio_patch_board", **args, patch=patch)
                assert (blocked["http_status"], blocked["code"], blocked["board_id"]) == (
                    409, "draft.protected", a,
                )
                ack = {"board_revision": 1, "read_token": original_read["read_token"]}
                borrowed = await fail(other, "studio_patch_board", **args,
                                      patch={**patch, "acknowledge_person_edit": ack})
                assert borrowed["code"] == "draft.invalid_read_token"
                read = await call(other, "studio_get_board", board_id=a)
                changed = await call(other, "studio_patch_board", **args,
                                     patch={**patch, "acknowledge_person_edit": {
                                         **ack, "read_token": read["read_token"],
                                     }})
                assert changed["drafted_by"]["key_id"] == new_key_id
                assert changed["draft_application"]["person_edit_acknowledgments"] == [{
                    "key_id": new_key_id, "board_revision": 1,
                    "acknowledged_at": changed["draft_application"]["applied_at"],
                }]
    asyncio.run(scenario())


def test_clients_cannot_write_server_managed_board_provenance(prepared):
    async def scenario():
        async with prepared.mcp.router.lifespan_context(prepared.mcp), prepared.session() as session:
            initial = await first_draft(prepared, session)
            a = initial.baseline["arrival"].board_id
            before = prepared.board(a).json()
            redraft = Draft.parse(prepared.raw("redraft.json"))
            declaration = {
                "board_key": "arrival", "draft_sha256": redraft.sha256, "model": redraft.model,
                "session": redraft.session, "previous_draft_sha256": initial.draft.sha256,
                "story_revision": prepared.story_record()["revision"],
            }
            person = prepared.edit(a, 1, draft_application=declaration)
            assert person.status_code == 422
            assert person.json()["error"]["code"] == "draft.agent_required"
            path = f"/v1/boards/{a}"
            headers = {**prepared.headers, "If-Match": "1"}
            forged = {
                "applied_at": before["updated_at"], "person_edit": "content",
                "drafted_by": before["drafted_by"], "created_by": before["created_by"],
                "person_edit_acknowledgments": [],
            }
            for key, value in forged.items():
                for body in ({key: value}, {"draft_application": {**declaration, key: value}}):
                    response = prepared.browser.patch(path, json=body, headers=headers)
                    assert response.status_code == 422, response.json()
                    assert response.json()["error"]["path"].endswith(f"/{key}")
            create = prepared.browser.post(f"/v1/stories/{prepared.story}/boards",
                                           json={"created_by": before["created_by"]},
                                           headers={**prepared.headers, "If-Match": str(declaration["story_revision"])})
            assert create.status_code == 422
            assert create.json()["error"]["path"] == "/created_by"
            assert prepared.board(a).json() == before
    asyncio.run(scenario())


def test_own_reorder_leaves_boards_eligible_for_redraft(prepared):
    async def scenario():
        async with prepared.mcp.router.lifespan_context(prepared.mcp), prepared.session() as session:
            initial = await first_draft(prepared, session)
            a, b, c = [row["board_id"] for row in initial.boards]
            await call(session, "studio_reorder_boards", story_id=prepared.story,
                       revision=prepared.story_record()["revision"], board_order=[b, a, c])
            for board_id in (a, b):
                reordered = prepared.board(board_id).json()
                stamp = reordered["draft_application"]
                assert stamp["board_revision"] == reordered["revision"] == 2
                assert stamp["applied_board_revision"] == 1
            redraft = Draft.parse(prepared.raw("redraft.json"))
            result = await apply_draft(session, redraft, initial.baseline)
            assert result.ok, result.document()
            assert {row["board_id"]: row["revision"] for row in result.boards} == {a: 3, b: 3, c: 2}
            assert prepared.story_record()["board_order"] == [b, a, c]

            # A new application with the same hash is not an uninterrupted reorder.
            await call(session, "studio_patch_board", board_id=a, revision=3, patch={
                "title": "An intervening application",
                "draft_application": {
                    "board_key": "arrival", "draft_sha256": redraft.sha256, "model": redraft.model,
                    "session": redraft.session, "previous_draft_sha256": redraft.sha256,
                    "story_revision": prepared.story_record()["revision"],
                },
            })
            retry = await apply_draft(session, initial.draft, result.baseline)
            assert next(row for row in retry.boards if row["board_id"] == a)["reason"] == "revision_changed"
            assert prepared.board(a).json()["title"] == "An intervening application"

            # Reordering does not make an ordinary content patch part of the draft stamp.
            await call(session, "studio_patch_board", board_id=b, revision=4,
                       patch={"title": "An ordinary agent edit"})
            await call(session, "studio_reorder_boards", story_id=prepared.story,
                       revision=prepared.story_record()["revision"], board_order=[a, b, c])
            reordered = prepared.board(b).json()
            assert reordered["draft_application"]["board_revision"] == 4
            assert reordered["revision"] == 6
            final = await apply_draft(session, redraft, retry.baseline)
            assert next(row for row in final.boards if row["board_id"] == b)["reason"] == "revision_changed"
            assert prepared.board(b).json()["title"] == "An ordinary agent edit"
    asyncio.run(scenario())


def test_cli_acknowledges_only_the_named_board_and_records_it(prepared, draft_command):
    args, draft_file, receipt_file, _ = draft_command
    assert main(args) == 0
    a, b, _ = prepared.story_record()["board_order"]
    for board_id in (a, b):
        assert prepared.edit(board_id, 1, title="Person's board").status_code == 200
    draft_file.write_bytes(prepared.raw("redraft.json"))
    next_receipt = receipt_file.with_name("redraft-receipt.json")
    args[args.index("--out") + 1] = str(next_receipt)
    assert main([*args, "--previous", str(receipt_file), "--acknowledge-person-edit", a]) == 1
    receipt = json.loads(next_receipt.read_text())
    assert receipt["acknowledge_person_edit"] == [a]
    outcomes = {row["board_id"]: row for row in receipt["boards"]}
    assert outcomes[b]["reason"] == "edited_by_person"
    assert outcomes[a]["outcome"] == "applied"
    stamp = prepared.board(a).json()["draft_application"]
    assert stamp["person_edit_revision"] == 2
    assert stamp["person_edit_acknowledgments"] == [outcomes[a]["person_edit_acknowledgment"]]
    assert prepared.board(b).json()["title"] == "Person's board"


@pytest.mark.parametrize("change,rule", [
    ({"motion": "s2v", "layer": "layered"}, "method.s2v_needs_line"),
    ({"motion": "s2v", "layer": "whole_frame"}, "method.unavailable"),
])
def test_invalid_method_in_last_board_refuses_whole_draft(prepared, change, rule):
    draft_doc = json.loads(prepared.raw("first.json"))
    draft_doc["boards"][-1]["fields"]["method"] = change
    draft = Draft.parse(json.dumps(draft_doc).encode())

    async def scenario():
        async with prepared.mcp.router.lifespan_context(prepared.mcp), prepared.session() as session:
            result = await apply_draft(session, draft)
            assert result.error["code"] == "draft.invalid"
            assert rule in {item["code"] for item in result.error["violations"]}
            assert {row["outcome"] for row in result.boards} == {"skipped"}
            assert result.document()["usage"]["input_tokens"] == 175
            summary = await call(session, "studio_get_story_summary", story_id=prepared.story)
            assert summary["board_count"] == 0 and summary["revision"] == 1
    asyncio.run(scenario())


def test_other_production_key_has_no_access_and_mcp_exposes_no_media_or_approval(prepared):
    async def scenario():
        async with prepared.mcp.router.lifespan_context(prepared.mcp), prepared.session(prepared.other_key) as session:
            draft = Draft.parse(prepared.raw("first.json"))
            result = await apply_draft(session, draft)
            assert result.error == {"code": "auth.forbidden", "http_status": 403}
            assert {row["outcome"] for row in result.boards} == {"skipped"}
            tools = {item.name for item in (await session.list_tools()).tools}
            assert not any("media" in name or "approv" in name or "publish" in name for name in tools)
            assert prepared.story_record()["board_order"] == []
    asyncio.run(scenario())


@pytest.mark.parametrize("race", ["board", "story", "lost_response"])
def test_mid_apply_failure_reports_confirmed_writes_and_stops(prepared, race):
    async def scenario():
        async with prepared.mcp.router.lifespan_context(prepared.mcp), prepared.session() as session:
            initial = await first_draft(prepared, session)
            ids = [row["board_id"] for row in initial.boards]
            attempted = []

            class ConcurrentEdit:
                async def call_tool(self, name, arguments):
                    if name != "studio_patch_board":
                        return await session.call_tool(name, arguments)
                    id_ = arguments["board_id"]
                    attempted.append(id_)
                    if id_ != ids[1]:
                        return await session.call_tool(name, arguments)
                    if race == "board":
                        assert prepared.edit(id_, 1, title="Concurrent person edit").status_code == 200
                    elif race == "story":
                        revision = prepared.story_record()["revision"]
                        response = prepared.browser.patch(f"/v1/stories/{prepared.story}",
                                                          json={"title": "Concurrent story edit"},
                                                          headers={**prepared.csrf, "If-Match": str(revision)})
                        assert response.status_code == 200
                    reply = await session.call_tool(name, arguments)
                    if race == "lost_response":
                        assert not reply.isError
                        raise httpx.ReadTimeout("fixture lost a committed tool reply")
                    return reply

            draft = Draft.parse(prepared.raw("redraft.json"))
            result = await apply_draft(ConcurrentEdit(), draft, initial.baseline)
            assert attempted == ids[:2]
            expected = "uncertain" if race == "lost_response" else "conflict"
            assert [row["outcome"] for row in result.boards] == ["applied", expected, "skipped"]
            assert result.boards[1]["reason"] == ("draft.transport_failed" if race == "lost_response"
                                                  else "conflict.revision")
            assert result.baseline["arrival"].draft_sha256 == draft.sha256
            assert result.baseline["paperwork"] == initial.baseline["paperwork"]
            assert prepared.board(ids[0]).json()["revision"] == 2
            assert prepared.board(ids[2]).json()["revision"] == 1
            second = prepared.board(ids[1]).json()
            assert second["revision"] == (1 if race == "story" else 2)
            if race == "board":
                assert second["title"] == "Concurrent person edit"
            if race == "lost_response":
                assert second["draft_application"]["draft_sha256"] == draft.sha256
    asyncio.run(scenario())
