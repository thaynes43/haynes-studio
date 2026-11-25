"""Escalation lifecycle through the HTTP and migration-role boundaries."""

import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event

import httpx
import pytest
import sqlalchemy as sa

from haynes_studio.api.oidc import random_secret
from haynes_studio.canonical.ids import Minter
from haynes_studio.db import identity, runs
from haynes_studio.db.catalog import record_asset_version
from haynes_studio.db.schema import agent_grants, agent_keys, run_check_overrides
from haynes_studio.escalation import lifecycle, storage
from haynes_studio.escalation.package import digest
from haynes_studio.escalation.settings import Settings
from haynes_studio.mcp.server import create_app as create_mcp
from haynes_studio.store import canonical_json

from tests.db.test_run_queue import queue, queue_run, read_run, set_pins, set_version, worker_api, worker_credentials
from tests.db.test_studio_api import (
    bearer, client, engine, new_production, owner_engine, register_agent, runtime_db, runtime_role, service,
)
from tests.mcp.client import API_URL, call, connect, fail

pytestmark = pytest.mark.db
ARTIFACT = "a" * 64
INPUT = "b" * 64
CALLBACK = {"outcome": "done", "summary": "Adjusted the timing", "usage": "unknown",
            "changed_board_ids": []}


class FakeTransport:
    def __init__(self):
        self.requests = {}

    def request(self, contract, *, sha256, deduplication_id):
        assert hashlib.sha256(contract).hexdigest() == sha256
        assert json.loads(contract)["deduplication_id"] == deduplication_id
        key = self.requests.setdefault(deduplication_id, (contract, f"fixture-{len(self.requests) + 1}"))
        assert key[0] == contract
        return key[1]


def check(*, artifact=ARTIFACT, input_sha256=INPUT, result="fail"):
    return {"check": "layered.decal_gate", "artifact": artifact, "key": f"sha256:{input_sha256}",
            "result": result, "thresholds": {"ecc": 0.8},
            "measured": {"ecc": 0.7, "scaled_sample": 1e-9, "diagnostic": "/private/fixture-" + "S" * 48}}


def open_attempt(q, key="observation"):
    queued = queue_run(q, key)
    assert queued.status_code == 201, queued.text
    auth = worker_credentials(q.owner)
    claim = worker_api(q, headers=auth).claim()
    assert claim.identity["run_id"] == queued.json()["id"]
    return claim, auth


def payload(q, claim, attempt, *, result=None, error_code="layered.decal_weak", **fields):
    return {**claim.identity, "attempt": attempt, "result": check() if result is None else result,
            "error_code": error_code, "board_id": q.board_id, **fields}


def observe(q, claim, auth, attempt, **fields):
    return client(q.app).post("/internal/v1/work/escalation-check-failure", headers=auth,
                              json=payload(q, claim, attempt, **fields))


def listing(q):
    response = q.browser.get(f"/v1/productions/{q.production_id}/escalations")
    assert response.status_code == 200, response.text
    return response.json()["items"]


def path(q, package_id):
    return f"/v1/productions/{q.production_id}/escalations/{package_id}"


def transition(q, package_id, decision, **kwargs):
    return q.browser.post(path(q, package_id) + f"/{decision}", headers=q.csrf, **kwargs)


def propose(q, *, key="observation"):
    claim, auth = open_attempt(q, key)
    run_id = claim.identity["run_id"]
    for attempt in (1, 2):
        response = observe(q, claim, auth, attempt)
        assert response.status_code == 204, response.text
    package, = (row for row in listing(q) if row["package"]["run_id"] == run_id)
    return claim, package


def accept(q, package_id, transport):
    with q.engine.begin() as conn:
        return lifecycle.request_with_transport(conn, q.production_id, package_id, transport)


def fixture_responder(q, package, *, extra_scopes=(), expires_at=None):
    # The only registration of the reserved ID is a disposable test fixture.
    key = package["responder_key"]
    secret = random_secret()
    with q.owner.begin() as conn:
        conn.execute(agent_keys.insert().values(
            id=key["id"], digest=identity.digest(secret),
            expires_at=expires_at or datetime.fromisoformat(package["expires_at"]),
        ))
        conn.execute(agent_grants.insert(), [
            {"key_id": key["id"], "production_id": key["production_id"], "scope": scope}
            for scope in [*key["scopes"], *extra_scopes]
        ])
    return bearer(secret)


def reported(q, package_id, auth, *, key="receipt-1", data=None):
    return client(q.app).post(path(q, package_id) + "/callback",
                              headers={**auth, "Idempotency-Key": key},
                              json=CALLBACK if data is None else data)


def test_two_independent_matching_failures_create_one_package_and_third_adds_nothing(queue):
    q = queue
    claim, auth = open_attempt(q)
    run_id = claim.identity["run_id"]
    assert observe(q, claim, auth, 1).status_code == 204
    assert observe(q, claim, auth, 1).status_code == 204
    conflict = observe(q, claim, auth, 1, result=check(input_sha256="c" * 64))
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "escalation.evaluation_conflict"
    assert observe(q, claim, auth, 2, result=check(input_sha256="c" * 64)).status_code == 204
    assert observe(q, claim, auth, 3, result=check(artifact="d" * 64)).status_code == 204
    assert listing(q) == []
    assert observe(q, claim, auth, 4).status_code == 204
    proposed, = listing(q)
    assert proposed["state"] == "proposed"
    assert observe(q, claim, auth, 5).status_code == 204
    assert listing(q) == [proposed]

    doc = proposed["package"]
    package_id = doc["deduplication_id"]
    run, _ = read_run(q, run_id)
    assert doc["snapshot_sha256"] == run["snapshot"]["sha256"]
    assert doc["board_ids"] == [q.board_id]
    assert proposed["sha256"] == digest(doc)
    assert doc["artifacts"] == [{"operation": "get_media", "sha256": ARTIFACT}]
    assert b"/private/" not in canonical_json(doc)
    seen = set()
    for ref in doc["failure"]["results"]:
        result_path = f"/v1/runs/{run_id}/escalation-checks/{ref['record_sha256']}"
        assert client(q.app).get(result_path).status_code == 401
        evidence = q.browser.get(result_path).json()
        assert evidence["result"]["check"] == check()
        assert digest(evidence["result"]) == ref["record_sha256"]
        seen.add(evidence["result"]["attempt"])
    assert seen == {1, 4}

    _, reader = register_agent(q.owner, {q.production_id: ["read"]})
    assert client(q.app).get(path(q, package_id), headers=reader).json() == proposed
    other_production = new_production(q.browser, q.csrf)
    _, outsider = register_agent(q.owner, {other_production: ["read"]})
    assert client(q.app).get(path(q, package_id), headers=outsider).status_code == 403
    with q.engine.connect() as conn:
        assert conn.scalar(sa.select(sa.func.count()).select_from(storage.failures)) == 4


def test_worker_admission_busy_overridden_and_foreign_board_do_not_count(queue):
    q = queue
    claim, auth = open_attempt(q)
    run_id = claim.identity["run_id"]
    assert observe(q, claim, {}, 1).status_code == 401
    assert observe(q, claim, auth, 1, error_code="wan.busy").status_code == 204
    assert observe(q, claim, auth, 2, error_code="wan.foreign_engine_queue").status_code == 204
    assert observe(q, claim, auth, 1, result=check(result="overridden")).status_code == 204
    inline_override = {**check(), "override": {
        "by": q.browser.get("/v1/me").json()["principal"], "reason": "Still readable",
    }}
    assert observe(q, claim, auth, 2, result=inline_override).status_code == 204
    assert observe(q, claim, auth, 1, board_id=Minter().mint("brd")).status_code == 422
    wrong_fence = observe(q, claim, auth, 1, fence=claim.identity["fence"] + 1)
    assert wrong_fence.json()["error"]["code"] == "work.fence_lost"
    assert observe(q, claim, auth, 1).status_code == 204
    with q.owner.begin() as conn:
        # Simulate an override already on file when a bounded retry reports.
        conn.execute(run_check_overrides.insert().values(
            run_id=run_id, artifact=ARTIFACT, document={"check": "layered.decal_gate"},
        ))
    assert observe(q, claim, auth, 2).status_code == 204
    assert listing(q) == []
    with q.engine.connect() as conn:
        assert conn.scalar(sa.select(sa.func.count()).select_from(storage.failures)) == 1


def test_person_override_after_proposal_fences_authorization(queue):
    q = queue
    claim, proposed = propose(q)
    package_id = proposed["package"]["deduplication_id"]
    run_id = claim.identity["run_id"]
    claim.fail(status="failed", reason="Fixture check failure", checks=[check()])
    _, etag = read_run(q, run_id)
    result = q.browser.post(f"/v1/runs/{run_id}/checks/layered.decal_gate/overrides",
                            headers={**q.csrf, "If-Match": etag},
                            json={"artifact": ARTIFACT, "reason": "Still readable"})
    assert result.status_code == 201, result.text
    assert transition(q, package_id, "authorize").json()["error"]["code"] == "escalation.override"
    assert transition(q, package_id, "cancel").json()["state"] == "cancelled"


@pytest.mark.parametrize("mode", ["person", "automatic", "typo"])
def test_only_signed_in_people_authorize_or_decline_in_either_mode(queue, mode):
    q = queue
    q.app.state.escalation = Settings(mode, 0, 0)
    _, proposed = propose(q)
    package_id = proposed["package"]["deduplication_id"]
    assert proposed["state"] == "proposed"
    expected_reason = "automatic_cap_reached" if mode == "automatic" else "person_authorization"
    assert proposed["transitions"][0]["detail"]["reason"] == expected_reason
    _, agent = register_agent(q.owner, {q.production_id: ["read", "draft:write", "runs:queue"]})
    for identity_headers, expected in [(agent, 403), (worker_credentials(q.owner), 401), ({}, 401)]:
        for decision in ("authorize", "decline", "cancel"):
            assert client(q.app).post(path(q, package_id) + f"/{decision}",
                                      headers=identity_headers).status_code == expected
    assert q.browser.post(path(q, package_id) + "/authorize").status_code == 403
    approved = transition(q, package_id, "authorize").json()
    assert approved["state"] == "authorized"
    assert approved["transitions"][-1]["by"]["kind"] == "human"
    assert approved["transitions"][-1]["detail"]["cap_counts_before"]["total_limit"] == 0


def test_automatic_daily_cap_leaves_second_proposed_and_counts_prior_authorizations(queue):
    q = queue
    q.app.state.escalation = Settings("automatic")
    claim, approved = propose(q)
    event = approved["transitions"][-1]
    assert event["state"] == "authorized"
    assert event["by"] == {"kind": "system", "component": "escalation"}
    assert event["detail"]["cap_counts_before"] == {
        "utc_day": q.clock.now.date().isoformat(), "production": 0, "total": 0,
        "production_limit": 1, "total_limit": 2,
    }
    cancel = transition(q, approved["package"]["deduplication_id"], "cancel")
    assert cancel.json()["state"] == "cancelled"
    claim.fail(status="failed", reason="Synthetic check failure", checks=[check()])
    second, held = propose(q, key="second")
    assert held["state"] == "proposed"
    fake = FakeTransport()
    with pytest.raises(lifecycle.EscalationError, match="authorized"):
        accept(q, held["package"]["deduplication_id"], fake)
    assert fake.requests == {}
    assert transition(q, held["package"]["deduplication_id"], "decline").json()["state"] == "declined"

    second.fail(status="failed", reason="Synthetic check failure")
    q.clock.advance(24 * 60 * 60)
    _, next_day = propose(q, key="next-day")
    assert next_day["state"] == "authorized"
    assert next_day["transitions"][-1]["detail"]["cap_counts_before"]["total"] == 0


def test_concurrent_proposals_cannot_both_take_last_global_slot(queue):
    q = queue
    q.app.state.escalation = Settings("automatic", 1, 2)
    claim, _ = propose(q)
    claim.fail(status="failed", reason="Synthetic check failure")
    with q.engine.begin() as conn:
        existing = runs.get(conn, claim.identity["run_id"])

    # The existing FIFO serializes a queue lane. Simulate two distinct fenced
    # producers so the cap is independently exercised across productions.
    def prepare(key):
        production = new_production(q.browser, q.csrf)
        with q.owner.begin() as conn:
            snapshot = {**existing["snapshot"], "story": {
                **existing["snapshot"]["story"], "production_id": production,
            }}
            row = runs.enqueue(conn, snapshot=snapshot, library=existing["frozen_library"],
                               snapshot_sha256=digest(snapshot), actor={"kind": "worker", "worker_id": "fixture"},
                               key=key, estimate={"estimate": existing["document"]["estimate"], "methods": []})
            return runs._save(conn, row, document={**row["document"], "status": "running"},
                              worker_id="fixture", claim_until=q.clock.now + runs.LEASE, fence=1)["id"]

    first, second = prepare("concurrent-1"), prepare("concurrent-2")
    worker = {"kind": "worker", "worker_id": "fixture"}

    def record(conn, run_id, attempt):
        row, _ = runs.lock_claim(conn, run_id, "fixture", 1)
        return lifecycle.record_failure(conn, row, actor=worker, attempt=attempt,
                                        board_id=q.board_id, result=check(),
                                        error_code="layered.decal_weak", settings=q.app.state.escalation)

    for run_id in (first, second):
        with q.engine.begin() as conn:
            assert record(conn, run_id, 1) is None

    entered = Event()

    def competing():
        with q.engine.begin() as conn:
            entered.set()
            return record(conn, second, 2)

    with ThreadPoolExecutor(1) as pool:
        with q.engine.begin() as conn:
            first_id = record(conn, first, 2)
            with q.engine.begin() as probe:
                assert not probe.scalar(sa.select(sa.func.pg_try_advisory_xact_lock(
                    sa.func.hashtext(sa.func.current_schema()), 445)))
            future = pool.submit(competing)
            assert entered.wait(5)
        second_id = future.result(timeout=10)

    with q.engine.begin() as conn:
        assert storage.history(conn, first_id)[-1]["state"] == "authorized"
        pending = storage.history(conn, second_id)[-1]
        assert pending["state"] == "proposed"
        assert pending["detail"]["reason"] == "automatic_cap_reached"


def test_transport_request_and_named_callback_have_single_receipts(queue):
    q = queue
    _, proposed = propose(q)
    doc = proposed["package"]
    package_id = doc["deduplication_id"]
    fake = FakeTransport()
    auth = fixture_responder(q, doc)
    assert reported(q, package_id, auth).status_code == 409
    assert transition(q, package_id, "authorize").json()["state"] == "authorized"
    requested = accept(q, package_id, fake)
    assert requested["package"] == doc and requested["sha256"] == proposed["sha256"]
    assert requested["transitions"][-1]["external_request_id"] == "fixture-1"
    assert requested["state"] == "requested"
    with pytest.raises(lifecycle.EscalationError, match="once"):
        accept(q, package_id, fake)
    assert len(fake.requests) == 1

    _, different_key = register_agent(q.owner, {q.production_id: doc["responder_key"]["scopes"]},
                                      expires_at=datetime.fromisoformat(doc["expires_at"]))
    for headers in (different_key, q.csrf):
        assert reported(q, package_id, headers).status_code in (401, 403)
    foreign = {**CALLBACK, "changed_board_ids": [Minter().mint("brd")]}
    assert reported(q, package_id, auth, data=foreign).json()["error"]["code"] == "escalation.changed_ids"
    invalid_usage = {**CALLBACK, "usage": {"elapsed_seconds": -1}}
    assert reported(q, package_id, auth, data=invalid_usage).status_code == 422
    report = {**CALLBACK, "usage": {"elapsed_seconds": 60, "cost_usd": 0},
              "changed_board_ids": [q.board_id]}
    done = reported(q, package_id, auth, data=report)
    assert done.status_code == 200, done.text
    assert done.json()["state"] == "done"
    assert done.json()["transitions"][-1]["detail"]["report"]["usage"]["cost_usd"] == 0
    assert reported(q, package_id, auth, data=report).json() == done.json()
    assert reported(q, package_id, auth, key="receipt-2", data=report).status_code == 409
    assert reported(q, package_id, auth, data={**report, "outcome": "failed"}).status_code == 409
    assert transition(q, package_id, "cancel").status_code == 409


@pytest.mark.parametrize("stop", ["expired_proposal", "expired_authorized", "expired_request", "cancelled"])
def test_expired_or_cancelled_package_refuses_new_work(queue, stop):
    q = queue
    _, proposed = propose(q)
    package_id = proposed["package"]["deduplication_id"]
    auth = fixture_responder(q, proposed["package"])
    fake = FakeTransport()
    if stop != "expired_proposal":
        assert transition(q, package_id, "authorize").status_code == 200
    if stop in ("expired_request", "cancelled"):
        accept(q, package_id, fake)
    if stop == "cancelled":
        assert transition(q, package_id, "cancel").json()["state"] == "cancelled"
    else:
        q.clock.advance(24 * 60 * 60)
        assert q.browser.get(path(q, package_id)).json()["expired"]
    if stop == "expired_proposal":
        assert transition(q, package_id, "authorize").json()["error"]["code"] == "escalation.expired"
    elif stop == "expired_authorized":
        with pytest.raises(lifecycle.EscalationError, match="expired"):
            accept(q, package_id, fake)
        assert fake.requests == {}
    else:
        code = "escalation.state" if stop == "cancelled" else "escalation.expired"
        assert reported(q, package_id, auth).json()["error"]["code"] == code


def test_responder_only_patches_named_draft_fields_with_cr23_acknowledgment(queue):
    q = queue
    _, proposed = propose(q)
    doc = proposed["package"]
    package_id = doc["deduplication_id"]
    auth = fixture_responder(q, doc)
    agent = client(q.app)
    board = f"/v1/boards/{q.board_id}"
    assert agent.get(board, headers=auth).status_code == 403
    assert transition(q, package_id, "authorize",
                      json={"acknowledge_board_ids": [q.board_id]}).status_code == 200
    accept(q, package_id, FakeTransport())
    assert agent.get("/v1/me", headers=auth).status_code == 200
    fresh = agent.get(board, headers=auth)
    assert fresh.status_code == 200, fresh.text
    headers = {**auth, "If-Match": fresh.headers["etag"]}
    protected = agent.patch(board, headers=headers, json={"title": "Adjusted"})
    assert protected.json()["error"]["code"] == "draft.protected"
    ack = {"board_revision": fresh.json()["revision"], "read_token": fresh.headers["x-studio-board-read-token"]}
    assert agent.patch(board, headers=headers, json={"lines": [], "acknowledge_person_edit": ack}).status_code == 403
    assert agent.delete(board, headers=headers).status_code == 403
    assert agent.patch(f"/v1/boards/{Minter().mint('brd')}", headers=headers, json={"title": "Other"}).status_code == 403
    assert agent.get(f"/v1/media/{'b' * 64}", headers=auth).status_code == 403
    assert agent.get(f"/v1/media/{ARTIFACT}", headers=auth).status_code == 404
    async def through_mcp():
        mcp = create_mcp(API_URL, api_transport=httpx.ASGITransport(app=q.app))
        async with mcp.router.lifespan_context(mcp):
            async with connect(mcp, auth["Authorization"]) as session:
                fresh = await call(session, "studio_get_board", board_id=q.board_id)
                confirmation = {"board_revision": fresh["revision"], "read_token": fresh["read_token"]}
                changed = await call(session, "studio_patch_board", board_id=q.board_id, revision=fresh["revision"],
                                     patch={"title": "Adjusted", "acknowledge_person_edit": confirmation})
                assert changed["id"] == q.board_id

    asyncio.run(through_mcp())
    assert agent.get(board, headers=auth).json()["title"] == "Adjusted"
    assert reported(q, package_id, auth).status_code == 200
    assert agent.get(board, headers=auth).status_code == 403


@pytest.mark.parametrize("transport", ["http", "mcp", "ordinary-mcp"])
def test_legacy_layout_edits_preserve_person_check_poses_and_queue_refusal(queue, transport):
    q = queue
    _, proposed = propose(q)
    package = proposed["package"]
    package_id = package["deduplication_id"]
    path = f"/v1/boards/{q.board_id}"
    poses = [{"key": "studio", "frame": 0}]
    legacy_layout = {"preset": "default", "foreground": False}
    person = q.browser.patch(path, headers={**q.csrf, "If-Match": "2"},
                             json={"layout": {**legacy_layout, "check_poses": poses}})
    assert person.status_code == 200, person.text

    if transport == "ordinary-mcp":
        _, auth = register_agent(q.owner, {q.production_id: ["read", "draft:write", "runs:queue"]})
    else:
        auth = fixture_responder(q, package)
        assert transition(q, package_id, "authorize",
                          json={"acknowledge_board_ids": [q.board_id]}).status_code == 200
        accept(q, package_id, FakeTransport())

    story_path = f"/v1/stories/{q.story_id}"
    before = q.browser.get(story_path).json()["revision"]
    first = queue_run(q, "before-layout-edit", rev=before, headers=auth)
    assert first.status_code == 422 and first.json()["error"]["code"] == "occlusion.check_unavailable"

    updated_layout = {**legacy_layout, "foreground": True}
    forbidden_poses = [None, [], [{"key": "other", "frame": 0}]]
    if transport == "http":
        agent = client(q.app)
        fresh = agent.get(path, headers=auth)
        acknowledgment = {"board_revision": fresh.json()["revision"],
                          "read_token": fresh.headers["x-studio-board-read-token"]}
        headers = {**auth, "If-Match": fresh.headers["etag"]}
        for poses_value in forbidden_poses:
            denied = agent.patch(path, headers=headers, json={
                "layout": {**updated_layout, "check_poses": poses_value},
                "acknowledge_person_edit": acknowledgment,
            })
            assert denied.status_code == 422, denied.text
            assert denied.json()["error"]["code"] == "draft.check_poses_protected"
        result = agent.patch(path, headers=headers, json={
            "layout": updated_layout, "acknowledge_person_edit": acknowledgment,
        })
        assert result.status_code == 200, result.text
    else:
        async def through_mcp():
            mcp = create_mcp(API_URL, api_transport=httpx.ASGITransport(app=q.app))
            async with mcp.router.lifespan_context(mcp):
                async with connect(mcp, auth["Authorization"]) as session:
                    fresh = await call(session, "studio_get_board", board_id=q.board_id)
                    acknowledgment = {"board_revision": fresh["revision"], "read_token": fresh["read_token"]}
                    for poses_value in forbidden_poses:
                        error = await fail(session, "studio_patch_board", board_id=q.board_id,
                                           revision=fresh["revision"], patch={
                            "layout": {**updated_layout, "check_poses": poses_value},
                            "acknowledge_person_edit": acknowledgment,
                        })
                        assert error["code"] == "draft.check_poses_protected"
                    changed = await call(session, "studio_patch_board", board_id=q.board_id,
                                         revision=fresh["revision"], patch={
                        "layout": updated_layout, "acknowledge_person_edit": acknowledgment,
                    })
                    assert changed["revision"] == fresh["revision"] + 1

        asyncio.run(through_mcp())
    stored = q.browser.get(path).json()
    assert stored["layout"] == {**updated_layout, "check_poses": poses}
    after = q.browser.get(story_path).json()["revision"]
    assert after == before + 1
    refused = queue_run(q, "after-layout-edit", rev=after, headers=auth)
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "occlusion.check_unavailable"


@pytest.mark.parametrize(("group", "target"), [
    ("foreground", {"key": "shelf", "label": None, "layer_order": 30}),
    ("focal_props", {"key": "menu", "label": "menu", "depth": "background", "layer_order": 0}),
])
@pytest.mark.parametrize("transport", ["responder", "ordinary-mcp"])
def test_agent_cannot_remove_or_replace_opted_in_set_pin(queue, group, target, transport):
    q = queue
    _, proposed = propose(q)
    package = proposed["package"]
    package_id = package["deduplication_id"]
    config = {"foreground": [], "focal_props": [], group: [target]}
    opted_in, legacy = set_version(q, config), set_version(q)
    with q.engine.begin() as conn:
        for plate in (opted_in, legacy):
            record_asset_version(conn, plate)
    path = f"/v1/stories/{q.story_id}"
    person = q.browser.patch(path, headers={**q.csrf, "If-Match": "3"}, json={"set": set_pins(opted_in)})
    assert person.status_code == 200, person.text

    rev = person.json()["revision"]
    if transport == "responder":
        auth = fixture_responder(q, package)
        assert transition(q, package_id, "authorize").status_code == 200
        accept(q, package_id, FakeTransport())
        agent = client(q.app)
        for replacement in (None, set_pins(legacy)):
            denied = agent.patch(path, headers={**auth, "If-Match": str(rev)}, json={"set": replacement})
            assert denied.status_code == 403, denied.text
    else:
        _, auth = register_agent(q.owner, {q.production_id: ["read", "draft:write", "runs:queue"]})

        async def through_mcp():
            mcp = create_mcp(API_URL, api_transport=httpx.ASGITransport(app=q.app))
            async with mcp.router.lifespan_context(mcp):
                async with connect(mcp, auth["Authorization"]) as session:
                    for replacement in (None, set_pins(legacy)):
                        error = await fail(session, "studio_patch_story", story_id=q.story_id,
                                           revision=rev, patch={"set": replacement})
                        assert error["code"] == "draft.set_occlusion_protected"

        asyncio.run(through_mcp())
    assert q.browser.get(path).json()["set"] == set_pins(opted_in)
    refused = queue_run(q, "after-denied-set-edit", rev=rev, headers=auth)
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "occlusion.check_unavailable"


def test_automatic_authorization_does_not_acknowledge_person_edits(queue):
    q = queue
    q.app.state.escalation = Settings("automatic")
    _, approved = propose(q)
    doc = approved["package"]
    auth = fixture_responder(q, doc)
    accept(q, doc["deduplication_id"], FakeTransport())
    agent = client(q.app)
    board = f"/v1/boards/{q.board_id}"
    response = agent.get(board, headers=auth)
    ack = {"board_revision": response.json()["revision"], "read_token": response.headers["x-studio-board-read-token"]}
    denied = agent.patch(board, headers={**auth, "If-Match": response.headers["etag"]},
                         json={"title": "Adjusted", "acknowledge_person_edit": ack})
    assert denied.status_code == 403


def test_responder_can_queue_one_run_in_the_named_story_and_replay_its_receipt(queue):
    q = queue
    _, proposed = propose(q)
    doc = proposed["package"]
    package_id = doc["deduplication_id"]
    auth = fixture_responder(q, doc)
    assert transition(q, package_id, "authorize").status_code == 200
    accept(q, package_id, FakeTransport())
    agent = client(q.app)
    assert agent.post(f"/v1/stories/{Minter().mint('sty')}/runs",
                      headers={**auth, "Idempotency-Key": "elsewhere", "If-Match": "3"}).status_code == 403
    first = queue_run(q, "one-rerun", headers=auth)
    assert first.status_code == 201, first.text
    new_run = first.json()["id"]
    replay = queue_run(q, "one-rerun", headers=auth)
    assert replay.status_code == 200 and replay.json()["id"] == new_run
    denied = queue_run(q, "another-rerun", headers=auth)
    assert denied.json()["error"]["code"] == "escalation.run_cap"
    assert agent.post(f"/v1/runs/{new_run}/cancel", headers={**auth, "If-Match": "1"}).status_code == 403
    assert reported(q, package_id, auth, data={
        **CALLBACK, "queued_run_ids": [doc["run_id"]],
    }).json()["error"]["code"] == "escalation.changed_ids"
    assert reported(q, package_id, auth, data={**CALLBACK, "queued_run_ids": [new_run]}).status_code == 200


def test_elapsed_execution_budget_stops_operations_but_keeps_reported_usage(queue):
    q = queue
    _, proposed = propose(q)
    doc = proposed["package"]
    package_id = doc["deduplication_id"]
    auth = fixture_responder(q, doc)
    assert transition(q, package_id, "authorize").status_code == 200
    accept(q, package_id, FakeTransport())
    q.clock.advance(900)
    denied = queue_run(q, "too-late", headers=auth)
    assert denied.json()["error"]["code"] == "escalation.budget_elapsed"
    failed = reported(q, package_id, auth, data={
        **CALLBACK, "outcome": "failed", "usage": {"elapsed_seconds": 905},
    })
    assert failed.json()["transitions"][-1]["detail"]["report"]["usage"]["elapsed_seconds"] == 905


@pytest.mark.parametrize("misbound", ["scopes", "expiry"])
def test_responder_key_with_overbroad_grants_or_wrong_expiry_is_refused(queue, misbound):
    q = queue
    _, proposed = propose(q)
    doc = proposed["package"]
    package_id = doc["deduplication_id"]
    if misbound == "scopes":
        auth = fixture_responder(q, doc, extra_scopes=["formats:write"])
    else:
        later = datetime.fromisoformat(doc["expires_at"]) + timedelta(minutes=1)
        auth = fixture_responder(q, doc, expires_at=later)
    assert transition(q, package_id, "authorize").status_code == 200
    accept(q, package_id, FakeTransport())
    assert reported(q, package_id, auth).status_code == 403
    assert client(q.app).get("/v1/me", headers=auth).status_code == 403


@pytest.mark.parametrize("table", [storage.failures, storage.packages, storage.events], ids=lambda table: table.name)
def test_runtime_cannot_update_or_delete_append_only_escalation_rows(engine, table):
    for operation in (table.update().values({list(table.c)[0]: "a" * 64}), table.delete()):
        with engine.connect() as conn, pytest.raises(sa.exc.ProgrammingError) as refused:
            conn.execute(operation)
        assert refused.value.orig.sqlstate == "42501"
