"""Exercise matte admission, fencing and publication through Studio's serving paths."""

import asyncio
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import numpy as np
import pytest
import sqlalchemy as sa

from haynes_studio.adapters import matting
from haynes_studio.adapters.matting import MattingClient
from haynes_studio.canonical.ids import Minter
from haynes_studio.db.catalog import record_asset_version
from haynes_studio.db.migrate import migrate
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
from haynes_studio.queue.worker_api import MediaClaimAPI
from haynes_studio.store import LIBRARY

from tests.assets.test_candidates import BY, NOW
from tests.db.test_media_jobs import (
    board_in, client, engine, job, owner_engine, register_agent, runtime_db, runtime_role, service, studio,
    success, upload,
)
from tests.db.test_run_queue import worker_api, worker_credentials
from tests.formats.fixtures import doll_short
from tests.matting.test_backend import PROFILE, load_fake, prepared
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
        refused(lane, "claim", 403 if lane is None else 422,
                "work.lane_forbidden" if lane is None else "schema.invalid",
                content=b'{"lane":"matte",')
    for lane in ("run", "image", "voice"):
        refused("matte", "claim", 403, "work.lane_forbidden", json={"lane": lane})
        refused("matte", "claim", 422, "schema.unknown_field", json={"lane": lane, "extra": True})
    refused("matte", "claim", 403, "work.lane_forbidden")
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


def test_matte_worker_publishes_and_rebuilds_all_pinned_files(matte_studio, matte_format, matte_client, monkeypatch):
    s = matte_studio
    source = opaque(s, scope=None)
    body = payload(source, matte_format)
    api = worker_api(s, lane="matte")
    local, weights = matte_client
    worker = MediaWorker(api, lane="matte", store=s.store, client=local)
    dispatches = []
    dispatch = local.run

    def trace(spec, data, **kwargs):
        dispatches.append(spec["job_id"])
        return dispatch(spec, data, **kwargs)

    monkeypatch.setattr(local, "run", trace)
    first = success(request(s, body, "first-press"), 202)["id"]
    with Engine(local.scratch, weights, PROFILE, factory=load_fake) as backend, listening(local.socket, backend):
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


def test_matte_busy_pin_missing_and_timeout_are_recorded(matte_studio, matte_format, matte_client, monkeypatch):
    s = matte_studio
    local, weights = matte_client
    original = opaque(s, scope=s.production_id)
    body = payload(original, matte_format)
    worker = MediaWorker(worker_api(s, lane="matte"), lane="matte", store=s.store, client=local)
    missing = success(request(s, body, "missing-backend"), 202)["id"]
    assert worker.tick()
    assert_failed(s, missing, NOT_FOUND)

    now, waits = 0, []

    def pause(seconds):
        nonlocal now
        now += seconds
        waits.append(seconds)

    monkeypatch.setattr(local, "pause", pause)
    monkeypatch.setattr(matting, "monotonic", lambda: now)
    with Engine(local.scratch, weights, PROFILE, factory=load_fake) as backend, listening(local.socket, backend):
        monkeypatch.setattr(local, "profile_sha256", "0" * 64)
        bad_pin = success(request(s, body, "pin-refused"), 202)["id"]
        assert worker.tick()
        assert_failed(s, bad_pin, PIN_MISMATCH)
        monkeypatch.setattr(local, "profile_sha256", backend.readiness["profile_sha256"])

        # The real socket reports busy while another request owns the engine.
        with backend._lock:
            busy = success(request(s, body, "busy"), 202)["id"]
            assert worker.tick()
            assert_failed(s, busy, BUSY)
        assert waits == [matting.BUSY_INTERVAL] * matting.BUSY_RETRIES

        real_call = matting.local_call
        sent = False

        def deadline(path, method, *args, **kwargs):
            nonlocal sent
            if method == "POST":
                sent = True
                raise TimeoutError
            if sent:
                raise FileNotFoundError
            return real_call(path, method, *args, **kwargs)

        monkeypatch.setattr(matting, "local_call", deadline)
        timed = success(request(s, body, "timeout"), 202)["id"]
        assert worker.tick()
        assert "next sweep" in assert_failed(s, timed, TIMEOUT)
        marker, = local.scratch.glob(".studio-matting-*")
        attempt = local.scratch / marker.name.removeprefix(".studio-matting-")
        assert attempt.is_dir()
        os.utime(marker, (0, time.time() - matting.POST_QUIESCENCE_SECONDS - 1))
        monkeypatch.setattr(matting, "local_call", real_call)
        next_job = success(request(s, body, "after-timeout"), 202)["id"]
        assert worker.tick() and job(s, next_job)["status"] == "succeeded"
        assert not marker.exists() and not attempt.exists()


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
