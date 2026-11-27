"""Queue acceptance through the runtime role, fake Wan and a fake clock."""

import asyncio
import hashlib
import json
from pathlib import Path
from secrets import token_hex
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace

import httpx
import psycopg
import pytest
import sqlalchemy as sa
from sqlalchemy.sql import visitors
from sqlalchemy.sql.selectable import ScalarSelect

from haynes_studio.adapters import wan
from haynes_studio.api.app import create_app
from haynes_studio.api.auth import SESSION_COOKIE
from haynes_studio.canonical.ids import Minter
from haynes_studio.canonical.model import Board, Story
from haynes_studio.db import drafts, identity, queue_controls, runs
from haynes_studio.db.catalog import record_asset_version
from haynes_studio.db.runs import database_time
from haynes_studio.db.schema import run_wan_attempts, worker_lane_grants, worker_tokens
from haynes_studio.library import Library
from haynes_studio.photo.plan import plan_photo
from haynes_studio.queue.wan import GPU_REFUSALS, LanePaused, ProductClips, ProductWan, product_request
from haynes_studio.queue.worker import BuildWorker
from haynes_studio.queue.worker_api import WorkerAPI, WorkerAPIError
from haynes_studio.queue.worker_tokens import worker_bearer

from tests.build_story.fixtures import example, photo_png, register
from tests.db.test_studio_api import (
    ISSUER, bearer, client, engine, new_production, new_story, owner_engine,
    register_agent, runtime_db, runtime_role, service, sign_in,
)
from tests.queue.fake_wan import Clock, FakeWan, STORY

pytestmark = pytest.mark.db


def worker_credentials(engine, *, lane="run"):
    secret = worker_bearer(token_hex(24))
    worker_id = "fixture-" + Minter().mint("run")
    with engine.begin() as conn:
        conn.execute(worker_tokens.insert().values(digest=identity.digest(secret), worker_id=worker_id))
        if lane is not None:
            conn.execute(worker_lane_grants.insert().values(worker_id=worker_id, lane=lane))
    return bearer(secret)


class LocalWorkerHTTP:
    """Adapt TestClient to the worker's POST-only HTTP interface."""
    def __init__(self, app, headers):
        self.client = client(app)
        self.headers = headers

    def post(self, url, *, headers=None, **kwargs):
        return self.client.post(url, headers={**self.headers, **(headers or {})}, **kwargs)


@pytest.fixture
def queue(service, engine, owner_engine, monkeypatch, tmp_path):
    app, store, issuer = service
    stage_root = tmp_path / "build-staging"
    stage_root.mkdir()
    app.state.build_stage_root = stage_root
    with owner_engine.begin() as conn:
        conn.exec_driver_sql("TRUNCATE escalation_events, escalation_packages, escalation_check_failures, "
                             "publications, release_packages, go_live_withdrawals, go_live_approvals, "
                             "run_check_overrides, run_wan_attempts, feedback_iteration_clears")
        conn.exec_driver_sql("UPDATE stories SET feedback_iteration_id = NULL WHERE feedback_iteration_id IS NOT NULL")
        conn.exec_driver_sql("DELETE FROM feedback_iterations")
        conn.exec_driver_sql("DELETE FROM candidate_feedback")
        conn.exec_driver_sql("DELETE FROM run_candidates")
        conn.exec_driver_sql("DELETE FROM runs")
        conn.exec_driver_sql("TRUNCATE media_jobs, queue_lane_events")
        conn.exec_driver_sql("UPDATE run_lane SET next_position = 1, worker_seen_at = NULL")
        conn.exec_driver_sql("UPDATE media_job_lanes SET next_position = 1")
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
    generator = version["provenance"]["generator"]
    generator["source_asset_version_ids"] = []
    with engine.begin() as conn:
        exchange = drafts.get_draft(conn, story_id).exchange()
        photo_fields = {"current_version_id": None, "prompt": "first angle", "input_asset_version_ids": []}
        planned = Board.from_document({**exchange["boards"][0], "photo": photo_fields})
        generator.setdefault("params", {})["input_signature"] = plan_photo(
            Story.from_document(exchange), planned, Library(),
        ).input_signature
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


def worker_api(q, *, app=None, headers=None, lane="run"):
    if headers is None:
        headers = worker_credentials(q.owner, lane=lane)
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
                        progress=lambda stage, **options: claim.heartbeat()["cancel_requested"],
                        clock=q.clock.monotonic, pause=q.clock.advance)


def clip_worker(q, client_, *, api=None, studio="git:unknown"):
    worker = BuildWorker(api or worker_api(q), ProductWan(client_), store=q.store, stage_root=q.stage_root,
                         register=register(), tracker_story=STORY, transcriber=None, studio=studio,
                         clock=q.clock.monotonic, pause=q.clock.advance)

    def render(claim, active, clips, inputs):
        clips.make(request_for(q), stage="fixture")
        return {"status": "failed", "stages": [], "checks": [],
                "error": {"code": "fixture.clip_only", "message": "Fixture stops after the clip",
                          "board_id": None, "stage": "wan"}}

    worker._render = render
    return worker


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
    assert q.browser.get(f'/v1/runs/{first["id"]}', headers=unscoped).status_code == 404
    cancelled = cancel(q, first["id"], '"1"', auth=agent)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert cancel(q, first["id"], '"1"', auth=agent).status_code == 409
    assert worker_api(q).claim().identity["run_id"] == second["id"]


def test_snapshot_serves_exact_run_bytes_to_scoped_readers(queue):
    q = queue
    queued = queue_run(q, "snapshot-read")
    assert queued.status_code == 201, queued.text
    run = queued.json()
    path = f'/v1/runs/{run["id"]}/snapshot'
    pin = run["snapshot"]
    with q.store.open(pin["locator"]) as handle:
        frozen = handle.read()
    assert hashlib.sha256(frozen).hexdigest() == pin["sha256"]
    updated = q.browser.patch(f"/v1/stories/{q.story_id}", json={"title": "Edited after queueing"},
                              headers={**q.csrf, "If-Match": "3"})
    assert updated.status_code == 200, updated.text

    _, reader = register_agent(q.owner, {q.production_id: ["read"]})
    for response in (q.browser.get(path), client(q.app).get(path, headers=reader)):
        assert response.status_code == 200, response.text
        assert response.content == frozen
        assert response.json()["schema"] == "studio.run-snapshot/v1"
        assert response.headers["content-type"] == "application/json"
        assert response.headers["etag"] == f'"{pin["sha256"]}"'
        assert response.headers["cache-control"] == "private, no-store"
    etag = f'"{pin["sha256"]}"'
    for condition in (etag, f'"other", W/{etag}', "*"):
        cached = client(q.app).get(path, headers={**reader, "If-None-Match": condition})
        assert cached.status_code == 304 and cached.content == b""
        assert cached.headers["etag"] == etag
        assert cached.headers["cache-control"] == "private, no-store"
    assert q.browser.get(path, headers={"If-None-Match": '"other"'}).content == frozen
    assert q.browser.get(f'/v1/media/{pin["sha256"]}').status_code == 404

    other = new_production(q.browser, q.csrf)
    _, outsider = register_agent(q.owner, {other: ["read"]})
    _, no_read = register_agent(q.owner, {q.production_id: ["runs:queue"]})
    missing = Minter().mint("run")
    for credentials in (outsider, no_read):
        for private in (path, f"/v1/runs/{missing}/snapshot", f'/v1/runs/{run["id"]}'):
            refused = client(q.app).get(private, headers={**credentials, "If-None-Match": etag})
            assert refused.status_code == 404
            assert refused.json()["error"]["code"] == "not_found"
            assert refused.headers["cache-control"] == "private, no-store"
    for credentials in ({}, worker_credentials(q.owner)):
        refused = client(q.app).get(path, headers=credentials)
        assert refused.status_code == 401
        assert refused.json()["error"]["code"] == "auth.required"

    blob = Path(q.store.root) / pin["locator"]
    blob.rename(blob.with_suffix(".original"))
    missing_blob = q.browser.get(path, headers={"If-None-Match": etag})
    assert missing_blob.status_code == 503 and missing_blob.json()["error"]["code"] == "run.snapshot_lost"
    assert "etag" not in missing_blob.headers
    blob.write_bytes(frozen + b" ")
    corrupt = q.browser.get(path, headers={"If-None-Match": etag})
    assert corrupt.status_code == 503 and corrupt.json()["error"]["code"] == "run.snapshot_changed"
    assert "etag" not in corrupt.headers


def test_snapshot_reader_caps_blob_io(queue, monkeypatch):
    from io import BytesIO

    from haynes_studio.api import run_routes

    q = queue
    run = queue_run(q, "snapshot-size-limit").json()
    reads = []

    class OversizedBlob(BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    monkeypatch.setattr(run_routes, "MAX_SNAPSHOT_BYTES", 64)
    monkeypatch.setattr(q.store, "open", lambda _: OversizedBlob(b" " * 128))
    response = q.browser.get(f'/v1/runs/{run["id"]}/snapshot')
    assert response.status_code == 503 and response.json()["error"]["code"] == "run.snapshot_too_large"
    assert reads == [65]
    assert "etag" not in response.headers


def test_oversized_server_built_snapshot_is_unprocessable_and_not_queued(queue, monkeypatch):
    from haynes_studio.api import run_routes

    q = queue
    monkeypatch.setattr(run_routes, "MAX_SNAPSHOT_BYTES", 1)
    response = queue_run(q, "draft-too-large")
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "run.snapshot_too_large"
    assert error["evidence"]["bytes"] > error["evidence"]["max_bytes"] == 1
    assert q.browser.get(f"/v1/stories/{q.story_id}/runs").json()["items"] == []


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


def test_claim_lock_rechecks_status_after_head_finishes(queue):
    q = queue
    first, second = [queue_run(q, key).json()["id"] for key in ("first", "second")]
    finishing = worker_api(q).claim()
    with q.engine.begin() as connection:
        position = runs.get(connection, first)["position"]

        class HeadSnapshot:
            def __getattr__(self, name):
                return getattr(connection, name)

            def execute(self, statement):
                if any(isinstance(node, ScalarSelect) for node in visitors.iterate(statement)):
                    finishing.fail(status="failed", reason="Head completed before row lock")
                    # Preserve the ID that the head subquery saw before the concurrent
                    # commit, and run the actual outer locking query on PostgreSQL.
                    statement = visitors.replacement_traverse(
                        statement, {}, lambda node: sa.literal(position) if isinstance(node, ScalarSelect) else None)
                return connection.execute(statement)

        assert runs.claim(HeadSnapshot(), "contending-worker") is None
    assert worker_api(q).claim().identity["run_id"] == second


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


def test_late_put_from_fenced_worker_is_deduplicated(queue, monkeypatch):
    q = queue
    first, second = [queue_run(q, key).json()["id"] for key in ("first", "next")]
    fake = FakeWan()
    stale = worker_api(q).claim()
    monkeypatch.setattr(wan, "measure_clip", lambda data: wan.Measured(5, 64, 64, "24"))
    with fake.client() as wan_http:
        replacement = clip_worker(q, wan_http)

        def take_over_during_first_put():
            q.clock.advance(91)
            assert replacement.tick()
            assert read_run(q, first)[0]["wan_attempts"][0]["state"] == "succeeded"
            assert read_run(q, second)[0]["status"] == "queued"

        fake.before_put = take_over_during_first_put
        with pytest.raises(WorkerAPIError, match="work.fence_lost"):
            clips_for(q, stale, wan_http).make(request_for(q), stage="fixture")
    assert fake.put_bodies == [fake.put_bodies[0]] * 2
    assert fake.submissions == [fake.put_bodies[0][0]]
    assert [verb for verb, path in fake.events if path == fake.puts()[0]] == ["PUT", "GET", "PUT", "GET"]
    assert worker_api(q).claim().identity["run_id"] == second


def _pause_run_lane(q, paused):
    response = q.browser.put("/v1/queue/lanes/run", headers=q.csrf, json={"paused": paused})
    assert response.status_code == 200
    assert response.json()["paused"] is paused


def _expire_run_claim(q, run_id):
    with q.owner.begin() as conn:
        expires = database_time(conn) - timedelta(seconds=1)
        conn.execute(runs.runs.update().where(runs.runs.c.id == run_id).values(claim_until=expires))


def _elapse_run_retry(q, run_id):
    with q.owner.begin() as conn:
        conn.execute(runs.runs.update().where(runs.runs.c.id == run_id)
                     .values(retry_at=database_time(conn) - timedelta(seconds=1)))


def _dispatch_to_fake_wan(q, claim, transport):
    request = request_for(q)
    body = product_request(request)
    attempt = claim.reserve("i2v", body)
    transport.stage(request.image_png, body["image_sha256"], "png")
    sent = claim.attempt(attempt["job_id"], "sent")
    transport.submit(sent)
    return attempt["job_id"]


@pytest.fixture
def paused_reconcile(queue, monkeypatch):
    monkeypatch.setattr(queue.app.state, "paused_reconcile", True)
    monkeypatch.setattr(runs, "database_time", database_time)
    return queue


@pytest.mark.parametrize(("enabled", "capability"), [(False, "1"), (True, "0")],
                         ids=["switch-unset", "capability-zero"])
def test_paused_sent_claim_requires_switch_and_explicit_capability(queue, monkeypatch, enabled, capability):
    q = queue
    if enabled:
        monkeypatch.setenv("STUDIO_PAUSED_RECONCILE", "1")
    else:
        monkeypatch.delenv("STUDIO_PAUSED_RECONCILE", raising=False)
    monkeypatch.setattr(runs, "database_time", database_time)
    app = create_app(q.engine, q.store, q.app.state.oidc)
    assert app.state.paused_reconcile is enabled
    run_id = queue_run(q, "expired-sent-claim").json()["id"]
    old = worker_api(q, app=app).claim()
    attempt = old.reserve("i2v", product_request(request_for(q)))
    old.attempt(attempt["job_id"], "sent")
    _pause_run_lane(q, True)
    _expire_run_claim(q, run_id)

    replacement = LocalWorkerHTTP(app, worker_credentials(q.owner))
    response = replacement.post("/internal/v1/work/claim", headers={"X-Studio-Paused-Reconcile": capability})
    assert response.status_code == 204, response.text
    assert response.content == b""
    with q.engine.connect() as conn:
        assert runs.get(conn, run_id)["fence"] == old.identity["fence"]


@pytest.mark.parametrize("outcome", ["succeeded", "failed"])
def test_pause_before_reclaim_drains_the_sent_job_and_preserves_fifo(paused_reconcile, monkeypatch, outcome):
    q = paused_reconcile
    monkeypatch.setattr(wan, "measure_clip", lambda data: wan.Measured(5, 64, 64, "24"))
    first, second, third = [queue_run(q, key).json()["id"] for key in ("sent-head", "next", "last")]
    old = worker_api(q).claim()
    replacement = worker_api(q)
    fake = FakeWan()
    with fake.client() as wan_http:
        job_id = _dispatch_to_fake_wan(q, old, ProductWan(wan_http))
        states = iter(("running", outcome))
        fake.before_get = lambda key: fake.jobs[key].update(state=next(states))
        _pause_run_lane(q, True)
        assert replacement.claim() is None  # Even dispatched work keeps its live fence.
        _expire_run_claim(q, first)

        worker = clip_worker(q, wan_http, api=replacement)
        assert worker.tick()
        with pytest.raises(WorkerAPIError, match="work.fence_lost"):
            old.heartbeat()
        assert not worker.tick()
    assert fake.submissions == [job_id]
    put, = fake.puts()
    assert fake.events.count(("GET", put)) == 2
    head, _ = read_run(q, first)
    assert head["status"] == ("held" if outcome == "succeeded" else "failed")
    assert head["wan_attempts"] == [{"job_id": job_id, "kind": "i2v", "attempt": 1, "state": outcome}]
    assert [read_run(q, ident)[0]["status"] for ident in (second, third)] == ["queued", "queued"]

    _pause_run_lane(q, False)
    if outcome == "succeeded":
        _elapse_run_retry(q, first)
    expected = (first, second, third) if outcome == "succeeded" else (second, third)
    for ident in expected:
        claim = replacement.claim()
        assert claim is not None and claim.identity["run_id"] == ident
        claim.fail(status="failed", reason="Fixture settles the FIFO head")


def test_pause_transaction_races_reclaim_of_a_released_sent_job(paused_reconcile):
    q = paused_reconcile
    first, second = [queue_run(q, key).json()["id"] for key in ("unconfirmed-head", "next")]
    old = worker_api(q).claim()
    attempt = old.reserve("i2v", product_request(request_for(q)))
    job_id = attempt["job_id"]
    old.attempt(job_id, "sent")
    old.fail(status="held", reason="Fixture loses the PUT before Wan receives it")
    _elapse_run_retry(q, first)

    fake = FakeWan()
    with fake.client() as wan_http:
        replacement = clip_worker(q, wan_http)
        with q.engine.begin() as conn:
            queue_controls.set_paused(conn, "run", True,
                                      {"kind": "human", "iss": ISSUER, "sub": "one"}, database_time)
            # The pause transaction still holds the lane row when this poll arrives.
            assert not replacement.tick()
            assert fake.events == []
        assert replacement.tick()
        assert fake.events == [("GET", f"/v1/jobs/i2v/{job_id}")]

        head, _ = read_run(q, first)
        assert head["status"] == "held" and head["error"]["code"] == "work.lane_paused"
        assert head["wan_attempts"][0]["state"] == "sent"
        assert read_run(q, second)[0]["status"] == "queued"


@pytest.mark.parametrize("replay", [False, True], ids=["first-send", "same-id-replay"])
@pytest.mark.parametrize("enabled", [False, True], ids=["disabled", "enabled"])
def test_pause_after_claim_orders_wan_dispatch(queue, monkeypatch, replay, enabled):
    q = queue
    monkeypatch.setattr(q.app.state, "paused_reconcile", enabled)
    monkeypatch.setattr(runs, "database_time", database_time)
    monkeypatch.setattr(wan, "measure_clip", lambda data: wan.Measured(5, 64, 64, "24"))
    run_id = queue_run(q, "pause-race").json()["id"]
    fake = FakeWan()
    with fake.client() as wan_http:
        worker = clip_worker(q, wan_http)
        if replay:
            old = worker_api(q).claim()
            request = request_for(q)
            body = product_request(request)
            job_id = old.reserve("i2v", body)["job_id"]
            worker.wan.stage(request.image_png, body["image_sha256"], "png")
            old.attempt(job_id, "sent")
            _expire_run_claim(q, run_id)
            # Reclaim wins the lock while the lane is open. Pause as it reads
            # the saved ID, before authorization to replay the missing PUT.
            fake.before_get = lambda key: _pause_run_lane(q, True)
        else:
            ready = worker.wan.ready

            def ready_then_pause(kind=None):
                ready(kind)
                if read_run(q, run_id)[0]["wan_attempts"] and kind is None:
                    _pause_run_lane(q, True)

            monkeypatch.setattr(worker.wan, "ready", ready_then_pause)
        assert worker.tick()
    head, _ = read_run(q, run_id)
    if enabled:
        assert fake.puts() == []
        assert head["status"] == "held" and head["error"]["code"] == "work.lane_paused"
        assert head["wan_attempts"][0]["state"] == "sent"
    else:
        # A switched-off API preserves the serving build's dispatch behavior.
        assert len(fake.puts()) == 1
        assert head["wan_attempts"][0]["state"] == "succeeded"


def test_paused_lane_does_not_reclaim_a_reserved_wan_job(paused_reconcile):
    q = paused_reconcile
    run_id = queue_run(q, "reserved-only").json()["id"]
    old = worker_api(q).claim()
    job_id = old.reserve("i2v", product_request(request_for(q)))["job_id"]
    _expire_run_claim(q, run_id)
    _pause_run_lane(q, True)
    replacement = worker_api(q)
    assert replacement.claim() is None
    _pause_run_lane(q, False)
    claim = replacement.claim()
    assert claim.identity == {"run_id": run_id, "fence": old.identity["fence"] + 1}
    assert claim.body["pending"]["job_id"] == job_id


@pytest.mark.parametrize("queued_with_sent", [False, True], ids=["no-pending-attempt", "queued-with-sent"])
def test_paused_lane_excludes_ineligible_run_heads(paused_reconcile, queued_with_sent):
    q = paused_reconcile
    run_id = queue_run(q, "ineligible-head").json()["id"]
    old = worker_api(q).claim()
    if queued_with_sent:
        attempt = old.reserve("i2v", product_request(request_for(q)))
        old.attempt(attempt["job_id"], "sent")
        # Simulate an inconsistent head without relying on a worker to create it.
        with q.owner.begin() as conn:
            row = runs.get(conn, run_id)
            conn.execute(runs.runs.update().where(runs.runs.c.id == run_id)
                         .values(document={**row["document"], "status": "queued"}))
    _expire_run_claim(q, run_id)
    _pause_run_lane(q, True)

    assert worker_api(q).claim() is None
    with q.engine.connect() as conn:
        assert runs.get(conn, run_id)["fence"] == old.identity["fence"]


def test_pause_refuses_sent_marker_before_wan_authorization(paused_reconcile):
    q = paused_reconcile
    run_id = queue_run(q, "mark-after-pause").json()["id"]
    claim = worker_api(q).claim()
    attempt = claim.reserve("i2v", product_request(request_for(q)))
    _pause_run_lane(q, True)

    with pytest.raises(WorkerAPIError, match="work.lane_paused") as refusal:
        claim.attempt(attempt["job_id"], "sent")
    assert refusal.value.status == 409
    assert read_run(q, run_id)[0]["wan_attempts"][0]["state"] == "reserved"


@pytest.mark.parametrize("existing", [False, True], ids=["new-id", "existing-id"])
def test_pause_refuses_wan_reservation(paused_reconcile, existing):
    q = paused_reconcile
    run_id = queue_run(q, "reserve-after-pause").json()["id"]
    claim = worker_api(q).claim()
    request = product_request(request_for(q))
    if existing:
        claim.reserve("i2v", request)
    before = read_run(q, run_id)[0]["wan_attempts"]
    _pause_run_lane(q, True)

    with pytest.raises(WorkerAPIError, match="work.lane_paused") as refusal:
        claim.reserve("i2v", request)
    assert refusal.value.status == 409
    assert read_run(q, run_id)[0]["wan_attempts"] == before


def test_paused_live_run_can_reserve_wan_attempt_with_switch_unset(queue, monkeypatch):
    q = queue
    monkeypatch.delenv("STUDIO_PAUSED_RECONCILE", raising=False)
    app = create_app(q.engine, q.store, q.app.state.oidc)
    assert app.state.paused_reconcile is False
    run_id = queue_run(q, "reserve-with-switch-unset").json()["id"]
    worker = LocalWorkerHTTP(app, worker_credentials(q.owner))
    claim = WorkerAPI(worker).claim()
    _pause_run_lane(q, True)

    proposal = {**product_request(request_for(q)), "kind": "i2v"}
    response = worker.post("/internal/v1/work/attempts", json={**claim.identity, "proposal": proposal})
    assert response.status_code == 200, response.text
    attempt, = read_run(q, run_id)[0]["wan_attempts"]
    assert attempt["job_id"] == response.json()["job_id"]
    assert attempt["state"] == "reserved"


def test_paused_final_wan_heartbeat_reports_cancellation_to_live_holder(paused_reconcile):
    q = paused_reconcile
    run_id = queue_run(q, "cancel-before-final-heartbeat").json()["id"]
    worker = LocalWorkerHTTP(q.app, worker_credentials(q.owner))
    claim = WorkerAPI(worker).claim()
    attempt = claim.reserve("i2v", product_request(request_for(q)))
    claim.attempt(attempt["job_id"], "sent")
    _pause_run_lane(q, True)
    _, etag = read_run(q, run_id)
    cancelled = cancel(q, run_id, etag)
    assert cancelled.status_code == 200 and cancelled.json()["cancel_requested"] is True

    response = worker.post("/internal/v1/work/heartbeat", json={
        **claim.identity, "progress": {"percent": 25, "stage": "wan_submitting"},
    })
    assert response.status_code == 200, response.text
    assert response.json()["cancel_requested"] is True


def test_wan_dispatch_check_waits_for_uncommitted_pause(paused_reconcile):
    q = paused_reconcile
    run_id = queue_run(q, "dispatch-lane-lock").json()["id"]
    claim = worker_api(q).claim()
    worker_id = claim.body["actor"]["worker_id"]
    with q.engine.begin() as pause:
        queue_controls.set_paused(pause, "run", True, {"kind": "human", "iss": ISSUER, "sub": "one"},
                                  database_time)
        with pytest.raises(sa.exc.OperationalError) as locked, q.engine.begin() as dispatch:
            dispatch.exec_driver_sql("SET LOCAL lock_timeout = '250ms'")
            runs.lock_claim(dispatch, run_id, worker_id, claim.identity["fence"], wan_dispatch=True)
        assert isinstance(locked.value.orig, psycopg.errors.LockNotAvailable)

    with pytest.raises(WorkerAPIError, match="work.lane_paused"):
        claim.heartbeat({"percent": 25, "stage": "wan_submitting"})


def test_live_run_can_send_an_authorized_wan_put_and_transcribe_after_pause(
    paused_reconcile, monkeypatch, tmp_path,
):
    from tests.delivery.media import write_master

    q = paused_reconcile
    add_sound_bed(q, tmp_path)
    queued = queue_run(q, "authorized-before-pause", rev=4)
    assert queued.status_code == 201
    clip = write_master(tmp_path / "wan-fixture.mp4", frames=121, width=576, height=1024,
                        audio_codec=None).read_bytes()
    fake = FakeWan(clip)
    transcripts = []

    def transcribe(_wav):
        assert fake.puts()
        run_lane, *_ = q.browser.get("/v1/queue/lanes").json()["items"]
        assert run_lane["paused"] is True and run_lane["live_claim"] is True
        transcripts.append("read")
        return ""

    with fake.client() as wan_http:
        worker = BuildWorker(worker_api(q), ProductWan(wan_http), store=q.store, stage_root=q.stage_root,
                             register=register(), tracker_story=STORY,
                             transcriber=SimpleNamespace(name="Fixture ASR", transcribe=transcribe),
                             clock=q.clock.monotonic, pause=q.clock.advance)
        submit = worker.wan.submit

        def pause_then_submit(attempt):
            _pause_run_lane(q, True)
            lanes = q.browser.get("/v1/queue/lanes").json()["items"]
            assert next(lane for lane in lanes if lane["lane"] == "run")["live_claim"] is True
            assert not fake.puts()
            return submit(attempt)

        monkeypatch.setattr(worker.wan, "submit", pause_then_submit)
        assert worker.tick()
    assert len(fake.puts()) == len(transcripts) == 1
    assert read_run(q, queued.json()["id"])[0]["status"] == "succeeded"
    run_lane, *_ = q.browser.get("/v1/queue/lanes").json()["items"]
    assert run_lane["paused"] is True and run_lane["live_claim"] is False


@pytest.mark.parametrize("state", ["sent", "busy"])
@pytest.mark.parametrize("committed", [False, True], ids=["before-commit", "after-commit"])
def test_lost_attempt_write_reconciles_from_wan(queue, monkeypatch, state, committed):
    q = queue
    run_id = queue_run(q, "lost-write").json()["id"]
    fake = FakeWan()
    if state == "busy":
        fake.gpu_refusal = GPU_REFUSALS[0]
    monkeypatch.setattr(wan, "measure_clip", lambda data: wan.Measured(5, 64, 64, "24"))

    class LoseWrite(LocalWorkerHTTP):
        def post(self, url, **kwargs):
            if "/attempts/" in url and kwargs["json"]["state"] == state:
                if committed:
                    assert super().post(url, **kwargs).status_code == 200
                raise httpx.ReadTimeout("Lost response for the attempt write")
            return super().post(url, **kwargs)

    with fake.client() as wan_http:
        if state == "busy":
            assert clip_worker(q, wan_http).tick()
            q.clock.advance(60)
        interrupted = WorkerAPI(LoseWrite(q.app, worker_credentials(q.owner)))
        with pytest.raises(WorkerAPIError, match="work.transport"):
            clip_worker(q, wan_http, api=interrupted).tick()
        puts = fake.puts()
        assert len(puts) == (2 if state == "busy" else 0)
        q.clock.advance(91)
        fake.gpu_refusal = None
        fake.events.clear()
        recovering = clip_worker(q, wan_http)
        if state == "busy" and committed:
            assert not recovering.tick()
            q.clock.advance(29)
        assert recovering.tick()
        if state == "busy" and not committed:
            assert fake.events == [("GET", puts[-1])]
            assert not recovering.tick()
            q.clock.advance(120)
            assert recovering.tick()
        if state == "sent":
            assert fake.events[0] == ("GET", fake.puts()[0])
        attempts = read_run(q, run_id)[0]["wan_attempts"]
    assert [a["state"] for a in attempts] == (["busy", "busy", "succeeded"] if state == "busy" else ["succeeded"])
    assert len(fake.submissions) == 1
    assert fake.puts()[-1].endswith(fake.submissions[0])


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ConnectTimeout])
def test_preconnect_put_failure_is_not_an_ambiguous_send(queue, monkeypatch, error):
    q = queue
    run_id = queue_run(q, "connection-error").json()["id"]
    fake = FakeWan()
    fake.connect_error = error
    monkeypatch.setattr(wan, "measure_clip", lambda data: wan.Measured(5, 64, 64, "24"))
    with fake.client() as wan_http:
        worker = clip_worker(q, wan_http)
        assert worker.tick()
        assert read_run(q, run_id)[0]["error"]["code"] == "wan.submit_not_sent"
        assert fake.events[-1] == ("PUT", fake.puts()[0])
        assert fake.submissions == []
        q.clock.advance(15)
        assert worker.tick()
    assert fake.put_bodies == [fake.put_bodies[0]] * 2
    assert fake.submissions == [fake.put_bodies[0][0]]
    assert read_run(q, run_id)[0]["wan_attempts"][0]["state"] == "succeeded"


@pytest.mark.parametrize(("status", "wan_code", "code"), [
    (409, "id_conflict", "wan.id_conflict"), (400, "invalid_input", "wan.submit_rejected"),
    (401, "unauthorized", "wan.submit_rejected"), (422, "validation", "wan.submit_rejected"),
])
def test_definite_put_rejection_fails_attempt_and_run(queue, status, wan_code, code):
    q = queue
    one, two = [queue_run(q, key).json()["id"] for key in ("first", "next")]
    fake = FakeWan()
    fake.submit_error = status, wan_code
    with fake.client() as wan_http:
        assert clip_worker(q, wan_http).tick()
    run, _ = read_run(q, one)
    assert run["status"] == "failed" and run["error"]["code"] == code
    evidence, = run["error"]["problems"]
    assert evidence["http_status"] == status and evidence["wan_code"] == wan_code
    assert run["wan_attempts"][0]["state"] == "failed"
    assert fake.events[-1] == ("PUT", fake.puts()[0])
    assert fake.submissions == []
    assert worker_api(q).claim().identity["run_id"] == two


def test_ambiguous_put_replays_only_after_reading_the_same_id(queue, monkeypatch):
    q = queue
    first, second = [queue_run(q, key).json()["id"] for key in ("first", "next")]
    fake = FakeWan()
    fake.disappear = True
    monkeypatch.setattr(wan, "measure_clip", lambda data: wan.Measured(5, 64, 64, "24"))
    with fake.client() as wan_http:
        worker = clip_worker(q, wan_http)
        assert worker.tick()
        run, _ = read_run(q, first)
        assert run["status"] == "held" and run["error"]["code"] == "wan.ambiguous_submit"
        assert not worker.tick()
        assert len(fake.puts()) == 2
        fake.disappear = False
        q.clock.advance(15)
        assert worker.tick()
    assert len(fake.put_bodies) == 3
    assert fake.put_bodies == [fake.put_bodies[0]] * 3
    path = fake.puts()[0]
    assert [verb for verb, target in fake.events if target == path] == [
        "PUT", "GET", "PUT", "GET", "GET", "PUT", "GET",
    ]
    assert fake.submissions == [fake.put_bodies[0][0]]
    assert read_run(q, first)[0]["wan_attempts"][0]["state"] == "succeeded"
    assert worker_api(q).claim().identity["run_id"] == second


@pytest.mark.parametrize("disposition", ["running", "succeeded", "foreign"])
def test_cancel_reconciles_running_or_held_attempt_and_releases(queue, disposition):
    q = queue
    first, second = [queue_run(q, key).json()["id"] for key in ("cancel", "next")]
    old = worker_api(q).claim()
    body = product_request(request_for(q))
    attempt = old.reserve("i2v", body)
    job_id = attempt["job_id"]
    old.attempt(job_id, "sent")
    with pytest.raises(WorkerAPIError, match="wan.attempt_state"):
        old.attempt(job_id, "sent")
    fake = FakeWan()
    fake.foreign_engine_queue = disposition == "foreign"
    with fake.client() as wan_http:
        product = ProductWan(wan_http)
        product.stage(q.png, body["image_sha256"], "png")
        product.submit(attempt)
        if disposition == "running":
            fake.jobs[job_id]["state"] = "running"
            # First status read shows active engine work, the second is terminal.
            def finish_after_first_read(job):
                fake.before_get = lambda _: fake.jobs[job].update(state="succeeded")

            fake.before_get = finish_after_first_read
        if disposition == "foreign":
            old.fail(status="held", reason="Recorded attempt still needs reconciliation",
                     admission_busy=True)
        _, etag = read_run(q, first)
        assert cancel(q, first, etag).json()["cancel_requested"]
        if disposition in ("running", "succeeded"):
            q.clock.advance(91)
        fake.held = True  # Terminal cancellation does not depend on readiness or result bytes.
        puts = fake.puts()
        start = q.clock.now
        assert clip_worker(q, wan_http).tick()
        assert (q.clock.now - start).seconds == (5 if disposition == "running" else 0)
        assert fake.puts() == puts
        assert not any(path.endswith("/file") for _, path in fake.events)
    cancelled, _ = read_run(q, first)
    assert cancelled["status"] == "cancelled"
    assert cancelled["wan_attempts"][0]["state"] == "cancelled"
    assert worker_api(q).claim().identity["run_id"] == second


def _cancel_pending_send(q):
    first, second = [queue_run(q, key).json()["id"] for key in ("cancel", "next")]
    claim = worker_api(q).claim()
    attempt = claim.reserve("i2v", product_request(request_for(q)))
    claim.attempt(attempt["job_id"], "sent")
    _, etag = read_run(q, first)
    assert cancel(q, first, etag).json()["cancel_requested"]
    q.clock.advance(91)
    return first, second, attempt


def test_cancel_unknown_sent_job_holds_until_two_absences_are_110_seconds_apart(queue):
    q = queue
    first, second, attempt = _cancel_pending_send(q)
    job_id = attempt["job_id"]
    fake = FakeWan()
    reads = []
    fake.before_get = lambda id_: reads.append((id_, q.clock.monotonic()))
    with fake.client() as wan_http:
        assert clip_worker(q, wan_http).tick()
        held, _ = read_run(q, first)
        assert held["status"] == "held" and held["cancel_requested"]
        assert held["error"]["code"] == "wan.cancel_waiting_for_absence"
        assert "claim lease and PUT timeout" in held["error"]["message"]
        assert held["wan_attempts"][0]["state"] == "sent"
        assert worker_api(q).claim() is None

        # A fresh worker observes another 404 before the cutoff and keeps the
        # previous observation across the hold it writes.
        q.clock.advance(95)
        assert clip_worker(q, wan_http).tick()
        assert read_run(q, first)[0]["status"] == "held"
        assert worker_api(q).claim() is None
        q.clock.advance(15)
        assert clip_worker(q, wan_http).tick()

    assert reads == [(job_id, reads[0][1] + elapsed) for elapsed in (0, 95, 110)]
    assert fake.events == [("GET", f"/v1/jobs/i2v/{job_id}")] * 3
    assert fake.submissions == []
    settled, _ = read_run(q, first)
    assert settled["status"] == "cancelled" and settled["wan_attempts"][0]["state"] == "cancelled"
    assert worker_api(q).claim().identity["run_id"] == second


def test_cancel_unknown_sent_job_restarts_absence_window_after_inconclusive_read(queue):
    q = queue
    first, _, attempt = _cancel_pending_send(q)
    fake = FakeWan()
    with fake.client() as wan_http:
        assert clip_worker(q, wan_http).tick()
        q.clock.advance(110)
        fake.poll_misses = 1
        assert clip_worker(q, wan_http).tick()
        assert read_run(q, first)[0]["status"] == "held"
        q.clock.advance(110)
        assert clip_worker(q, wan_http).tick()

    assert fake.events == [("GET", f"/v1/jobs/i2v/{attempt['job_id']}")] * 4
    assert fake.submissions == []
    assert read_run(q, first)[0]["status"] == "cancelled"


def test_pending_wan_attempt_cannot_be_settled_by_unrelated_failure(queue):
    q = queue
    run_id = queue_run(q, "pending-attempt").json()["id"]
    claim = worker_api(q).claim()
    job_id = claim.reserve("i2v", product_request(request_for(q)))["job_id"]
    claim.attempt(job_id, "sent")
    claims = [
        ("wan.unsettled", {"status": "failed"}),
        ("wan.attempt_state", {"status": "failed", "wan_job_id": "f" * 32}),
        ("wan.outcome", {"status": "held", "wan_job_id": job_id}),
        ("wan.outcome", {"status": "queued", "wait_reason": "lease_busy", "admission_busy": True}),
        ("run.transition", {"status": "cancelled", "wan_job_id": job_id}),
    ]
    for error, fields in claims:
        with pytest.raises(WorkerAPIError, match=error):
            claim.fail(reason="Attempt has no proven outcome", **fields)
    assert read_run(q, run_id)[0]["wan_attempts"][0]["state"] == "sent"


def test_cancel_between_readiness_and_put_prevents_new_wan_send(queue):
    q = queue
    one, two = [queue_run(q, key).json()["id"] for key in ("cancel", "next")]
    fake = FakeWan()
    with fake.client() as wan_http:
        worker = clip_worker(q, wan_http)
        ready = worker.wan.ready
        checks = 0

        def ready_then_cancel(kind=None):
            nonlocal checks
            ready(kind)
            checks += 1
            if checks == 3:
                _, etag = read_run(q, one)
                assert cancel(q, one, etag).json()["cancel_requested"]

        worker.wan.ready = ready_then_cancel
        assert worker.tick()
    assert fake.puts() == []
    assert all("/v1/jobs/" not in path for _, path in fake.events)
    assert read_run(q, one)[0]["status"] == "cancelled"
    assert worker_api(q).claim().identity["run_id"] == two


def test_auto_cancel_wins_during_definite_outcome(queue):
    q = queue
    run_id = queue_run(q, "cancel-during-verification").json()["id"]
    fake = FakeWan()
    fake.corrupt_graph = "0" * 64

    def request_cancel(_):
        _, etag = read_run(q, run_id)
        assert cancel(q, run_id, etag).json()["cancel_requested"]

    fake.before_get = request_cancel
    with fake.client() as wan_http:
        assert clip_worker(q, wan_http).tick()
    doc, _ = read_run(q, run_id)
    assert doc["status"] == "cancelled" and doc["error"] is None
    assert doc["wan_attempts"][0]["state"] == "cancelled"


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


def add_sound_bed(q, tmp_path):
    from tests.support.synthetic import write_sine_wav

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


@pytest.mark.parametrize("refused", [False, True], ids=["lost-reply", "definite-refusal"])
def test_worker_recovers_or_fails_staged_delivery(queue, tmp_path, refused):
    from tests.delivery.media import write_master

    q = queue
    add_sound_bed(q, tmp_path)
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
                _, etag = read_run(q, run_id)
                rejected_cancel = cancel(q, run_id, etag)
                assert rejected_cancel.status_code == 409
                assert rejected_cancel.json()["error"]["code"] == "run.transition"
                if not refused:
                    raise httpx.ReadTimeout("worker disappeared before the API received completion")
            return super().post(url, **kwargs)

    with fake.client() as wan_http:
        options = dict(store=q.store, stage_root=q.stage_root, register=register(), tracker_story=STORY,
                       transcriber=SimpleNamespace(name="Fixture ASR", transcribe=lambda _: ""),
                       clock=q.clock.monotonic, pause=q.clock.advance)
        before = WorkerAPI(StopBeforeCompletion(q.app, worker_credentials(q.owner)))
        worker = BuildWorker(before, ProductWan(wan_http), **options)
        if refused:
            q.app.state.build_stage_root = None
            second = queue_run(q, "next", rev=4).json()["id"]
            assert worker.tick()
            failed, _ = read_run(q, run_id)
            assert failed["status"] == "failed" and failed["error"]["code"] == "work.delivery_rejected"
            assert len(fake.puts()) == 1
            assert worker_api(q).claim().identity["run_id"] == second
            return
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
    _, etag = read_run(q, run_id)
    assert cancel(q, run_id, etag).status_code == 409

    # Today's revision changes the snapshot while the kept Wan clip key stays the same.
    new_revision = "git:" + "a" * 40
    q.app.state.build_revision = new_revision
    requeue = queue_run(q, "reuse-after-deploy", rev=4)
    assert requeue.status_code == 201, requeue.text
    assert requeue.json()["snapshot"]["sha256"] != queued["sha256"]
    with fake.client() as wan_http:
        worker = BuildWorker(worker_api(q), ProductWan(wan_http), studio=new_revision, **options)
        assert worker.tick()
    reused, _ = read_run(q, requeue.json()["id"])
    assert reused["status"] == "succeeded", reused["error"]
    assert reused["wan_attempts"] == [] and len(fake.puts()) == 1
    reused_clip = reused["stages"][0]["clips"][0]["clips"][0]
    assert reused_clip["engine_job_id"] == result["wan_attempts"][0]["job_id"]
    assert reused_clip["kept"]["made"] is False


@pytest.mark.parametrize(("mismatch", "code"), [
    ("short", "wan.result_invalid"), ("hash", "wan.result_invalid"),
    ("long", "wan.result_invalid"), ("graph", "wan.graph_mismatch"),
    ("frames", "wan.clip_invalid"), ("rate", "wan.clip_invalid"),
    ("dimensions", "wan.clip_invalid"), ("decode", "wan.clip_invalid"),
])
def test_result_mismatch_fails_attempt_and_releases_queue(queue, monkeypatch, mismatch, code):
    q = queue
    first, second = [queue_run(q, key).json()["id"] for key in ("bad-download", "next")]
    fake = FakeWan(b"1234567890")
    fake.corrupt = {"short": b"123", "hash": b"x" * 10, "long": b"x" * 11}.get(mismatch)
    if mismatch == "short":
        fake.before_get = lambda job: fake.jobs[job]["result"].update(
            sha256=hashlib.sha256(fake.corrupt).hexdigest())
    if mismatch == "graph":
        fake.corrupt_graph = "0" * 64

    def measure(_):
        if mismatch == "decode":
            raise ValueError("not a video")
        return wan.Measured(6 if mismatch == "frames" else 5, 32 if mismatch == "dimensions" else 64,
                            64, "16" if mismatch == "rate" else "24")

    monkeypatch.setattr(wan, "measure_clip", measure)
    with fake.client() as wan_http:
        assert clip_worker(q, wan_http).tick()
    run, _ = read_run(q, first)
    assert run["status"] == "failed" and run["error"]["code"] == code
    problem, = run["error"]["problems"]
    assert problem["job_id"] == run["wan_attempts"][0]["job_id"]
    assert problem["actual"] != problem["expected"]
    if mismatch == "long":
        assert problem["actual"]["bytes_at_least"] == len(fake.corrupt)
    assert run["wan_attempts"][0]["state"] == "failed"
    assert len(fake.puts()) == 1
    assert worker_api(q).claim().identity["run_id"] == second


def test_toolchain_change_fails_head_even_while_wan_is_offline(queue):
    q = queue
    old = queue_run(q, "old-revision").json()
    new_revision = "git:" + "a" * 40
    q.app.state.build_revision = new_revision
    new = queue_run(q, "new-revision").json()
    assert old["snapshot"] != new["snapshot"]
    fake = FakeWan()
    fake.outage = True
    with fake.client() as wan_http:
        assert clip_worker(q, wan_http, studio=new_revision).tick()
    failed = read_run(q, old["id"])[0]
    assert failed["status"] == "failed" and failed["error"]["code"] == "work.revision_mismatch"
    assert "Queue a new run" in failed["error"]["message"] and failed["snapshot"] == old["snapshot"]
    assert fake.events == []
    assert worker_api(q).claim().identity["run_id"] == new["id"]


@pytest.mark.parametrize("blocked", [{"ready": False}, {"active_video_job": "other-video"},
                                    {"active_foley_job": "other-foley"}])
def test_readiness_blocks_put_if_admission_changes_while_staging(queue, monkeypatch, blocked):
    q = queue
    run_id = queue_run(q, "readiness").json()["id"]
    fake = FakeWan()
    monkeypatch.setattr(wan, "measure_clip", lambda data: wan.Measured(5, 64, 64, "24"))
    with fake.client() as wan_http:
        worker = clip_worker(q, wan_http)
        stage_input = worker.wan.stage

        def stage_then_block(*args):
            stage_input(*args)
            for field, value in blocked.items():
                setattr(fake, field, value)

        monkeypatch.setattr(worker.wan, "stage", stage_then_block)
        assert worker.tick()
        assert fake.puts() == []
        assert read_run(q, run_id)[0]["status"] == "held"
        fake.ready, fake.active_video_job, fake.active_foley_job = True, None, None
        q.clock.advance(15)
        assert worker.tick()
    assert len(fake.submissions) == 1
    assert read_run(q, run_id)[0]["wan_attempts"][0]["state"] == "succeeded"


def test_gpu_refusal_backoff_grows_and_caps(queue, monkeypatch):
    q = queue
    first, second = [queue_run(q, key).json()["id"] for key in ("warm", "next")]
    fake = FakeWan()
    monkeypatch.setattr(wan, "measure_clip", lambda data: wan.Measured(5, 64, 64, "24"))
    with fake.client() as wan_http:
        worker = clip_worker(q, wan_http)
        # Exercise both asynchronous GPU refusals and the immediate 409 without a job record.
        for index, delay in enumerate((60, 120, 240, 240), start=1):
            fake.busy = index >= 3
            fake.gpu_refusal = GPU_REFUSALS[(index - 1) % len(GPU_REFUSALS)]
            assert worker.tick()
            assert len(fake.puts()) == index and fake.submissions == []
            q.clock.advance(delay - 1)
            assert not worker.tick()
            q.clock.advance(1)
            assert read_run(q, second)[0]["wan_attempts"] == []
        fake.gpu_refusal, fake.busy = None, False
        assert worker.tick()
    assert [a["state"] for a in read_run(q, first)[0]["wan_attempts"]] == ["busy", "busy", "succeeded"]
    assert len(set(fake.puts())) == 3
    assert fake.put_bodies[2:] == [fake.put_bodies[2]] * 3
    assert worker_api(q).claim().identity["run_id"] == second


def test_cancel_wins_before_publication_and_fences_completion(queue):
    q = queue
    first, second = [queue_run(q, key).json()["id"] for key in ("cancel", "next")]
    claim = worker_api(q).claim()
    claim.reserve("i2v", product_request(request_for(q)))
    _, etag = read_run(q, first)
    result = cancel(q, first, etag)
    assert result.status_code == 200 and result.json()["status"] == "cancelled"
    assert result.json()["wan_attempts"][0]["state"] == "cancelled"
    with pytest.raises(WorkerAPIError, match="work.fence_lost"):
        claim.publish()
    with pytest.raises(WorkerAPIError, match="work.fence_lost"):
        claim.complete({"stages": [], "outputs": {}, "checks": [], "provenance": {}, "delivery_id": "unused"})
    assert worker_api(q).claim().identity["run_id"] == second


def test_publication_wins_before_cancel(queue):
    q = queue
    run_id = queue_run(q, "publish").json()["id"]
    claim = worker_api(q).claim()
    claim.publish()
    _, etag = read_run(q, run_id)
    refused = cancel(q, run_id, etag)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "run.transition"
    assert not claim.heartbeat()["cancel_requested"]


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


def test_refusal_and_foreign_engine_queue_never_start_the_next_run(queue, monkeypatch):
    q = queue
    first, second = [queue_run(q, key).json()["id"] for key in ("first", "second")]
    fake = FakeWan()
    fake.foreign_engine_queue = True
    monkeypatch.setattr(wan, "measure_clip", lambda data: wan.Measured(5, 64, 64, "24"))
    with fake.client() as wan_http:
        worker = clip_worker(q, wan_http)
        assert worker.tick()
        waiting = read_run(q, first)[0]
        assert waiting["status"] == "queued" and waiting["error"]["code"] == "wan.foreign_engine_queue"
        assert waiting["wan_attempts"][0]["state"] == "busy"
        assert fake.submissions == []
        assert not worker.tick()
        assert read_run(q, second)[0]["wan_attempts"] == []
        fake.foreign_engine_queue = False
        q.clock.advance(60)
        assert worker.tick()
    assert len(set(fake.puts())) == 2
    assert fake.submissions == [fake.put_bodies[-1][0]]
    assert [a["state"] for a in read_run(q, first)[0]["wan_attempts"]] == ["busy", "succeeded"]
    assert worker_api(q).claim().identity["run_id"] == second


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


@pytest.mark.parametrize(("admission_code", "legacy_message", "state", "reason"), [
    ("gpu_busy", "changed diagnostic", "queued", "wan.busy"),
    ("gpu_warm", "changed diagnostic", "queued", "wan.busy"),
    ("engine_busy", "changed diagnostic", "queued", "wan.foreign_engine_queue"),
    ("lease_held", "changed diagnostic", "queued", "wan.busy"),
    ("local_model_handover", "changed diagnostic", "queued", "wan.busy"),
    ("local_model_unavailable", "changed diagnostic", "queued", "wan.busy"),
    ("pre_admission_failed", GPU_REFUSALS[0], "held", "wan.pre_admission_failed"),
    ("new_code", GPU_REFUSALS[0], "held", "wan.admission_unknown"),
    (None, GPU_REFUSALS[0], "queued", "wan.busy"),
])
def test_terminal_admission_prefers_machine_code(queue, admission_code, legacy_message, state, reason):
    q = queue
    run_id = queue_run(q, "admission-code").json()["id"]
    fake = FakeWan()
    fake.gpu_refusal = legacy_message
    if admission_code is not None:
        def code_on_status(job_id):
            fake.jobs[job_id]["admission_code"] = admission_code
        fake.before_get = code_on_status
    with fake.client() as wan_http:
        assert clip_worker(q, wan_http).tick()
    run, _ = read_run(q, run_id)
    assert run["status"] == state and run["error"]["code"] == reason
    attempt_state = "busy" if state == "queued" else "sent"
    assert run["wan_attempts"][0]["state"] == attempt_state
    assert len(fake.puts()) == 1 and not fake.submissions


def select_role_set(q, tmp_path, *, with_unmasked=False, loop_source=None):
    from copy import deepcopy

    from haynes_studio.store import blob_locator
    from tests.build_story import fixtures as f
    from tests.build_story.test_foreground_roles import MASK, SOURCE, UNMASKED_SET, role_world
    from tests.layered import media

    world, example_story, plate = role_world(tmp_path / "role-store", right=SOURCE[0])
    if with_unmasked or loop_source == "unmasked":
        original = deepcopy(plate)
        original["id"] = UNMASKED_SET
        del original["occlusion"]
        plate["number"] = 2
        world.docs.insert(world.docs.index(plate), original)
    if loop_source is not None:
        world.loop(f.SET_LOOP, 41, still_sha=plate["content"]["sha256"], clip=media.set_clip(f.SET_N),
                   start=media.set_plate(), subject="set", frames=f.SET_N)
        source = UNMASKED_SET if loop_source == "unmasked" else f.PLATE
        world.docs[-1]["provenance"]["generator"]["source_asset_version_ids"] = [source]
    add_sound_bed(q, tmp_path)
    minter = Minter()
    ids = {doc["id"]: minter.mint("asv") for doc in world.docs}
    assets = {asset_id: minter.mint("ast") for asset_id in {doc["asset_id"] for doc in world.docs}}
    with q.engine.begin() as conn:
        for doc in deepcopy(world.docs):
            doc.update(id=ids[doc["id"]], asset_id=assets[doc["asset_id"]])
            doc["provenance"]["source_key"] = "fixture:role:" + doc["id"]
            if doc["legacy"] is not None:
                doc["legacy"]["source_key"] = doc["provenance"]["source_key"]
            if doc["content"] is not None:
                content = doc["content"]
                doc["scope"] = {"production_id": q.production_id}
                with world.store.open(content["locator"]) as data:
                    published = q.store.publish(data, scope=q.production_id, media_type=content["media_type"])
                content["locator"] = published.locator
            if doc.get("occlusion"):
                doc["occlusion"]["foreground"][0]["mask"]["version_id"] = ids[MASK]
            if doc.get("motion"):
                generator = doc["provenance"]["generator"]
                if "source_asset_version_ids" in generator:
                    generator["source_asset_version_ids"] = [ids[source] for source in generator["source_asset_version_ids"]]
                digest = doc["motion"]["source"]["image_sha256"]
                origin = blob_locator(example_story["production_id"], digest, "image/png")
                with world.store.open(origin) as start:
                    q.store.publish(start, scope=q.production_id, media_type="image/png", expected_sha256=digest)
            record_asset_version(conn, doc)

    story_path = f"/v1/stories/{q.story_id}"
    example_story["layouts"]["default"] = {}
    example_story["cast"][0]["voice_version_id"] = ids[example_story["cast"][0]["voice_version_id"]]
    example_story["set"]["asset_version_id"] = ids[example_story["set"]["asset_version_id"]]
    changed = q.browser.patch(story_path, headers={**q.csrf, "If-Match": "4"}, json={
        key: example_story[key] for key in ("cast", "set", "layouts", "motion_style")
    })
    assert changed.status_code == 200, changed.text
    board_path = f"/v1/boards/{q.board_id}"
    sample = example_story["boards"][0]
    sample["timing"]["hold_ms"] = 500
    for key in ("asset_version_id", "motion_asset_version_id"):
        sample["cast"][0][key] = ids[sample["cast"][0][key]]
    board = q.browser.patch(board_path, headers={**q.csrf, "If-Match": "2"}, json={
        key: sample[key] for key in ("cast", "layout", "method", "timing", "photo")
    })
    assert board.status_code == 200, board.text
    return ids, example_story["set"]["asset_version_id"], board.headers["etag"]


def test_queue_and_run_writer_require_foreground_and_pin_the_mask(queue, tmp_path, request):
    from copy import deepcopy

    from haynes_studio.build.prebuild import snapshot_bytes
    from haynes_studio.errors import ContractError
    from haynes_studio.layered.foreground import FOREGROUND_REQUIRED, MASK_STALE
    from tests.build_story.test_foreground_roles import MASK

    q = queue
    ids, set_id, etag = select_role_set(q, tmp_path)
    board_path = f"/v1/boards/{q.board_id}"
    disabled = q.browser.patch(board_path, headers={**q.csrf, "If-Match": etag},
                               json={"layout": {"preset": "pair", "foreground": False}})
    assert disabled.status_code == 200, disabled.text
    refused = queue_run(q, "disabled-role", rev=7)
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == FOREGROUND_REQUIRED

    enabled = q.browser.patch(board_path, headers={**q.csrf, "If-Match": disabled.headers["etag"]},
                              json={"layout": {"preset": "pair", "foreground": True}})
    assert enabled.status_code == 200, enabled.text
    queued = queue_run(q, "enabled-role", rev=8)
    assert queued.status_code == 201, queued.text
    run_id = queued.json()["id"]
    with q.engine.begin() as conn:
        row = runs.get(conn, run_id)
        [mask_pin] = [pin for pin in row["snapshot"]["resolved_asset_versions"] if pin["id"] == ids[MASK]]
        [mask] = [doc for doc in row["frozen_library"] if doc["id"] == ids[MASK]]
        assert mask_pin == {"id": ids[MASK], "kind": "prop", "sha256": mask["content"]["sha256"]}
        for code in (FOREGROUND_REQUIRED, MASK_STALE):
            snapshot = deepcopy(row["snapshot"])
            if code == FOREGROUND_REQUIRED:
                snapshot["story"]["boards"][0]["layout"]["foreground"] = False
            else:
                mask_pin = next(pin for pin in snapshot["resolved_asset_versions"] if pin["id"] == ids[MASK])
                mask_pin["sha256"] = "0" * 64
            with pytest.raises(ContractError) as rejected:
                runs.enqueue(conn, snapshot=snapshot, snapshot_sha256=snapshot_bytes(snapshot)[1],
                             library=row["frozen_library"], actor=row["document"]["queued_by"], key=code,
                             store=q.store, estimate={"estimate": None, "methods": []})
            assert [issue.rule for issue in rejected.value.violations] == [code]
        library = deepcopy(row["frozen_library"])
        version = next(version for version in library if version["id"] == set_id)
        version["occlusion"]["foreground"][0]["layer_order"] += 1
        with pytest.raises(runs.QueueConflict) as rejected:
            runs.enqueue(conn, snapshot=row["snapshot"], snapshot_sha256=row["document"]["snapshot"]["sha256"],
                         library=library, actor=row["document"]["queued_by"], key="changed-declaration",
                         store=q.store, estimate={"estimate": None, "methods": []})
        assert rejected.value.code == "run.snapshot_changed"
        assert [held["id"] for held in runs.list_story(conn, q.story_id, None, 10)] == [run_id]

    wan_client = FakeWan().client()
    request.addfinalizer(wan_client.close)
    worker = BuildWorker(worker_api(q), ProductWan(wan_client), store=q.store, stage_root=q.stage_root,
                         register=register(), tracker_story=STORY,
                         transcriber=SimpleNamespace(name="Fixture ASR", transcribe=lambda _: ""),
                         clock=q.clock.monotonic, pause=q.clock.advance)
    assert worker.tick()
    built, _ = read_run(q, run_id)
    assert built["status"] == "succeeded", built["error"]


@pytest.mark.parametrize("path", [
    "layered-photo", "layered-photo-rerender", "layered-film", "layered-film-rerun",
    "whole-frame-photo", "whole-frame-photo-selected-reference", "whole-frame-photo-reference", "whole-frame-film",
    "external-upload", "external-upload-reference",
    "layered-set-loop", "layered-set-loop-and-still", "layered-set-loop-unmasked",
])
def test_picture_paths_draw_the_selected_role_mask_or_refuse(queue, tmp_path, path):
    from io import BytesIO

    import numpy as np
    from PIL import Image

    from haynes_studio.db.schema import media_jobs
    from haynes_studio.layered.foreground import UNSUPPORTED
    from haynes_studio.queue.staging import BuildStageStore
    from haynes_studio.render.encode import decode_frames
    from haynes_studio.store import blob_locator
    from tests.build_story.fixtures import SET_LOOP
    from tests.build_story.test_foreground_roles import UNMASKED_SET
    from tests.db.test_media_jobs import PROVENANCE, image_worker

    q = queue
    loop = path.startswith("layered-set-loop")
    unmasked_loop = path == "layered-set-loop-unmasked"
    loop_source = ("unmasked" if unmasked_loop else "masked") if loop else None
    ids, set_id, etag = select_role_set(q, tmp_path, loop_source=loop_source)
    board_path = f"/v1/boards/{q.board_id}"
    story_path = f"/v1/stories/{q.story_id}"
    if loop:
        story = q.browser.get(story_path)
        setting = {**story.json()["set"], "motion_asset_version_id": ids[SET_LOOP]}
        changed = q.browser.patch(story_path, json={"set": setting},
                                  headers={**q.csrf, "If-Match": story.headers["etag"]})
        assert changed.status_code == 200, changed.text
        if path != "layered-set-loop-and-still":
            setting["asset_version_id"] = None
            changed = q.browser.patch(story_path, json={"set": setting},
                                      headers={**q.csrf, "If-Match": changed.headers["etag"]})
            assert changed.status_code == 200, changed.text
        if not unmasked_loop:
            refused = queue_run(q, path, rev=changed.json()["revision"])
            assert refused.status_code == 422, refused.text
            assert refused.json()["error"]["code"] == UNSUPPORTED
            with q.owner.connect() as conn:
                assert runs.list_story(conn, q.story_id, None, 10) == []
            if path == "layered-set-loop":
                assert_loop_source_cannot_be_stripped_from_sql_run(q, set_id)
            return

    if not path.startswith("layered-"):
        # Exercise both an explicitly selected set and an unselected set used as an image reference.
        reference_only = path in ("whole-frame-photo-reference", "external-upload-reference")
        if reference_only:
            story = q.browser.get(story_path)
            changed = q.browser.patch(story_path, json={"set": None},
                                      headers={**q.csrf, "If-Match": story.headers["etag"]})
            assert changed.status_code == 200, changed.text
        sources = [set_id] if path.startswith("whole-frame-photo") and path.endswith("-reference") else []
        changed = q.browser.patch(board_path, headers={**q.csrf, "If-Match": etag}, json={
            "method": {"layer": "whole_frame", "motion": "i2v"}, "cast": [],
            "photo": {"current_version_id": q.version_id, "prompt": "first angle",
                      "input_asset_version_ids": sources},
        })
        assert changed.status_code == 200, changed.text
        if path.startswith("external-"):
            _, headers = register_agent(q.owner, {q.production_id: ["read", "assets:upload"]})
            declared = {**PROVENANCE, "source_asset_version_ids": [set_id] if reference_only else []}
            refused = q.browser.post(board_path + "/photo-versions", content=q.png, headers={
                **headers, "If-Match": changed.headers["etag"], "Content-Type": "image/png",
                "X-Studio-Photo-Provenance": json.dumps(declared),
            })
        elif path == "whole-frame-film":
            revision = q.browser.get(story_path).json()["revision"]
            refused = queue_run(q, path, rev=revision)
        else:
            refused = q.browser.post(board_path + "/photo-jobs", json={},
                                     headers={**q.csrf, "Idempotency-Key": path})
        assert refused.status_code == 422, refused.text
        assert refused.json()["error"]["code"] == UNSUPPORTED
        with q.owner.connect() as conn:
            assert conn.scalar(sa.select(sa.func.count()).select_from(media_jobs)) == 0
            assert runs.list_story(conn, q.story_id, None, 10) == []
        return

    if path.startswith("layered-photo"):
        worker, runner = image_worker(q)
        attempts = 2 if path.endswith("rerender") else 1
        for attempt in range(attempts):
            queued = q.browser.post(board_path + "/photo-jobs", json={},
                                    headers={**q.csrf, "Idempotency-Key": f"{path}-{attempt}"})
            assert queued.status_code == 202, queued.text
            job_id = queued.json()["id"]
            assert worker.tick()
            result = q.browser.get(f"/v1/jobs/{job_id}/result")
            assert result.status_code == 200, result.text
            version = result.json()
            # The same stored bytes feed the job preview and board thumbnails.
            digest = version["content"]["sha256"]
            preview = q.browser.get(f"/v1/jobs/{job_id}/media/{digest}")
            assert preview.status_code == 200, preview.text
            with Image.open(BytesIO(preview.content)) as image:
                assert image.size == (1080, 1920)
                assert np.count_nonzero(np.asarray(image)) == 0
        assert not runner.calls
        return

    with FakeWan().client() as wan_client:
        worker = BuildWorker(worker_api(q), ProductWan(wan_client), store=q.store, stage_root=q.stage_root,
                             register=register(), tracker_story=STORY,
                             transcriber=SimpleNamespace(name="Fixture ASR", transcribe=lambda _: ""),
                             clock=q.clock.monotonic, pause=q.clock.advance)
        attempts = 2 if path.endswith("rerun") else 1
        for attempt in range(attempts):
            revision = q.browser.get(story_path).json()["revision"]
            queued = queue_run(q, f"{path}-{attempt}", rev=revision)
            assert queued.status_code == 201, queued.text
            if unmasked_loop:
                with q.owner.connect() as conn:
                    frozen = runs.get(conn, queued.json()["id"])["snapshot"]
                assert {pin["id"] for pin in frozen["resolved_asset_versions"]} >= {ids[SET_LOOP], ids[UNMASKED_SET]}
                assert frozen["story"]["set"]["asset_version_id"] is None
            assert worker.tick()
            built, _ = read_run(q, queued.json()["id"])
            assert built["status"] == "succeeded", built["error"]
            stage = built["stages"][0]
            segment = next(artifact for artifact in stage["artifacts"] if artifact["name"] == "segment")
            staging = BuildStageStore(q.stage_root, built["id"], q.store)
            for store, digest in ((staging, segment["sha256"]),
                                  (q.store, built["outputs"]["master_sha256"]),
                                  (q.store, built["outputs"]["proxy_sha256"])):
                locator = blob_locator(q.production_id, digest, "video/mp4")
                with store.open(locator) as media:
                    assert bool(np.count_nonzero(next(decode_frames(media)))) is unmasked_loop


def assert_loop_source_cannot_be_stripped_from_sql_run(q, source_id):
    from haynes_studio.build.prebuild import snapshot_bytes
    from haynes_studio.db.catalog import build_library
    from haynes_studio.errors import ContractError
    from haynes_studio.layered.foreground import UNSUPPORTED
    from haynes_studio.library.resolve import story_references
    from haynes_studio.queue.inputs import freeze, prepare_queue
    from tests.build_story.fixtures import OPERATOR

    with q.engine.begin() as conn:
        story = drafts.get_draft(conn, q.story_id).exchange()
        catalog = build_library(conn, story, {ref.version_id for ref in story_references(story)})
        documents = [catalog.document(id_) for id_ in catalog.versions]
        source = next(version for version in documents if version["id"] == source_id)
        del source["occlusion"]
        prepared = prepare_queue(story, Library.from_version_documents(documents))
        assert prepared.ok, prepared.report.problems
        frozen, library = freeze(prepared, studio="git:fixture")
        with pytest.raises(ContractError) as rejected:
            runs.enqueue(conn, snapshot=frozen, snapshot_sha256=snapshot_bytes(frozen)[1],
                         library=library, actor=OPERATOR, key="stripped-loop-source", store=q.store,
                         estimate={"estimate": None, "methods": []})
        assert [issue.rule for issue in rejected.value.violations] == [UNSUPPORTED]
        assert runs.list_story(conn, q.story_id, None, 10) == []


def test_catalog_reader_refuses_all_five_noncanonical_role_fields(queue):
    from haynes_studio.db.catalog import version_library
    from haynes_studio.db.schema import asset_versions
    from haynes_studio.errors import ContractError

    with queue.owner.connect() as conn:
        document = conn.scalar(sa.select(asset_versions.c.document).where(asset_versions.c.id == queue.version_id))
        for value in (None, [], {}, {"foreground": []}, {"foreground": None}):
            conn.execute(asset_versions.update().where(asset_versions.c.id == queue.version_id).values(
                document={**document, "occlusion": value},
            ))
            with pytest.raises(ContractError) as refused:
                version_library(conn, version_id=queue.version_id)
            assert [issue.rule for issue in refused.value.violations] == ["occlusion.noncanonical"]
        conn.rollback()
