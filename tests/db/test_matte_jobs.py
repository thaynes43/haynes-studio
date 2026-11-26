"""Exercise matte admission, fencing and publication through Studio's serving paths."""

import asyncio
import multiprocessing
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import numpy as np
import pytest
import sqlalchemy as sa

from haynes_studio.adapters import matting
from haynes_studio.adapters.matting import MattingClient
from haynes_studio.api.transport import WRITE_LIMIT
from haynes_studio.canonical.ids import Minter
from haynes_studio.db.catalog import record_asset_version
from haynes_studio.db.migrate import migrate
from haynes_studio.db.runs import database_time
from haynes_studio.db.schema import asset_versions, media_jobs, queue_lane_events, worker_lane_grants
from haynes_studio.library import EMPTY, Content, Scope, VersionRequest, import_version
from haynes_studio.library.model import Licence, version_document
from haynes_studio.matting.backend import Engine
from haynes_studio.matting.pixels import encode_png
from haynes_studio.matting.profile import (
    BUSY, COMMAND_FAILED, NOT_FOUND, PIN_MISMATCH, REQUEST_INVALID, RESPONSE_INVALID, TIMEOUT,
)
from haynes_studio.matting.service import listening
from haynes_studio.mcp.server import create_app
from haynes_studio.queue.media_worker import MediaWorker
from haynes_studio.queue.progress import ProgressFile
from haynes_studio.queue.worker_api import MediaClaimAPI, WorkerAPIError
from haynes_studio.store import LIBRARY

from tests.assets.test_candidates import BY, NOW
from tests.assets.test_matte import load_waiting_matte
from tests.db.test_media_jobs import (
    board_in, client, engine, job, owner_engine, register_agent, runtime_db, runtime_role, service, studio,
    success, upload,
)
from tests.db.test_run_queue import worker_api, worker_credentials
from tests.formats.fixtures import doll_short
from tests.matting.test_backend import PROFILE, load_fake, prepared, request_for
from tests.mcp.client import API_URL, call, connect, fail

pytestmark = pytest.mark.db
PNG = "image/png"
PATH = "/v1/asset-jobs/matte"
WORK = "/internal/v1/work"


@pytest.fixture
def matte_studio(studio):
    yield studio
    # Shared migration fixtures downgrade the disposable schema between modules.
    with studio.owner.begin() as conn:
        for table in (media_jobs, queue_lane_events, worker_lane_grants):
            conn.execute(table.delete().where(table.c.lane == "matte"))


@pytest.fixture
def matte_format(matte_studio):
    declaration = doll_short()
    declaration["id"] = f'matte-{Minter().mint("fmv")[-12:].lower()}'
    declaration["recipe"]["cast"]["matte_slots"] = {
        "a": {"target_height_px": 160},
        "b": {"target_height_px": 800},
    }
    return success(matte_studio.browser.post("/v1/formats", headers=matte_studio.csrf, json=declaration), 201)


@pytest.fixture
def matte_client(prepared):
    root, weights, digest = prepared
    with TemporaryDirectory(prefix="matte-sock-") as directory:
        yield MattingClient(PROFILE, digest, scratch=root, socket=Path(directory) / "matte.sock"), weights


def opaque(studio, *, scope, value=33, size=256):
    byte_content = encode_png(np.full((size, size, 3), value, dtype=np.uint8))
    blob = studio.store.publish(byte_content, scope=scope or LIBRARY, media_type=PNG)
    identifier = Minter().mint("asv")
    outcome = import_version(EMPTY, VersionRequest(
        kind="cast", name="Synthetic portrait", scope=Scope(scope), capabilities=("opaque_photo",),
        content=Content(blob.sha256, blob.bytes, PNG, blob.locator, size, size),
        provenance={"origin": "imported", "source_key": f"fixture:{identifier}",
                    "generator": {"role": "image"}, "external": None},
        licence=Licence.unknown("Synthetic fixture"), version_id=identifier,
    ), by=BY, now=NOW)
    document = version_document(outcome.version, outcome.library.asset_of(identifier))
    with studio.owner.begin() as conn:
        record_asset_version(conn, document)
    return document


def payload(source, format_, slot="a"):
    return {"source_version_id": source["id"], "format_version_id": format_["id"], "slot": slot}


def request(studio, body, key, *, headers=None):
    http, actor = (studio.browser, studio.csrf) if headers is None else (studio.agent, headers)
    return http.post(PATH, headers={**actor, "Idempotency-Key": key}, json=body)


def retire(claim):
    return claim.fail(code="work.fixture", message="Fixture finished")["status"]


def row_of(studio, identifier):
    with studio.owner.connect() as conn:
        return conn.execute(sa.select(media_jobs).where(media_jobs.c.id == identifier)).mappings().one()


def expire(studio, identifier):
    with studio.owner.begin() as conn:
        conn.execute(media_jobs.update().where(media_jobs.c.id == identifier)
                     .values(claim_until=database_time(conn) - timedelta(seconds=1)))


def conflict(action, code="work.fence_lost"):
    with pytest.raises(WorkerAPIError) as caught:
        action()
    assert caught.value.status == 409 and caught.value.code == code


def test_matte_admission_and_scoped_job_reads(matte_studio, matte_format):
    s = matte_studio
    source = opaque(s, scope=s.production_id)
    body = payload(source, matte_format)
    for existing in (s.auth, s.reader, s.outsider):
        assert request(s, body, "agent-matte", headers=existing).status_code == 403
    response = request(s, body, "a-cutout")
    queued = success(response, 202)
    assert queued["kind"] == "matte" and queued["target_id"] == source["id"]
    assert queued["status"] == "queued"
    url = response.headers["location"]
    assert url == f'/v1/jobs/{queued["id"]}'
    assert success(request(s, body, "a-cutout")) == queued
    mismatch = request(s, {**body, "slot": "b"}, "a-cutout")
    assert mismatch.status_code == 422 and mismatch.json()["error"]["code"] == "idempotency.mismatch"
    invalid = request(s, {**body, "slot": "z"}, "missing-slot")
    assert invalid.status_code == 422 and invalid.json()["error"]["path"] == "/slot"
    for field, prefix in (("source_version_id", "asv"), ("format_version_id", "fmv")):
        assert request(s, {**body, field: Minter().mint(prefix)}, "missing-pin").status_code == 404
    original = upload(s, board_in(s), encode_png(np.full((64, 64, 3), 4, dtype=np.uint8)))
    uploaded = success(original, 201)["version"]
    board_source = request(s, payload(uploaded, matte_format), "board-scope")
    assert board_source.status_code == 422 and board_source.json()["error"]["path"] == "/source_version_id"

    scoped = success(s.agent.get(url, headers=s.reader))
    assert scoped["matte"] == {
        **body, "production_id": s.production_id, "kind": "cast", "format_sha256": matte_format["sha256"],
        "source_sha256": source["content"]["sha256"], "target_height_px": 160,
    }
    _, writer = register_agent(s.owner, {s.production_id: ["assets:generate"]})
    for headers in (writer, s.outsider):
        assert s.agent.get(url, headers=headers).status_code == 404
    assert s.agent.get(f"{url}/result", headers=s.reader).status_code == 404

    global_source = opaque(s, scope=None)
    global_id = success(request(s, payload(global_source, matte_format), "global-photo"), 202)["id"]
    assert job(s, global_id)["matte"]["production_id"] is None
    assert s.agent.get(f"/v1/jobs/{global_id}", headers=s.reader).status_code == 404

    async def mcp_reads():
        app = create_app(API_URL, api_transport=httpx.ASGITransport(app=s.app))
        async with app.router.lifespan_context(app):
            async with connect(app, s.reader["Authorization"]) as session:
                result = await call(session, "studio_get_job", job_id=queued["id"])
                assert result["matte"] == scoped["matte"] and result["status"] == "queued"
                assert (await fail(session, "studio_get_job", job_id=global_id))["code"] == "not_found"
            async with connect(app, s.outsider["Authorization"]) as session:
                assert (await fail(session, "studio_get_job", job_id=queued["id"]))["code"] == "not_found"

    asyncio.run(mcp_reads())


def test_matte_lane_grants_pause_resume_and_fifo(matte_studio, matte_format):
    s = matte_studio
    source = opaque(s, scope=s.production_id)
    body = payload(source, matte_format)
    first = success(request(s, body, "before-pause"), 202)["id"]
    image_board = board_in(s)
    image_id = success(s.agent.post(f"/v1/boards/{image_board}/photo-jobs",
                                   headers={**s.auth, "Idempotency-Key": "other-lane"}, json={}), 202)["id"]
    http = client(s.app)
    headers = {lane: worker_credentials(s.owner, lane=lane) for lane in ("run", "image", "voice", "matte", None)}

    def refused(lane, action, status, code, **kwargs):
        response = http.post(f"{WORK}/{action}", headers=headers[lane], **kwargs)
        assert response.status_code == status, response.text
        assert response.json()["error"]["code"] == code

    for lane in ("run", "image", "voice", None):
        refused(lane, "claim", 403, "work.lane_forbidden", json={"lane": "matte"})
        refused(lane, "claim", 403, "work.lane_forbidden", json={"lane": "matte", "extra": True})
        refused(lane, "claim", 403 if lane is None else 422,
                "work.lane_forbidden" if lane is None else "schema.invalid",
                content=b'{"lane":"matte",')
        refused(lane, "release-matte", 403, "work.lane_forbidden", json={"job_id": first, "fence": 1})
        refused(lane, "release-matte", 403, "work.lane_forbidden", content=b"{")
    for lane in ("run", "image", "voice"):
        refused(lane, "claim", 403, "work.lane_forbidden", json={"lane": lane, "settle_only": True})
        refused("matte", "claim", 403, "work.lane_forbidden", json={"lane": lane})
        refused("matte", "claim", 403, "work.lane_forbidden", json={"lane": lane, "extra": True})
    refused("matte", "claim", 403, "work.lane_forbidden")
    refused("matte", "claim", 403, "work.lane_forbidden", json={"extra": True})
    refused("matte", "claim", 422, "schema.unknown_field", json={"lane": "matte", "extra": True})
    refused("matte", "claim", 422, "schema.invalid", json={"lane": ["matte"], "extra": True})
    refused("matte", "resume", 403, "work.lane_forbidden", content=b"{")
    refused("matte", "resume", 403, "work.lane_forbidden", json={"run_id": "malformed", "fence": "invalid"})
    refused("matte", "heartbeat", 403, "work.lane_forbidden", json={"run_id": Minter().mint("run"), "fence": 1})
    refused("matte", "heartbeat", 403, "work.lane_forbidden", json={"run_id": "malformed", "fence": "invalid"})
    assert job(s, first)["status"] == job(s, image_id)["status"] == "queued"
    matte = worker_api(s, headers=headers["matte"])
    image = worker_api(s, headers=headers["image"])
    claim = matte.claim("matte")
    image_claim = image.claim("image")
    assert claim.body["job"]["id"] == first
    assert image_claim.body["job"]["id"] == image_id
    for route, extra in (
        ("heartbeat", {}), ("publish", {}), ("complete", {"result": None}),
        ("fail", {"code": "work.fixture", "message": "Fixture error"}),
    ):
        refused("image", route, 404, "not_found", json={**claim.identity, **extra})
        refused("matte", route, 404, "not_found", json={**image_claim.identity, **extra})
        refused("matte", route, 422, "schema.invalid", json={**image_claim.identity, **extra, "fence": "invalid"})
        refused("image", route, 422, "schema.invalid", json={**claim.identity, **extra, "fence": "invalid"})

    lane_path = "/v1/queue/lanes/matte"
    assert s.agent.put(lane_path, headers=s.auth, json={"paused": True}).status_code == 403
    assert success(s.browser.put(lane_path, headers=s.csrf, json={"paused": True}))["paused"]
    second = success(request(s, body, "during-pause"), 202)["id"]
    assert claim.heartbeat()["cancel_requested"] is False
    assert retire(claim) == "failed"
    assert matte.claim("matte") is None and job(s, second)["status"] == "queued"
    assert not success(s.browser.put(lane_path, headers=s.csrf, json={"paused": False}))["paused"]
    assert matte.claim("matte").body["job"]["id"] == second
    assert job(s, image_id)["status"] == "running"


@pytest.mark.parametrize("route", ("claim", "heartbeat", "publish", "complete", "fail"))
def test_shared_work_checks_auth_and_size_before_lane_then_validates_body(matte_studio, route):
    s = matte_studio
    http = client(s.app)
    headers = {lane: worker_credentials(s.owner, lane=lane) for lane in ("run", "matte")}
    path = f"{WORK}/{route}"
    body = b'{"lane":"matte","fence":"invalid"}' if route == "claim" else (
        b'{"job_id":"malformed","fence":"invalid"}'
    )
    oversized = b" " * WRITE_LIMIT + body
    for credentials, content, status, code in (
        ({}, oversized, 401, "auth.required"),
        (headers["run"], oversized, 413, "request.too_large"),
        (headers["run"], body, 403, "work.lane_forbidden"),
        (headers["matte"], body, 422, "schema.unknown_field" if route == "claim" else "schema.invalid"),
    ):
        response = http.post(path, headers={**credentials, "content-type": "application/json"}, content=content)
        assert response.status_code == status, response.text
        assert response.json()["error"]["code"] == code


def test_matte_worker_publishes_and_rebuilds_all_pinned_files(matte_studio, matte_format, matte_client, monkeypatch):
    s = matte_studio
    source = opaque(s, scope=None)
    body = payload(source, matte_format)
    api = worker_api(s, lane="matte")
    local, weights = matte_client
    worker = MediaWorker(api, lane="matte", store=s.store, client=local)
    dispatches = []
    recorded_before_send = []
    dispatch = local.run

    def trace(spec, data, **kwargs):
        dispatches.append(spec["job_id"])
        return dispatch(spec, data, **kwargs)

    monkeypatch.setattr(local, "run", trace)
    first = success(request(s, body, "first-press"), 202)["id"]
    with Engine(local.scratch, weights, PROFILE, factory=load_fake) as backend, listening(local.socket, backend):
        run_backend = backend.run

        def read_fence(value):
            with s.owner.connect() as conn:
                row = conn.execute(sa.select(media_jobs.c.id, media_jobs.c.dispatched)
                                   .where(media_jobs.c.lane == "matte", media_jobs.c.worker_id.is_not(None))).one()
            recorded_before_send.append(tuple(row))
            return run_backend(value)

        monkeypatch.setattr(backend, "run", read_fence)
        assert worker.tick()
        finished = job(s, first)
        assert finished["status"] == "succeeded" and finished["result_is_current"] is False, finished.get("error")
        result = success(s.browser.get(f"/v1/jobs/{first}/result"))
        version = result["id"]
        assert result["state"] == "candidate" and result["capabilities"] == ["rgba_cutout", "mask"]
        assert version != source["id"]
        assert all(item["id"] != version for item in success(s.browser.get("/v1/assets"))["items"])
        params = result["provenance"]["generator"]["params"]
        assert params["receipt"]["job_id"] == first and params["normalization"]["slot"] == "a"
        assert params["receipt"]["shape"]["scale"]["numerator"] == 160
        descriptors = (result["content"], params["mask"], params["receipt_blob"])
        paths = [Path(s.store.root) / item["locator"] for item in descriptors]
        expected = [path.read_bytes() for path in paths]
        preview = f'/v1/jobs/{first}/media/{result["content"]["sha256"]}'
        assert s.browser.get(preview, headers={"Range": "bytes=0-7"}).status_code == 206
        assert s.agent.get(preview, headers=s.reader).status_code == 404
        assert s.agent.post(f"/v1/asset-versions/{version}/promote", headers=s.auth).status_code == 403
        promoted = success(s.browser.post(f"/v1/asset-versions/{version}/promote", headers=s.csrf))
        assert promoted == {**result, "state": "promoted"}
        assert s.browser.get(preview).status_code == 200

        for path in paths:
            path.unlink()
        rebuild = success(request(s, body, "restore-missing"), 202)["id"]
        assert worker.tick()
        assert success(s.browser.get(f"/v1/jobs/{rebuild}/result")) == promoted
        assert [path.read_bytes() for path in paths] == expected
        cached = success(request(s, body, "verify-available"), 202)["id"]
        assert worker.tick()
        assert success(s.browser.get(f"/v1/jobs/{cached}/result")) == promoted
    assert dispatches == [first, first]
    assert recorded_before_send == [(first, True), (rebuild, True)]
    latest = {item["id"]: item for item in success(s.browser.get("/v1/assets"))["items"]}
    assert latest[source["id"]] == source and latest[version] == promoted


def assert_failed(studio, identifier, code):
    failed = job(studio, identifier)
    assert failed["status"] == "failed" and failed["result_version_id"] is None
    assert failed["error"]["code"] == code
    assert studio.browser.get(f"/v1/jobs/{identifier}/result").status_code == 404
    with studio.owner.connect() as conn:
        assert not conn.scalar(sa.select(sa.exists().where(
            asset_versions.c.document["provenance"]["source_key"].astext.startswith("matting:"),
            asset_versions.c.document["provenance"]["generator"]["source_asset_version_ids"].contains(
                [failed["target_id"]],
            ),
        )))
    return failed["error"]["message"]


def test_matte_completion_requires_all_canonical_artifacts(matte_studio, matte_format, matte_client, monkeypatch):
    s = matte_studio
    source = opaque(s, scope=s.production_id)
    identifier = success(request(s, payload(source, matte_format), "missing-publish"), 202)["id"]
    local, weights = matte_client
    worker = MediaWorker(worker_api(s, lane="matte"), lane="matte", store=s.store, client=local)
    complete = MediaClaimAPI.complete
    evidence = []

    def lose_mask(claim, body):
        version = body["result"]["matte_version"]
        evidence.append(version["content"]["sha256"])
        mask = version["provenance"]["generator"]["params"]["mask"]
        (Path(s.store.root) / mask["locator"]).unlink()
        return complete(claim, body)

    monkeypatch.setattr(MediaClaimAPI, "complete", lose_mask)
    with Engine(local.scratch, weights, PROFILE, factory=load_fake) as backend, listening(local.socket, backend):
        assert worker.tick()
    assert_failed(s, identifier, "work.result_rejected")
    cutout, = evidence
    assert s.browser.get(f"/v1/jobs/{identifier}/media/{cutout}").status_code == 404
    assert s.browser.get(f"/v1/media/{cutout}").status_code == 404


def test_matte_backend_and_size_refusals_leave_no_candidates(matte_studio, matte_format, matte_client):
    s = matte_studio
    local, weights = matte_client
    worker = MediaWorker(worker_api(s, lane="matte"), lane="matte", store=s.store, client=local)
    with Engine(local.scratch, weights, PROFILE, factory=load_fake) as backend, listening(local.socket, backend):
        for code, value, size, slot in (
            (REQUEST_INVALID, 33, 32, "a"), (COMMAND_FAILED, 55, 256, "a"),
            (RESPONSE_INVALID, 57, 256, "a"), ("matting.shape_invalid", 33, 256, "b"),
        ):
            original = opaque(s, scope=s.production_id, value=value, size=size)
            identifier = success(request(s, payload(original, matte_format, slot), code), 202)["id"]
            assert worker.tick()
            assert_failed(s, identifier, code)
            assert row_of(s, identifier)["matte_releases"] == 0


def test_matte_waits_for_pinned_sidecar_then_runs_in_order(
    matte_studio, matte_format, matte_client, monkeypatch, tmp_path, caplog,
):
    s = matte_studio
    local, weights = matte_client
    marker = tmp_path / "worker-progress"
    worker = MediaWorker(worker_api(s, lane="matte"), lane="matte", store=s.store, client=local,
                         progress=ProgressFile(marker))
    body = payload(opaque(s, scope=s.production_id), matte_format)
    ids = [success(request(s, body, key), 202)["id"] for key in ("first", "second")]

    def waiting(code):
        assert not worker.tick()
        assert all(job(s, identifier)["status"] == "queued" and row_of(s, identifier)["fence"] == 0
                   for identifier in ids)
        line = f"Waiting for the matting sidecar ({code})"
        assert line in caplog.messages
        assert marker.read_text().strip() == line and worker.progress.fresh(5)

    waiting(NOT_FOUND)
    with Engine(local.scratch, weights, PROFILE, factory=load_fake) as backend, listening(local.socket, backend):
        with monkeypatch.context() as patch:
            patch.setattr(backend, "_digest", None)
            waiting(NOT_FOUND)
            patch.setattr(backend, "_digest", "0" * 64)
            waiting(PIN_MISMATCH)
        assert worker.tick()
        assert [job(s, identifier)["status"] for identifier in ids] == ["succeeded", "queued"]
        assert marker.read_text().strip() == "Matting sidecar ready"
        assert worker.tick()
        assert [job(s, identifier)["status"] for identifier in ids] == ["succeeded", "succeeded"]


def test_matte_busy_attempt_prevents_any_claim(matte_studio, matte_format, matte_client, tmp_path, caplog, monkeypatch):
    s = matte_studio
    local, weights = matte_client
    monkeypatch.setattr(local, "pause", lambda seconds: None)
    marker = tmp_path / "worker-progress"
    worker = MediaWorker(worker_api(s, lane="matte"), lane="matte", store=s.store, client=local,
                         progress=ProgressFile(marker))
    identifier = success(request(s, payload(opaque(s, scope=s.production_id), matte_format), "busy"), 202)["id"]
    ctx = multiprocessing.get_context("spawn")
    entered, resume = ctx.Event(), ctx.Event()
    factory = partial(load_waiting_matte, entered=entered, resume=resume)
    prior = request_for(local.scratch, local.profile_sha256, value=77)
    data = (local.scratch / prior["attempt_id"] / "input").read_bytes()
    with Engine(local.scratch, weights, PROFILE, factory=factory) as backend, listening(local.socket, backend):
        with ThreadPoolExecutor(max_workers=1) as pool:
            active = pool.submit(local.run, prior["request"], data, check_fence=lambda: None)
            try:
                assert entered.wait(5)
                assert not worker.tick()
                assert job(s, identifier)["status"] == "queued" and row_of(s, identifier)["fence"] == 0
                line = f"Waiting for the matting sidecar ({BUSY})"
                assert line in caplog.messages and marker.read_text().strip() == line
            finally:
                resume.set()
            active.result(timeout=5)
        assert worker.tick() and job(s, identifier)["status"] == "succeeded"


def test_matte_untracked_busy_requeues_even_at_release_limit(
    matte_studio, matte_format, matte_client, caplog, monkeypatch,
):
    s = matte_studio
    local, weights = matte_client
    body = payload(opaque(s, scope=s.production_id), matte_format)
    first, second = [success(request(s, body, key), 202)["id"] for key in ("occupied", "next")]
    worker = MediaWorker(worker_api(s, lane="matte"), lane="matte", store=s.store, client=local)
    waits = []
    monkeypatch.setattr(local, "pause", waits.append)
    with Engine(local.scratch, weights, PROFILE, factory=load_fake) as backend, listening(local.socket, backend):
        with backend._lock:
            local.ready_for_claim()
            assert not list(local.scratch.glob(".studio-matting-*"))
            for release_count in (1, 2, 3, 3):
                assert not worker.tick()
                view = job(s, first)
                assert view["status"] == "queued" and view["error"] is None
                row = row_of(s, first)
                assert row["matte_releases"] == release_count
                assert row["worker_id"] is None and not row["dispatched"]
                assert not waits
            assert row_of(s, second)["fence"] == 0
            assert f"Waiting for the matting sidecar ({BUSY})" in caplog.messages
        assert worker.tick() and job(s, first)["status"] == "succeeded"


@pytest.mark.parametrize("outages", [1, 4])
def test_matte_engine_loading_at_submission_counts_as_readiness_outage(
    matte_studio, matte_format, matte_client, monkeypatch, outages,
):
    s = matte_studio
    local, weights = matte_client
    body = payload(opaque(s, scope=s.production_id), matte_format)
    first, second = [success(request(s, body, key), 202)["id"] for key in ("loading", "following")]
    call = matting.local_call

    def during_recovery(path, method, *args, **kwargs):
        if method != "POST":
            return call(path, method, *args, **kwargs)
        assert row_of(s, first)["dispatched"]
        # Model the engine's replacement-load state after the readiness probes.
        # The real Unix handler and engine produce the refusal.
        with backend._lock, monkeypatch.context() as patch:
            patch.setattr(backend, "_digest", None)
            reply = call(path, method, *args, **kwargs)
        assert reply == (503, {"code": NOT_FOUND})
        return reply

    with Engine(local.scratch, weights, PROFILE, factory=load_fake) as backend, listening(local.socket, backend):
        with monkeypatch.context() as patch:
            patch.setattr(matting, "local_call", during_recovery)
            for attempt in range(1, outages + 1):
                worker = MediaWorker(worker_api(s, lane="matte"), lane="matte", store=s.store, client=local)
                assert not worker.tick()
                row = row_of(s, first)
                assert row["fence"] == attempt and row["matte_releases"] == min(attempt, 3)
                assert row["claim_until"] is None and row["worker_id"] is None and not row["dispatched"]
                assert row_of(s, second)["fence"] == 0
                assert not list(local.scratch.glob(".studio-matting-*"))
                if attempt <= 3:
                    view = job(s, first)
                    assert view["status"] == "queued" and view["error"] is None
        if outages == 4:
            assert_failed(s, first, "matting.sidecar_unavailable")
        else:
            assert worker.tick() and job(s, first)["status"] == "succeeded"
            assert row_of(s, second)["fence"] == 0


@pytest.mark.parametrize("disconnects", [1, 4])
def test_matte_socket_loss_before_send_releases_with_durable_bound(
    matte_studio, matte_format, matte_client, monkeypatch, disconnects,
):
    s = matte_studio
    local, weights = matte_client
    identifier = success(request(s, payload(opaque(s, scope=s.production_id), matte_format), "race"), 202)["id"]
    real_call = matting.local_call

    def disappear(path, method, *args, **kwargs):
        if method == "POST":
            path.unlink()
        return real_call(path, method, *args, **kwargs)

    with Engine(local.scratch, weights, PROFILE, factory=load_fake) as backend:
        for number in range(1, disconnects + 1):
            # A new worker still sees the count stored by the preceding claim.
            worker = MediaWorker(worker_api(s, lane="matte"), lane="matte", store=s.store, client=local)
            with listening(local.socket, backend), monkeypatch.context() as patch:
                patch.setattr(matting, "local_call", disappear)
                assert not worker.tick()
            row = row_of(s, identifier)
            assert row["fence"] == number and row["matte_releases"] == min(number, 3)
            assert row["claim_until"] is None and row["worker_id"] is None and not row["dispatched"]
            assert not list(local.scratch.glob(".studio-matting-*"))
            if number <= 3:
                view = job(s, identifier)
                assert view["status"] == "queued" and view["error"] is None
        if disconnects == 1:
            with listening(local.socket, backend):
                assert worker.tick()
                assert job(s, identifier)["status"] == "succeeded"
        else:
            assert_failed(s, identifier, "matting.sidecar_unavailable")


@pytest.mark.parametrize("refusal", [403, 404, "transport"])
def test_matte_release_refusal_leaves_claim_to_expire(
    matte_studio, matte_format, matte_client, monkeypatch, caplog, refusal,
):
    s = matte_studio
    local, weights = matte_client
    body = payload(opaque(s, scope=s.production_id), matte_format)
    first, second = [success(request(s, body, key), 202)["id"] for key in ("refused", "following")]
    api = worker_api(s, lane="matte")
    worker = MediaWorker(api, lane="matte", store=s.store, client=local)
    post = api.client.post

    def refuse(path, **kwargs):
        if path == f"{WORK}/release-matte":
            if refusal == "transport":
                raise httpx.ConnectError("fixture transport failure")
            return httpx.Response(refusal, text="fixture listener refusal")
        return post(path, **kwargs)

    def disconnect(path, method, *args, **kwargs):
        if method == "POST":
            path.unlink()
        return call_sidecar(path, method, *args, **kwargs)

    call_sidecar = matting.local_call
    monkeypatch.setattr(api.client, "post", refuse)
    with Engine(local.scratch, weights, PROFILE, factory=load_fake) as backend:
        with listening(local.socket, backend), monkeypatch.context() as patch:
            patch.setattr(matting, "local_call", disconnect)
            assert not worker.tick()
        assert "Matte claim release was not confirmed. The worker will let the claim expire." in caplog.messages
        row = row_of(s, first)
        assert row["matte_releases"] == 0 and row["worker_id"] is not None and row["dispatched"]
        assert not worker.tick()
        assert [job(s, id_)["status"] for id_ in (first, second)] == ["running", "queued"]
        expire(s, first)
        assert not worker.tick()
        assert_failed(s, first, "work.dispatch_unconfirmed")
        with listening(local.socket, backend):
            assert worker.tick() and job(s, second)["status"] == "succeeded"


def test_matte_ready_worker_settles_refused_release_while_paused(
    matte_studio, matte_format, matte_client, monkeypatch,
):
    s = matte_studio
    local, weights = matte_client
    body = payload(opaque(s, scope=s.production_id), matte_format)
    first, second = [success(request(s, body, key), 202)["id"] for key in ("refused", "following")]
    api = worker_api(s, lane="matte")
    worker = MediaWorker(api, lane="matte", store=s.store, client=local)
    post = api.client.post
    releases = []

    def refuse(path, **kwargs):
        if path == f"{WORK}/release-matte":
            releases.append(kwargs["json"])
            return httpx.Response(403, text="fixture listener refusal")
        return post(path, **kwargs)

    monkeypatch.setattr(api.client, "post", refuse)
    with Engine(local.scratch, weights, PROFILE, factory=load_fake) as backend, listening(local.socket, backend):
        with backend._lock:
            assert not worker.tick()
        row = row_of(s, first)
        assert releases == [{"job_id": first, "fence": row["fence"], "reason": "busy"}]
        assert row["dispatched"] and row["matte_releases"] == 0
        local.ready_for_claim()
        lane = "/v1/queue/lanes/matte"
        success(s.browser.put(lane, headers=s.csrf, json={"paused": True}))
        assert not worker.tick() and job(s, first)["status"] == "running"
        expire(s, first)
        assert not worker.tick()
        assert_failed(s, first, "work.dispatch_unconfirmed")
        assert row_of(s, first)["fence"] == row["fence"]
        assert not worker.tick()
        assert job(s, second)["status"] == "queued" and row_of(s, second)["fence"] == 0
        success(s.browser.put(lane, headers=s.csrf, json={"paused": False}))
        assert worker.tick() and job(s, second)["status"] == "succeeded"


def test_matte_slow_publish_reply_leaves_time_for_sidecar_first_byte(
    matte_studio, matte_format, matte_client, monkeypatch,
):
    s = matte_studio
    local, weights = matte_client
    identifier = success(request(s, payload(opaque(s, scope=s.production_id), matte_format), "slow-publish"), 202)["id"]
    api = worker_api(s, lane="matte")
    post = api.client.post
    call_sidecar = matting.local_call
    events = []

    def hold_reply(path, **kwargs):
        result = post(path, **kwargs)
        if path == f"{WORK}/publish":
            assert result.status_code == 204 and row_of(s, identifier)["dispatched"]
            # Model a slow API reply past the real handler's three-second
            # first-byte deadline, within the worker API's 15-second timeout.
            time.sleep(3.25)
            events.append("publish replied")
        return result

    def check_publish(path, method, *args, **kwargs):
        if method == "POST":
            events.append("matte POST")
        return call_sidecar(path, method, *args, **kwargs)

    monkeypatch.setattr(api.client, "post", hold_reply)
    monkeypatch.setattr(matting, "local_call", check_publish)
    monkeypatch.setattr(local, "pause", lambda _: None)
    worker = MediaWorker(api, lane="matte", store=s.store, client=local)
    with Engine(local.scratch, weights, PROFILE, factory=load_fake) as backend, listening(local.socket, backend):
        assert worker.tick()
        assert job(s, identifier)["status"] == "succeeded"
        assert events == ["publish replied", "matte POST"]
        assert row_of(s, identifier)["matte_releases"] == 0


@pytest.mark.parametrize(("socket_error", "code"), [(TimeoutError, TIMEOUT), (ConnectionResetError, NOT_FOUND)])
def test_matte_uncertain_socket_result_after_dispatch_is_recorded(
    matte_studio, matte_format, matte_client, monkeypatch, socket_error, code,
):
    s = matte_studio
    local, weights = matte_client
    body = payload(opaque(s, scope=s.production_id), matte_format)
    worker = MediaWorker(worker_api(s, lane="matte"), lane="matte", store=s.store, client=local)
    now, waits = 0, []

    def pause(seconds):
        nonlocal now
        now += seconds
        waits.append(seconds)

    monkeypatch.setattr(local, "pause", pause)
    monkeypatch.setattr(matting, "monotonic", lambda: now)
    with Engine(local.scratch, weights, PROFILE, factory=load_fake) as backend, listening(local.socket, backend):
        real_call = matting.local_call
        sent = False

        def deadline(path, method, *args, **kwargs):
            nonlocal sent
            if method == "POST":
                sent = True
                raise socket_error
            if sent:
                raise FileNotFoundError
            return real_call(path, method, *args, **kwargs)

        monkeypatch.setattr(matting, "local_call", deadline)
        identifier = success(request(s, body, "uncertain"), 202)["id"]
        assert worker.tick()
        message = assert_failed(s, identifier, code)
        if code == TIMEOUT:
            assert "next sweep" in message
        row = row_of(s, identifier)
        assert row["dispatched"] and row["matte_releases"] == 0
        assert waits[0] == matting.POST_QUIESCENCE_SECONDS
        marker, = local.scratch.glob(".studio-matting-*")
        attempt = local.scratch / marker.name.removeprefix(".studio-matting-")
        assert attempt.is_dir()
        os.utime(marker, (0, time.time() - matting.POST_QUIESCENCE_SECONDS - 1))
        monkeypatch.setattr(matting, "local_call", real_call)
        next_job = success(request(s, body, "after-timeout"), 202)["id"]
        assert worker.tick() and job(s, next_job)["status"] == "succeeded"
        assert not marker.exists() and not attempt.exists()


@pytest.mark.parametrize(("status", "body"), [
    pytest.param(500, {"code": BUSY}, id="wrong-http-status"),
    pytest.param(409, {"code": BUSY, "detail": "Synthetic extra field"}, id="extra-json-field"),
])
def test_matte_invalid_busy_reply_after_inference_does_not_release(
    matte_studio, matte_format, matte_client, monkeypatch, status, body,
):
    s = matte_studio
    local, weights = matte_client
    source = opaque(s, scope=s.production_id)
    identifier = success(request(s, payload(source, matte_format), "invalid-busy"), 202)["id"]
    worker = MediaWorker(worker_api(s, lane="matte"), lane="matte", store=s.store, client=local)
    real_call = matting.local_call
    waits = []

    def invalid_busy(path, method, *args, **kwargs):
        reply = real_call(path, method, *args, **kwargs)
        if method == "POST":
            # Replace the reply only after the real engine has completed inference.
            assert reply[0] == 200
            assert row_of(s, identifier)["dispatched"]
            return status, body
        return reply

    monkeypatch.setattr(matting, "local_call", invalid_busy)
    monkeypatch.setattr(local, "pause", waits.append)
    with Engine(local.scratch, weights, PROFILE, factory=load_fake) as backend, listening(local.socket, backend):
        handled = worker.tick()
    assert_failed(s, identifier, RESPONSE_INVALID)
    assert handled
    row = row_of(s, identifier)
    assert row["dispatched"] and row["matte_releases"] == 0
    assert waits == [matting.POST_QUIESCENCE_SECONDS]


def test_matte_reclaim_refuses_stale_fence_and_duplicate_completion(
    matte_studio, matte_format, matte_client, monkeypatch,
):
    s = matte_studio
    identifier = success(request(s, payload(opaque(s, scope=s.production_id), matte_format), "reclaim"), 202)["id"]
    api = worker_api(s, lane="matte")
    stale = api.claim("matte")
    expire(s, identifier)
    current = api.claim("matte")
    assert current.identity == {**stale.identity, "fence": stale.identity["fence"] + 1}
    conflict(stale.publish)
    conflict(lambda: retire(stale))
    conflict(stale.release)
    conflict(lambda: stale.release(reason="busy"))
    assert job(s, identifier)["status"] == "running" and not row_of(s, identifier)["dispatched"]

    complete = MediaClaimAPI.complete

    def complete_once(claim, evidence):
        conflict(lambda: complete(stale, evidence))
        finished = complete(claim, evidence)
        assert finished["status"] == "succeeded"
        conflict(lambda: complete(claim, evidence))
        return finished

    monkeypatch.setattr(MediaClaimAPI, "complete", complete_once)
    monkeypatch.setattr(api, "claim", lambda lane: current)
    local, weights = matte_client
    worker = MediaWorker(api, lane="matte", store=s.store, client=local)
    with Engine(local.scratch, weights, PROFILE, factory=load_fake) as backend, listening(local.socket, backend):
        assert worker.tick() and job(s, identifier)["status"] == "succeeded"


def test_matte_expiry_after_dispatch_fails_without_reclaim(matte_studio, matte_format):
    s = matte_studio
    body = payload(opaque(s, scope=s.production_id), matte_format)
    first, second = [success(request(s, body, key), 202)["id"] for key in ("dispatched", "following")]
    api = worker_api(s, lane="matte")
    claim = api.claim("matte")
    assert claim.identity["job_id"] == first
    claim.publish()
    conflict(claim.release, "work.dispatched")
    with pytest.raises(WorkerAPIError) as invalid:
        claim.release(reason="transport")
    assert invalid.value.status == 422
    expire(s, first)
    assert api.claim("matte") is None
    assert_failed(s, first, "work.dispatch_unconfirmed")
    assert api.claim("matte").identity["job_id"] == second


def test_matte_waiting_worker_settles_only_expired_dispatched_claims(matte_studio, matte_format, matte_client):
    s = matte_studio
    local, weights = matte_client
    body = payload(opaque(s, scope=s.production_id), matte_format)
    first, second = [success(request(s, body, key), 202)["id"] for key in ("abandoned", "following")]
    api = worker_api(s, lane="matte")
    worker = MediaWorker(api, lane="matte", store=s.store, client=local)
    assert not worker.tick() and row_of(s, first)["fence"] == 0
    abandoned = api.claim("matte")
    expire(s, first)
    assert not worker.tick() and row_of(s, first)["fence"] == abandoned.identity["fence"]
    current = api.claim("matte")
    # Even a paused lane must settle the abandoned dispatch while the socket
    # is absent. The next job must remain untouched.
    lane = "/v1/queue/lanes/matte"
    success(s.browser.put(lane, headers=s.csrf, json={"paused": True}))
    current.publish()
    assert not worker.tick() and job(s, first)["status"] == "running"
    expire(s, first)
    assert not worker.tick()
    assert_failed(s, first, "work.dispatch_unconfirmed")
    success(s.browser.put(lane, headers=s.csrf, json={"paused": False}))
    assert not worker.tick()
    assert job(s, second)["status"] == "queued" and row_of(s, second)["fence"] == 0
    with Engine(local.scratch, weights, PROFILE, factory=load_fake) as backend, listening(local.socket, backend):
        assert worker.tick() and job(s, second)["status"] == "succeeded"


def test_matte_migration_round_trip_and_downgrade_refusal(matte_studio, matte_format, runtime_role):
    s = matte_studio
    migrate(s.owner, direction="downgrade", target="0012_release_constraints")
    with s.owner.connect() as conn:
        assert conn.exec_driver_sql("SELECT lane FROM media_job_lanes ORDER BY lane").scalars().all() == ["image", "voice"]
    migrate(s.owner, target="0013_matte_jobs", runtime_role=runtime_role[0])
    original = opaque(s, scope=s.production_id)
    queued = success(request(s, payload(original, matte_format), "durable-matte"), 202)
    with pytest.raises(sa.exc.IntegrityError):
        migrate(s.owner, direction="downgrade", target="0012_release_constraints")
    assert job(s, queued["id"])["status"] == "queued"
