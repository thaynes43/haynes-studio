"""Go-live acceptance through the runtime role with fixture provenance and no platform I/O."""

import hashlib
import socket
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from haynes_studio.api.approval_routes import licence_register
from haynes_studio.api.auth import SESSION_COOKIE
from haynes_studio.build.provenance import Use, credits, engines
from haynes_studio.canonical.ids import Minter
from haynes_studio.db import identity, runs
from haynes_studio.db.catalog import record_delivery
from haynes_studio.db.schema import (
    go_live_approvals, go_live_withdrawals, runs as run_table, sessions, stories,
)
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


def finished_fixture(s, *, failure=None):
    uses = {"wan-ti2v": Use("video", hardware="two RTX 3090s"),
            "kokoro": Use("voice"), "stable-audio": Use("sound"),
            "qwen-image": Use("image"), "asr": Use("check")}
    if failure == "file":
        uses["wan-ti2v"].files["unlisted-placeholder"] = digest("file")
    register = licence_register()
    engine_list = engines(register, uses, {})
    if failure == "engine":
        engine_list.append({"key": "unregistered-placeholder", "role": "writer", "files": []})
    external_id = Minter().mint("asv")
    provenance = {
        "engines": engine_list, "toolchain": {},
        "inputs_externally_generated": [{"id": external_id, "kind": "board_photo",
                                         "agent": {"session": "private-fixture"}}],
        "public": {"ai_generated": failure != "disclosure",
                   "credits": credits(engine_list, {key: use.hardware for key, use in uses.items()})},
    }
    with s.owner.begin() as conn:
        draft = conn.scalar(sa.select(stories.c.document).where(stories.c.id == s.story))
        key = Minter().mint("run")
        row = runs.enqueue(conn, snapshot={"story": {**draft, "boards": []}},
                           snapshot_sha256=digest("snapshot " + key), library={}, actor=APPROVER,
                           key=key, estimate={"estimate": {}, "methods": []})
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
    response = s.browser.post(older.path, json=older.body, headers=s.csrf)
    assert response.status_code == 201, response.text
    approval = response.json()
    assert approval["run_id"] == older.id
    assert approval["master_sha256"] == older.body["master_sha256"]
    assert approval["run_snapshot_sha256"] == older.snapshot
    assert approval["delivery_id"] == older.delivery["id"]
    assert approval["approver"] == APPROVER and approval["approver_display_name"] == "Fixture Person"
    assert datetime.fromisoformat(approval["auth_time"]) <= datetime.fromisoformat(approval["approved_at"])
    evidence = approval["release_checks"]
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
    # Stand in for story 449's eventual publication writer and prove it is independent.
    with s.owner.begin() as conn:
        conn.execute(stories.update().where(stories.c.id == s.story).values(published=True))
    assert listing(publication="published", approved=True) == [s.story]

    refused = s.browser.post(older.path, json=older.body, headers=s.csrf)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "approval.already_active"
    path = f"/v1/go-live-approvals/{approval['id']}/withdraw"
    withdrawn = s.browser.post(path, headers=s.csrf)
    assert withdrawn.status_code == 201, withdrawn.text
    output = withdrawn.json()
    assert output["master_sha256"] == approval["master_sha256"]
    assert output["derived"]["state"] == "withdrawn"
    assert output["derived"]["withdrawal"]["withdrawn_by"] == APPROVER
    assert listing(publication="published", approved=False) == [s.story]
    assert listing(publication="published", approved=True) == []
    assert s.browser.post(path, headers=s.csrf).json()["error"]["code"] == "approval.already_withdrawn"
    with engine.connect() as conn:
        persisted = conn.scalar(sa.select(go_live_approvals.c.document).where(go_live_approvals.c.id == approval["id"]))
        assert persisted == {key: value for key, value in approval.items() if key != "derived"}
    renewed = s.browser.post(older.path, json=older.body, headers=s.csrf)
    assert renewed.status_code == 201 and renewed.json()["id"] != approval["id"]
    for mutation in (go_live_approvals.update().values(document={}), go_live_withdrawals.delete()):
        with pytest.raises(sa.exc.ProgrammingError) as denied, engine.begin() as conn:
            conn.execute(mutation)
        assert denied.value.orig.sqlstate == "42501"


@pytest.mark.parametrize(("failure", "code"), [
    ("unfinished", "run_unfinished"), ("legacy", "legacy_run"), ("unverified", "delivery_unverified"),
    ("delivery", "delivery_mismatch"), ("engine", "licence_missing"), ("file", "licence_missing"),
    ("disclosure", "ai_label_missing"), ("setting", "ai_label_missing"), ("hash", "not_exact_run"),
])
def test_approval_refuses_each_invalid_release_result(setup, failure, code):
    s = setup
    held = finished_fixture(s, failure=failure)
    if failure == "setting":
        del held.body["platform_setting"]
    if failure == "hash":
        held.body["master_sha256"] = digest("wrong")
    result = s.browser.post(held.path, json=held.body, headers=s.csrf)
    assert result.status_code == 422, result.text
    error = result.json()["error"]
    assert error["code"] == "approval." + code
    if code == "licence_missing":
        assert error["evidence"]["result"] == "fail"
        missing = [row for row in error["evidence"]["rows"] if row["state"] == "missing"]
        assert len(missing) == 1 and ("file" in missing[0]) == (failure == "file")
    assert s.browser.get(f"/v1/runs/{held.id}").json()["active_approval_id"] is None


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
