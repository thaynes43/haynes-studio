"""Media job and upload acceptance through the real HTTP and MCP adapters."""

import asyncio
import base64
import json
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace

import httpx
import psycopg
import pytest
import sqlalchemy as sa
from PIL import Image

from haynes_studio.adapters.comfyui import ImageClient
from haynes_studio.adapters.errors import AdapterError
from haynes_studio.adapters.fakes import FakeComfyUI, FakeKokoro, FakeRunner
from haynes_studio.adapters.kokoro import KokoroClient
from haynes_studio.canonical.ids import Minter
from haynes_studio.db.catalog import record_asset_version
from haynes_studio.db.runs import database_time
from haynes_studio.db.schema import asset_promotions, asset_versions, boards, media_jobs, queue_lane_events, runs
from haynes_studio.drafting.declaration import READ_TOKEN_HEADER
from haynes_studio.library.model import version_document
from haynes_studio.mcp.server import MAX_UPLOAD_REQUEST_BYTES, create_app
from haynes_studio.photo_limits import DEFAULT_BODY_SECONDS, IDLE_SECONDS
from haynes_studio.photo.validation import MAX_UPLOAD_BYTES
from haynes_studio.queue.media_worker import Dispatch, MediaWorker
from haynes_studio.queue.wan import product_request
from haynes_studio.queue.worker import ActiveClaim
from haynes_studio.queue.worker_api import WorkerAPIError
from haynes_studio.store import blob_locator
from haynes_studio.voice.model import Job

from tests.db.test_run_queue import (
    queue, queue_run, request_for, worker_api, worker_credentials,
)
from tests.db.test_studio_api import (
    client, engine, new_production, new_story, owner_engine, register_agent,
    runtime_db, runtime_role, service, sign_in,
)
from tests.build_story.fixtures import example
from tests.library.fixtures import register, winter_menu
from tests.mcp.client import API_URL, UPLOAD_URL, call, connect, fail

pytestmark = pytest.mark.db
PROVENANCE = {
    "model": "fixture/illustrator", "prompt": "An invented workshop", "session": "fixture-session",
    "harness": "fixture", "source_asset_version_ids": [], "paid_api": False,
}


def success(response, code=200):
    assert response.status_code == code, response.text
    return response.json()


@pytest.fixture
def studio(service, owner_engine):
    app, store, issuer = service
    with owner_engine.begin() as conn:
        conn.exec_driver_sql("TRUNCATE media_jobs, queue_lane_events")
        conn.exec_driver_sql("UPDATE media_job_lanes SET next_position = 1")
    browser = client(app)
    csrf = sign_in(browser, issuer)
    production_id = new_production(browser, csrf)
    story_id = new_story(browser, csrf, production_id)
    other = new_production(browser, csrf)
    _, agent = register_agent(owner_engine, {
        production_id: ["read", "assets:generate", "assets:upload", "draft:write", "runs:queue"],
    })
    _, reader = register_agent(owner_engine, {production_id: ["read"]})
    _, outsider = register_agent(owner_engine, {other: ["read", "assets:generate", "assets:upload"]})
    return SimpleNamespace(app=app, store=store, owner=owner_engine, browser=browser, agent=client(app),
                           csrf=csrf, auth=agent, reader=reader, outsider=outsider,
                           production_id=production_id, story_id=story_id)


def board_in(s, *, spoken=False, by_human=False, draft_application=None):
    if spoken:
        library = winter_menu().library
        stock = next(v for v in library.versions.values() if v.kind == "voice")
        stock_doc = version_document(stock, library.asset_of(stock.id))
        with s.owner.begin() as conn:
            record_asset_version(conn, stock_doc)
        current = success(s.browser.get(f"/v1/stories/{s.story_id}"))
        success(s.browser.patch(f"/v1/stories/{s.story_id}",
                                headers={**s.csrf, "If-Match": str(current["revision"])},
                                json={"cast": [{"slot": "a", "name": "A doll", "voice_version_id": stock.id}]}))
    current = success(s.browser.get(f"/v1/stories/{s.story_id}"))
    values = {
        "photo": {"current_version_id": None, "prompt": "A small workshop", "input_asset_version_ids": []},
        "timing": {"lead_ms": None, "tail_ms": None, "hold_ms": 500},
    }
    if spoken:
        values.update(
            lines=[{"speaker": "a", "text": "The kettle is on.", "gap_before_ms": None}],
            timing={"lead_ms": 0, "tail_ms": 750, "hold_ms": None},
            voice={"style": "cast", "current_version_id": None},
        )
    if draft_application is not None:
        values["draft_application"] = draft_application
    browser, credentials = (s.browser, s.csrf) if by_human else (s.agent, s.auth)
    doc = success(browser.post(f"/v1/stories/{s.story_id}/boards", json=values,
                               headers={**credentials, "If-Match": str(current["revision"])}), 201)
    return doc["id"]


def operation(s, board, kind, key, *, headers=None, body=None):
    return s.agent.post(f"/v1/boards/{board}/{kind}-jobs", json={} if body is None else body,
                        headers={**(s.auth if headers is None else headers), "Idempotency-Key": key})


def job(s, id_):
    return success(s.browser.get(f"/v1/jobs/{id_}"))


def current_board(s, board):
    return success(s.browser.get(f"/v1/boards/{board}"))


def patch(s, board, payload, *, by_human=True):
    browser, credentials = (s.browser, s.csrf) if by_human else (s.agent, s.auth)
    return success(browser.patch(f"/v1/boards/{board}", json=payload, headers={
        **credentials, "If-Match": str(current_board(s, board)["revision"]),
    }))


def image_worker(s, fake=None, *, pause=None):
    runner = FakeRunner(fake or FakeComfyUI())
    options = {} if pause is None else {"pause": pause}
    worker = MediaWorker(worker_api(s, lane="image"), lane="image", store=s.store, client=ImageClient(runner),
                         licences=register(), **options)
    return worker, runner


def speech_worker(s, fake):
    runner = FakeRunner(fake)
    return MediaWorker(worker_api(s, lane="voice"), lane="voice", store=s.store, client=KokoroClient(runner),
                       licences=register())


def image_file(tmp_path, *, animated=False):
    path = tmp_path / ("animated.png" if animated else "photo.png")
    with Image.new("RGB", (12, 18), "white") as first, Image.new("RGB", (12, 18), "black") as second:
        if animated:
            first.save(path, save_all=True, append_images=[second], duration=100, loop=0)
        else:
            first.save(path)
    return path.read_bytes()


def upload(s, board, data, declaration=PROVENANCE, *, headers=None, media_type="image/png", extra=None):
    metadata = {} if declaration is None else {"X-Studio-Photo-Provenance": json.dumps(declaration)}
    return s.agent.post(f"/v1/boards/{board}/photo-versions", content=data, headers={
        **(s.auth if headers is None else headers), **metadata, **(extra or {}),
        "If-Match": str(current_board(s, board)["revision"]), "Content-Type": media_type,
    })


def test_photo_candidate_preview_and_promotion(studio):
    s = studio
    board = board_in(s)
    human = {**s.csrf, "Idempotency-Key": "fixture-asset"}
    payload = {"kind": "cast", "name": "Workshop doll", "prompt": "A doll against a plain wall"}
    forbidden = s.agent.post("/v1/asset-jobs", headers={**s.auth, "Idempotency-Key": "same"}, json=payload)
    assert forbidden.status_code == 403
    candidate = success(s.browser.post("/v1/asset-jobs", headers=human, json=payload), 202)
    assert success(s.browser.post("/v1/asset-jobs", headers=human, json=payload))["id"] == candidate["id"]
    changed = s.browser.post("/v1/asset-jobs", headers=human, json={**payload, "seed": 1})
    assert changed.status_code == 422 and changed.json()["error"]["code"] == "idempotency.mismatch"

    fake = FakeComfyUI(running=1)
    waits = []

    def empty_queue(seconds):
        assert not fake.payloads
        waits.append(seconds)
        fake.running = 0

    worker, runner = image_worker(s, fake, pause=empty_queue)
    assert worker.tick()
    assert waits == [10]
    assert len(fake.payloads) == 1 and len(runner.calls) == 3
    assert job(s, candidate["id"])["status"] == "succeeded"
    result = success(s.browser.get(f'/v1/jobs/{candidate["id"]}/result'))
    assert result["state"] == "candidate" and result["scope"]["production_id"] is None
    digest, version = result["content"]["sha256"], result["id"]
    assert s.browser.get(f"/v1/media/{digest}").status_code == 404
    url = f'/v1/jobs/{candidate["id"]}/media/{digest}'
    partial = s.browser.get(url, headers={"Range": "bytes=0-7"})
    assert partial.status_code == 206 and partial.content == b"\x89PNG\r\n\x1a\n"
    ranged_head = s.browser.head(f"/v1/asset-versions/{version}/media/{digest}",
                                 headers={"Range": "bytes=-4"})
    assert ranged_head.status_code == 206 and ranged_head.content == b""
    assert ranged_head.headers["content-length"] == "4"
    unknown = s.browser.get(f"/v1/asset-versions/{Minter().mint('asv')}/media/{digest}")
    denied = s.agent.get(url, headers=s.auth)
    assert unknown.status_code == denied.status_code == 404
    assert unknown.json()["error"]["code"] == denied.json()["error"]["code"] == "not_found"
    assert s.agent.get(f'/v1/jobs/{candidate["id"]}', headers=s.auth).status_code == 404
    assert s.agent.post(f"/v1/asset-versions/{version}/promote", headers=s.auth).status_code == 403
    promoted = success(s.browser.post(f"/v1/asset-versions/{version}/promote", headers=s.csrf))
    assert promoted["id"] == version and promoted["state"] == "promoted"
    assert s.browser.get(url).status_code == 200

    patch(s, board, {"photo": {"current_version_id": None, "prompt": "A closer view",
                               "input_asset_version_ids": [version]}}, by_human=False)
    first = operation(s, board, "photo", "photo-1", body={"seed": 17})
    queued = success(first, 202)
    assert first.headers["location"] == f'/v1/jobs/{queued["id"]}'
    assert queued["schema"] == "studio.job/v1" and queued["status"] == "queued"
    assert current_board(s, board)["derived"]["photo_state"] == "generating"
    assert success(operation(s, board, "photo", "photo-1", body={"seed": 17})) == queued
    assert operation(s, board, "photo", "photo-1", body={"seed": 18}).status_code == 422
    assert operation(s, board, "photo", "denied", headers=s.reader).status_code == 403
    assert operation(s, board, "photo", "other", headers=s.outsider).status_code == 403
    assert s.agent.get(f'/v1/jobs/{queued["id"]}', headers=s.outsider).status_code == 404
    assert worker.tick()
    assert fake.payloads[-1]["upload"]["name"].startswith("studio-")
    finished = job(s, queued["id"])
    assert finished["status"] == "succeeded" and finished["result_is_current"]
    assert current_board(s, board)["photo"]["current_version_id"] == finished["result_version_id"]
    versions = success(s.agent.get(f"/v1/boards/{board}/photo-versions", headers=s.auth))["items"]
    assert versions[0]["provenance"]["generator"]["seed"] == 17
    assert s.agent.get(f'/v1/media/{versions[0]["content"]["sha256"]}', headers=s.auth).status_code == 200
    assert success(s.agent.get(f"/v1/boards/{board}/jobs", headers=s.auth))["items"][0]["status"] == "succeeded"


def test_draft_edit_retains_photo_and_voice_and_failed_engine(studio):
    s = studio
    board = board_in(s, spoken=True)
    fake = FakeKokoro()
    voice = speech_worker(s, fake)
    first = success(operation(s, board, "voice", "voice-1"), 202)
    assert voice.tick()
    finished = job(s, first["id"])
    assert finished["status"] == "succeeded" and finished["result_is_current"]
    assert len(fake.requests) == 1 and fake.requests[0]["text"] == "The kettle is on."
    assert current_board(s, board)["voice"]["current_version_id"] == finished["result_version_id"]

    voice_id = success(operation(s, board, "voice", "voice-2"), 202)["id"]
    photo_id = success(operation(s, board, "photo", "photo-2"), 202)["id"]
    board_doc = current_board(s, board)
    line = {**board_doc["lines"][0], "text": "Keep the door closed."}
    patch(s, board, {"lines": [line], "photo": {**board_doc["photo"], "prompt": "A different view"}})
    image_fake = FakeComfyUI()
    image, _ = image_worker(s, image_fake)
    assert voice.tick() and image.tick()
    assert len(fake.requests) == 1  # the worker reuses the frozen take and track
    assert any(node["inputs"].get("prompt") == "A small workshop"
               for node in image_fake.payloads[0]["graph"].values())
    for job_id in (voice_id, photo_id):
        stale = job(s, job_id)
        assert stale["status"] == "succeeded" and stale["result_is_current"] is False
        assert stale["result_version_id"] is not None
    assert current_board(s, board)["photo"]["current_version_id"] is None
    result = success(s.browser.get(f"/v1/jobs/{photo_id}/result"))
    digest = result["content"]["sha256"]
    assert s.agent.get(f"/v1/media/{digest}", headers=s.auth).status_code == 404
    assert s.browser.get(f"/v1/asset-versions/{result['id']}/media/{digest}").status_code == 200

    failing = FakeKokoro()

    class FailedSpeech(KokoroClient):
        def synthesize(self, request):
            super().synthesize(request)
            raise AdapterError("adapter.command_failed", "kokoro", "fixture failure")

    bad = MediaWorker(worker_api(s, lane="voice"), lane="voice", store=s.store,
                      client=FailedSpeech(FakeRunner(failing)))
    failed_id = success(operation(s, board, "voice", "voice-fail"), 202)["id"]
    assert bad.tick()
    failed = job(s, failed_id)
    assert failed["status"] == "failed" and failed["error"]["code"] == "adapter.command_failed"
    assert failed["created_by"]["kind"] == "agent" and failed["voice"]["lines"][0]["text"] == line["text"]
    assert failing.requests == [{"voice": fake.requests[0]["voice"], "text": line["text"]}]


@pytest.mark.parametrize(("case", "status", "code"), [
    ("oversize", 413, "photo.too_large"), ("corrupt", 422, "photo.image_invalid"),
    ("animated", 422, "photo.image_invalid"), ("wrong-mime", 422, "photo.image_invalid"),
    ("missing", 422, "prov.external_incomplete"), ("paid", 422, "prov.external_incomplete"),
    ("false-claim", 422, "prov.external_incomplete"), ("hash", 422, "photo.hash_mismatch"),
    ("source-traversal", 422, "prov.external_incomplete"), ("name-traversal", 422, "prov.external_incomplete"),
    ("filename", 422, "prov.external_incomplete"), ("other-production", 403, "auth.forbidden"),
    ("no-scope", 403, "auth.forbidden"),
])
def test_upload_refusals(studio, tmp_path, case, status, code):
    s = studio
    board = board_in(s)
    data = image_file(tmp_path, animated=case == "animated")
    metadata, options = dict(PROVENANCE), {}
    if case == "oversize":
        data = b"x" * (MAX_UPLOAD_BYTES + 1)
    elif case == "corrupt":
        data = b"not an image"
    elif case == "wrong-mime":
        options["media_type"] = "image/jpeg"
    elif case == "missing":
        metadata = None
    elif case == "paid":
        metadata["paid_api"] = True
    elif case == "false-claim":
        metadata["server_computed_sha256"] = True
    elif case == "hash":
        metadata["upload_sha256"] = "0" * 64
    elif case == "source-traversal":
        metadata["source_asset_version_ids"] = ["../../fixture"]
    elif case == "name-traversal":
        metadata["harness"] = "runner/../fixture"
    elif case == "filename":
        options["extra"] = {"Content-Disposition": 'attachment; filename="../../image.png"'}
    elif case == "other-production":
        options["headers"] = s.outsider
    elif case == "no-scope":
        options["headers"] = s.reader
    response = upload(s, board, data, metadata, **options)
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
    assert success(s.browser.get(f"/v1/boards/{board}/photo-versions"))["items"] == []


@pytest.mark.parametrize("size", [16, MAX_UPLOAD_BYTES + 1], ids=["small", "oversized"])
def test_anonymous_upload_does_not_read_the_body(studio, size):
    s = studio
    board = board_in(s)

    async def scenario():
        read = False

        async def body():
            nonlocal read
            read = True
            yield b"x" * size

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=s.app),
                                     base_url="https://studio.example.invalid") as http:
            response = await http.post(f"/v1/boards/{board}/photo-versions", content=body(), headers={
                "If-Match": "1", "Content-Type": "image/png", "Content-Length": str(size),
                "X-Studio-Photo-Provenance": json.dumps(PROVENANCE),
            })
        assert response.status_code == 401 and response.json()["error"]["code"] == "auth.required"
        assert not read

    asyncio.run(scenario())


def upload_transport(s, board, data, transport):
    if transport == "api":
        return (s.app, f"https://studio.example.invalid/v1/boards/{board}/photo-versions",
                {**s.auth, "If-Match": "1", "Content-Type": "image/png",
                 "X-Studio-Photo-Provenance": json.dumps(PROVENANCE)}, data)
    app = create_app(API_URL, api_transport=httpx.ASGITransport(app=s.app))
    envelope = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "studio_upload_photo", "arguments": {
            "data_base64": base64.b64encode(data).decode("ascii"), "board_id": board,
            "revision": 1, "media_type": "image/png", "provenance": PROVENANCE,
        },
    }}
    return (app, UPLOAD_URL, {**s.auth, "Content-Type": "application/json",
                            "Accept": "application/json, text/event-stream"},
            json.dumps(envelope).encode("ascii"))


def assert_upload_accepted(response, transport):
    if transport == "api":
        assert success(response, 201)["selected"]
    else:
        assert success(response)["result"]["structuredContent"]["selected"]


@pytest.mark.parametrize("transport", ["api", "mcp"])
def test_concurrent_upload_is_refused_before_reading_its_body(studio, tmp_path, transport):
    s = studio
    board = board_in(s)

    async def scenario(app, url, headers, payload):
        first_read = asyncio.Event()
        finish = asyncio.Event()
        second_read = False

        async def first_body():
            first_read.set()
            await finish.wait()
            yield payload

        async def second_body():
            nonlocal second_read
            second_read = True
            yield payload

        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
        ) as http:
            first = asyncio.create_task(http.post(url, headers=headers, content=first_body()))
            try:
                await first_read.wait()
                busy = await http.post(url, headers=headers, content=second_body())
            finally:
                finish.set()
                accepted = await first
            assert busy.status_code == 503 and busy.json()["error"]["code"] == "photo.upload_busy"
            assert busy.headers["retry-after"] == "1" and not second_read
            assert_upload_accepted(accepted, transport)
            retry = await http.post(url, headers=headers, content=payload)
            # The revision already moved, so the retry gets a normal API conflict.
            if transport == "api":
                assert retry.status_code == 409
            else:
                assert retry.json()["result"]["structuredContent"]["error"]["http_status"] == 409

    asyncio.run(scenario(*upload_transport(s, board, image_file(tmp_path), transport)))


async def post_stream(app, url, headers, receive, messages):
    request = httpx.Request("POST", url, headers=headers)
    scope = {"type": "http", "http_version": "1.1", "method": "POST", "scheme": request.url.scheme,
             "path": request.url.path, "query_string": b"",
             "headers": [(key.lower(), value) for key, value in request.headers.raw]}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)


@pytest.mark.parametrize("transport", ["api", "mcp"])
@pytest.mark.parametrize("failure", ["trickle", "buffered", "stall", "disconnect", "size", "exception"])
def test_interrupted_upload_releases_slot(studio, tmp_path, monkeypatch, transport, failure):
    s = studio
    board = board_in(s)
    data = image_file(tmp_path)

    async def scenario(app, url, headers, payload):
        loop = asyncio.get_running_loop()
        real_time = loop.time
        offset = 0
        monkeypatch.setattr(loop, "time", lambda: real_time() + offset)

        def tick(seconds):
            nonlocal offset
            offset += seconds

        async def advance(seconds):
            resumed = loop.create_future()

            def resume():
                if not resumed.done():
                    resumed.set_result(None)

            loop.call_at(loop.time() + seconds, resume)
            loop.call_soon(tick, seconds)
            await resumed

        reads = 0
        messages = []

        async def receive():
            nonlocal reads
            reads += 1
            if reads == 1:
                return {"type": "http.request", "body": payload[:1], "more_body": True}
            if failure in ("trickle", "buffered"):
                interval = IDLE_SECONDS - 1
                if reads <= DEFAULT_BODY_SECONDS // interval + 2:
                    if failure == "buffered":
                        tick(interval)
                    else:
                        await advance(interval)
                    return {"type": "http.request", "body": payload[reads - 1:reads], "more_body": True}
            elif failure == "stall":
                await advance(IDLE_SECONDS + 1)
            elif failure == "disconnect":
                return {"type": "http.disconnect"}
            elif failure == "size":
                if reads > 2:
                    pytest.fail("The route must refuse oversize bodies before reading another chunk")
                limit = MAX_UPLOAD_BYTES if transport == "api" else MAX_UPLOAD_REQUEST_BYTES
                return {"type": "http.request", "body": b"x" * limit, "more_body": True}
            else:
                raise RuntimeError("fixture receive failed")
            return {"type": "http.request", "body": payload[reads - 1:], "more_body": False}

        async with app.router.lifespan_context(app):
            if failure == "exception" and transport == "mcp":
                with pytest.raises(RuntimeError, match="fixture receive failed"):
                    await post_stream(app, url, headers, receive, messages)
            else:
                await post_stream(app, url, headers, receive, messages)
            if failure == "disconnect" and transport == "mcp":
                assert not messages
            else:
                expected = {"trickle": 408, "buffered": 408, "stall": 408,
                            "disconnect": 400, "size": 413, "exception": 500}
                assert messages[0]["status"] == expected[failure]
                if expected[failure] == 408:
                    assert json.loads(messages[1]["body"])["error"]["code"] == "photo.upload_timeout"
            assert reads >= 2
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                assert_upload_accepted(await http.post(url, headers=headers, content=payload), transport)

    asyncio.run(scenario(*upload_transport(s, board, data, transport)))
    versions = success(s.browser.get(f"/v1/boards/{board}/photo-versions"))["items"]
    assert len(versions) == 1


@pytest.mark.parametrize("transport", ["api", "mcp"])
def test_scope_refusal_never_acquires_upload_slot(studio, tmp_path, monkeypatch, transport):
    from haynes_studio.api import job_routes
    from haynes_studio.mcp import server

    s = studio
    board = board_in(s)
    module = job_routes if transport == "api" else server

    def unexpected_call(*args, **kwargs):
        pytest.fail("Scope refusal must precede upload slot acquisition and body reads")

    monkeypatch.setattr(module, "_upload_slot", SimpleNamespace(acquire=unexpected_call))

    async def scenario(app, url, headers, payload):
        messages = []
        async with app.router.lifespan_context(app):
            await post_stream(app, url, {**headers, **s.reader}, unexpected_call, messages)
        assert messages[0]["status"] == 403
        assert json.loads(messages[1]["body"])["error"]["code"] == "auth.forbidden"

    asyncio.run(scenario(*upload_transport(s, board, image_file(tmp_path), transport)))


def test_mcp_media_tools_and_upload_hash(studio, tmp_path):
    s = studio
    board = board_in(s, spoken=True)
    data = image_file(tmp_path)
    fake = FakeKokoro()
    voice_worker = speech_worker(s, fake)
    image, _ = image_worker(s)

    async def scenario():
        mcp = create_app(API_URL, api_transport=httpx.ASGITransport(app=s.app))
        async with mcp.router.lifespan_context(mcp), connect(mcp, s.auth["Authorization"]) as session, \
                connect(mcp, s.auth["Authorization"], url=UPLOAD_URL) as uploads:
            uploaded = await call(uploads, "studio_upload_photo", board_id=board, revision=1,
                                  media_type="image/png", data_base64=base64.b64encode(data).decode(),
                                  provenance={**PROVENANCE, "upload_sha256": sha256(data).hexdigest()})
            assert uploaded["selected"] and uploaded["board_revision"] == 2
            photo_id = uploaded["version"]["id"]
            result = success(s.browser.get(f"/v1/boards/{board}/photo-versions"))["items"][0]
            assert result["id"] == photo_id
            assert result["provenance"]["external"]["server_computed_sha256"]
            with s.owner.connect() as conn:
                assert conn.scalar(asset_versions.select().with_only_columns(asset_versions.c.received_sha256)
                                   .where(asset_versions.c.id == photo_id)) == sha256(data).hexdigest()
            voice = await call(session, "studio_generate_voice", board_id=board, idempotency_key="mcp-voice")
            assert voice["status"] == "queued"
            photo = await call(session, "studio_generate_photo", board_id=board, idempotency_key="mcp-photo",
                               seed=4)
            retry = await call(session, "studio_generate_photo", board_id=board, idempotency_key="mcp-photo",
                               seed=4)
            assert photo == retry
            refused = await fail(session, "studio_generate_photo", board_id=board, idempotency_key="mcp-photo",
                                 seed=5)
            assert refused["code"] == "idempotency.mismatch"
            assert voice_worker.tick() and image.tick()
            for pending in (voice, photo):
                done = await call(session, "studio_get_job", job_id=pending["id"])
                assert done["status"] == "succeeded" and done["result_is_current"]
            assert len(fake.requests) == 1

    asyncio.run(scenario())


def test_run_and_image_lanes_and_mcp_run_tools(queue):
    q = queue
    _, auth = register_agent(q.owner, {q.production_id: ["read", "runs:queue", "assets:generate"]})

    async def scenario():
        mcp = create_app(API_URL, api_transport=httpx.ASGITransport(app=q.app))
        async with mcp.router.lifespan_context(mcp), connect(mcp, auth["Authorization"]) as session:
            estimate = await call(session, "studio_estimate_run", story_id=q.story_id)
            assert estimate["methods"][0]["chunks"] == 1
            run = await call(session, "studio_queue_run", story_id=q.story_id, revision=3,
                             idempotency_key="parallel-run")
            retry = await call(session, "studio_queue_run", story_id=q.story_id, revision=3,
                               idempotency_key="parallel-run")
            assert run["id"] == retry["id"]
            claim = worker_api(q).claim()
            assert claim.body["run"]["id"] == run["id"]
            image, runner = image_worker(q)
            photo = await call(session, "studio_generate_photo", board_id=q.board_id,
                               idempotency_key="parallel-photo")
            assert image.tick() and len(runner.calls) == 2
            done = await call(session, "studio_get_job", job_id=photo["id"])
            assert done["status"] == "succeeded"
            live = await call(session, "studio_get_run", run_id=run["id"])
            assert live["status"] == "running"
            listed = await call(session, "studio_list_runs", story_id=q.story_id)
            assert [item["id"] for item in listed["items"]] == [run["id"]]
            cancelled = await call(session, "studio_cancel_run", run_id=run["id"], revision=live["revision"])
            assert cancelled["status"] == "cancelled"

    asyncio.run(scenario())


def test_worker_lane_refusals_leave_queue_rows_unchanged(queue, studio):
    q, s = queue, studio
    board = board_in(s, spoken=True)
    run_id = success(queue_run(q, "lane-run"), 201)["id"]
    job_ids = {
        lane: success(operation(s, board, kind, f"lane-{lane}"), 202)["id"]
        for lane, kind in (("image", "photo"), ("voice", "voice"))
    }
    api = client(q.app)
    path = "/internal/v1/work"
    headers = {lane: worker_credentials(q.owner, lane=lane) for lane in ("run", "voice", "image", None)}

    def queue_state():
        tables = ("run_lane", "runs", "run_wan_attempts", "run_check_overrides",
                  "media_job_lanes", "media_jobs", "queue_lane_events",
                  "escalation_check_failures", "escalation_packages", "escalation_events")
        with q.owner.connect() as conn:
            state = {}
            for table in tables:
                rows = conn.exec_driver_sql(
                    f"SELECT row_to_json(entry)::text AS bytes FROM {table} AS entry ORDER BY bytes",
                ).scalars().all()
                state[table] = (len(rows), tuple(row.encode("utf-8") for row in rows))
            return state

    def refuse(action, lane, status=403, code="work.lane_forbidden", **payload):
        before = queue_state()
        response = api.post(f"{path}/{action}", headers=headers[lane], **payload)
        assert (response.status_code, response.json()["error"]["code"]) == (status, code), response.text
        assert queue_state() == before

    for lane in headers:
        for target in ("run", "voice", "image"):
            if lane != target:
                refuse("claim", lane, json={"lane": target})
    for lane in ("voice", "image", None):
        refuse("claim", lane)
    refuse("claim", None, content=b"{")  # An unbound ID is refused before body parsing.

    run_claim = success(api.post(f"{path}/claim", headers=headers["run"]))
    assert run_claim["run"]["id"] == run_id
    media_claims = {
        lane: success(api.post(f"{path}/claim", headers=headers[lane], json={"lane": lane}))
        for lane in job_ids
    }
    assert {lane: claim["job"]["id"] for lane, claim in media_claims.items()} == job_ids
    run_fence = {"run_id": run_id, "fence": run_claim["fence"]}
    success(api.post(f"{path}/heartbeat", headers=headers["run"], json=run_fence))

    # Model a pre-migration claim owned by the wrong lane, with a valid fence.
    with q.owner.begin() as conn:
        voice_worker = conn.scalar(sa.select(media_jobs.c.worker_id).where(media_jobs.c.id == job_ids["voice"]))
        conn.execute(runs.update().where(runs.c.id == run_id).values(worker_id=voice_worker))
        conn.execute(media_jobs.update().where(media_jobs.c.id == job_ids["image"]).values(worker_id=voice_worker))

    wan = request_for(q)
    for action, payload in {
        "heartbeat": {},
        "resume": {},
        "attempts": {"proposal": {"kind": wan.kind, **product_request(wan)}},
        f"attempts/{'a' * 32}": {"state": "sent"},
        "publish": {},
        "complete": {"stages": [], "outputs": {}, "checks": [], "provenance": {}, "delivery_id": "fixture"},
        "fail": {"status": "failed", "reason": "Fixture failure"},
        "escalation-check-failure": {"attempt": 1, "error_code": "layered.decal_weak",
                                     "board_id": q.board_id, "result": {}},
    }.items():
        refuse(action, "voice", json={**run_fence, **payload})

    image_fence = {"job_id": job_ids["image"], "fence": media_claims["image"]["fence"]}
    for action, payload in {
        "heartbeat": {}, "publish": {}, "complete": {"result": None},
        "fail": {"code": "work.fixture", "message": "Fixture failure"},
    }.items():
        refuse(action, "voice", 404, "not_found", json={**image_fence, **payload})
        refuse(action, "run", json={**image_fence, **payload})

    voice_fence = {"job_id": job_ids["voice"], "fence": media_claims["voice"]["fence"]}
    refuse("heartbeat", "voice", 409, "work.fence_lost", json={**voice_fence, "fence": voice_fence["fence"] + 1})
    success(api.post(f"{path}/heartbeat", headers=headers["voice"], json=voice_fence))


def test_media_claim_expiry_fences_old_worker_and_never_replays_dispatch(studio):
    s = studio
    board = board_in(s)
    id_ = success(operation(s, board, "photo", "expired"), 202)["id"]
    old = worker_api(s, lane="image").claim("image")
    old.publish()
    with s.owner.begin() as conn:
        expired = database_time(conn) - timedelta(seconds=1)
        conn.execute(media_jobs.update().where(media_jobs.c.id == id_).values(claim_until=expired))
    assert worker_api(s, lane="image").claim("image") is None
    with pytest.raises(WorkerAPIError) as caught:
        old.heartbeat()
    assert caught.value.code == "work.fence_lost"
    assert job(s, id_)["error"]["code"] == "work.dispatch_unconfirmed"


def test_upload_wins_over_running_photo_with_same_inputs(studio, tmp_path):
    s = studio
    board = board_in(s)
    id_ = success(operation(s, board, "photo", "slow"), 202)["id"]
    data = image_file(tmp_path)
    uploaded = []

    class DuringRender(FakeComfyUI):
        def answer(self, name, command, args):
            if name == "comfyui_prompt.py":
                assert job(s, id_)["status"] == "running"
                uploaded.append(success(upload(s, board, data), 201)["version"])
            return super().answer(name, command, args)

    fake = DuringRender()
    worker, _ = image_worker(s, fake)
    assert worker.tick() and len(fake.payloads) == 1
    result = job(s, id_)
    assert not result["result_is_current"]
    assert current_board(s, board)["photo"]["current_version_id"] == uploaded[0]["id"]
    assert result["photo"]["prompt"] == "A small workshop"
    versions = success(s.browser.get(f"/v1/boards/{board}/photo-versions"))["items"]
    assert {version["id"] for version in versions} == {uploaded[0]["id"], result["result_version_id"]}
    assert sorted(version["number"] for version in versions) == [1, 2]


def test_agent_cannot_read_unselected_board_photo_by_hash(studio, tmp_path):
    s = studio
    board = board_in(s)
    doc = success(upload(s, board, image_file(tmp_path)), 201)["version"]
    digest = doc["content"]["sha256"]
    assert doc["state"] == "board"
    assert s.agent.get(f"/v1/media/{digest}", headers=s.auth).status_code == 200
    patch(s, board, {"photo": {**current_board(s, board)["photo"], "current_version_id": None}})
    assert s.agent.get(f"/v1/media/{digest}", headers=s.auth).status_code == 404
    assert s.browser.get(f"/v1/asset-versions/{doc['id']}/media/{digest}").status_code == 200


def test_upload_keeps_result_unselected_on_person_edited_board(studio, tmp_path):
    s = studio
    board = board_in(s)
    before = patch(s, board, {"title": "A person's draft title"})
    _, editor = register_agent(s.owner, {s.production_id: ["draft:write"]})
    path = f"/v1/boards/{board}"
    denied = s.agent.patch(path, headers={**editor, "If-Match": str(before["revision"])},
                           json={"title": "An agent draft title"})
    assert denied.status_code == 409 and denied.json()["error"]["code"] == "draft.protected"

    uploaded = success(upload(s, board, image_file(tmp_path)), 201)
    after = current_board(s, board)
    assert uploaded["selected"] is False and uploaded["board_revision"] is None
    assert after["photo"] == before["photo"]
    for field in ("title", "revision", "drafted_by", "person_edit", "person_edit_revision"):
        assert after[field] == before[field]
    versions = success(s.browser.get(path + "/photo-versions"))["items"]
    assert [version["id"] for version in versions] == [uploaded["version"]["id"]]


@pytest.mark.parametrize("kind", ["photo", "voice"])
@pytest.mark.parametrize("by_human", [False, True], ids=["agent", "person"])
def test_job_media_selection_respects_person_edit(studio, kind, by_human):
    s = studio
    board = board_in(s, spoken=kind == "voice")
    before = patch(s, board, {"title": "Person's title"})
    if by_human:
        response = s.browser.post(f"/v1/boards/{board}/{kind}-jobs", json={},
                                  headers={**s.csrf, "Idempotency-Key": "protected"})
    else:
        response = operation(s, board, kind, "protected")
    queued = success(response, 202)["id"]
    worker = speech_worker(s, FakeKokoro()) if kind == "voice" else image_worker(s)[0]
    assert worker.tick()
    result = job(s, queued)
    assert result["status"] == "succeeded" and result["result_is_current"] is by_human
    after = current_board(s, board)
    for field in ("title", "drafted_by", "person_edit", "person_edit_revision"):
        assert after[field] == before[field]
    assert after[kind]["current_version_id"] == (result["result_version_id"] if by_human else None)
    assert after["revision"] == before["revision"] + int(by_human)
    versions = success(s.browser.get(f"/v1/boards/{board}/{kind}-versions"))["items"]
    assert [version["id"] for version in versions] == [result["result_version_id"]]


@pytest.mark.parametrize(("kind", "reuse"), [("photo", False), ("voice", False), ("voice", True)],
                         ids=["photo", "voice", "voice-reuse"])
def test_person_job_selection_protects_an_untouched_board(studio, kind, reuse):
    s = studio
    board = board_in(s, spoken=kind == "voice")
    path = f"/v1/boards/{board}"
    worker = speech_worker(s, FakeKokoro()) if kind == "voice" else image_worker(s)[0]
    if reuse:
        success(operation(s, board, kind, "agent-choice"), 202)
        assert worker.tick()
    before = current_board(s, board)
    assert "person_edit" not in before
    queued = success(s.browser.post(f"{path}/{kind}-jobs", json={},
                                    headers={**s.csrf, "Idempotency-Key": "person-choice"}), 202)
    assert worker.tick()
    read = s.agent.get(path, headers=s.auth)
    selected = success(read)
    result = job(s, queued["id"])
    assert result["result_is_current"]
    assert selected[kind]["current_version_id"] == result["result_version_id"]
    if reuse:
        assert before[kind]["current_version_id"] == result["result_version_id"]
    revision = selected["revision"]
    assert revision == before["revision"] + 1
    headers = {**s.auth, "If-Match": str(revision)}
    change = {kind: {**selected[kind], "current_version_id": None}}
    denied = s.agent.patch(path, headers=headers, json=change)
    assert denied.status_code == 409 and denied.json()["error"]["code"] == "draft.protected"
    assert selected["person_edit"] == "content" and selected["person_edit_revision"] == revision
    allowed = success(s.agent.patch(path, headers=headers, json={
        **change, "acknowledge_person_edit": {
            "board_revision": revision, "read_token": read.headers[READ_TOKEN_HEADER],
        },
    }))
    assert allowed[kind]["current_version_id"] is None
    assert allowed["person_edit_acknowledgments"][0]["board_revision"] == revision


@pytest.mark.parametrize("kind", ["photo", "voice"])
def test_agent_job_selection_preserves_own_redraft(studio, kind):
    s = studio
    declaration = {"board_key": "workshop", "draft_sha256": "a" * 64,
                   "model": "fixture", "session": "fixture"}
    board = board_in(s, spoken=kind == "voice", draft_application=declaration)
    queued = success(operation(s, board, kind, "agent-choice"), 202)
    worker = speech_worker(s, FakeKokoro()) if kind == "voice" else image_worker(s)[0]
    assert worker.tick()
    assert job(s, queued["id"])["result_is_current"]
    after = current_board(s, board)
    story = success(s.browser.get(f"/v1/stories/{s.story_id}"))
    response = s.agent.patch(f"/v1/boards/{board}", headers={**s.auth, "If-Match": str(after["revision"])},
                             json={"title": "Second draft", "draft_application": {
                                 **declaration, "draft_sha256": "b" * 64,
                                 "previous_draft_sha256": declaration["draft_sha256"],
                                 "story_revision": story["revision"],
                             }})
    assert success(response)["title"] == "Second draft"
    assert after["draft_application"]["board_revision"] == after["revision"]
    assert after["draft_application"]["applied_board_revision"] == 1


@pytest.mark.parametrize("case", ["other-agent", "stale-stamp"])
def test_agent_job_selection_does_not_advance_an_ineligible_stamp(studio, case):
    s = studio
    board = board_in(s, draft_application={"board_key": "workshop", "draft_sha256": "a" * 64,
                                          "model": "fixture", "session": "fixture"})
    requester = s.auth
    if case == "other-agent":
        _, requester = register_agent(s.owner, {s.production_id: ["assets:generate"]})
    else:
        patch(s, board, {"title": "A separate agent edit"}, by_human=False)
    queued = success(operation(s, board, "photo", "agent-stamp", headers=requester), 202)
    assert image_worker(s)[0].tick()
    result = job(s, queued["id"])
    assert result["status"] == "succeeded" and result["result_version_id"]
    assert result["result_is_current"] is (case == "stale-stamp")
    after = current_board(s, board)
    assert after["draft_application"]["board_revision"] == 1
    assert after["revision"] == (1 if case == "other-agent" else 3)


def test_runtime_cannot_update_job_requester(studio, engine):
    board = board_in(studio)
    queued = success(operation(studio, board, "photo", "requester-privilege"), 202)
    target = media_jobs.c.id == queued["id"]
    forged = {"kind": "human", "iss": "https://fixture.invalid", "sub": "forged"}
    with pytest.raises(sa.exc.ProgrammingError) as refused, engine.begin() as conn:
        conn.execute(media_jobs.update().where(target).values(requester=forged))
    assert isinstance(refused.value.orig, psycopg.errors.InsufficientPrivilege)


def stage_result(worker, claim):
    with ActiveClaim(claim, progress=worker.progress) as active:
        return worker._result(Job.from_document(claim.body["job"]), claim, Dispatch(active))


@pytest.mark.parametrize("kind", ["photo", "voice"])
def test_mutable_job_document_cannot_override_requester(studio, engine, kind):
    s = studio
    board = board_in(s, spoken=kind == "voice", by_human=True)
    queued = success(operation(s, board, kind, "forged-requester"), 202)
    target = media_jobs.c.id == queued["id"]
    lane = "image" if kind == "photo" else "voice"
    claim = worker_api(s, lane=lane).claim(lane)
    worker = speech_worker(s, FakeKokoro()) if kind == "voice" else image_worker(s)[0]
    evidence = stage_result(worker, claim)
    original = claim.body["job"]["created_by"]
    forged = success(s.browser.get("/v1/me"))["principal"]
    with engine.begin() as conn:
        conn.execute(media_jobs.update().where(target).values(document={**claim.body["job"], "created_by": forged}))
    finished = claim.complete({"result": evidence})
    assert finished["status"] == "succeeded" and finished["created_by"] == original
    assert not finished["result_is_current"]
    assert current_board(s, board)[kind]["current_version_id"] is None


@pytest.mark.parametrize("requester", [None, {"kind": "human", "iss": "https://fixture.invalid"}])
def test_invalid_job_requester_refuses_completion(studio, requester):
    s = studio
    board = board_in(s)
    queued = success(operation(s, board, "photo", "invalid-requester"), 202)
    target = media_jobs.c.id == queued["id"]
    claim = worker_api(s, lane="image").claim("image")
    evidence = stage_result(image_worker(s)[0], claim)
    with s.owner.begin() as conn:
        conn.execute(media_jobs.update().where(target).values(requester=requester))
    with pytest.raises(WorkerAPIError) as refused:
        claim.complete({"result": evidence})
    assert (refused.value.status, refused.value.code) == (422, "job.requester_invalid")
    with s.owner.connect() as conn:
        assert conn.scalar(sa.select(media_jobs.c.document["status"].astext).where(target)) == "running"
    assert success(s.browser.get(f"/v1/boards/{board}/photo-versions"))["items"] == []


def recorded_photo(s, board):
    version = example("asset-version-photo-external.json")
    minter = Minter()
    version.update(id=minter.mint("asv"), asset_id=minter.mint("ast"), recorded_without_media=True,
                   scope={"production_id": s.production_id, "story_id": s.story_id, "board_id": board})
    content = version["content"]
    content["locator"] = blob_locator(s.production_id, content["sha256"], content["media_type"])
    with s.owner.begin() as conn:
        record_asset_version(conn, version)
    return version["id"]


def assert_recorded_problem(response, path):
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert (error["code"], error["path"]) == ("asset.recorded_without_media", path)


def test_photo_job_refuses_recorded_only_input(studio):
    s = studio
    board = board_in(s)
    version = recorded_photo(s, board)
    photo = current_board(s, board)["photo"]
    patch(s, board, {"photo": {**photo, "input_asset_version_ids": [version]}}, by_human=False)
    assert_recorded_problem(operation(s, board, "photo", "recorded-input"), "/photo/input_asset_version_ids/0")
    assert success(s.browser.get(f"/v1/boards/{board}/jobs"))["items"] == []


@pytest.fixture
def recorded_voice(studio):
    s = studio
    board = board_in(s, spoken=True)
    queued = success(operation(s, board, "voice", "recorded-voice"), 202)
    claim = worker_api(s, lane="voice").claim("voice")
    worker = speech_worker(s, FakeKokoro())
    result = stage_result(worker, claim)
    result["version"]["recorded_without_media"] = True
    with s.owner.begin() as conn:
        record_asset_version(conn, result["version"])
    return board, queued, claim, result


@pytest.mark.parametrize("kind", ["photo", "voice"])
def test_board_refuses_recorded_only_selection(studio, request, kind):
    s = studio
    if kind == "photo":
        board = board_in(s)
        version = recorded_photo(s, board)
    else:
        board, _, _, result = request.getfixturevalue("recorded_voice")
        version = result["version"]["id"]
    before = current_board(s, board)
    response = s.browser.patch(f"/v1/boards/{board}", headers={**s.csrf, "If-Match": str(before["revision"])},
                               json={kind: {**before[kind], "current_version_id": version}})
    assert_recorded_problem(response, f"/{kind}/current_version_id")
    assert current_board(s, board) == before


def test_voice_completion_refuses_recorded_only_result(studio, recorded_voice, monkeypatch):
    board, queued, claim, result = recorded_voice

    def unexpected_probe(*args):
        pytest.fail("Recorded voice must be refused before probing the store")

    monkeypatch.setattr(studio.store, "verify", unexpected_probe)
    with pytest.raises(WorkerAPIError) as refused:
        claim.complete({"result": result})
    assert (refused.value.status, refused.value.code) == (422, "asset.recorded_without_media")
    assert job(studio, queued["id"])["status"] == "running"
    assert current_board(studio, board)["voice"]["current_version_id"] is None


def test_promotion_refuses_recorded_only_version(studio):
    s = studio
    version = recorded_photo(s, board_in(s))
    assert_recorded_problem(s.browser.post(f"/v1/asset-versions/{version}/promote", headers=s.csrf), "/id")


@pytest.mark.parametrize("use", ["selection", "source"])
def test_upload_requires_media_only_for_sources(studio, tmp_path, use):
    s = studio
    board = board_in(s)
    version = recorded_photo(s, board)
    declaration = dict(PROVENANCE)
    if use == "selection":
        # An archive import can retain the saved pin without registering media.
        draft = current_board(s, board)
        draft.pop("derived")
        draft["photo"]["current_version_id"] = version
        with s.owner.begin() as conn:
            conn.execute(boards.update().where(boards.c.id == board).values(document=draft))
        result = success(upload(s, board, image_file(tmp_path), declaration), 201)
        assert result["selected"]
        selected = result["version"]["id"]
        assert current_board(s, board)["photo"]["current_version_id"] == selected
    else:
        declaration["source_asset_version_ids"] = [version]
        assert_recorded_problem(upload(s, board, image_file(tmp_path), declaration),
                                "/provenance/generator/source_asset_version_ids/0")
    versions = success(s.browser.get(f"/v1/boards/{board}/photo-versions"))["items"]
    expected = {version, selected} if use == "selection" else {version}
    assert {row["id"] for row in versions} == expected


@pytest.mark.parametrize("scope", ["another-board", "another-production"])
def test_worker_cannot_complete_voice_for_another_scope(studio, scope):
    s = studio
    board = board_in(s, spoken=True)
    foreign = s
    if scope == "another-production":
        production = new_production(s.browser, s.csrf)
        foreign = SimpleNamespace(**{**vars(s), "production_id": production,
                                    "story_id": new_story(s.browser, s.csrf, production)})
    other_board = board_in(foreign, by_human=True)
    queued = success(operation(s, board, "voice", "scoped-voice"), 202)
    claim = worker_api(s, lane="voice").claim("voice")
    result = speech_worker(s, FakeKokoro())._result(Job.from_document(claim.body["job"]), claim, claim.publish)
    false_result = deepcopy(result)
    version = false_result["version"]
    version["scope"] = {"production_id": foreign.production_id, "story_id": foreign.story_id,
                        "board_id": other_board}
    if scope == "another-production":
        track = version["voice"]["track"]
        with s.store.open(track["locator"]) as original:
            track["locator"] = s.store.publish(original, scope=foreign.production_id,
                                               media_type="audio/wav").locator
    with pytest.raises(WorkerAPIError) as refused:
        claim.complete({"result": false_result})
    assert (refused.value.status, refused.value.code) == (422, "work.result_invalid")
    assert job(s, queued["id"])["status"] == "running"
    assert success(s.browser.get(f"/v1/boards/{other_board}/voice-versions"))["items"] == []
    assert claim.complete({"result": result})["status"] == "succeeded"


def test_runtime_cannot_rewrite_promoted_pinned_or_foreign_asset_versions(queue):
    q = queue
    run = success(queue_run(q, "immutable-pin"), 201)
    assert run["status"] == "queued"
    candidate = success(q.browser.post("/v1/asset-jobs",
        headers={**q.csrf, "Idempotency-Key": "immutable-candidate"},
        json={"kind": "cast", "name": "A new doll", "prompt": "A doll in a workshop"}), 202)
    assert image_worker(q)[0].tick()
    version = success(q.browser.get(f"/v1/jobs/{candidate['id']}/result"))["id"]
    url = f"/v1/asset-versions/{version}/promote"
    promoted = success(q.browser.post(url, headers=q.csrf))
    assert promoted["state"] == "promoted"
    assert success(q.browser.post(url, headers=q.csrf)) == promoted
    with q.engine.connect() as conn:
        stored = conn.execute(sa.select(asset_versions.c.state, asset_versions.c.document)
                              .where(asset_versions.c.id == version)).one()
        assert stored.state == stored.document["state"] == "candidate"
        assert conn.scalar(sa.select(asset_promotions.c.promoted_by)
                           .where(asset_promotions.c.version_id == version))["kind"] == "human"

    production = new_production(q.browser, q.csrf)
    foreign = SimpleNamespace(**{**vars(q), "production_id": production,
                                 "story_id": new_story(q.browser, q.csrf, production)})
    board = board_in(foreign, by_human=True)
    other = example("asset-version-photo-external.json")
    other.update(id=Minter().mint("asv"), asset_id=Minter().mint("ast"),
                 scope={"production_id": production, "story_id": foreign.story_id, "board_id": board})
    blob = q.store.publish(q.png, scope=production, media_type="image/png")
    other["content"].update(sha256=blob.sha256, bytes=blob.bytes, locator=blob.locator)
    with q.owner.begin() as conn:
        record_asset_version(conn, other)

    for target in (version, q.version_id, other["id"]):
        for fields in ({"document": {}}, {"state": "candidate"}):
            with pytest.raises(sa.exc.ProgrammingError) as refused, q.engine.begin() as conn:
                conn.execute(asset_versions.update().where(asset_versions.c.id == target).values(**fields))
            assert isinstance(refused.value.orig, psycopg.errors.InsufficientPrivilege)


def test_queue_controls_are_people_only(studio):
    s = studio
    path = "/v1/queue/lanes"
    assert s.agent.get(path).status_code == 401
    assert s.agent.get(path, headers=s.auth).status_code == 403
    assert s.agent.put(path + "/image", headers=s.auth, json={"paused": True}).status_code == 403
    assert s.agent.put(path + "/image", headers=worker_credentials(s.owner),
                       json={"paused": True}).status_code == 401
    assert s.browser.put(path + "/image", json={"paused": True}).status_code == 403
    assert s.browser.put(path + "/image", headers=s.csrf, json={"paused": "true"}).status_code == 422


def test_pausing_run_lane_drains_current_claim_and_blocks_new_claims(queue):
    q = queue
    path = "/v1/queue/lanes"
    first = success(queue_run(q, "before-pause"), 201)["id"]
    worker = worker_api(q)
    claim = worker.claim()
    assert claim.body["run"]["id"] == first
    paused = success(q.browser.put(path + "/run", headers=q.csrf, json={"paused": True}))
    assert paused["changed_at"] == q.clock.now.isoformat().replace("+00:00", "Z")
    assert paused["changed_by"]["kind"] == "human" and paused["changed_by"]["sub"] == "one"
    second = success(queue_run(q, "after-pause"), 201)
    assert second["status"] == "queued"
    assert claim.heartbeat()["cancel_requested"] is False
    ended = claim.fail(status="failed", reason="Fixture finished",
                       error={"code": "work.fixture", "message": "Fixture finished",
                              "stage": "prebuild", "board_id": None})
    assert ended["id"] == first and ended["status"] == "failed"
    assert worker.claim() is None
    assert success(q.browser.get(f"/v1/runs/{second['id']}"))["status"] == "queued"

    _, auth = register_agent(q.owner, {q.production_id: ["assets:generate"]})
    assert success(operation(SimpleNamespace(agent=q.browser, auth=auth), q.board_id, "photo", "open-image"), 202)
    assert image_worker(q)[0].tick()
    assert success(q.browser.get(path))["items"][0] == paused
    q.clock.advance(10)
    resumed = success(q.browser.put(path + "/run", headers=q.csrf, json={"paused": False}))
    assert resumed["paused"] is False and resumed["changed_at"] > paused["changed_at"]
    assert success(q.browser.put(path + "/run", headers=q.csrf, json={"paused": False})) == resumed
    assert worker.claim().body["run"]["id"] == second["id"]
    with q.engine.connect() as conn:
        history = conn.scalars(sa.select(queue_lane_events.c.paused)
                               .where(queue_lane_events.c.lane == "run")
                               .order_by(queue_lane_events.c.sequence)).all()
        assert history == [True, False]


@pytest.mark.parametrize("lane", ["image", "voice"])
def test_pausing_media_lane_leaves_requests_queued_until_resumed(studio, lane):
    s = studio
    board = board_in(s, spoken=True)
    kind = "photo" if lane == "image" else "voice"
    first = success(operation(s, board, kind, "before-media-pause"), 202)["id"]
    worker = worker_api(s, lane=lane)
    claim = worker.claim(lane)
    assert claim.body["job"]["id"] == first
    path = f"/v1/queue/lanes/{lane}"
    assert success(s.browser.put(path, headers=s.csrf, json={"paused": True}))["paused"]
    second = success(operation(s, board, kind, "after-media-pause"), 202)["id"]
    claim.heartbeat()
    assert claim.fail(code="work.fixture", message="Fixture finished")["status"] == "failed"
    assert worker.claim(lane) is None
    assert job(s, second)["status"] == "queued"
    assert not success(s.browser.put(path, headers=s.csrf, json={"paused": False}))["paused"]
    assert worker.claim(lane).body["job"]["id"] == second


def test_photo_currency_blocks_build_and_preserves_frozen_run(queue):
    q = queue
    frozen = queue_run(q, "frozen")
    first = success(frozen, 201)
    current = current_board(q, q.board_id)
    patch(q, q.board_id, {"photo": {**current["photo"], "prompt": "An edited prompt"}})
    new = queue_run(q, "new", rev=4)
    assert new.status_code == 422 and new.json()["error"]["code"] == "photo.stale"
    assert worker_api(q).claim().body["run"]["id"] == first["id"]
    assert current_board(q, q.board_id)["derived"]["photo_state"] == "stale"
