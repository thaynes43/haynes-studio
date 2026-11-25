"""Queue acceptance through the runtime role, fake Wan and a fake clock."""

import asyncio
import hashlib
from secrets import token_hex
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.sql import visitors
from sqlalchemy.sql.selectable import ScalarSelect

from haynes_studio.adapters import wan
from haynes_studio.api.app import create_app
from haynes_studio.api.auth import SESSION_COOKIE
from haynes_studio.canonical.ids import Minter
from haynes_studio.canonical.model import Board, Story
from haynes_studio.db import drafts, identity, runs
from haynes_studio.db.catalog import record_asset_version
from haynes_studio.db.schema import run_wan_attempts, worker_tokens
from haynes_studio.library import Library
from haynes_studio.photo.plan import plan_photo
from haynes_studio.queue.wan import GPU_REFUSALS, LanePaused, ProductClips, ProductWan, product_request
from haynes_studio.queue.worker import BuildWorker
from haynes_studio.queue.worker_api import WorkerAPI, WorkerAPIError
from haynes_studio.queue.worker_tokens import worker_bearer

from tests.build_story.fixtures import example, photo_png, register
from tests.db.test_studio_api import (
    bearer, client, engine, new_production, new_story, owner_engine,
    register_agent, runtime_db, runtime_role, service, sign_in,
)
from tests.queue.fake_wan import Clock, FakeWan, STORY

pytestmark = pytest.mark.db


def worker_credentials(engine):
    secret = worker_bearer(token_hex(24))
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
        conn.exec_driver_sql("TRUNCATE escalation_events, escalation_packages, escalation_check_failures, "
                             "go_live_withdrawals, go_live_approvals, run_check_overrides, run_wan_attempts, runs")
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


@pytest.mark.parametrize("refused", [False, True], ids=["lost-reply", "definite-refusal"])
def test_worker_recovers_or_fails_staged_delivery(queue, tmp_path, refused):
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
