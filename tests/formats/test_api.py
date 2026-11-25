"""Format request and access guards through the HTTP and MCP applications."""

import asyncio
import copy
import json
from contextlib import nullcontext
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from haynes_studio.api.app import schema_app
from haynes_studio.canonical.ids import Minter
from haynes_studio.db import identity
from haynes_studio.mcp.server import create_app
from haynes_studio.store import canonical_json
from tests.formats.fixtures import doll_short, wide
from tests.mcp.client import API_URL, connect, fail


@pytest.fixture
def catalog(monkeypatch):
    app = schema_app()
    conn = Mock()
    conn.begin.side_effect = nullcontext
    conn.scalar.side_effect = lambda statement: 1 if statement.is_select else "fixture"
    app.state.engine = Mock()
    app.state.engine.begin.side_effect = lambda: nullcontext(conn)
    app.state.engine.connect.return_value.execution_options.return_value = nullcontext(conn)
    agent, worker = "a" * 43, "w" * 43
    minter = Minter()
    production = minter.mint("prd")
    key = minter.mint("key")

    def get_agent(_, credential):
        if credential == agent:
            return key, {production: frozenset({"read", "formats:write"})}
        return None

    monkeypatch.setattr(identity, "get_agent", get_agent)
    monkeypatch.setattr(identity, "get_worker", lambda _, value: "worker-fixture" if value == worker else None)
    return TestClient(app, headers={"Authorization": f"Bearer {agent}"}), conn, f"Bearer {worker}"


def post(client, payload, *, append=False):
    if append:
        return client.post(f"/v1/formats/{payload['id']}/versions", json=payload["recipe"])
    return client.post("/v1/formats", json=payload)


def refusal(reply, code, path):
    assert reply.status_code == 422, reply.text
    error = reply.json()["error"]
    assert (error["code"], error["path"]) == (code, path)
    return error["message"]


@pytest.mark.parametrize("fixture", [doll_short, wide])
@pytest.mark.parametrize("append", [False, True], ids=["create", "append"])
def test_api_accepts_recipe_fixtures(catalog, fixture, append):
    client, conn, _ = catalog
    payload = fixture()
    reply = post(client, payload, append=append)
    assert reply.status_code == 201, reply.text
    assert reply.json()["recipe"] == payload["recipe"]
    assert reply.json()["number"] == (2 if append else 1)
    assert conn.execute.call_count == (2 if append else 1)


@pytest.mark.parametrize("name", [
    "token", "access_token", "clientSecret", "password", "passwd", "api_key", "ApiKey",
    "key", "signing_key", "cookie", "credential", "authorization", "bearer", "session",
    "privatekey", "accesskey", "signingkey",
])
def test_api_refuses_credential_property_names(catalog, name):
    client, conn, _ = catalog
    payload = doll_short()
    costume = payload["recipe"]["cast"]["team_costumes"]["yellowbirds"]
    costume[name] = "synthetic-value"
    reply = post(client, payload)
    path = "/recipe/cast/team_costumes/yellowbirds/" + name
    assert refusal(reply, "format.credential", path) == "Credential-like property names are forbidden"
    assert "synthetic-value" not in reply.text
    conn.execute.assert_not_called()


def test_api_refuses_root_property_and_hides_a_credential_in_a_property_path(catalog):
    client, conn, _ = catalog
    payload = wide()
    payload["recipe"]["upload/session"] = {}
    refusal(post(client, payload), "format.credential", "/recipe/upload~1session")
    del payload["recipe"]["upload/session"]
    payload["recipe"]["cast"]["team_costumes"]["Bearer synthetic-value"] = {}
    reply = post(client, payload)
    refusal(reply, "format.credential", "/recipe/cast/team_costumes")
    assert "synthetic-value" not in reply.text
    conn.execute.assert_not_called()


@pytest.mark.parametrize("value", [
    "-----BEGIN TEST-----\nsynthetic-value\n-----END TEST-----",
    "https://example:synthetic-value@example.invalid",
    "AKIA" + "0" * 16,
    "Bearer synthetic-value-" + "s9" * 8,
    "Basic " + "c3ludGhldGljOnZhbHVl" * 2,
    "password=synthetic-value",
    'the cookie: "synthetic-value-' + "s9" * 8 + '"',
    "token: synthetic-value-" + "s9" * 8,
    "password: synthetic9",
], ids=["pem", "url-userinfo", "aws-key-shape", "auth-scheme", "auth-scheme-mixed-case",
        "assignment", "quoted", "keyed-token", "keyed-password"])
@pytest.mark.parametrize("append", [False, True], ids=["create", "append"])
def test_api_refuses_credential_values_without_echoing_them(catalog, value, append):
    client, conn, _ = catalog
    payload = doll_short()
    payload["recipe"]["targets"][0]["owner_note"] = value
    reply = post(client, payload, append=append)
    path = ("" if append else "/recipe") + "/targets/0/owner_note"
    assert refusal(reply, "format.credential", path) == "Credential-like values are forbidden"
    assert value not in reply.text and "synthetic-value" not in reply.text
    conn.execute.assert_not_called()


@pytest.mark.parametrize("text", [
    "Basic shots stay ambient.",
    "Spend one token per line.",
    "Bearer of bad news",
    "Keep the cookie: crumbly",
    "Basic 1080x1920 frames, basic over-the-shoulder framing",
    "The secret: nobody at the table knows",
    'Her password: "open sesame", said twice',
    "b" * 64,
    "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
], ids=["basic", "token", "bearer", "cookie", "frame-size", "secret", "quoted-phrase",
        "sha256", "uuid"])
def test_api_accepts_ordinary_prose_that_names_a_credential_word(catalog, text):
    client, _, _ = catalog
    payload = doll_short()
    payload["recipe"]["targets"][0]["owner_note"] = text
    reply = post(client, payload)
    assert reply.status_code == 201, reply.text


def test_api_refuses_a_credential_in_the_format_name(catalog):
    client, conn, _ = catalog
    payload = wide()
    payload["name"] = "Bearer synthetic-value-" + "s9" * 8
    reply = post(client, payload)
    refusal(reply, "format.credential", "/name")
    assert "synthetic-value" not in reply.text
    conn.execute.assert_not_called()


def test_api_restricts_checks_to_known_names_and_parameter_types(catalog):
    client, _, _ = catalog
    payload = doll_short()
    checks = payload["recipe"]["checks"]
    checks["unknown.check"] = {}
    refusal(post(client, payload), "schema.unknown_field", "/recipe/checks/unknown.check")
    del checks["unknown.check"]
    checks["decal.drift"]["arbitrary"] = 2
    refusal(post(client, payload), "schema.unknown_field", "/recipe/checks/decal.drift/arbitrary")
    checks["decal.drift"].pop("arbitrary")
    checks["decal.drift"]["min_ecc"] = "synthetic-value"
    reply = post(client, payload)
    refusal(reply, "schema.invalid", "/recipe/checks/decal.drift/min_ecc")
    assert "synthetic-value" not in reply.text


@pytest.mark.parametrize("path", [("notes",), ("cast", "rules"), ("voice", "style"), ("audio", "style")])
def test_api_bounds_text_lists(catalog, path):
    client, _, _ = catalog
    payload = wide()
    obj = payload["recipe"]
    for name in path[:-1]:
        obj = obj[name]
    obj[path[-1]] = ["Plain text"] * 32
    assert post(client, payload).status_code == 201
    obj[path[-1]].append("One more entry")
    message = refusal(post(client, payload), "schema.invalid", "/recipe/" + "/".join(path))
    assert message == "must have at most 32 entries"


def test_api_bounds_target_count(catalog):
    client, _, _ = catalog
    payload = doll_short()
    targets = payload["recipe"]["targets"]
    for index in range(1, 16):
        targets.append({**targets[0], "id": f"target-{index}"})
    assert post(client, payload).status_code == 201
    targets.append({**targets[0], "id": "target-16"})
    assert refusal(post(client, payload), "schema.invalid", "/recipe/targets") == "must have at most 16 entries"


def test_api_bounds_method_and_gate_counts(catalog):
    client, _, _ = catalog
    payload = doll_short()
    methods = payload["recipe"]["shot_types"]["speaking"]
    methods += [{"layer": "layered", "motion": "i2v"}, {"layer": "whole_frame", "motion": "i2v"}]
    assert post(client, payload).status_code == 201
    methods.append({"layer": "whole_frame", "motion": "s2v"})
    message = refusal(post(client, payload), "schema.invalid", "/recipe/shot_types/speaking")
    assert message == "must have at most 3 entries"
    methods.pop()
    payload["recipe"]["human_gates"].append("go_live")
    assert refusal(post(client, payload), "schema.invalid", "/recipe/human_gates") == "must have at most 1 entry"


@pytest.mark.parametrize(("field", "value"), [
    ("id", "a" * 64), ("platform", "b" * 64), ("account_id", "A" * 128),
    ("owner_note", "é" * 1000),
], ids=["id", "platform", "account-id", "owner-note"])
def test_api_bounds_target_string_lengths(catalog, field, value):
    client, _, _ = catalog
    payload = doll_short()
    target = payload["recipe"]["targets"][0]
    target.update(state="existing", account_id="public-account")
    target[field] = value
    assert post(client, payload).status_code == 201
    target[field] += "a"
    message = refusal(post(client, payload), "schema.invalid", f"/recipe/targets/0/{field}")
    assert message == f"must have at most {len(value)} characters"


def test_api_bounds_note_length(catalog):
    client, _, _ = catalog
    payload = wide()
    payload["recipe"]["notes"] = ["é" * 1000]
    assert post(client, payload).status_code == 201
    payload["recipe"]["notes"][0] += "é"
    message = refusal(post(client, payload), "schema.invalid", "/recipe/notes/0")
    assert message == "must have at most 1000 characters"


def test_api_bounds_aspect_and_costume_attribute_lengths(catalog):
    client, _, _ = catalog
    payload = doll_short()
    recipe = payload["recipe"]
    rules = recipe["targets"][0]["rules"]
    rules["aspect"] = "12345:12345"
    costume = recipe["cast"]["team_costumes"]["yellowbirds"]
    key = "a" * 64
    costume[key] = "Plain text"
    assert post(client, payload).status_code == 201
    rules["aspect"] += "6"
    message = refusal(post(client, payload), "schema.invalid", "/recipe/targets/0/rules/aspect")
    assert message == "must have at most 11 characters"
    rules["aspect"] = "12345:12345"
    costume[key + "a"] = costume.pop(key)
    message = refusal(post(client, payload), "schema.invalid", f"/recipe/cast/team_costumes/yellowbirds/{key}a")
    assert message.endswith("must have at most 64 characters")


@pytest.mark.parametrize("append", [False, True], ids=["create", "append"])
def test_api_bounds_canonical_utf8_bytes(catalog, append):
    client, _, _ = catalog
    payload = wide()
    recipe = payload["recipe"]
    recipe["notes"] = ["é" * 500] * 32
    recipe["cast"]["rules"] = ["é" * 500] * 31
    style = recipe["voice"]["style"] = ["x" * 1000, ""]
    remainder = 65_536 - len(canonical_json(recipe))
    assert 0 < remainder < 1000
    style[1] = "x" * remainder
    assert len(canonical_json(recipe)) == 65_536
    path = f"/v1/formats/{payload['id']}/versions" if append else "/v1/formats"
    body = recipe if append else payload
    # Escaped Unicode and formatting increase the wire size, which is a separate limit.
    reply = client.post(path, content=json.dumps(body, indent=2), headers={"Content-Type": "application/json"})
    assert reply.status_code == 201, reply.text
    style[1] += "x"
    assert len(canonical_json(recipe)) == 65_537
    refusal(post(client, payload, append=append), "format.recipe_too_large", "" if append else "/recipe")


def test_worker_cannot_read_any_catalog_route(catalog):
    client, conn, worker = catalog
    result = post(client, wide()).json()
    for path in ("/v1/formats", f"/v1/formats/{result['format_id']}/versions",
                 f"/v1/format-versions/{result['id']}"):
        response = client.get(path, headers={"Authorization": worker})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "auth.required"
    conn.execute.assert_called_once()


def test_mcp_has_no_format_write_tool_for_writer_key(catalog):
    client, _, _ = catalog
    authorization = client.headers["Authorization"]
    scopes = client.get("/v1/me").json()["production_scopes"]
    assert list(scopes.values()) == [["formats:write", "read"]]
    assert post(client, wide()).status_code == 201

    async def scenario():
        mcp = create_app(API_URL, api_transport=httpx.ASGITransport(app=client.app))
        async with mcp.router.lifespan_context(mcp), connect(mcp, authorization) as session:
            tools = {tool.name: tool for tool in (await session.list_tools()).tools if "format" in tool.name}
            assert set(tools) == {"studio_list_formats", "studio_list_format_versions", "studio_get_format_version"}
            assert all(tool.annotations.readOnlyHint for tool in tools.values())
            for name in ("studio_create_format", "studio_add_format_version"):
                assert (await fail(session, name))["code"] == "tool.not_found"

    asyncio.run(scenario())
