"""Visibility declaration writes through the public draft transports."""

import asyncio

import httpx
import pytest

from haynes_studio.mcp.server import create_app as create_mcp
from tests.mcp.client import API_URL, call, connect, fail

from .test_studio_api import (
    client, engine, new_production, new_story, owner_engine, register_agent, runtime_db, runtime_role,
    service, sign_in,
)

pytestmark = pytest.mark.db
LEGACY_LAYOUT = {"preset": "default", "foreground": False}
POSES = [{"key": "still", "frame": 0}]


@pytest.mark.parametrize("create", [True, False], ids=["create", "replace"])
@pytest.mark.parametrize("actor", ["person", "agent-http", "agent-mcp"])
def test_board_write_refuses_poses_and_omits_empty_values(service, owner_engine, create, actor):
    app, _, issuer = service
    browser = client(app)
    csrf = sign_in(browser, issuer)
    production = new_production(browser, csrf)
    story = new_story(browser, csrf, production)
    story_path = f"/v1/stories/{story}"
    collection = f"{story_path}/boards"
    auth, writer = csrf, browser
    if actor != "person":
        _, auth = register_agent(owner_engine, {production: ["read", "draft:write"]})
        writer = client(app)
    if create:
        path = collection
        revision = 1
    else:
        # Create with the same actor so any refusal comes from the field rule.
        added = writer.post(collection, headers={**auth, "If-Match": "1"}, json={})
        assert added.status_code == 201, added.text
        board = added.json()["id"]
        path = f"/v1/boards/{board}"
        revision = 1

    if actor == "agent-mcp":
        async def through_mcp():
            mcp = create_mcp(API_URL, api_transport=httpx.ASGITransport(app=app))
            async with mcp.router.lifespan_context(mcp), connect(mcp, auth["Authorization"]) as session:
                tool, resource, payload = (
                    ("studio_add_board", {"story_id": story}, "fields") if create else
                    ("studio_patch_board", {"board_id": board}, "patch")
                )
                args = {**resource, "revision": revision}
                error = await fail(session, tool, **args, **{
                    payload: {"layout": {**LEGACY_LAYOUT, "check_poses": POSES}},
                })
                assert error["code"] == "occlusion.check_unavailable"
                for empty in ([], None):
                    saved = await call(session, tool, **args, **{
                        payload: {"layout": {**LEGACY_LAYOUT, "check_poses": empty}},
                    })
                    assert writer.get(f"/v1/boards/{saved['id']}", headers=auth).json()["layout"] == LEGACY_LAYOUT
                    args["revision"] += 1

        asyncio.run(through_mcp())
    else:
        request = writer.post if create else writer.patch
        headers = {**auth, "If-Match": str(revision)}
        denied = request(path, headers=headers, json={"layout": {**LEGACY_LAYOUT, "check_poses": POSES}})
        assert denied.status_code == 422, denied.text
        error = denied.json()["error"]
        assert error["code"] == "occlusion.check_unavailable"
        assert error["path"].endswith("/layout/check_poses")
        for empty in (None, []):
            saved = request(path, headers=headers, json={"layout": {**LEGACY_LAYOUT, "check_poses": empty}})
            assert saved.status_code == (201 if create else 200), saved.text
            held = writer.get(f"/v1/boards/{saved.json()['id']}", headers=auth)
            assert held.json()["layout"] == LEGACY_LAYOUT
            revision += 1
            headers["If-Match"] = str(revision)
