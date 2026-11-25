"""Format authoring, draft pins and immutable queued recipes via the runtime role."""

import hashlib
import io
import json
import socket
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
import sqlalchemy as sa
from PIL import Image

from haynes_studio.canonical.ids import Minter
from haynes_studio.canonical.model import Board, Story
from haynes_studio.db import drafts
from haynes_studio.db.catalog import record_asset_version
from haynes_studio.db.schema import format_versions, stories
from haynes_studio.formats.recipe import recipe_hash
from haynes_studio.library import Library
from haynes_studio.photo.plan import plan_photo
from haynes_studio.queue.worker import BuildWorker
from tests.canonical.fixtures import example
from tests.formats.fixtures import doll_short, wide

from .test_run_queue import queue, queue_run, worker_api, worker_credentials
from .test_studio_api import (
    bearer, client, engine, owner_engine, register_agent, runtime_db, runtime_role, service,
)
from .test_studio_mcp import admin, issue

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def no_platform_network(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Format operations attempted an external connection")

    monkeypatch.setattr(socket, "create_connection", unexpected)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", unexpected)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", unexpected)


def create_format(q, payload, headers=None):
    response = q.browser.post("/v1/formats", headers=q.csrf if headers is None else headers, json=payload)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["number"] == 1
    assert result["format_id"] == payload["id"]
    assert result["sha256"] == recipe_hash(payload["recipe"])
    assert response.headers["location"] == f'/v1/format-versions/{result["id"]}'
    return result


def pin(q, version, *, revision=3, headers=None):
    return q.browser.patch(f"/v1/stories/{q.story_id}", json={"format_version_id": version},
                           headers={**(q.csrf if headers is None else headers), "If-Match": str(revision)})


def frozen_json(q, run):
    with q.store.open(run["snapshot"]["locator"]) as handle:
        data = handle.read()
    assert hashlib.sha256(data).hexdigest() == run["snapshot"]["sha256"]
    return json.loads(data)


def test_real_recipe_version_and_story_revision_are_frozen(queue):
    q = queue
    payload = doll_short()
    first = create_format(q, payload)
    _, agent = register_agent(q.owner, {q.production_id: ["read", "draft:write", "runs:queue"]})
    assert pin(q, first["id"], revision=2, headers=agent).status_code == 409
    unknown = pin(q, Minter().mint("fmv"), headers=agent)
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "ref.unknown"
    pinned = pin(q, first["id"], headers=agent)
    assert pinned.status_code == 200 and pinned.json()["revision"] == 4
    with q.engine.connect() as conn:
        assert conn.scalar(sa.select(stories.c.format_version_id).where(stories.c.id == q.story_id)) == first["id"]
    timing = q.browser.get(f"/v1/stories/{q.story_id}/timing", headers=agent).json()
    assert timing["format_length"] == {"format_version_id": first["id"], **first["recipe"]["length"]}
    queued = queue_run(q, "first-format", rev=4, headers=agent)
    assert queued.status_code == 201, queued.text

    revised = doll_short()["recipe"]
    revised["notes"].append("A future cut may use a different recording.")
    revised["length"]["max_ms"] += 1000
    version_path = f'/v1/formats/{payload["id"]}/versions'
    response = q.browser.post(version_path, json=revised, headers=q.csrf)
    assert response.status_code == 201, response.text
    second = response.json()
    assert second["number"] == 2 and second["id"] != first["id"]
    assert second["sha256"] != first["sha256"]
    assert q.browser.get(f'/v1/format-versions/{first["id"]}', headers=agent).json() == first
    page = q.browser.get(version_path, headers=agent, params={"limit": 1}).json()
    assert len(page["items"]) == 1
    rest = q.browser.get(version_path, headers=agent, params={"cursor": page["next_cursor"]}).json()
    assert {item["id"] for item in page["items"] + rest["items"]} == {first["id"], second["id"]}
    assert rest["next_cursor"] is None
    assert pin(q, second["id"], revision=4, headers=agent).status_code == 200

    expected_pin = {name: first[name] for name in ("id", "sha256", "recipe")}
    frozen = frozen_json(q, queued.json())
    assert frozen["story"]["format_version_id"] == first["id"]
    assert frozen["format_version"] == expected_pin
    claim = worker_api(q).claim()
    assert claim.body["snapshot"] == frozen
    worker = BuildWorker(None, None, store=q.store, stage_root=q.stage_root, register={}, tracker_story="447",
                         transcriber=None, studio=q.app.state.build_revision)
    assert worker._inputs(claim).format_version == expected_pin
    assert pin(q, None, revision=5, headers=agent).status_code == 200


def test_writer_scope_is_explicit_and_workers_can_only_read_the_catalog(queue, admin, tmp_path):
    q = queue
    _, reader = register_agent(q.owner, {q.production_id: ["read", "draft:write"]})
    _, scoped = register_agent(q.owner, {q.production_id: ["draft:write"]})
    worker = worker_credentials(q.owner)
    writer = issue(admin, tmp_path / "format-key", q.production_id, "read", "formats:write")
    writer_headers = bearer(writer["key"])
    format_ = wide()
    format_["id"] = "scoped-format"
    result = create_format(q, format_, writer_headers)
    add_path = f'/v1/formats/{format_["id"]}/versions'
    read_path = f'/v1/format-versions/{result["id"]}'
    anonymous = client(q.app)
    for headers, expected in ((reader, 403), (worker, 403), ({}, 401)):
        assert anonymous.post("/v1/formats", json=format_, headers=headers).status_code == expected
        assert anonymous.post(add_path, json=format_["recipe"], headers=headers).status_code == expected
    assert anonymous.get(read_path).status_code == 401
    assert anonymous.get(read_path, headers=scoped).status_code == 403
    assert anonymous.get(read_path, headers=reader).json() == result
    assert anonymous.get(read_path, headers=worker).json() == result
    assert anonymous.get("/v1/me", headers=worker).status_code == 401
    assert anonymous.post(add_path, json=format_["recipe"], headers=writer_headers).status_code == 201
    failure = admin("create", "--out", str(tmp_path / "ungrantable"), "--production", q.production_id,
                    "--scope", "go_live:approve", expect=1)
    assert failure == "key_admin.invalid_scope"
    assert not (tmp_path / "ungrantable").exists()


def test_wide_format_length_and_target_maximum_do_not_block_queueing(queue):
    q = queue
    payload = wide()
    target = doll_short()["recipe"]["targets"][0]
    target["rules"].update(max_length_ms=200, aspect="16:9")
    payload["recipe"]["targets"] = [target]
    version = create_format(q, payload)
    wrong_kind = pin(q, version["id"])
    assert wrong_kind.status_code == 422 and wrong_kind.json()["error"]["code"] == "format.frame_mismatch"

    production_path = f"/v1/productions/{q.production_id}"
    response = q.browser.put(f"{production_path}/media-types/video", headers={**q.csrf, "If-Match": "2"})
    assert response.status_code == 200, response.text
    response = q.browser.post(f"{production_path}/media-types/video/stories", headers=q.csrf,
                              json={"title": "Wide fixture", "format_version_id": version["id"]})
    assert response.status_code == 201, response.text
    story_id = response.json()["id"]
    story_path = f"/v1/stories/{story_id}"
    response = q.browser.post(f"{story_path}/boards", headers={**q.csrf, "If-Match": "1"},
                              json={"timing": {"lead_ms": None, "tail_ms": None, "hold_ms": 500},
                                    "seeds": {"i2v:frame": 5}})
    assert response.status_code == 201, response.text
    board = response.json()
    assert board["method"] == {"layer": "whole_frame", "motion": "i2v"}

    photo_bytes = io.BytesIO()
    Image.new("RGB", (256, 144), "green").save(photo_bytes, format="PNG")
    blob = q.store.publish(photo_bytes.getvalue(), scope=q.production_id, media_type="image/png")
    photo = example("valid/asset-version-photo-external.json")
    photo.update(id=Minter().mint("asv"), asset_id=Minter().mint("ast"),
                 scope={"production_id": q.production_id, "story_id": story_id, "board_id": board["id"]})
    photo["content"].update(sha256=blob.sha256, bytes=blob.bytes, locator=blob.locator, width=256, height=144)
    generator = photo["provenance"]["generator"]
    generator["source_asset_version_ids"] = []
    photo_fields = {"current_version_id": None, "prompt": "wide fixture", "input_asset_version_ids": []}
    with q.engine.begin() as conn:
        exchange = drafts.get_draft(conn, story_id).exchange()
        planned = Board.from_document({**board, "photo": photo_fields})
        generator.setdefault("params", {})["input_signature"] = plan_photo(
            Story.from_document(exchange), planned, Library(),
        ).input_signature
        record_asset_version(conn, photo)
    response = q.browser.patch(f'/v1/boards/{board["id"]}', headers={**q.csrf, "If-Match": "1"},
                               json={"photo": {**photo_fields, "current_version_id": photo["id"]}})
    assert response.status_code == 200, response.text

    estimate = q.browser.get(f"{story_path}/estimate").json()
    [warning] = estimate["warnings"]
    assert warning["code"] == "format.length_exceeded" and warning["build_allowed"]
    assert estimate["problems"] == []
    timing = q.browser.get(f"{story_path}/timing").json()
    assert timing["warnings"] == [warning] and timing["build_allowed"]
    summary = q.browser.get(story_path).json()
    assert summary["derived"]["warnings"] == [warning]
    queued = q.browser.post(f"{story_path}/runs",
                            headers={**q.csrf, "If-Match": "3", "Idempotency-Key": "wide-over-limit"})
    assert queued.status_code == 201, queued.text
    assert frozen_json(q, queued.json())["format_version"]["recipe"] == payload["recipe"]


def test_invalid_recipe_and_out_of_recipe_board_keep_existing_error_codes(queue):
    q = queue
    payload = doll_short()
    payload["id"] = "recipe-without-ambient"
    payload["recipe"]["shot_types"]["speaking"][0]["layer"] = "whole_frame"
    refused = q.browser.post("/v1/formats", headers=q.csrf, json=payload)
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "method.unavailable"
    payload["recipe"]["shot_types"]["speaking"][0]["layer"] = "layered"
    target = payload["recipe"]["targets"][0]
    target["account_id"] = "placeholder-cannot-have-id"
    refused = q.browser.post("/v1/formats", headers=q.csrf, json=payload)
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "format.target_invalid"
    assert refused.json()["error"]["path"] == "/recipe/targets/0/account_id"
    target["account_id"] = None
    del payload["recipe"]["shot_types"]["ambient"]
    version = create_format(q, payload)
    assert pin(q, version["id"]).status_code == 200
    estimate = q.browser.get(f"/v1/stories/{q.story_id}/estimate").json()
    [problem] = estimate["problems"]
    assert (problem["rule"], problem["status"], problem["board_id"]) == (
        "method.unavailable", "unavailable", q.board_id,
    )
    refused = queue_run(q, "unavailable-format", rev=4)
    error = refused.json()["error"]
    assert (refused.status_code, error["code"], error["status"]) == (422, "method.unavailable", "unavailable")


def test_concurrent_appends_allocate_distinct_version_numbers(queue):
    q = queue
    payload = doll_short()
    payload["id"] = "concurrent-format"
    version = create_format(q, payload)
    path = f'/v1/formats/{version["format_id"]}/versions'

    def append():
        reply = q.browser.post(path, headers=q.csrf, json=payload["recipe"])
        assert reply.status_code == 201, reply.text
        return reply.json()["number"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(append), pool.submit(append)
        assert {first.result(), second.result()} == {2, 3}


def test_legacy_reserved_pin_can_be_read_and_explicitly_cleared(queue):
    q = queue
    story_path = f"/v1/stories/{q.story_id}"
    reserved = Minter().mint("fmv")
    with q.owner.begin() as conn:
        query = stories.c.id == q.story_id
        doc = conn.scalar(sa.select(stories.c.document).where(query))
        conn.execute(stories.update().where(query).values(document={**doc, "format_version_id": reserved}))

    assert q.browser.get(story_path).json()["format_version_id"] == reserved
    edited = q.browser.patch(story_path, json={"title": "Legacy format pin"},
                             headers={**q.csrf, "If-Match": "3"})
    assert edited.status_code == 200 and edited.json()["format_version_id"] == reserved
    refused = queue_run(q, "unresolved-pin", rev=4)
    assert refused.status_code == 422 and refused.json()["error"]["path"] == "/format_version_id"
    cleared = pin(q, None, revision=4)
    assert cleared.status_code == 200 and cleared.json()["format_version_id"] is None


def test_format_runtime_grants_keep_recipe_rows_append_only(engine):
    privileges = sa.text("""
        SELECT has_table_privilege('formats', 'SELECT'), has_table_privilege('formats', 'INSERT'),
               has_table_privilege('formats', 'UPDATE'), has_table_privilege('formats', 'DELETE'),
               has_table_privilege('format_versions', 'SELECT'), has_table_privilege('format_versions', 'INSERT'),
               has_table_privilege('format_versions', 'UPDATE'), has_table_privilege('format_versions', 'DELETE'),
               has_column_privilege('stories', 'format_version_id', 'UPDATE'),
               has_column_privilege('stories', 'production_id', 'UPDATE')
    """)
    with engine.connect() as conn:
        assert tuple(conn.execute(privileges).one()) == (
            True, True, False, False, True, True, False, False, True, False,
        )
