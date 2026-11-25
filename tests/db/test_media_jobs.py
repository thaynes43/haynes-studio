"""Media job and upload acceptance through the real HTTP and MCP adapters."""

import asyncio
import base64
import json
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from haynes_studio.adapters.comfyui import ImageClient
from haynes_studio.adapters.errors import AdapterError
from haynes_studio.adapters.fakes import FakeComfyUI, FakeKokoro, FakeRunner
from haynes_studio.adapters.kokoro import KokoroClient
from haynes_studio.canonical.ids import Minter
from haynes_studio.db.catalog import record_asset_version
from haynes_studio.db.runs import database_time
from haynes_studio.db.schema import asset_versions, media_jobs
from haynes_studio.library.model import version_document
from haynes_studio.mcp.server import create_app
from haynes_studio.photo.validation import MAX_UPLOAD_BYTES
from haynes_studio.queue.media_worker import MediaWorker
from haynes_studio.queue.worker_api import WorkerAPIError

from tests.db.test_run_queue import (
    queue, queue_run, worker_api,
)
from tests.db.test_studio_api import (
    client, engine, new_production, new_story, owner_engine, register_agent,
    runtime_db, runtime_role, service, sign_in,
)
from tests.library.fixtures import register, winter_menu

from tests.mcp.client import API_URL, call, connect, fail

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
        conn.exec_driver_sql("TRUNCATE media_jobs")
        conn.exec_driver_sql("UPDATE media_job_lanes SET next_position = 1")
    browser = client(app)
    csrf = sign_in(browser, issuer)
    production_id = new_production(browser, csrf)
    story_id = new_story(browser, csrf, production_id)
    other = new_production(browser, csrf)
    _, agent = register_agent(owner_engine, {
        production_id: ["read", "assets:generate", "assets:upload", "runs:queue"],
    })
    _, reader = register_agent(owner_engine, {production_id: ["read"]})
    _, outsider = register_agent(owner_engine, {other: ["read", "assets:generate", "assets:upload"]})
    return SimpleNamespace(app=app, store=store, owner=owner_engine, browser=browser, agent=client(app),
                           csrf=csrf, auth=agent, reader=reader, outsider=outsider,
                           production_id=production_id, story_id=story_id)


def board_in(s, *, spoken=False):
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
    doc = success(s.browser.post(f"/v1/stories/{s.story_id}/boards", json=values,
                                 headers={**s.csrf, "If-Match": str(current["revision"])}), 201)
    return doc["id"]


def operation(s, board, kind, key, *, headers=None, body=None):
    return s.agent.post(f"/v1/boards/{board}/{kind}-jobs", json={} if body is None else body,
                        headers={**(s.auth if headers is None else headers), "Idempotency-Key": key})


def job(s, id_):
    return success(s.browser.get(f"/v1/jobs/{id_}"))


def current_board(s, board):
    return success(s.browser.get(f"/v1/boards/{board}"))


def patch(s, board, payload):
    return success(s.browser.patch(f"/v1/boards/{board}", json=payload, headers={
        **s.csrf, "If-Match": str(current_board(s, board)["revision"]),
    }))


def image_worker(s, fake=None, *, pause=None):
    runner = FakeRunner(fake or FakeComfyUI())
    options = {} if pause is None else {"pause": pause}
    worker = MediaWorker(worker_api(s), lane="image", store=s.store, client=ImageClient(runner),
                         licences=register(), **options)
    return worker, runner


def speech_worker(s, fake):
    runner = FakeRunner(fake)
    return MediaWorker(worker_api(s), lane="voice", store=s.store, client=KokoroClient(runner),
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
                               "input_asset_version_ids": [version]}})
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

    bad = MediaWorker(worker_api(s), lane="voice", store=s.store,
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


def test_mcp_media_tools_and_upload_hash(studio, tmp_path):
    s = studio
    board = board_in(s, spoken=True)
    data = image_file(tmp_path)
    fake = FakeKokoro()
    voice_worker = speech_worker(s, fake)
    image, _ = image_worker(s)

    async def scenario():
        mcp = create_app(API_URL, api_transport=httpx.ASGITransport(app=s.app))
        async with mcp.router.lifespan_context(mcp), connect(mcp, s.auth["Authorization"]) as session:
            uploaded = await call(session, "studio_upload_photo", board_id=board, revision=1,
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


def test_media_claim_expiry_fences_old_worker_and_never_replays_dispatch(studio):
    s = studio
    board = board_in(s)
    id_ = success(operation(s, board, "photo", "expired"), 202)["id"]
    old = worker_api(s).claim("image")
    old.publish()
    with s.owner.begin() as conn:
        expired = database_time(conn) - timedelta(seconds=1)
        conn.execute(media_jobs.update().where(media_jobs.c.id == id_).values(claim_until=expired))
    assert worker_api(s).claim("image") is None
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
