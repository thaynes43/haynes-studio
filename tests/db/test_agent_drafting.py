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
from PIL import Image

from haynes_studio.canonical import to_document
from haynes_studio.canonical.ids import Minter
from haynes_studio.cli import main
from haynes_studio.db.catalog import record_asset_version
from haynes_studio.drafting import cli as draft_cli
from haynes_studio.drafting.apply import apply_draft, read_baseline
from haynes_studio.drafting.document import Draft
from haynes_studio.mcp.server import create_app
from tests.library.fixtures import winter_menu
from tests.mcp.client import API_URL, MCP_URL, call, connect, fail

from .test_studio_api import (
    client, engine, new_production, owner_engine, register_agent, runtime_db, service, sign_in,
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


def test_cli_first_draft_records_provenance_pins_and_usage(prepared, tmp_path, monkeypatch, capsys):
    @asynccontextmanager
    async def in_process_http(**kwargs):
        async with prepared.mcp.router.lifespan_context(prepared.mcp):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=prepared.mcp), **kwargs) as http:
                yield http

    monkeypatch.setattr(draft_cli, "httpx", SimpleNamespace(
        AsyncClient=in_process_http, URL=httpx.URL, InvalidURL=httpx.InvalidURL,
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
            "applied_at": row["applied_at"], "board_revision": 1,
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
