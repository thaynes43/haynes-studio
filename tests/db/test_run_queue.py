"""Queue acceptance through the runtime role, fake Wan and a fake clock."""

import asyncio
import hashlib
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
import sqlalchemy as sa

from haynes_studio.adapters import wan
from haynes_studio.api.app import create_app
from haynes_studio.api.auth import SESSION_COOKIE
from haynes_studio.api.oidc import random_secret
from haynes_studio.canonical.ids import Minter
from haynes_studio.db import identity, runs
from haynes_studio.db.catalog import record_asset_version
from haynes_studio.db.schema import run_wan_attempts, worker_tokens
from haynes_studio.queue.wan import LanePaused, ProductClips, ProductWan, product_request
from haynes_studio.queue.worker import BuildWorker
from haynes_studio.queue.worker_api import WorkerAPI, WorkerAPIError

from tests.build_story.fixtures import example, photo_png, register
from tests.db.test_studio_api import (
    bearer, client, engine, new_production, new_story, owner_engine,
    register_agent, runtime_db, runtime_role, service, sign_in,
)
from tests.queue.fake_wan import Clock, FakeWan, STORY

pytestmark = pytest.mark.db


def worker_credentials(engine):
    secret = random_secret()
    with engine.begin() as conn:
        conn.execute(worker_tokens.insert().values(digest=identity.digest(secret),
                                                   worker_id="fixture-" + Minter().mint("run")))
    return bearer(secret)


class LocalWorkerHTTP:
    """Adapt TestClient to the worker's POST-only HTTP interface."""
    def __init__(self, app, headers):
        self.client = client(app)
        self.headers = headers

    def post(self, url, **kwargs):
        return self.client.post(url, headers=self.headers, **kwargs)


@pytest.fixture
def queue(service, engine, owner_engine, monkeypatch, tmp_path):
    app, store, issuer = service
    stage_root = tmp_path / "build-staging"
    stage_root.mkdir()
    app.state.build_stage_root = stage_root
    with owner_engine.begin() as conn:
        conn.exec_driver_sql("TRUNCATE run_check_overrides, run_wan_attempts, runs")
        conn.exec_driver_sql("UPDATE run_lane SET next_position = 1, worker_seen_at = NULL")
    clock = Clock()
    monkeypatch.setattr(runs, "database_time", clock.db_time)
    browser = client(app)
    csrf = sign_in(browser, issuer)
    production_id = new_production(browser, csrf)
    story_id = new_story(browser, csrf, production_id)
    png = photo_png()
    response = browser.post(f"/v1/stories/{story_id}/boards",
                            headers={**csrf, "If-Match": "1"},
                            json={"timing": {"lead_ms": None, "tail_ms": None, "hold_ms": 500}, "seeds": {"i2v:frame": 5}})
    assert response.status_code == 201, response.text
    board = response.json()
    blob = store.publish(png, scope=production_id, media_type="image/png")
    version_id = Minter().mint("asv")
    version = example("asset-version-photo-external.json")
    version.update(id=version_id, asset_id=Minter().mint("ast"),
                   scope={"production_id": production_id, "story_id": story_id, "board_id": board["id"]})
    version["content"].update(sha256=blob.sha256, bytes=blob.bytes, locator=blob.locator,
                              width=144, height=256)
    version["provenance"]["generator"]["source_asset_version_ids"] = []
    with engine.begin() as conn:
        record_asset_version(conn, version)
    response = browser.patch(f'/v1/boards/{board["id"]}', headers={**csrf, "If-Match": "1"},
                             json={"photo": {"current_version_id": version_id, "prompt": "first angle",
                                             "input_asset_version_ids": []}})
    assert response.status_code == 200, response.text
    return SimpleNamespace(app=app, store=store, issuer=issuer, browser=browser, csrf=csrf,
                           engine=engine, owner=owner_engine, clock=clock, story_id=story_id,
                           stage_root=stage_root,
                           production_id=production_id, board_id=board["id"], version_id=version_id,
                           png=png)


def queue_run(q, key, *, rev=3, headers=None):
    return q.browser.post(f"/v1/stories/{q.story_id}/runs",
                          headers={**(q.csrf if headers is None else headers),
                                   "Idempotency-Key": key, "If-Match": str(rev)})


def worker_api(q, *, app=None, headers=None):
    if headers is None:
        headers = worker_credentials(q.owner)
    return WorkerAPI(LocalWorkerHTTP(app or q.app, headers))


def read_run(q, run_id):
    response = q.browser.get(f"/v1/runs/{run_id}")
    assert response.status_code == 200
    return response.json(), response.headers["etag"]


def cancel(q, run_id, etag, *, auth=None):
    return q.browser.post(f"/v1/runs/{run_id}/cancel",
                          headers={**(q.csrf if auth is None else auth), "If-Match": etag})


def request_for(q):
    return wan.ImageToVideo(q.png, "An invented doll", 7, STORY, width=64, height=64, length=5)


def clips_for(q, claim, client_):
    return ProductClips(claim, ProductWan(client_), story=STORY,
                        progress=lambda stage, **options: claim.heartbeat(),
                        clock=q.clock.monotonic, pause=q.clock.advance)


def test_queued_inputs_order_estimate_idempotency_and_production_scope(queue):
    q = queue
    assert worker_api(q).claim() is None
    _, agent = register_agent(q.owner, {q.production_id: ["read", "runs:queue"]})
    _, reader = register_agent(q.owner, {q.production_id: ["read"]})
    assert queue_run(q, "refused", headers=reader).status_code == 403
    assert queue_run(q, "stale", rev=2, headers=agent).json()["error"]["code"] == "conflict.revision"
    estimate = q.browser.get(f"/v1/stories/{q.story_id}/estimate", headers=agent).json()
    assert estimate["estimate"]["uncertain"]
    assert estimate["methods"] == [{"method": "whole_frame/i2v", "chunks": 1, "gpu_wall_s": [90, 210]}]
    assert estimate["queue_wait"]["wall_s"] == [0, 0]
    first = queue_run(q, "first", headers=agent)
    assert first.status_code == 201, first.text
    first = first.json()
    frozen_path = first["snapshot"]["locator"]
    with q.store.open(frozen_path) as handle:
        frozen = handle.read()
    assert hashlib.sha256(frozen).hexdigest() == first["snapshot"]["sha256"]
    updated = q.browser.patch(f"/v1/stories/{q.story_id}", json={"title": "Revision four"},
                              headers={**q.csrf, "If-Match": "3"})
    assert updated.status_code == 200, updated.text
    replay = queue_run(q, "first", headers=agent)
    assert replay.status_code == 200 and replay.json() == first
    assert queue_run(q, "first", rev=4, headers=agent).json()["error"]["code"] == "idempotency.mismatch"
    second = queue_run(q, "second", rev=4, headers=agent)
    assert second.status_code == 201, second.text
    second = second.json()
    assert second["number"] == first["number"] + 1 and second["queue_wait"]["ahead"] == 1
    assert second["snapshot"]["sha256"] != first["snapshot"]["sha256"]
    with q.store.open(frozen_path) as handle:
        assert handle.read() == frozen
    page = q.browser.get(f"/v1/stories/{q.story_id}/runs", params={"limit": 1}, headers=agent).json()
    assert page["items"][0]["id"] == page["next_cursor"] == first["id"]
    next_page = q.browser.get(f"/v1/stories/{q.story_id}/runs", params={"cursor": page["next_cursor"]},
                              headers=agent).json()
    assert next_page["items"][0]["id"] == second["id"]
    _, unscoped = register_agent(q.owner, {})
    assert q.browser.get(f'/v1/runs/{first["id"]}', headers=unscoped).status_code == 403
    cancelled = cancel(q, first["id"], '"1"', auth=agent)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert cancel(q, first["id"], '"1"', auth=agent).status_code == 409
    assert worker_api(q).claim().identity["run_id"] == second["id"]


def test_worker_auth_rejects_credentials_before_body_or_query(queue):
    q = queue
    _, agent = register_agent(q.owner, {q.production_id: ["runs:queue"]})
    # Use a real signed-in cookie and a real agent key from this API.
    session = {"cookie": f"{SESSION_COOKIE}={q.browser.cookies.get(SESSION_COOKIE)}"}
    h = worker_credentials(q.owner)
    for headers in ({}, agent, session):
        for path in ("claim", "heartbeat", "attempts", "complete", "fail"):
            response = q.browser.post(f"/internal/v1/work/{path}?q=%00", headers=headers, content=b"{")
            assert response.status_code == 401, response.text
            assert response.json()["error"]["code"] == "auth.required"
    assert q.browser.post("/internal/v1/work/claim?q=%00", headers=h).status_code == 422
    assert q.browser.post("/internal/v1/work/heartbeat", headers=h, content=b"{").status_code == 422
    assert q.browser.get("/v1/me", headers=h).status_code == 401
    # Prove the route never received even the first byte from an unauthenticated body.
    messages = []

    async def test_receive():
        raise AssertionError("untrusted body was read")

    async def send(message):
        messages.append(message)

    asyncio.run(q.app({"type": "http", "method": "POST", "scheme": "https", "path": "/internal/v1/work/complete",
                      "query_string": b"q=%00", "root_path": "", "headers": []}, test_receive, send))
    assert messages[0]["status"] == 401


def test_fencing_skips_locked_head_and_survives_api_restart(queue):
    q = queue
    first, second = [queue_run(q, key).json() for key in ("first", "second")]
    a, b = worker_api(q), worker_api(q)
    with q.engine.begin() as conn:
        runs.get(conn, first["id"], lock=True)
        assert a.claim() is None and b.claim() is None
    with ThreadPoolExecutor(max_workers=2) as pool:
        one, other = [f.result() for f in (pool.submit(a.claim), pool.submit(b.claim))]
    claims = [claim for claim in (one, other) if claim is not None]
    assert len(claims) == 1
    abandoned = claims[0]
    assert abandoned.identity["run_id"] == first["id"]
    assert abandoned.body["snapshot"]["story"]["boards"][0]["photo"]["current_version_id"] == q.version_id
    assert b.claim() is None
    restarted = create_app(q.engine, q.store, q.app.state.oidc)
    assert worker_api(q, app=restarted).claim() is None
    q.clock.advance(91)
    takeover = worker_api(q, app=restarted).claim()
    assert takeover.identity == {"run_id": first["id"], "fence": abandoned.identity["fence"] + 1}
    assert takeover.body["run"]["status"] == "held"
    with pytest.raises(WorkerAPIError, match="work.fence_lost"):
        abandoned.heartbeat()
    with pytest.raises(WorkerAPIError, match="work.fence_lost"):
        abandoned.fail(status="failed", reason="stale")
    takeover.resume()
    takeover.fail(status="failed", reason="fixture finished")
    assert worker_api(q).claim().identity["run_id"] == second["id"]


def test_runtime_grants_protect_frozen_inputs_and_attempt_ids(queue):
    q = queue
    run = queue_run(q, "first").json()
    c = worker_api(q).claim()
    attempt = c.reserve("i2v", product_request(request_for(q)))
    pairs = ((runs.runs, {"snapshot": {}}), (runs.runs, {"position": 3}),
             (run_wan_attempts, {"job_id": "0" * 32}),
             (run_wan_attempts, {"request": {}}), (runs.run_check_overrides, {"document": {}}))
    for table, fields in pairs:
        with q.engine.connect() as conn, pytest.raises(sa.exc.ProgrammingError) as refused:
            conn.execute(table.update().values(**fields))
        assert refused.value.orig.sqlstate == "42501"
    assert attempt["run_id"] == run["id"] and attempt["state"] == "reserved"


def test_lost_put_reply_and_slow_poll_use_the_recorded_id(queue, monkeypatch):
    q = queue
    queue_run(q, "recover")
    claim = worker_api(q).claim()
    fake = FakeWan()
    fake.lose_reply = True
    fake.poll_misses = 2
    monkeypatch.setattr(wan, "measure_clip", lambda data: wan.Measured(5, 64, 64, "24"))
    with fake.client() as wan_http:
        clip = clips_for(q, claim, wan_http).make(request_for(q), stage="fixture")
    assert len(fake.puts()) == 1
    assert fake.events.count(("GET", fake.puts()[0])) == 3
    run, _ = read_run(q, claim.identity["run_id"])
    assert run["wan_attempts"] == [{"job_id": clip.job_id, "kind": "i2v", "attempt": 1, "state": "succeeded"}]


def test_lost_id_holds_fifo_and_recovery_reads_it_before_any_put(queue):
    q = queue
    first = queue_run(q, "first").json()["id"]
    queue_run(q, "next")
    claim = worker_api(q).claim()
    fake = FakeWan()
    fake.disappear = True
    with fake.client() as wan_http:
        with pytest.raises(LanePaused, match="sent ID") as paused:
            clips_for(q, claim, wan_http).make(request_for(q), stage="fixture")
        assert paused.value.code == "wan.ambiguous_submit"
        claim.fail(status="held", reason="Wan lacks the sent ID")
        q.clock.advance(16)
        recovery = worker_api(q).claim()
        assert recovery.identity["run_id"] == first
        with pytest.raises(LanePaused, match="sent ID"):
            clips_for(q, recovery, wan_http).reconcile()
        with pytest.raises(WorkerAPIError, match="wan.unsettled"):
            recovery.resume()
    assert len(fake.puts()) == 1
    assert fake.events[-1] == ("GET", fake.puts()[0])


def test_expired_claim_drains_an_owned_job_and_cancel_blocks_next_submission(queue, monkeypatch):
    q = queue
    first = queue_run(q, "cancel").json()["id"]
    second = queue_run(q, "next").json()["id"]
    claim = worker_api(q).claim()
    body = product_request(request_for(q))
    attempt = claim.reserve("i2v", body)
    claim.attempt(attempt["job_id"], "sent")
    with pytest.raises(WorkerAPIError, match="wan.attempt_state"):
        claim.attempt(attempt["job_id"], "sent")
    fake = FakeWan()
    monkeypatch.setattr(wan, "measure_clip", lambda data: wan.Measured(5, 64, 64, "24"))
    with fake.client() as wan_http:
        product = ProductWan(wan_http)
        product.stage(q.png, body["image_sha256"], "png")
        product.submit(attempt)
        _, etag = read_run(q, first)
        requested = cancel(q, first, etag).json()
        assert requested["cancel_requested"] and requested["status"] == "running"
        q.clock.advance(91)
        replacement = worker_api(q).claim()
        assert replacement.identity["run_id"] == first
        clips_for(q, replacement, wan_http).reconcile()
        assert replacement.heartbeat()["cancel_requested"]
        with pytest.raises(WorkerAPIError, match="run.stopping"):
            replacement.publish()
        replacement.fail(status="cancelled", reason="Existing Wan attempt reconciled")
    assert len(fake.puts()) == 1
    assert read_run(q, first)[0]["status"] == "cancelled"
    assert worker_api(q).claim().identity["run_id"] == second


def test_wan_restart_retries_one_new_id_and_unknown_work_holds(queue, monkeypatch):
    q = queue
    first = queue_run(q, "restart").json()["id"]
    claim = worker_api(q).claim()
    fake = FakeWan()
    fake.restart_failures = 1
    fake.foreign = True
    monkeypatch.setattr(wan, "measure_clip", lambda data: wan.Measured(5, 64, 64, "24"))
    with fake.client() as wan_http:
        with pytest.raises(LanePaused) as paused:
            clips_for(q, claim, wan_http).make(request_for(q), stage="fixture")
        assert paused.value.code == "wan.foreign_work"
        claim.fail(status="held", reason="Foreign work",
                   error={"code": "wan.foreign_work", "message": "Foreign work", "stage": "wan",
                          "board_id": None})
        assert len(fake.puts()) == 1
        q.clock.advance(16)
        replacement = worker_api(q).claim()
        fake.foreign = False
        source = clips_for(q, replacement, wan_http)
        fake.held = True
        with pytest.raises(LanePaused) as paused:
            source.reconcile()
        assert paused.value.code == "wan.foreign_work"
        fake.held = False
        source.reconcile()
        replacement.resume()
        clip = source.make(request_for(q), stage="fixture")
    assert len(set(fake.puts())) == 2
    assert fake.events.index(("GET", fake.puts()[0])) < fake.events.index(("PUT", fake.puts()[1]))
    states = {item["job_id"]: item["state"] for item in read_run(q, first)[0]["wan_attempts"]}
    assert states == {fake.puts()[0].rsplit("/", 1)[-1]: "restart_failed", clip.job_id: "succeeded"}


def test_talosw01_unavailable_pauses_queue_but_crud_still_works(queue):
    q = queue
    run_id = queue_run(q, "outage").json()["id"]
    fake = FakeWan()
    fake.outage = True
    with fake.client() as wan_http:
        worker = BuildWorker(worker_api(q), ProductWan(wan_http), store=q.store, stage_root=q.stage_root,
                             register=register(),
                             tracker_story=STORY, transcriber=None, clock=q.clock.monotonic,
                             pause=q.clock.advance)
        assert worker.tick()
        run, _ = read_run(q, run_id)
        assert run["status"] == "queued" and run["wait_reason"] == "gpu_unavailable"
        assert run["queue_wait"]["wall_s"] is None
        assert q.browser.patch(f"/v1/stories/{q.story_id}", headers={**q.csrf, "If-Match": "3"},
                               json={"title": "Still editable"}).status_code == 200
        assert not worker.tick()
    assert fake.puts() == []


def test_only_a_person_can_append_an_override_without_mutating_the_run(queue):
    q = queue
    run_id = queue_run(q, "checks").json()["id"]
    claim = worker_api(q).claim()
    hash_ = "0" * 64
    checks = [{"check": "layered.decal_gate", "result": "fail", "artifact": hash_, "value": 0.7},
              {"check": "frame_count", "result": "fail", "artifact": hash_}]
    claim.fail(status="failed", reason="Fixture check failure", checks=checks)
    original, etag = read_run(q, run_id)
    _, agent = register_agent(q.owner, {q.production_id: ["runs:queue"]})
    body = {"artifact": hash_, "reason": "The decal stays readable in the affected frames"}
    path = f"/v1/runs/{run_id}/checks"
    assert q.browser.post(f"{path}/layered.decal_gate/overrides", json=body,
                          headers={**agent, "If-Match": etag}).status_code == 403
    assert q.browser.post(f"{path}/frame_count/overrides", json=body,
                          headers={**q.csrf, "If-Match": etag}).status_code == 403
    result = q.browser.post(f"{path}/layered.decal_gate/overrides", json=body,
                            headers={**q.csrf, "If-Match": etag})
    assert result.status_code == 201, result.text
    current, _ = read_run(q, run_id)
    assert current["status"] == "failed" and current["checks"] == original["checks"]
    assert current["check_overrides"] == [result.json()]
    assert result.json()["by"]["kind"] == "human"


def test_worker_recovers_staged_delivery_then_registers_private_playback(queue, tmp_path):
    from tests.delivery.media import write_master
    from tests.support.synthetic import write_sine_wav

    q = queue
    audio = write_sine_wav(tmp_path / "bed.wav", seconds=2.5, rate=48000).read_bytes()
    blob = q.store.publish(audio, scope=q.production_id, media_type="audio/wav")
    version = example("asset-version-cast.json")
    version.update(id=Minter().mint("asv"), asset_id=Minter().mint("ast"), kind="sound",
                   name="Synthetic bed", scope={"production_id": q.production_id},
                   labels=[], attributes={}, capabilities=["sound_bed"], legacy=None,
                   content={"sha256": blob.sha256, "bytes": blob.bytes, "locator": blob.locator,
                            "media_type": "audio/wav"})
    version["provenance"].update(generator={"role": "sound", "engine": "Synthetic test sine"}, source_key=None)
    with q.engine.begin() as conn:
        record_asset_version(conn, version)
    update = q.browser.patch(f"/v1/stories/{q.story_id}", headers={**q.csrf, "If-Match": "3"},
                             json={"beds": [{"type": "bed", "asset_version_id": version["id"],
                                             "level_rms_dbfs": -24, "clock": "film"}]})
    assert update.status_code == 200, update.text
    response = queue_run(q, "real-fixture", rev=4)
    assert response.status_code == 201, response.text
    run_id = response.json()["id"]
    queued = response.json()["snapshot"]

    # The fixture proves a real encode and authenticated proxy read, with no GPU.
    clip = write_master(tmp_path / "wan-fixture.mp4", frames=121, width=576, height=1024,
                        audio_codec=None).read_bytes()
    fake = FakeWan(clip)
    fake.lose_reply = True
    class StopBeforeCompletion(LocalWorkerHTTP):
        def post(self, url, **kwargs):
            if url.endswith("/complete"):
                from haynes_studio.store import MISSING, blob_locator

                sha = kwargs["json"]["outputs"]["proxy_sha256"]
                locator = blob_locator(q.production_id, sha, "video/mp4")
                assert q.store.verify(locator, sha) == MISSING
                raise httpx.ReadTimeout("worker disappeared before the API received completion")
            return super().post(url, **kwargs)

    with fake.client() as wan_http:
        options = dict(store=q.store, stage_root=q.stage_root, register=register(), tracker_story=STORY,
                       transcriber=SimpleNamespace(name="Fixture ASR", transcribe=lambda _: ""),
                       clock=q.clock.monotonic, pause=q.clock.advance)
        before = WorkerAPI(StopBeforeCompletion(q.app, worker_credentials(q.owner)))
        worker = BuildWorker(before, ProductWan(wan_http), **options)
        with pytest.raises(WorkerAPIError, match="work.transport"):
            worker.tick()
        assert read_run(q, run_id)[0]["status"] == "running"
        q.clock.advance(91)
        restarted = create_app(q.engine, q.store, q.app.state.oidc, build_stage_root=q.stage_root)
        worker = BuildWorker(worker_api(q, app=restarted), ProductWan(wan_http), **options)
        assert worker.tick()
        assert not worker.tick()
    result, _ = read_run(q, run_id)
    assert result["status"] == "succeeded", result["error"]
    assert result["snapshot"] == queued
    assert [transition["to"] for transition in result["transitions"]] == [
        "queued", "running", "held", "running", "succeeded",
    ]
    assert result["progress"] == {"percent": 100, "stage": "delivered"}
    assert len(fake.puts()) == 1
    assert result["wan_attempts"][0]["job_id"] == result["stages"][0]["clips"][0]["clips"][0]["engine_job_id"]
    assert any(c["check"] == "master.transcript" and c["result"] == "pass" for c in result["checks"])
    proxy_sha = result["outputs"]["proxy_sha256"]
    media = q.browser.get(f"/v1/media/{proxy_sha}", headers={"Range": "bytes=0-31"})
    assert media.status_code == 206 and len(media.content) == 32
    delivery = q.browser.get(f"/v1/runs/{run_id}/delivery").json()
    assert delivery["id"] == result["delivery_id"]
    assert delivery["proxy"]["sha256"] == proxy_sha


@pytest.mark.parametrize("contents", [b"too short", b"not the same checksum!", b"longer than the recorded Wan clip"])
def test_result_mismatch_keeps_job_unsettled(queue, contents):
    q = queue
    queue_run(q, "bad-download")
    claim = worker_api(q).claim()
    fake = FakeWan(b"this is the real clip!")
    fake.corrupt = contents
    with fake.client() as wan_http, pytest.raises(LanePaused, match="bytes|byte count") as refused:
        clips_for(q, claim, wan_http).make(request_for(q), stage="fixture")
    assert refused.value.code == "wan.result_invalid"
    run, _ = read_run(q, claim.identity["run_id"])
    assert run["wan_attempts"][0]["state"] == "sent"
    assert len(fake.puts()) == 1


def test_s2v_stages_both_hashes_and_uses_the_chunk_clock(queue, tmp_path, monkeypatch):
    from tests.support.synthetic import write_sine_wav

    q = queue
    queue_run(q, "s2v")
    claim = worker_api(q).claim()
    drive = write_sine_wav(tmp_path / "drive.wav", seconds=119 / 24, rate=24000).read_bytes()
    request = wan.SpeechToVideo(q.png, drive, 119, "A doll speaks", 7, STORY, width=64, height=64)
    fake = FakeWan()
    monkeypatch.setattr(wan, "measure_clip",
                        lambda data: wan.Measured(request.frames_expected, 64, 64, "16"))
    with fake.client() as wan_http:
        clip = clips_for(q, claim, wan_http).make(request, stage="fixture")
    assert clip.record["frames_requested"] == 154 and clip.record["frames_delivered"] == 158
    assert set(fake.inputs) == {request.image_sha256, hashlib.sha256(drive).hexdigest()}
    assert fake.puts() == [f"/v1/jobs/s2v/{clip.job_id}"]


def test_restart_before_send_reads_reserved_id_then_sends_once(queue, monkeypatch):
    q = queue
    queue_run(q, "reserved")
    old = worker_api(q).claim()
    request = product_request(request_for(q))
    attempt = old.reserve("i2v", request)
    q.clock.advance(91)
    new = worker_api(q).claim()
    with pytest.raises(WorkerAPIError, match="work.fence_lost"):
        old.attempt(attempt["job_id"], "sent")
    fake = FakeWan()
    monkeypatch.setattr(wan, "measure_clip", lambda data: wan.Measured(5, 64, 64, "24"))
    with fake.client() as wan_http:
        source = clips_for(q, new, wan_http)
        source.reconcile()
        new.resume()
        assert new.reserve("i2v", {**request, "story": STORY.replace("410", "437")}) == attempt
        clip = source.make(request_for(q), stage="fixture")
    assert clip.job_id == attempt["job_id"]
    assert len(fake.puts()) == 1
    assert fake.events[0] == ("GET", fake.puts()[0])


def test_refusal_and_foreign_engine_queue_never_start_the_next_run(queue):
    q = queue
    one = queue_run(q, "first").json()["id"]
    queue_run(q, "second")
    claim = worker_api(q).claim()
    fake = FakeWan()
    fake.busy = True
    with fake.client() as wan_http:
        source = clips_for(q, claim, wan_http)
        with pytest.raises(LanePaused, match="shared lease") as busy:
            source.make(request_for(q), stage="fixture")
        claim.fail(status="queued", reason="Wan refused admission", wait_reason=busy.value.wait_reason)
        assert worker_api(q).claim() is None
        q.clock.advance(16)
        current = worker_api(q).claim()
        assert current.identity["run_id"] == one
        fake.busy = False
        fake.foreign_engine_queue = True
        with pytest.raises(LanePaused, match="unknown ComfyUI work"):
            clips_for(q, current, wan_http).make(request_for(q), stage="fixture")
        current.fail(status="held", reason="Wan found foreign queue work")
        q.clock.advance(16)
        held = worker_api(q).claim()
        assert held.identity["run_id"] == one
        with pytest.raises(LanePaused, match="unknown ComfyUI work"):
            clips_for(q, held, wan_http).reconcile()
    assert len(fake.puts()) == 2 and len(set(fake.puts())) == 2


def test_absent_render_worker_leaves_queued_runs_available_and_labels_wait(queue):
    q = queue
    api = worker_api(q)
    assert api.claim() is None
    q.clock.advance(91)
    response = queue_run(q, "worker-lost")
    assert response.status_code == 201, response.text
    doc = response.json()
    assert doc["status"] == "queued" and doc["wait_reason"] == "gpu_unavailable"
    assert doc["queue_wait"]["wall_s"] is None
    assert q.browser.get(f"/v1/stories/{q.story_id}").status_code == 200
    claim = api.claim()
    assert claim.body["run"]["id"] == doc["id"] and claim.body["run"]["wait_reason"] is None


def test_repeated_wan_restart_pauses_before_retrying_under_another_id(queue, monkeypatch):
    q = queue
    queue_run(q, "restarts")
    claim = worker_api(q).claim()
    fake = FakeWan()
    fake.restart_failures = 2
    monkeypatch.setattr(wan, "measure_clip", lambda data: wan.Measured(5, 64, 64, "24"))
    with fake.client() as wan_http:
        with pytest.raises(LanePaused, match="restarted again") as paused:
            clips_for(q, claim, wan_http).make(request_for(q), stage="fixture")
        assert paused.value.code == "wan.restarting"
        assert len(set(fake.puts())) == 2
        claim.fail(status="queued", reason="Wan restarted twice", wait_reason=paused.value.wait_reason)
        assert worker_api(q).claim() is None
        q.clock.advance(16)
        replacement = worker_api(q).claim()
        clip = clips_for(q, replacement, wan_http).make(request_for(q), stage="fixture")
    assert len(set(fake.puts())) == 3
    assert fake.puts()[-1].endswith(clip.job_id)
