"""Go-live acceptance through the runtime role with fixture provenance and no platform I/O."""

import hashlib
import socket
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from haynes_studio.api.approval_routes import licence_register
from haynes_studio.api.auth import Actor, SESSION_COOKIE
from haynes_studio.build.provenance import Use, credits, engines
from haynes_studio.canonical.ids import Minter
from haynes_studio.db import identity, runs
from haynes_studio.db.catalog import record_delivery
from haynes_studio.db.schema import (
    go_live_approvals, go_live_withdrawals, metadata, runs as run_table, sessions, stories,
)
from haynes_studio.golive import records
from haynes_studio.golive.checks import AI_DESCRIPTION_LINE
from haynes_studio.store.layout import blob_locator
from tests.canonical.fixtures import example
from tests.db.test_run_queue import worker_credentials
from tests.db.test_studio_api import (
    ALLOWED_GROUP, ISSUER, assert_auth_redirect, begin_login, client, engine, new_production, new_story,
    owner_engine, register_agent, runtime_db, runtime_role, service, sign_in,
)

pytestmark = pytest.mark.db
APPROVER = {"kind": "human", "iss": ISSUER, "sub": "one"}


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def setup(service, owner_engine):
    app, _, issuer = service
    app.state.oidc.settings = replace(issuer.settings(), allowed_groups=frozenset({ALLOWED_GROUP}),
                                    go_live_approver_subjects=frozenset({"one"}))
    browser = client(app)
    csrf = sign_in(browser, issuer)
    production = new_production(browser, csrf)
    story = new_story(browser, csrf, production)
    return SimpleNamespace(app=app, issuer=issuer, browser=browser, csrf=csrf, owner=owner_engine,
                           production=production, story=story,
                           list_path=f"/v1/productions/{production}/media-types/short/stories")


def finished_fixture(s, *, failure=None, queued_id=None, format_pin=None, extra_uses=None):
    uses = {"wan-ti2v": Use("video", hardware="two RTX 3090s"),
            "kokoro": Use("voice"), "stable-audio": Use("sound"),
            "qwen-image": Use("image"), "asr": Use("check")}
    uses.update(extra_uses or {})
    if failure == "file":
        uses["wan-ti2v"].files["unlisted-placeholder"] = digest("file")
    register = licence_register()
    engine_list = engines(register, uses, {})
    if failure == "engine":
        engine_list.append({"key": "unregistered-placeholder", "role": "writer", "files": []})
    external_id = Minter().mint("asv")
    provenance = {
        "engines": engine_list, "toolchain": {"studio": "git:fixture"}, "usage": None,
        "inputs_externally_generated": [{"id": external_id, "kind": "board_photo",
                                         "agent": {"session": "private-fixture"}}],
        "public": {"ai_generated": failure != "disclosure",
                   "credits": credits(engine_list, {key: use.hardware for key, use in uses.items()})},
    }
    if failure == "provenance":
        del provenance["toolchain"]
    if failure == "no_video":
        provenance["engines"] = [engine for engine in engine_list if engine["role"] != "video"]
    with s.owner.begin() as conn:
        if queued_id is None:
            draft = conn.scalar(sa.select(stories.c.document).where(stories.c.id == s.story))
            key = Minter().mint("run")
            snapshot_doc = {"story": {**draft, "boards": []}}
            if format_pin is not None:
                snapshot_doc["format_version"] = format_pin
            row = runs.enqueue(conn, snapshot=snapshot_doc,
                               snapshot_sha256=digest("snapshot " + key), library={}, actor=APPROVER,
                               key=key, estimate={"estimate": {}, "methods": []})
        else:
            row = runs.get(conn, queued_id)
        delivery = example("valid/delivery.json")
        delivery.update(id=Minter().mint("dlv"), run_id=row["id"])
        for name in ("master", "proxy"):
            sha = digest(name + " " + row["id"])
            delivery[name].update(sha256=sha, locator=blob_locator(s.production, sha, "video/mp4"))
        run = row["document"]
        if failure != "unfinished":
            if failure == "unverified":
                delivery["verification"]["sha256_verified"] = False
            else:
                record_delivery(conn, s.story, delivery)
            run.update(status="succeeded", finished_at=runs.timestamp(runs.database_time(conn)),
                       delivery_id=delivery["id"], provenance=provenance,
                       outputs={"master_sha256": (digest("wrong") if failure == "delivery" else
                                                  delivery["master"]["sha256"])})
        if failure == "legacy":
            run["legacy"] = {"format": "fixture"}
        conn.execute(run_table.update().where(run_table.c.id == row["id"]).values(document=run))
    return SimpleNamespace(id=row["id"], path=f"/v1/runs/{row['id']}/go-live-approvals",
                           snapshot=row["document"]["snapshot"]["sha256"], delivery=delivery,
                           body={"master_sha256": delivery["master"]["sha256"], "platform_setting": True},
                           external_id=external_id)


def read_review(s, run, browser=None):
    def counts(conn):
        return {table.name: conn.scalar(sa.select(sa.func.count()).select_from(table))
                for table in metadata.tables.values()}

    with s.owner.connect() as conn:
        before = counts(conn)
        auth_times = conn.execute(sa.select(sessions.c.digest, sessions.c.auth_time)).all()
        run_before = conn.scalar(sa.select(run_table.c.document).where(run_table.c.id == run.id))
        response = (browser or s.browser).get(run.path)
        assert response.status_code == 200, response.text
        assert counts(conn) == before
        assert set(conn.execute(sa.select(sessions.c.digest, sessions.c.auth_time))) == set(auth_times)
        assert conn.scalar(sa.select(run_table.c.document).where(run_table.c.id == run.id)) == run_before
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["run_id"] == run.id
    return response.json()


def assert_decision(decision, write, code=None):
    if code is None:
        assert write.status_code == 201, write.text
        assert decision == {"allowed": True}
    else:
        assert write.json()["error"]["code"] == "approval." + code
        assert decision == {"allowed": False, "code": write.json()["error"]["code"]}


def test_approved_older_run_keeps_exact_evidence_and_withdrawal_is_append_only(setup, engine, monkeypatch):
    s = setup
    older = finished_fixture(s)
    edited = s.browser.patch(f"/v1/stories/{s.story}", json={"title": "A changed fixture draft"},
                             headers={**s.csrf, "If-Match": "1"})
    assert edited.status_code == 200
    latest = finished_fixture(s)
    expected_latest = {"id": latest.id, "active_approval_id": None, "status": "succeeded"}

    def network_attempt(*args, **kwargs):
        pytest.fail("Approval and withdrawal must not open a network connection from Python")

    monkeypatch.setattr(socket.socket, "connect", network_attempt)
    preview = read_review(s, older)
    assert preview["master_sha256"] == older.body["master_sha256"]
    assert preview["approvals"] == []
    response = s.browser.post(older.path, json=older.body, headers=s.csrf)
    assert_decision(preview["approve"], response)
    approval = response.json()
    assert approval["run_id"] == older.id
    assert approval["master_sha256"] == older.body["master_sha256"]
    assert approval["run_snapshot_sha256"] == older.snapshot
    assert approval["delivery_id"] == older.delivery["id"]
    assert approval["approver"] == APPROVER and approval["approver_display_name"] == "Fixture Person"
    assert datetime.fromisoformat(approval["auth_time"]) <= datetime.fromisoformat(approval["approved_at"])
    evidence = approval["release_checks"]
    assert preview["release_checks"] == evidence
    assert evidence["delivery"]["verification"]["sha256_verified"] is True
    assert evidence["licences"]["result"] == "pass"
    assert {row["engine_key"] for row in evidence["licences"]["rows"] if "file" not in row} == {
        "wan-ti2v", "kokoro", "stable-audio", "qwen-image", "asr",
    }
    terms = {row["licence"]["commercial_use"] for row in evidence["licences"]["rows"]}
    assert {"allowed", "conditional", "noncommercial", "unknown"} <= terms
    description = evidence["ai_label"]["description"]
    assert evidence["ai_label"]["platform_setting"] is True
    assert description.splitlines()[0] == AI_DESCRIPTION_LINE
    assert all(word in description for word in ("Wan2.2", "Kokoro", "Stable Audio", "two RTX 3090s"))
    assert all(word not in description for word in ("Qwen", "Parakeet", "private-fixture", older.external_id))
    assert evidence["external_inputs"] == [{"id": older.external_id, "kind": "board_photo"}]

    def listing(**filters):
        result = s.browser.get(s.list_path, params=filters)
        assert result.status_code == 200
        return [item["id"] for item in result.json()["items"]]

    story = s.browser.get(f"/v1/stories/{s.story}").json()
    assert story["approved"] and not story["published"]
    assert expected_latest.items() <= story["latest_finished_run"].items()
    assert s.browser.get(f"/v1/runs/{older.id}").json()["active_approval_id"] == approval["id"]
    assert s.browser.get(f"/v1/runs/{latest.id}").json()["active_approval_id"] is None
    assert listing(publication="unpublished") == listing(approved=True) == [s.story]
    assert listing(publication="unpublished", approved=True) == [s.story]
    assert listing(publication="published", approved=True) == listing(approved=False) == []
    active = read_review(s, older)
    assert active["approvals"] == [approval] and active["release_checks"] == evidence
    refused = s.browser.post(older.path, json=older.body, headers=s.csrf)
    assert refused.status_code == 409
    assert_decision(active["approve"], refused, "already_active")
    path = f"/v1/go-live-approvals/{approval['id']}/withdraw"
    withdrawn = s.browser.post(path, headers=s.csrf)
    assert_decision(active["withdraw"], withdrawn)
    output = withdrawn.json()
    assert output["master_sha256"] == approval["master_sha256"]
    assert output["derived"]["state"] == "withdrawn"
    assert output["derived"]["withdrawal"]["withdrawn_by"] == APPROVER
    assert listing(publication="unpublished", approved=False) == [s.story]
    assert listing(publication="published", approved=True) == []
    past = read_review(s, older)
    assert past["approvals"] == [output]
    assert_decision(past["withdraw"], s.browser.post(path, headers=s.csrf), "already_withdrawn")
    with engine.connect() as conn:
        persisted = conn.scalar(sa.select(go_live_approvals.c.document).where(go_live_approvals.c.id == approval["id"]))
        assert persisted == {key: value for key, value in approval.items() if key != "derived"}
    renewed = s.browser.post(older.path, json=older.body, headers=s.csrf)
    assert_decision(past["approve"], renewed)
    assert renewed.json()["id"] != approval["id"]
    assert read_review(s, older)["approvals"] == [renewed.json(), output]
    for mutation in (go_live_approvals.update().values(document={}), go_live_withdrawals.delete()):
        with pytest.raises(sa.exc.ProgrammingError) as denied, engine.begin() as conn:
            conn.execute(mutation)
        assert denied.value.orig.sqlstate == "42501"


@pytest.mark.parametrize(("failure", "code"), [
    ("unfinished", "run_unfinished"), ("legacy", "legacy_run"), ("unverified", "delivery_unverified"),
    ("delivery", "delivery_mismatch"), ("engine", "licence_missing"), ("file", "licence_missing"),
    ("disclosure", "ai_label_missing"), ("setting", "ai_label_missing"), ("hash", "not_exact_run"),
    ("provenance", "provenance_missing"), ("no_video", "provenance_missing"),
])
def test_approval_refuses_each_invalid_release_result(setup, failure, code):
    s = setup
    held = finished_fixture(s, failure=failure)
    preview = read_review(s, held)
    if failure == "setting":
        del held.body["platform_setting"]
    if failure == "hash":
        held.body["master_sha256"] = digest("wrong")
    result = s.browser.post(held.path, json=held.body, headers=s.csrf)
    assert result.status_code == 422, result.text
    error = result.json()["error"]
    assert error["code"] == "approval." + code
    if failure in ("setting", "hash"):
        # The read proposes the exact delivery with the platform setting on.
        assert preview["approve"] == {"allowed": True}
    else:
        assert_decision(preview["approve"], result, code)
    if code == "licence_missing":
        assert preview["release_checks"]["licences"] == error["evidence"]
        assert preview["release_checks"]["delivery"]["delivery_id"] == held.delivery["id"]
        assert error["evidence"]["result"] == "fail"
        missing = [row for row in error["evidence"]["rows"] if row["state"] == "missing"]
        assert len(missing) == 1 and ("file" in missing[0]) == (failure == "file")
    assert s.browser.get(f"/v1/runs/{held.id}").json()["active_approval_id"] is None


@pytest.mark.parametrize(("identity_kind", "code"), [
    ("subject", "subject_not_permitted"), ("empty", "approver_not_configured"),
    ("stale", "sign_in_again"), ("group", "group_not_permitted"),
])
def test_review_refuses_the_same_identity_as_both_writes(setup, identity_kind, code):
    s = setup
    held = finished_fixture(s)
    approved = s.browser.post(held.path, headers=s.csrf, json=held.body)
    assert approved.status_code == 201
    browser = client(s.app)
    if identity_kind == "empty":
        csrf = sign_in(browser, s.issuer)
        s.app.state.oidc.settings = replace(s.app.state.oidc.settings, go_live_approver_subjects=frozenset())
    elif identity_kind == "subject":
        csrf = sign_in(browser, s.issuer, "two")
    elif identity_kind == "group":
        csrf = sign_in(browser, s.issuer, "group-only", groups=[ALLOWED_GROUP])
    else:
        old = datetime.now(UTC) - timedelta(minutes=16)
        csrf = sign_in(browser, s.issuer, auth_time=int(old.timestamp()))

    review = read_review(s, held, browser)
    expected = approved.json()
    if identity_kind != "stale":
        assert {"approver", "auth_time"}.isdisjoint(review["approvals"][0])
        expected.pop("approver")
        expected.pop("auth_time")
    assert review["approvals"] == [expected]
    assert review["release_checks"] == approved.json()["release_checks"]
    assert_decision(review["approve"], browser.post(held.path, headers=csrf, json=held.body), code)
    path = f"/v1/go-live-approvals/{approved.json()['id']}/withdraw"
    assert_decision(review["withdraw"], browser.post(path, headers=csrf), code)


def test_approval_review_hides_withdrawal_identity_from_non_approvers(setup):
    s = setup
    run = finished_fixture(s)
    approval = s.browser.post(run.path, headers=s.csrf, json=run.body).json()
    path = f"/v1/go-live-approvals/{approval['id']}/withdraw"
    withdrawn = s.browser.post(path, headers=s.csrf)
    assert withdrawn.status_code == 201
    private = withdrawn.json()
    assert read_review(s, run)["approvals"] == [private]
    reader = client(s.app)
    sign_in(reader, s.issuer, "two")
    public = read_review(s, run, reader)["approvals"][0]
    assert public["approver_display_name"] == private["approver_display_name"]
    assert public["approved_at"] == private["approved_at"]
    assert {"approver", "auth_time"}.isdisjoint(public)
    assert public["derived"]["withdrawal"] == {
        key: private["derived"]["withdrawal"][key] for key in ("schema", "approval_id", "withdrawn_at")
    }
    with s.owner.begin() as conn:
        row = conn.scalar(sa.select(go_live_approvals.c.document).where(go_live_approvals.c.id == approval["id"]))
        conn.execute(go_live_approvals.update().where(go_live_approvals.c.id == approval["id"])
                     .values(document={**row, "future_private_field": "fixture"}))
        assert records.history(conn, run.id, show_identity=False) == [public]


def test_review_scope_and_principal_refusals(setup, monkeypatch):
    s = setup
    held = finished_fixture(s)
    outsider = client(s.app)
    sign_in(outsider, s.issuer, "two")
    original = Actor.productions
    other = new_production(s.browser, s.csrf)
    # People currently read all productions. Exercise the production filter
    # with a restricted signed-in actor and the normal session machinery.
    monkeypatch.setattr(Actor, "productions", lambda actor, scope: (
        frozenset({other}) if actor.principal.sub == "two" else original(actor, scope)
    ))
    missing = Minter().mint("run")
    for path in (f"/v1/runs/{held.id}", held.path, f"/v1/runs/{missing}/go-live-approvals"):
        response = outsider.get(path)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
        assert response.headers["cache-control"] == "private, no-store"

    _, agent = register_agent(s.owner, {s.production: ["read"]})
    for headers, status, code in (
        (agent, 403, "approval.approver_not_permitted"),
        (worker_credentials(s.owner), 403, "approval.worker_not_permitted"),
        ({}, 401, "auth.required"),
    ):
        response = client(s.app).get(held.path, headers=headers)
        assert response.status_code == status
        assert response.json()["error"]["code"] == code


def test_review_keeps_one_snapshot_across_a_concurrent_withdrawal(setup, monkeypatch):
    s = setup
    held = finished_fixture(s)
    approval = s.browser.post(held.path, headers=s.csrf, json=held.body).json()
    path = f"/v1/go-live-approvals/{approval['id']}/withdraw"
    history = records.history
    with monkeypatch.context() as patch:
        def withdraw_then_read(conn, run_id, *, show_identity):
            result = s.browser.post(path, headers=s.csrf)
            assert result.status_code == 201, result.text
            return history(conn, run_id, show_identity=show_identity)

        patch.setattr(records, "history", withdraw_then_read)
        old = s.browser.get(held.path)
    assert old.status_code == 200, old.text
    assert old.json()["withdraw"] == {"allowed": True}
    assert old.json()["approvals"] == [approval]
    fresh = read_review(s, held)
    assert fresh["withdraw"] == {"allowed": False, "code": "approval.already_withdrawn"}
    assert fresh["approvals"][0]["derived"]["state"] == "withdrawn"


def test_delivery_only_legacy_import_has_own_refusal(setup):
    s = setup
    delivery = example("valid/delivery-legacy-r4.json")
    delivery.update(id=Minter().mint("dlv"), run_id=Minter().mint("run"))
    with s.owner.begin() as conn:
        record_delivery(conn, s.story, delivery)
    answer = s.browser.post(f"/v1/runs/{delivery['run_id']}/go-live-approvals",
                            json={"master_sha256": delivery["master"]["sha256"], "platform_setting": True},
                            headers=s.csrf)
    assert answer.status_code == 422 and answer.json()["error"]["code"] == "approval.legacy_run"


@pytest.mark.parametrize(("identity_kind", "code"), [
    ("empty", "approver_not_configured"), ("group", "group_not_permitted"),
    ("subject", "subject_not_permitted"), ("agent", "approver_not_permitted"),
    ("worker", "worker_not_permitted"), ("stale", "sign_in_again"), ("old_session", "sign_in_again"),
])
def test_approval_authenticates_before_request_parsing(setup, identity_kind, code):
    s = setup
    browser, headers = s.browser, s.csrf
    if identity_kind == "empty":
        s.app.state.oidc.settings = replace(s.app.state.oidc.settings, go_live_approver_subjects=frozenset())
    elif identity_kind in {"group", "subject", "stale"}:
        browser = client(s.app)
        if identity_kind == "group":
            headers = sign_in(browser, s.issuer, "group-only", groups=[ALLOWED_GROUP])
        elif identity_kind == "subject":
            headers = sign_in(browser, s.issuer, "two")
        else:
            old = datetime.now(UTC) - timedelta(minutes=16)
            headers = sign_in(browser, s.issuer, auth_time=int(old.timestamp()))
    elif identity_kind == "agent":
        _, headers = register_agent(s.owner, {s.production: [*identity.AGENT_SCOPES, "go_live:approve"]})
    elif identity_kind == "worker":
        headers = worker_credentials(s.owner)
    else:
        with s.owner.begin() as conn:
            conn.execute(sessions.update().where(sessions.c.digest == identity.digest(
                browser.cookies.get(SESSION_COOKIE),
            )).values(auth_time=None))
    response = browser.post(f"/v1/runs/{Minter().mint('run')}/go-live-approvals", content=b"{", headers=headers)
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "approval." + code
    response = browser.post(f"/v1/go-live-approvals/{Minter().mint('apr')}/withdraw", headers=headers)
    assert response.status_code == 403 and response.json()["error"]["code"] == "approval." + code


def test_release_checks_are_not_overridable(setup):
    s = setup
    run = finished_fixture(s)
    for check in ("delivery", "licences", "ai_label"):
        answer = s.browser.post(f"/v1/runs/{run.id}/checks/{check}/overrides",
                                json={"artifact": run.body["master_sha256"], "reason": "Fixture"},
                                headers={**s.csrf, "If-Match": "1"})
        assert answer.status_code == 403 and answer.json()["error"]["code"] == "check.not_overridable"


def test_callback_preserves_return_path_and_uses_verified_auth_time(service, owner_engine):
    app, _, issuer = service
    browser = client(app)
    target = "/productions/example/shorts?approved=true"
    query = begin_login(browser, return_to=target, fresh="true")
    assert query["prompt"] == ["login"]
    auth_time = int((datetime.now(UTC) - timedelta(seconds=20)).timestamp())
    code = issuer.authorize(query, "one", auth_time=auth_time)
    answer = browser.get("/auth/callback", params={"code": code, "state": query["state"][0],
                                                   "return_to": "https://elsewhere.example.invalid/"})
    assert answer.status_code == 303 and answer.headers["location"] == target
    with owner_engine.connect() as conn:
        recorded = conn.scalar(sa.select(sessions.c.auth_time).where(
            sessions.c.digest == identity.digest(browser.cookies.get(SESSION_COOKIE))))
    assert recorded == datetime.fromtimestamp(auth_time, UTC)
    query = begin_login(browser, return_to=target)
    assert_auth_redirect(browser.get("/auth/callback", params={"error": "refused", "state": query["state"][0]}),
                         "auth.oidc_invalid")


def test_callback_clamps_auth_time_within_provider_leeway(service, owner_engine):
    app, _, issuer = service
    app.state.oidc.settings = replace(issuer.settings(), leeway_seconds=60)
    browser = client(app)
    lower_bound = datetime.now(UTC)
    future = lower_bound + timedelta(seconds=30)
    sign_in(browser, issuer, auth_time=future.timestamp())
    with owner_engine.connect() as conn:
        recorded = conn.scalar(sa.select(sessions.c.auth_time).where(
            sessions.c.digest == identity.digest(browser.cookies.get(SESSION_COOKIE))))
    assert lower_bound <= recorded <= datetime.now(UTC)
    assert recorded < future
