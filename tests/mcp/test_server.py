import asyncio
import json
import logging
import secrets
import ssl
from datetime import UTC, datetime
from ipaddress import ip_address

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jsonschema import Draft202012Validator

from haynes_studio.canonical.ids import Minter
from haynes_studio.mcp.server import MAX_ARGUMENT_BYTES, MAX_REQUEST_BYTES, MAX_RESULT_BYTES, _api_origin, create_app
from haynes_studio.mcp.upstream import MAX_ERROR_BYTES
from tests.canonical.fixtures import example
from tests.formats.fixtures import doll_short

from .client import API_URL, MCP_URL, UPLOAD_URL, call, connect, fail

pytestmark = pytest.mark.anyio

NAMES = set("""
studio_list_productions studio_get_production studio_list_stories studio_create_story
studio_get_story_summary studio_patch_story studio_get_story_timing studio_add_board
studio_list_candidates
studio_get_board studio_patch_board studio_reorder_boards studio_remove_board
studio_search_assets studio_get_asset studio_get_delivery
studio_list_formats studio_list_format_versions studio_get_format_version
studio_generate_voice studio_generate_photo studio_get_job
studio_estimate_run studio_queue_run studio_list_runs studio_get_run studio_cancel_run
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
        self.fmv = minter.mint("fmv")
        self.cid, self.fid = minter.mint("cnd"), minter.mint("fbk")
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
            return httpx.Response(401, json={"error": {
                "code": "auth.required", "status": "unauthenticated", "http_status": 401,
                "path": "", "message": "Present a valid credential", "request_id": "req-auth",
            }})
        assert "cookie" not in request.headers
        if path == "/v1/me":
            return httpx.Response(200, json={"principal": {"kind": "agent"},
                                             "production_scopes": {self.pid: ["assets:upload"]}},
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
        elif path == f"/v1/stories/{self.sid}/candidates":
            doc = {"revision": 5, "iteration": None, "next_cursor": None, "items": [{
                "id": self.cid, "run_id": self.rid, "target_id": "fixture-shorts",
                "notes": [{"id": self.fid, "text": "Hold the last reaction", "board_ids": [self.bid],
                           "internal": "not projected"}],
                "answering_runs": [],
            }]}
        elif path == "/v1/assets":
            doc = {"items": [self.version], "next_cursor": self.vid}
        elif path == f"/v1/assets/{self.aid}":
            doc = {"asset": {"id": self.aid, "revision": 3}, "versions": [self.version],
                   "next_cursor": self.vid}
        elif path == f"/v1/runs/{self.rid}/delivery":
            doc = {"run_id": self.rid, "master": {"frames": 24, "locator": "never-forward-this"}, "proxy": None}
        elif path == "/v1/formats":
            doc = {"items": [{"id": "doll-short", "name": "Doll short"}], "next_cursor": None}
        elif path in ("/v1/formats/doll-short/versions", f"/v1/format-versions/{self.fmv}"):
            version = {"id": self.fmv, "number": 1, "format_id": "doll-short", "sha256": "0" * 64}
            doc = ({"items": [version], "next_cursor": None} if path.endswith("/versions") else
                   {**version, "recipe": doll_short()["recipe"]})
        elif path in (f"/v1/stories/{self.sid}/boards", f"/v1/boards/{self.bid}"):
            doc = self.board
        else:
            raise AssertionError(f"Unhandled API route {path}")
        return httpx.Response(status, json=doc, headers={"X-Request-ID": "req-fixture"})


async def test_find_selected_feedback_through_read_only_mcp(api):
    async with api.app.router.lifespan_context(api.app), connect(api.app, api.authorization) as session:
        tools = (await session.list_tools()).tools
        tool = next(tool for tool in tools if tool.name == "studio_list_candidates")
        assert tool.annotations.readOnlyHint is True
        page = await call(session, tool.name, story_id=api.sid, candidate_id=api.cid,
                          run_id=api.rid, note_ids=[api.fid])
        assert page["items"][0]["notes"] == [{
            "id": api.fid, "text": "Hold the last reaction", "board_ids": [api.bid],
        }]
        request = api.requests[-1]
        assert request.method == "GET" and request.content == b""
        assert request.url.path == f"/v1/stories/{api.sid}/candidates"
        assert dict(request.url.params) == {
            "candidate_id": api.cid, "run_id": api.rid, "note_ids": api.fid, "limit": "1",
        }


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

        format_tools = [tool for tool in tools if "format" in tool.name]
        assert len(format_tools) == 3 and all(tool.annotations.readOnlyHint for tool in format_tools)
        catalog = await call(session, "studio_list_formats")
        assert catalog["items"] == [{"id": "doll-short", "name": "Doll short"}]
        versions = await call(session, "studio_list_format_versions", format_id="doll-short", limit=1)
        assert versions["items"][0]["id"] == api.fmv
        assert dict(api.requests[-1].url.params) == {"limit": "1"}
        result = await call(session, "studio_get_format_version", version_id=api.fmv)
        assert result["recipe"] == doll_short()["recipe"]


async def test_writes_forward_only_expected_methods_bodies_and_etags(api):
    async with api.app.router.lifespan_context(api.app), connect(api.app, api.authorization) as session:
        await call(session, "studio_create_story", production_id=api.pid, kind="short", fields={"title": "Draft"})
        await call(session, "studio_patch_story", story_id=api.sid, revision=5,
                   patch={"set": None, "motion_style": {"style": "fixture"}, "format_version_id": api.fmv})
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
        {"title": "Draft"}, {"set": None, "motion_style": {"style": "fixture"}, "format_version_id": api.fmv}, {},
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
        invalid = await fail(session, "studio_patch_board", board_id="../media/file", revision=True,
                             patch={"raw/~graph": "sensitive-fixture-value",
                                    "notes": [{}, "sensitive-fixture-value"]})
        assert invalid["status"] == "invalid"
        assert invalid["path"] in {item["path"] for item in invalid["violations"]}
        assert {(item["path"], item["rule"]) for item in invalid["violations"]} == {
            ("/board_id", "string_pattern_mismatch"), ("/revision", "int_type"),
            ("/patch/raw~1~0graph", "extra_forbidden"), ("/patch/notes/1", "dict_type"),
        }
        assert "sensitive-fixture-value" not in json.dumps(invalid) and "../media/file" not in json.dumps(invalid)
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
        for token in ("A" * 42, "A" * 47, "_" * 48, "A" * 129):
            response = await http.post(MCP_URL, json=body, headers={"Authorization": "Bearer " + token})
            assert response.status_code == 401
            assert response.json()["error"]["request_id"].startswith("mcp-")
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


async def test_upload_tool_has_its_own_endpoint_and_main_requests_stay_bounded(api):
    headers = {"Accept": "application/json, text/event-stream", "Authorization": api.authorization,
               "Content-Type": "application/json"}
    async with api.app.router.lifespan_context(api.app), connect(api.app, api.authorization) as regular, \
            connect(api.app, api.authorization, url=UPLOAD_URL) as uploads, httpx.AsyncClient(
                transport=httpx.ASGITransport(app=api.app), headers=headers,
            ) as http:
        assert {tool.name for tool in (await uploads.list_tools()).tools} == {"studio_upload_photo"}
        assert (await fail(regular, "studio_upload_photo"))["code"] == "tool.not_found"
        assert (await fail(uploads, "studio_get_board", board_id=api.bid))["code"] == "tool.not_found"

        oversized = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "studio_get_board", "arguments": {"board_id": "x" * (256 * 1024)},
        }}
        assert (await http.post(MCP_URL, json=oversized)).status_code == 413
        assert not api.requests


async def test_upload_endpoint_bounds_chunked_body(api):
    limit = 4 * ((20 * 1024 * 1024 + 2) // 3) + 256 * 1024
    started = 0

    async def oversized():
        nonlocal started
        block = b" " * (256 * 1024)
        for _ in range(limit // len(block) + 3):
            started += 1
            yield block

    async with api.app.router.lifespan_context(api.app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api.app),
        headers={"Accept": "application/json, text/event-stream", "Authorization": api.authorization,
                 "Content-Type": "application/json"},
    ) as http:
        assert (await http.post(UPLOAD_URL, content=oversized())).status_code == 413
        assert started == limit // (256 * 1024) + 1
        assert (await http.request("GET", UPLOAD_URL, content=b" " * (256 * 1024 + 1))).status_code == 413
    assert not api.requests


@pytest.mark.parametrize(("transport_status", "envelope"), [
    (422, example("valid/error-method-unavailable.json")),
    (418, example("valid/error-method-unavailable.json")),
    (400, {"error": {
        "code": "conflict.revision", "status": "conflict", "http_status": 409, "path": "/revision",
        "message": "Expected the current revision", "request_id": "req-api", "current_revision": 12,
        "context": {"hints": ["Read the current draft"]},
    }}),
    (503, {"error": {
        "code": "database.failed", "status": "service_unavailable", "http_status": 503,
        "path": "", "message": "Database unavailable", "request_id": "req-api",
    }}),
    (500, {"error": {
        "code": "request.failed", "status": "internal", "http_status": 500,
        "path": "", "message": "The request could not be completed", "request_id": "req-api",
    }}),
])
async def test_api_error_envelopes(api, transport_status, envelope):
    api.override = lambda _: httpx.Response(transport_status, json=envelope)
    async with api.app.router.lifespan_context(api.app), connect(api.app, api.authorization) as session:
        result = await fail(session, "studio_patch_board", board_id=api.bid, revision=5, patch={})
    assert result == envelope["error"]


async def test_api_error_envelopes_bound_invalid_and_oversize_errors(api):
    document = example("valid/error-method-unavailable.json")
    async with api.app.router.lifespan_context(api.app), connect(api.app, api.authorization) as session:
        api.override = lambda _: httpx.Response(418, text="upstream diagnostic")
        assert (await fail(session, "studio_get_board", board_id=api.bid))["status"] == "internal"
        api.override = lambda _: httpx.Response(502, text="upstream diagnostic")
        assert (await fail(session, "studio_get_board", board_id=api.bid))["status"] == "service_unavailable"
        api.override = lambda _: httpx.Response(422, json=document)
        document["error"]["diagnostic"] = "x" * MAX_ERROR_BYTES
        oversized = await fail(session, "studio_get_board", board_id=api.bid)
        assert oversized["code"] == "internal" and "diagnostic" not in oversized
        document["error"]["status"] = "unsupported"
        document["error"].pop("diagnostic")
        invalid = await fail(session, "studio_get_board", board_id=api.bid)
        assert invalid["status"] == "invalid" and "board_id" not in invalid


@pytest.mark.parametrize("url", [
    "http://studio-api.studio.svc.cluster.local:8000", "http://studio-api.studio.svc.cluster.local.",
    "http://localhost", "http://127.1.2.3:8000", "http://[::1]:8000", "https://example.invalid",
])
def test_accepts_https_and_local_http_origins(url):
    assert _api_origin(url) == httpx.URL(url)


@pytest.mark.parametrize("url", [
    "http://example.invalid", "http://studio-api", "http://10.0.0.1",
    "http://studio-api.studio.svc", "http://studio-api.studio.svc.",
    "http://studio-api.studio.svc.cluster.local.example.invalid",
    "https://example.invalid/api", "https://user:pass@example.invalid", "https://example.invalid/?token=fixture",
])
def test_refuses_invalid_or_nonlocal_http_origins(url):
    with pytest.raises(ValueError, match="STUDIO_API_URL"):
        _api_origin(url)


async def test_api_tls_uses_explicit_ca_and_ignores_environment(tmp_path, monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "Studio test CA")])
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(1).not_valid_before(datetime(2020, 1, 1, tzinfo=UTC))
        .not_valid_after(datetime(2099, 1, 1, tzinfo=UTC))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ip_address("127.0.0.1"))]), critical=False)
        .sign(key, hashes.SHA256())
    )
    bundle, private_key = tmp_path / "ca.pem", tmp_path / "key.pem"
    bundle.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private_key.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(bundle, private_key)
    body = b'{"principal":{"kind":"agent"}}'

    async def upstream(reader, writer):
        try:
            assert (await reader.readuntil(b"\r\n\r\n")).startswith(b"GET /v1/me HTTP/1.1\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                         + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def discover(app):
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            return await client.post(MCP_URL, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers={
                "Authorization": "Bearer " + secrets.token_urlsafe(32),
                "Accept": "application/json, text/event-stream",
            })

    monkeypatch.setenv("SSL_CERT_FILE", str(bundle))
    monkeypatch.setenv("NO_PROXY", "*")
    async with await asyncio.start_server(upstream, "127.0.0.1", 0, ssl=context) as server:
        url = f"https://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        assert (await discover(create_app(url))).status_code == 503
        monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
        monkeypatch.setenv("NO_PROXY", "")
        response = await discover(create_app(url, api_ca_file=bundle))
        assert response.status_code == 200
        assert {tool["name"] for tool in response.json()["result"]["tools"]} == NAMES


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
