import json
import logging
import secrets

import httpx
import pytest
from jsonschema import Draft202012Validator

from haynes_studio.canonical.ids import Minter
from haynes_studio.mcp.server import MAX_ARGUMENT_BYTES, MAX_REQUEST_BYTES, MAX_RESULT_BYTES, create_app

from .client import API_URL, MCP_URL, call, connect, fail

pytestmark = pytest.mark.anyio

NAMES = set("""
studio_list_productions studio_get_production studio_list_stories studio_create_story
studio_get_story_summary studio_patch_story studio_get_story_timing studio_add_board
studio_get_board studio_patch_board studio_reorder_boards studio_remove_board
studio_search_assets studio_get_asset studio_get_delivery
""".split())


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def api():
    return FakeStudio()


class FakeStudio:
    def __init__(self):
        minter = Minter(clock=lambda: 1, random_bits=lambda: 1)
        self.pid = minter.mint("prd")
        self.sid = minter.mint("sty")
        self.bid, self.bid2 = minter.mint("brd"), minter.mint("brd")
        self.aid, self.vid, self.rid = (minter.mint(prefix) for prefix in ("ast", "asv", "run"))
        self.authorization = "bEaReR " + secrets.token_urlsafe(32)
        self.requests = []
        self.override = None
        self.production = {"id": self.pid, "schema": "studio.production/v1", "revision": 4,
                           "name": "A production", "labels": ["fixture"], "media_types": [{"kind": "short"}]}
        self.story = {"id": self.sid, "schema": "studio.story/v1", "revision": 5,
                      "production_id": self.pid, "title": "A story", "cast": [],
                      "board_order": [self.bid2, self.bid], "beds": []}
        self.board = {"id": self.bid, "schema": "studio.board/v1", "revision": 6, "story_id": self.sid,
                      "number": 1, "title": "A board", "lines": [], "notes": [], "cues": []}
        self.version = {"id": self.vid, "number": 2, "asset_id": self.aid, "kind": "voice",
                        "content": {"locator": "never-forward-this"}}
        self.app = create_app(API_URL, api_transport=httpx.MockTransport(self.request))

    def request(self, request):
        path = request.url.path
        if request.headers.get("authorization") != self.authorization:
            return httpx.Response(401, json={"error": {"code": "auth.required", "request_id": "req-auth"}})
        assert "cookie" not in request.headers
        if path == "/v1/me":
            return httpx.Response(200, json={"principal": {"kind": "agent"}},
                                  headers={"set-cookie": "fixture=ignored"})
        self.requests.append(request)
        if self.override is not None:
            return self.override(request)
        if request.method == "DELETE":
            return httpx.Response(204)
        status = 201 if request.method == "POST" else 200
        if path == "/v1/productions":
            doc = {"items": [self.production], "next_cursor": self.pid}
        elif path == f"/v1/productions/{self.pid}":
            doc = self.production
        elif path == f"/v1/productions/{self.pid}/media-types/short/stories" and request.method == "GET":
            doc = {"items": [self.story], "next_cursor": self.sid}
        elif path.endswith("/stories") or path in (f"/v1/stories/{self.sid}", f"/v1/stories/{self.sid}/board-order"):
            doc = self.story
        elif path == f"/v1/stories/{self.sid}/timing":
            doc = {"story_id": self.sid, "story_revision": self.story["revision"], "build_blockers": [],
                   "boards": [{"board_id": id_, "frames": 24} for id_ in self.story["board_order"]]}
        elif path == "/v1/assets":
            doc = {"items": [self.version], "next_cursor": self.vid}
        elif path == f"/v1/assets/{self.aid}":
            doc = {"asset": {"id": self.aid, "revision": 3}, "versions": [self.version],
                   "next_cursor": self.vid}
        elif path == f"/v1/runs/{self.rid}/delivery":
            doc = {"run_id": self.rid, "master": {"frames": 24, "locator": "never-forward-this"}, "proxy": None}
        elif path in (f"/v1/stories/{self.sid}/boards", f"/v1/boards/{self.bid}"):
            doc = self.board
        else:
            raise AssertionError(f"Unhandled API route {path}")
        return httpx.Response(status, json=doc, headers={"X-Request-ID": "req-fixture"})


async def test_discovery_pages_and_projections(api):
    async with api.app.router.lifespan_context(api.app), connect(api.app, api.authorization) as session:
        tools = (await session.list_tools()).tools
        assert {tool.name for tool in tools} == NAMES
        for tool in tools:
            Draft202012Validator.check_schema(tool.inputSchema)
        patch = next(tool for tool in tools if tool.name == "studio_patch_board")
        assert set(patch.inputSchema["required"]) == {"board_id", "patch", "revision"}
        assert patch.annotations.readOnlyHint is False
        assert {"lines", "cues", "notes", "photo"} <= set(patch.inputSchema["$defs"]["BoardFields"]["properties"])

        productions = await call(session, "studio_list_productions", cursor=api.pid, limit=1)
        assert productions["next_cursor"] == api.pid
        assert productions["items"][0]["revision"] == 4
        assert dict(api.requests[-1].url.params) == {"cursor": api.pid, "limit": "1"}
        assert (await call(session, "studio_get_production", production_id=api.pid))["labels"] == ["fixture"]
        stories = await call(session, "studio_list_stories", production_id=api.pid, kind="short",
                             publication="unpublished", approved=False, cursor=api.sid)
        assert stories["items"][0]["board_count"] == 2
        assert stories["next_cursor"] == api.sid
        assert dict(api.requests[-1].url.params) == {
            "cursor": api.sid, "limit": "10", "publication": "unpublished", "approved": "false",
        }
        first = await call(session, "studio_get_story_summary", story_id=api.sid, fields=["cast"], limit=1)
        assert first["revision"] == 5 and first["board_order"] == [api.bid2] and first["cast"] == []
        second = await call(session, "studio_get_story_summary", story_id=api.sid, cursor=first["next_cursor"])
        assert second["board_order"] == [api.bid] and second["next_cursor"] is None
        timing = await call(session, "studio_get_story_timing", story_id=api.sid, limit=1)
        assert timing["story_revision"] == 5 and timing["boards"][0]["board_id"] == api.bid2
        assert timing["next_cursor"] == first["next_cursor"]
        api.story["revision"] += 1
        stale = await fail(session, "studio_get_story_summary", story_id=api.sid, cursor=first["next_cursor"])
        assert (stale["code"], stale["current_revision"], stale["request_id"]) == (
            "conflict.revision", 6, "req-fixture",
        )

        board = await call(session, "studio_get_board", board_id=api.bid, fields=["notes"])
        assert board["notes"] == [] and "lines" not in board and board["revision"] == 6
        search = await call(session, "studio_search_assets", production=api.pid, board=api.bid,
                            kind="voice", label=["one", "two"], cursor=api.vid)
        assert search["items"][0]["number"] == 2 and search["next_cursor"] == api.vid
        assert "content" not in search["items"][0]
        assert api.requests[-1].url.params.get_list("label") == ["one", "two"]
        asset = await call(session, "studio_get_asset", asset_id=api.aid, limit=1)
        assert asset["asset"]["revision"] == 3 and asset["versions"] == search["items"]
        delivery = await call(session, "studio_get_delivery", run_id=api.rid)
        assert delivery["master"] == {"frames": 24}


async def test_writes_forward_only_expected_methods_bodies_and_etags(api):
    async with api.app.router.lifespan_context(api.app), connect(api.app, api.authorization) as session:
        await call(session, "studio_create_story", production_id=api.pid, kind="short", fields={"title": "Draft"})
        await call(session, "studio_patch_story", story_id=api.sid, revision=5,
                   patch={"set": None, "motion_style": {"style": "fixture"}})
        added = await call(session, "studio_add_board", story_id=api.sid, revision=6, fields={})
        assert added["story_revision"] == 7
        patch = {"photo": {"current_version_id": api.vid}, "notes": [{"text": "Hold"}],
                 "lines": [], "cues": []}
        await call(session, "studio_patch_board", board_id=api.bid, revision=7, patch=patch)
        order = [api.bid, api.bid2]
        await call(session, "studio_reorder_boards", story_id=api.sid, revision=8, board_order=order)
        removed = await call(session, "studio_remove_board", board_id=api.bid, revision=9)
        assert removed == {"id": api.bid, "revision": 10, "tombstone": True}

    assert [req.method for req in api.requests] == ["POST", "PATCH", "POST", "PATCH", "PUT", "DELETE"]
    assert [req.headers.get("if-match") for req in api.requests] == [None, '"5"', '"6"', '"7"', '"8"', '"9"']
    assert [json.loads(req.content) if req.content else None for req in api.requests] == [
        {"title": "Draft"}, {"set": None, "motion_style": {"style": "fixture"}}, {},
        patch, {"board_order": order}, None,
    ]


async def test_rejects_unknown_tools_malformed_and_oversize_arguments(api):
    async with api.app.router.lifespan_context(api.app), connect(api.app, api.authorization) as session:
        for name in ("go_live:approve", "studio_get_media"):
            assert (await fail(session, name))["code"] == "tool.not_found"
        args = {"board_id": api.bid, "revision": 1}
        oversized = await fail(session, "studio_patch_board", **args,
                               patch={"notes": [{"text": "x" * MAX_ARGUMENT_BYTES}]})
        assert oversized["status"] == "too_large"
        for invalid in ({"patch": {"raw_graph": {}}}, {"patch": {}, "revision": True},
                        {"patch": {}, "board_id": "../media/file"}):
            result = await fail(session, "studio_patch_board", **{**args, **invalid})
            assert result["status"] == "invalid"
        assert not api.requests


async def test_transport_auth_host_origin_and_request_limit(api, caplog):
    caplog.set_level(logging.INFO)
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    async with api.app.router.lifespan_context(api.app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api.app),
        headers={"Accept": "application/json, text/event-stream"},
    ) as http:
        missing = await http.post(MCP_URL, json=body, headers={"Cookie": "attempt=browser-session"})
        invalid = await http.post(MCP_URL, json=body, headers={"Authorization": "Bearer " + secrets.token_urlsafe(32)})
        duplicate = await http.post(MCP_URL, json=body, headers=[("Authorization", api.authorization)] * 2)
        assert [response.status_code for response in (missing, invalid, duplicate)] == [401, 401, 401]
        assert invalid.headers["www-authenticate"] == "Bearer"
        assert invalid.json()["error"]["request_id"] == "req-auth"
        assert (await http.post(MCP_URL, json=body, headers={"Host": "other.example.invalid"})).status_code == 421
        assert (await http.post(MCP_URL, json=body,
                                headers={"Origin": "https://other.example.invalid"})).status_code == 403
        response = await http.post(MCP_URL, content=b" " * (MAX_REQUEST_BYTES + 1), headers={
            "Authorization": api.authorization, "Content-Type": "application/json",
        })
        assert response.status_code == 413
        ok = await http.post(MCP_URL, json=body, headers={"Authorization": api.authorization})
        assert ok.headers["cache-control"] == "no-store"
        assert ok.status_code == 200 and {tool["name"] for tool in ok.json()["result"]["tools"]} == NAMES
    assert api.authorization.split()[1] not in caplog.text


@pytest.mark.parametrize(("status", "code", "studio_status", "expected"), [
    (422, "method.unavailable", "unavailable", "unavailable"),
    (409, "conflict.revision", "conflict", "conflict"),
    (503, "database.failed", "service_unavailable", "service_unavailable"),
    (500, "request.failed", "internal", "internal"),
    (502, None, None, "service_unavailable"),
])
async def test_api_error_envelopes(api, status, code, studio_status, expected):
    def error(_):
        if code is None:
            return httpx.Response(status, text="upstream diagnostic")
        return httpx.Response(status, json={"error": {
            "code": code, "status": studio_status, "http_status": status,
            "path": "/revision", "message": "Fixture", "request_id": "req-api", "current_revision": 12,
        }})

    api.override = error
    async with api.app.router.lifespan_context(api.app), connect(api.app, api.authorization) as session:
        result = await fail(session, "studio_patch_board", board_id=api.bid, revision=5, patch={})
    assert result["status"] == expected
    if code:
        assert result["code"] == code and result["request_id"] == "req-api"
    if status == 409:
        assert result["current_revision"] == 12


async def test_transport_failure_redirect_binary_and_bounded_results(api):
    def network_error(request):
        raise httpx.ConnectError("upstream diagnostic", request=request)

    async with api.app.router.lifespan_context(api.app), connect(api.app, api.authorization) as session:
        api.override = network_error
        unavailable = await fail(session, "studio_get_board", board_id=api.bid)
        assert unavailable["code"] == "service_unavailable" and unavailable["http_status"] == 503
        api.override = lambda _: httpx.Response(307, headers={"Location": "https://other.example.invalid/"})
        redirected = await fail(session, "studio_get_board", board_id=api.bid)
        assert redirected["code"] == "internal"
        assert len(api.requests) == 2
        api.override = lambda _: httpx.Response(200, content=b"fixture", headers={"Content-Type": "video/mp4"})
        binary = await fail(session, "studio_get_board", board_id=api.bid)
        assert binary["code"] == "internal"
        api.override = None
        api.board["notes"] = [{"text": "x" * MAX_RESULT_BYTES}]
        huge = await fail(session, "studio_get_board", board_id=api.bid)
        assert huge["code"] == "result.too_large" and huge["request_id"] == "req-fixture"
        doc = await call(session, "studio_get_board", board_id=api.bid, fields=["cues"])
        assert doc["cues"] == [] and "notes" not in doc
