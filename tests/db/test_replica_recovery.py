"""Studio integration through two API apps, PostgreSQL, and synthetic engines."""

import asyncio
from contextlib import ExitStack
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace

import httpx
import pytest
import sqlalchemy as sa

from haynes_studio.adapters.fakes import FakeComfyUI, FakeKokoro
from haynes_studio.api.app import create_app
from haynes_studio.api.auth import CSRF_HEADER, SESSION_COOKIE
from haynes_studio.api.oidc import OIDC
from haynes_studio.canonical import to_document
from haynes_studio.canonical.ids import Minter
from haynes_studio.db import identity
from haynes_studio.db.catalog import record_delivery
from haynes_studio.db.engine import connect_engine
from haynes_studio.db.schema import media_jobs, sessions
from haynes_studio.delivery import deliver
from haynes_studio.queue.wan import ProductWan
from haynes_studio.queue.worker import BuildWorker
from haynes_studio.queue.worker_api import WorkerAPIError
from haynes_studio.store import LocalStore

from tests.build_story.fixtures import register
from tests.db.test_escalation import CALLBACK, FakeTransport, accept, fixture_responder, path, propose, transition
from tests.db.test_go_live import finished_fixture
from tests.db.test_media_jobs import (
    board_in, image_worker, operation, speech_worker, success, upload,
)
from tests.db.test_run_queue import (
    add_sound_bed, clips_for, queue, queue_run, request_for, worker_api, worker_credentials,
)
from tests.db.test_studio_api import (
    ORIGIN, assert_auth_redirect, begin_login, client, engine, owner_engine,
    register_agent, runtime_db, runtime_role, service,
)
from tests.delivery.media import write_master
from tests.formats.fixtures import doll_short
from tests.queue.fake_wan import STORY, FakeWan

pytestmark = pytest.mark.db


class WorkerStopped(BaseException):
    """An engine received work but the caller never returned to the worker."""


@pytest.fixture
def replicas(queue, runtime_db, tmp_path):
    """Separate application state, OIDC caches, store handles and DB pools."""
    with ExitStack() as stack:
        def start(**settings):
            engine = connect_engine(runtime_db.url, runtime_db.schema)
            stack.callback(engine.dispose)
            oidc = OIDC(replace(queue.issuer.settings(), **settings),
                        httpx.MockTransport(queue.issuer.request))
            app = create_app(engine, LocalStore(tmp_path / "store"), oidc,
                             build_stage_root=queue.stage_root)
            browser = client(app)
            stack.callback(browser.close)
            return app, browser

        yield start


def assert_error(response, status, code):
    assert response.status_code == status
    error = response.json()["error"]
    assert error["code"] == code
    assert error["request_id"] == response.headers["x-request-id"]


def as_person(browser, q):
    browser.cookies.set(SESSION_COOKIE, q.browser.cookies[SESSION_COOKIE])
    return browser


def media_board(q, *, spoken=False):
    base = f"/v1/productions/{q.production_id}/media-types/short/stories"
    story = success(q.browser.post(base, headers=q.csrf, json={"title": "Media fixture"}), 201)["id"]
    context = SimpleNamespace(browser=q.browser, csrf=q.csrf, story_id=story, owner=q.owner)
    return board_in(context, spoken=spoken, by_human=True)


def concurrent_claims(*requests):
    async def claim(app, headers, body):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as http:
            return await http.post("/internal/v1/work/claim", headers=headers, json=body)

    async def both():
        return await asyncio.gather(*(claim(*request) for request in requests))

    return asyncio.run(both())


def test_two_replicas_share_one_queue_and_restart_recovers_the_expired_claim(queue, replicas):
    q = queue
    first = success(queue_run(q, "head"), 201)
    second = success(queue_run(q, "tail"), 201)
    image = success(q.browser.post(f"/v1/boards/{media_board(q)}/photo-jobs",
                                  headers={**q.csrf, "Idempotency-Key": "photo"}, json={}), 202)
    selections = "/v1/me/selections"
    selected = success(q.browser.put(selections, headers={**q.csrf, "If-Match": '"0"'},
                                    json={"values": {"story": q.story_id}}))
    original_snapshot = q.browser.get(f"/v1/runs/{first['id']}/snapshot")
    assert original_snapshot.status_code == 200

    app_b, browser_b = replicas()
    worker_a, worker_b = worker_credentials(q.owner), worker_credentials(q.owner)
    workers = [(q.app, worker_a, None), (app_b, worker_b, None)]
    with ExitStack() as live:
        # Close whichever app handled the successful claim, keeping the other
        # lifespan active. PostgreSQL must preserve the claim from either app.
        lifespans = [live.enter_context(ExitStack()) for _ in workers]
        browsers = [lifetime.enter_context(browser)
                    for lifetime, browser in zip(lifespans, (client(q.app), browser_b), strict=True)]
        results = concurrent_claims(*workers)
        assert sorted(r.status_code for r in results) == [200, 204]
        winner = next(i for i, r in enumerate(results) if r.status_code == 200)
        old = results[winner].json()
        assert old["run"]["id"] == first["id"]
        assert old["snapshot"] == original_snapshot.json()
        identity_a = workers[winner][1]
        identity_b = workers[1 - winner][1]
        lifespans[winner].close()
        surviving_browser = as_person(browsers[1 - winner], q)
        assert success(surviving_browser.get(selections)) == selected

        app_c, browser_c = replicas()
        live.enter_context(browser_c)
        new_worker = worker_api(q, app=app_c, headers=identity_b)
        assert new_worker.claim() is None
        frozen = as_person(browser_c, q).get(f"/v1/runs/{first['id']}/snapshot")
        assert frozen.content == original_snapshot.content
        assert frozen.headers["etag"] == original_snapshot.headers["etag"]

        q.clock.now = datetime.fromisoformat(old["claim_until"])
        takeover = new_worker.claim()
        assert takeover.identity == {"run_id": first["id"], "fence": old["fence"] + 1}
        assert takeover.body["run"]["status"] == "held"
        stale = {"run_id": first["id"], "fence": old["fence"]}
        for route, extra in (
            ("heartbeat", {}), ("publish", {}),
            ("complete", {"stages": [], "outputs": {}, "checks": [], "provenance": {}, "delivery_id": "unused"}),
            ("fail", {"status": "failed", "reason": "Superseded worker"}),
        ):
            assert_error(surviving_browser.post(f"/internal/v1/work/{route}", headers=identity_a,
                                                json={**stale, **extra}), 409, "work.fence_lost")
        assert takeover.heartbeat()["cancel_requested"] is False
        takeover.resume()
        takeover.fail(status="failed", reason="Fixture finished")
        next_run, next_image = concurrent_claims((app_c, identity_b, None),
                                                (surviving_browser.app, identity_a, {"lane": "image"}))
        assert success(next_run)["run"]["id"] == second["id"]
        assert success(next_image)["job"]["id"] == image["id"]


def test_slow_wan_poll_allows_reads_and_other_lane_claims(queue, replicas, tmp_path):
    q = queue
    head = success(queue_run(q, "slow-head"), 201)["id"]
    tail = success(queue_run(q, "slow-tail"), 201)["id"]
    photo = success(q.browser.post(f"/v1/boards/{media_board(q)}/photo-jobs",
                                  headers={**q.csrf, "Idempotency-Key": "during-poll"}, json={}), 202)
    claim = worker_api(q).claim()
    assert claim.identity["run_id"] == head
    standby, browser = replicas()
    as_person(browser, q)
    other = worker_api(q, app=standby)
    clip = write_master(tmp_path / "wan.mp4", frames=5, width=64, height=64, audio_codec=None)
    fake = FakeWan(clip.read_bytes())
    fake.poll_misses = 1
    checked = []

    def while_poll_is_blocked(job_id):
        # The real client has entered its external GET and cannot finish it until
        # the other replica handles the foreground requests.
        assert other.claim() is None
        assert success(browser.get(f"/v1/runs/{tail}"))["status"] == "queued"
        assert other.claim("image").identity["job_id"] == photo["id"]
        checked.append(job_id)
        fake.before_get = None

    fake.before_get = while_poll_is_blocked
    with fake.client() as engine:
        result = clips_for(q, claim, engine).make(request_for(q), stage="fixture")
    assert checked == [result.job_id]
    assert fake.submissions == [result.job_id]
    assert fake.events.count(("GET", fake.puts()[0])) == 2
    assert success(browser.get(f"/v1/runs/{head}"))["wan_attempts"][0]["state"] == "succeeded"
    claim.fail(status="failed", reason="Fixture finished")
    assert other.claim().identity["run_id"] == tail


def test_terminated_database_connection_rolls_back_claim_and_retry_keeps_id(queue, replicas, record_property):
    q = queue
    key = "lost-enqueue-response"
    made = queue_run(q, key)
    assert made.status_code == 201
    first = made.json()["id"]
    second = success(queue_run(q, "next"), 201)["id"]
    restarted, browser = replicas()
    as_person(browser, q)
    enqueue = f"/v1/stories/{q.story_id}/runs"
    idem = {**q.csrf, "Idempotency-Key": key, "If-Match": '"3"'}
    # The client retries the already committed request through another replica.
    replay = browser.post(enqueue, headers=idem)
    assert replay.status_code == 200 and replay.json()["id"] == first
    record_property("queue_head", first)
    record_property("enqueue_request", made.headers["x-request-id"])
    record_property("replay_request", replay.headers["x-request-id"])
    assert_error(browser.post(enqueue, headers={**idem, "If-Match": '"2"'}),
                 422, "idempotency.mismatch")

    terminated = []

    def disconnect_after_update(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE runs SET") and not terminated:
            pid = conn.connection.driver_connection.info.backend_pid
            with q.owner.connect() as admin:
                terminated.append(admin.scalar(sa.select(sa.func.pg_terminate_backend(pid, 5000))))

    # Terminate the actual PostgreSQL backend after the claim updates the row
    # and before commit. The failure therefore exercises DB rollback and pool recovery.
    sa.event.listen(q.engine, "after_cursor_execute", disconnect_after_update)
    try:
        with pytest.raises(WorkerAPIError) as failure:
            worker_api(q).claim()
        assert terminated == [True]
        assert (failure.value.status, failure.value.code) == (503, "database.failed")
    finally:
        sa.event.remove(q.engine, "after_cursor_execute", disconnect_after_update)
    before = success(browser.get(f"/v1/runs/{first}"))
    assert before["status"] == "queued"
    claim = worker_api(q).claim()  # The same API pool must replace the dead connection.
    assert claim.identity == {"run_id": first, "fence": 1}
    assert worker_api(q, app=restarted).claim() is None
    claim.fail(status="failed", reason="Fixture finished")
    assert worker_api(q, app=restarted).claim().identity["run_id"] == second


def test_worker_interrupted_after_image_dispatch_is_not_replayed(queue, replicas):
    q = queue
    q.agent, q.auth = q.browser, q.csrf
    board = media_board(q)
    accepted = success(operation(q, board, "photo", "ambiguous-image", body={"seed": 17}), 202)

    class LostAfterDispatch(FakeComfyUI):
        def answer(self, name, command, args):
            reply = super().answer(name, command, args)
            if name == "comfyui_prompt.py":
                raise WorkerStopped
            return reply

    fake = LostAfterDispatch()
    worker, _ = image_worker(q, fake)
    with pytest.raises(WorkerStopped):
        worker.tick()
    assert len(fake.payloads) == 1

    app, browser = replicas()
    as_person(browser, q)
    body = {"seed": 17}
    headers = {**q.csrf, "Idempotency-Key": "ambiguous-image"}
    image_url = f"/v1/boards/{board}/photo-jobs"
    replay = success(browser.post(image_url, headers=headers, json=body))
    assert replay["id"] == accepted["id"] and replay["status"] == "running"
    assert_error(browser.post(image_url, headers=headers, json={"seed": 18}), 422, "idempotency.mismatch")
    replacement, _ = image_worker(SimpleNamespace(app=app, store=q.store, owner=q.owner), fake)
    assert not replacement.tick()
    with q.owner.begin() as conn:
        conn.execute(media_jobs.update().where(media_jobs.c.id == accepted["id"])
                     .values(claim_until=sa.func.now() - timedelta(seconds=1)))
    assert not replacement.tick()
    settled = success(browser.post(image_url, headers=headers, json=body))
    assert settled["id"] == accepted["id"] and settled["status"] == "failed"
    job = success(browser.get(f"/v1/jobs/{accepted['id']}"))
    assert job["error"]["code"] == "work.dispatch_unconfirmed"
    jobs = success(browser.get(f"/v1/boards/{board}/jobs"))["items"]
    assert [job["id"] for job in jobs] == [accepted["id"]]
    assert len(fake.payloads) == 1


def test_replacement_looks_up_interrupted_wan_submission_before_letting_the_queue_advance(
    queue, replicas, tmp_path, record_property,
):
    q = queue
    add_sound_bed(q, tmp_path)
    first = success(queue_run(q, "wan-interrupted", rev=4), 201)["id"]
    second = success(queue_run(q, "next", rev=4), 201)["id"]
    run_path = f"/v1/runs/{first}"

    class LostAfterDispatch(FakeWan):
        def request(self, request):
            reply = super().request(request)
            if request.method == "PUT" and request.url.path.startswith("/v1/jobs/"):
                raise WorkerStopped
            return reply

    fake = LostAfterDispatch()
    settings = dict(store=q.store, stage_root=q.stage_root, register=register(),
                    tracker_story=STORY, transcriber=None, clock=q.clock.monotonic, pause=q.clock.advance)
    with fake.client() as wan:
        first_worker = BuildWorker(worker_api(q), ProductWan(wan), **settings)
        try:
            first_worker.tick()
        except WorkerStopped:
            pass
        else:
            failed = success(q.browser.get(run_path))
            pytest.fail(f"Wan dispatch was never reached: {failed['status']}, {failed.get('error')}")
        job_id, = fake.submissions
        put, = fake.puts()
        record_property("queue_head", first)
        record_property("fake_wan_job", job_id)

        replacement_app, browser = replicas()
        as_person(browser, q)
        live = browser.get(run_path)
        assert success(live)["wan_attempts"] == [{"job_id": job_id, "kind": "i2v", "attempt": 1, "state": "sent"}]
        assert success(browser.get(f"/v1/runs/{second}"))["status"] == "queued"
        replay = browser.post(f"/v1/stories/{q.story_id}/runs",
                              headers={**q.csrf, "Idempotency-Key": "wan-interrupted", "If-Match": '"4"'})
        assert success(replay)["id"] == first
        cancel = browser.post(run_path + "/cancel", headers={**q.csrf, "If-Match": replay.headers["etag"]})
        assert success(cancel)["cancel_requested"] is True

        replacement_api = worker_api(q, app=replacement_app)
        replacement = BuildWorker(replacement_api, ProductWan(wan), **settings)
        assert not replacement.tick()
        q.clock.advance(91)
        assert replacement.tick()
        assert success(browser.get(run_path))["status"] == "cancelled"
        assert replacement_api.claim().identity["run_id"] == second
    assert [(method, path) for method, path in fake.events if path == put] == [("PUT", put), ("GET", put)]
    assert fake.submissions == [job_id]


def approval_fixture(q):
    return finished_fixture(SimpleNamespace(owner=q.owner, story=q.story_id,
                                            production=q.production_id))


def test_oidc_callback_on_other_replica_enforces_state_nonce_replay_and_freshness(queue, replicas):
    q = queue
    settings = {"go_live_approver_subjects": frozenset({"one"}), "go_live_freshness_seconds": 90}
    _, login = replicas(**settings)
    _, callback = replicas(**settings)
    approval = approval_fixture(q)

    def begin(**params):
        query = begin_login(login, **params)
        callback.cookies.update(login.cookies)
        return query

    def finish(query, code, *, state=None):
        return callback.get("/auth/callback", params={"code": code, "state": state or query["state"][0]})

    query = begin()
    assert_auth_redirect(finish(query, q.issuer.authorize(query, "one"), state="incorrect"), "auth.oidc_state")
    assert_auth_redirect(finish(query, q.issuer.authorize(query, "one", nonce="incorrect")), "auth.oidc_invalid")
    assert callback.get("/v1/me").status_code == 401

    q.clock.now = datetime.now(UTC)
    query = begin(return_to="/editor")
    stale_time = int(q.clock.now.timestamp()) - 91
    code = q.issuer.authorize(query, "one", auth_time=stale_time)
    response = finish(query, code)
    assert response.status_code == 303 and response.headers["location"] == "/editor"
    me = success(callback.get("/v1/me"))
    assert me["principal"]["sub"] == "one"
    csrf = {CSRF_HEADER: me["csrf_token"]}
    assert_error(callback.post(approval.path, headers=csrf, json=approval.body),
                 403, "approval.sign_in_again")

    # A new valid state reaches the provider with the used code and is refused.
    assert_auth_redirect(finish(begin(), code), "auth.oidc_invalid")
    assert success(callback.get("/v1/me"))["principal"] == me["principal"]
    with q.owner.begin() as conn:
        conn.execute(sessions.update().where(
            sessions.c.digest == identity.digest(callback.cookies[SESSION_COOKIE]),
        ).values(expires_at=sa.func.now() - timedelta(seconds=1)))
    assert callback.get("/v1/me").status_code == 401
    assert callback.get(approval.path).status_code == 401

    query = begin(fresh="true")
    assert query["prompt"] == ["login"]
    response = finish(query, q.issuer.authorize(query, "one", auth_time=int(q.clock.now.timestamp())))
    assert response.status_code == 303 and response.headers["location"] == "/"
    csrf = {CSRF_HEADER: success(callback.get("/v1/me"))["csrf_token"]}
    approved = success(callback.post(approval.path, headers=csrf, json=approval.body), 201)
    assert approved["run_id"] == approval.id
    assert approved["master_sha256"] == approval.body["master_sha256"]


def test_person_agent_scopes_responder_and_worker_cross_the_same_http_boundaries(queue, replicas):
    q = queue
    q.clock.now = datetime.now(UTC)
    claim, proposed = propose(q)
    package = proposed["package"]
    package_id = package["deduplication_id"]
    assert transition(q, package_id, "authorize").status_code == 200
    accept(q, package_id, FakeTransport())
    finished = approval_fixture(q)
    board = media_board(q)
    _, browser = replicas(go_live_approver_subjects=frozenset({"one"}))
    as_person(browser, q)

    path_prefix = f"/v1/productions/{q.production_id}"
    story_path = f"/v1/stories/{q.story_id}"
    drafts = f"{path_prefix}/media-types/short/stories"
    board_path = f"/v1/boards/{board}"
    run = f"/v1/runs/{claim.identity['run_id']}"
    package_path = path(q, package_id)
    media_path = f"/v1/media/{sha256(q.png).hexdigest()}"
    scopes = ("read", "draft:write", "assets:generate", "assets:upload", "runs:queue", "formats:write")
    identities = {
        **{scope: register_agent(q.owner, {q.production_id: [scope]})[1] for scope in scopes},
        "person": q.csrf,
        "worker": worker_credentials(q.owner),
        "anonymous": {},
        # Callback is last for this identity because it closes the package.
        "responder": fixture_responder(q, package),
    }

    for role, auth in identities.items():
        http = browser if role == "person" else client(browser.app)
        public_denied = 401 if role in {"worker", "anonymous"} else 403
        hidden = 404 if role in scopes else public_denied

        def check(method, url, allowed, *, denied=public_denied, headers=None, **kwargs):
            response = http.request(method, url, headers={**auth, **(headers or {})}, **kwargs)
            expected = allowed.get(role, denied)
            assert response.status_code == expected, (role, method, url, expected, response.status_code)
            assert response.headers.get("x-request-id")
            return response

        check("GET", "/v1/me", dict.fromkeys(("person", "responder", *scopes), 200))
        check("GET", "/v1/me/selections", {"person": 200})
        check("GET", path_prefix, {"person": 200, "read": 200})
        check("GET", story_path, {"person": 200, "read": 200, "responder": 200})
        check("POST", drafts, {"person": 201, "draft:write": 201}, json={"title": f"Created by {role}"})
        check("GET", "/v1/assets", {"person": 200, "read": 200}, params={"production": q.production_id})
        check("POST", board_path + "/photo-jobs", {"person": 202, "assets:generate": 202},
              headers={"Idempotency-Key": "scope-test"}, json={})
        check("GET", board_path + "/jobs", {"person": 200, "read": 200})
        uploaded = upload(SimpleNamespace(agent=http, browser=q.browser, story_id=q.story_id),
                          board, q.png, headers=auth)
        assert uploaded.status_code == (201 if role == "assets:upload" else public_denied), (role, "upload")
        ranged = check("GET", media_path, {"person": 206, "read": 206},
                       denied=hidden, headers={"Range": "bytes=1-7"})
        if ranged.status_code == 206:
            assert ranged.content == q.png[1:8]
            assert ranged.headers["content-range"] == f"bytes 1-7/{len(q.png)}"
        else:
            assert "content-range" not in ranged.headers
        check("POST", story_path + "/runs", {"person": 201, "runs:queue": 201, "responder": 201},
              headers={"Idempotency-Key": "scope-test", "If-Match": '"3"'})
        check("GET", run + "/snapshot", {"person": 200, "read": 200}, denied=hidden)
        check("GET", story_path + "/candidates", {"person": 200, "read": 200}, denied=hidden)
        check("GET", finished.path.replace("/go-live-approvals", "/delivery"), {"person": 200, "read": 200})
        check("GET", "/v1/queue/lanes", {"person": 200})
        recipe = {**doll_short(), "id": "scope-" + role.replace(":", "-")}
        check("POST", "/v1/formats", {"person": 201, "formats:write": 201}, json=recipe)
        check("POST", finished.path, {"person": 201, "worker": 403}, json=finished.body)
        check("GET", package_path, {"person": 200, "read": 200})
        check("POST", "/internal/v1/work/claim", {"worker": 204}, denied=401, json={})
        check("POST", package_path + "/callback", {"responder": 200},
              headers={"Idempotency-Key": "scope-callback"}, json=CALLBACK)

    _, draft_writer = register_agent(q.owner, {q.production_id: ["draft:write"]})
    _, reader = register_agent(q.owner, {q.production_id: ["read"]})
    editor = client(browser.app)
    patched = editor.patch(story_path, headers={**draft_writer, "If-Match": '"3"'},
                           json={"title": "Edited from the other replica"})
    assert patched.status_code == 200
    assert_error(q.browser.patch(story_path, headers={**q.csrf, "If-Match": '"3"'},
                                 json={"title": "Stale title"}), 409, "conflict.revision")
    assert success(editor.get(story_path, headers=reader))["title"] == "Edited from the other replica"


def test_run_node_unavailable_leaves_drafts_existing_media_and_other_lanes_available(queue, replicas, tmp_path):
    q = queue
    queued = success(queue_run(q, "run-node-unavailable"), 201)
    fake_wan = FakeWan()
    fake_wan.outage = True
    with fake_wan.client() as wan:
        run_worker = BuildWorker(worker_api(q), ProductWan(wan), store=q.store, stage_root=q.stage_root,
                                 register=register(), tracker_story=STORY, transcriber=None,
                                 clock=q.clock.monotonic, pause=q.clock.advance)
        assert run_worker.tick()
    assert fake_wan.events == [("GET", "/v1/ready")]
    # Stop polling the run lane and age out its last check-in.
    q.clock.advance(91)
    app, browser = replicas()
    as_person(browser, q)
    context = SimpleNamespace(app=app, store=q.store, owner=q.owner, agent=browser, auth=q.csrf)
    assert {item["lane"] for item in success(browser.get("/v1/queue/lanes"))["items"]} == {"run", "voice", "image"}
    run = success(browser.get(f"/v1/runs/{queued['id']}"))
    assert (run["status"], run["wait_reason"], run["queue_wait"]["wall_s"]) == ("queued", "gpu_unavailable", None)
    listed = success(browser.get(f"/v1/stories/{q.story_id}/runs"))["items"]
    assert [item["id"] for item in listed] == [run["id"]]
    frozen = browser.get(f"/v1/runs/{run['id']}/snapshot")
    assert frozen.status_code == 200 and sha256(frozen.content).hexdigest() == queued["snapshot"]["sha256"]

    # Register a prior delivery and range-read the generated proxy bytes.
    master = write_master(tmp_path / "prior-master.mp4", frames=24)
    delivered = deliver(master, store=q.store, production_id=q.production_id,
                        run_id=Minter().mint("run"), expected_frames=24, now=q.clock.now)
    with q.engine.begin() as conn:
        record_delivery(conn, q.story_id, to_document(delivered))
    proxy = delivered.proxy
    partial = browser.get(f"/v1/media/{proxy.sha256}", headers={"Range": "bytes=-8"})
    with q.store.open(proxy.locator) as handle:
        handle.seek(-8, 2)
        assert partial.status_code == 206 and partial.content == handle.read()
    assert partial.headers["content-range"] == f"bytes {proxy.bytes - 8}-{proxy.bytes - 1}/{proxy.bytes}"

    board = media_board(q, spoken=True)
    board_path = f"/v1/boards/{board}"
    original = browser.get(board_path)
    edit = browser.patch(board_path, headers={**q.csrf, "If-Match": original.headers["etag"]},
                         json={"notes": [{"text": "Still editable"}]})
    assert edit.status_code == 200
    fake_voice, fake_image = FakeKokoro(), FakeComfyUI()
    voice_worker = speech_worker(context, fake_voice)
    image, _ = image_worker(context, fake_image)
    for lane, worker in (("voice", voice_worker), ("photo", image)):
        submitted = success(operation(context, board, lane, f"outage-{lane}"), 202)
        assert worker.tick()
        finished_job = success(browser.get(f"/v1/jobs/{submitted['id']}"))
        assert finished_job["status"] == "succeeded" and finished_job["result_is_current"]
    assert len(fake_voice.requests) == len(fake_image.payloads) == 1
    current = browser.get(board_path)
    assert browser.delete(board_path, headers={**q.csrf, "If-Match": current.headers["etag"]}).status_code == 204
    assert browser.get(board_path).status_code == 404
    remaining = success(browser.get(f"/v1/runs/{queued['id']}"))
    assert (remaining["status"], remaining["wait_reason"]) == ("queued", "gpu_unavailable")
