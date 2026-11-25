"""Exercise private package and publication boundaries through the real API."""

import socket
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
import sqlalchemy as sa

from haynes_studio.build.provenance import Use
from haynes_studio.canonical.ids import Minter
from haynes_studio.db.schema import go_live_approvals, publications, release_packages, stories
from haynes_studio.formats.recipe import recipe_hash
from haynes_studio.golive.checks import licence_register
from haynes_studio.store import blob_locator, canonical_json
from tests.db.test_go_live import (
    APPROVER, client, engine, finished_fixture, new_production, owner_engine, register_agent,
    runtime_db, runtime_role, service, setup, sign_in, worker_credentials,
)
from tests.formats.fixtures import doll_short

pytestmark = pytest.mark.db


def target_fixture(s, *, max_length=60_000, aspect="9:16", failure=None, extra_uses=None):
    recipe = doll_short()["recipe"]
    target = recipe["targets"][0]
    target["rules"].update(max_length_ms=max_length, aspect=aspect, ai_label_required=False)
    pin = {"id": Minter().mint("fmv"), "sha256": recipe_hash(recipe), "recipe": recipe}
    run = finished_fixture(s, failure=failure, format_pin=pin, extra_uses=extra_uses)
    return run, target["id"]


def path(run, resource="release-packages"):
    return f"/v1/runs/{run.id}/{resource}"


def prepare(s, run, target, headers=None):
    return s.browser.post(path(run), json={"target_id": target},
                          headers=s.csrf if headers is None else headers)


def get(s, run):
    result = s.browser.get(path(run))
    assert result.status_code == 200, result.text
    assert result.headers["cache-control"] == "private, no-store"
    return result.json()["items"][0]


def succeed(response, code=201):
    assert response.status_code == code, response.text
    return response.json()


def refuse(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
    return response.json()["error"]


def test_package_bytes_are_stable_and_common_evidence_is_pinned(setup, monkeypatch):
    s = setup
    run, target = target_fixture(s, extra_uses={
        "controlfoley": Use("sound", hardware="Fixture sound GPU"),
        "kokoro": Use("voice", hardware="Fixture voice CPU"),
    })
    register = licence_register()

    def no_connection(*args, **kwargs):
        pytest.fail("Release operations must never open an external connection")

    monkeypatch.setattr(socket.socket, "connect", no_connection)
    monkeypatch.setattr(socket, "create_connection", no_connection)
    monkeypatch.setattr(socket, "getaddrinfo", no_connection)
    preview = s.browser.get(run.path).json()["release_checks"]
    receipt = succeed(prepare(s, run, target))
    item = get(s, run)
    assert receipt == {key: item[key] for key in ("sha256", "bytes")}
    assert item["state"] == "held" and item["held_reason"] == "release.approval_required"
    package = item["package"]
    assert package["release_checks"] == preview
    assert package["description"].splitlines() == [
        "This video was AI-generated.",
        f"Sound: {register.engines['controlfoley']['name']} on Fixture sound GPU",
        f"Voices: {register.engines['kokoro']['name']} on Fixture voice CPU",
        f"Sound: {register.engines['stable-audio']['name']}",
        f"Video: {register.engines['wan-ti2v']['name']} on two RTX 3090s",
    ]
    assert package["checklist"][0] == "Turn on the synthetic-content setting."
    assert package["target"]["rules"]["ai_label_required"] is False
    assert package["master"] == {key: run.delivery["master"][key] for key in ("sha256", "bytes", "media_type")}
    assert package["run_id"] == run.id and package["run_snapshot_sha256"] == run.snapshot
    assert package["delivery_id"] == run.delivery["id"]
    assert package["target_checks"]["length"]["max_length_ms"] == 60_000
    rows = package["release_checks"]["licences"]["rows"]
    sound = next(row for row in rows if row["register_key"] == "controlfoley")
    assert sound["register_entry"].items() <= register.engines["controlfoley"].items()
    assert "where" not in sound["register_entry"]
    assert sound["register_entry"]["licence"]["commercial_use"] == "noncommercial"
    unknown = next(row for row in rows if row["state"] == "unknown")
    assert unknown["register_entry"]["licence"]["commercial_use"] == "unknown"
    assert {"allowed", "conditional", "unknown", "noncommercial"} <= {
        row["licence"]["commercial_use"] for row in rows
    }
    location = blob_locator(s.production, item["sha256"], "application/json")
    with s.app.state.store.open(location) as handle:
        data = handle.read()
    assert data == canonical_json(package)
    assert sha256(data).hexdigest() == item["sha256"] and len(data) == item["bytes"]
    assert s.browser.get(f'/v1/media/{item["sha256"]}').status_code == 404
    assert succeed(prepare(s, run, target), 200) == receipt
    assert get(s, run) == item

    # A later register change cannot silently change the evidence signed for these bytes.
    monkeypatch.setattr("haynes_studio.golive.checks.licence_register", no_connection)
    approval = succeed(s.browser.post(run.path, json=run.body, headers=s.csrf))
    assert approval["release_checks"] == package["release_checks"]
    assert get(s, run)["state"] == "releasable"


@pytest.mark.parametrize(("failure", "maximum", "aspect", "code"), [
    ("legacy", 60_000, "9:16", "approval.legacy_run"),
    ("unfinished", 60_000, "9:16", "approval.run_unfinished"),
    ("unverified", 60_000, "9:16", "approval.delivery_unverified"),
    ("delivery", 60_000, "9:16", "approval.delivery_mismatch"),
    ("disclosure", 60_000, "9:16", "approval.ai_label_missing"),
    ("provenance", 60_000, "9:16", "approval.provenance_missing"),
    ("file", 60_000, "9:16", "approval.licence_missing"),
    ("engine", 60_000, "9:16", "approval.licence_missing"),
    (None, None, "9:16", "release.maximum_unset"),
    (None, 1_000, "9:16", "release.over_length"),
    (None, 60_000, "1:1", "release.aspect_mismatch"),
], ids=["legacy", "unfinished", "unverified", "mismatched", "disclosure", "provenance",
        "file", "engine", "maximum", "length", "aspect"])
def test_prepare_refuses_failed_checks(setup, failure, maximum, aspect, code):
    run, target = target_fixture(setup, max_length=maximum, aspect=aspect, failure=failure)
    error = refuse(prepare(setup, run, target), 422, code)
    if code == "approval.licence_missing":
        missing = [row for row in error["evidence"]["rows"] if row["state"] == "missing"]
        assert len(missing) == 1 and ("file" in missing[0]) == (failure == "file")
    assert setup.browser.get(path(run)).json()["items"] == []


def test_preparation_uses_production_scope_and_only_the_frozen_target(setup):
    s = setup
    run, target = target_fixture(s)
    other = new_production(s.browser, s.csrf)
    _, outsider = register_agent(s.owner, {other: ["read", "runs:queue"]})
    _, reader = register_agent(s.owner, {s.production: ["read"]})
    _, queuer = register_agent(s.owner, {s.production: ["runs:queue"]})
    refuse(prepare(s, run, target, outsider), 404, "not_found")
    refuse(s.browser.get(path(run), headers=outsider), 404, "not_found")
    refuse(prepare(s, run, target, reader), 404, "not_found")
    refuse(s.browser.get(path(run), headers=queuer), 404, "not_found")
    refuse(prepare(s, run, "unfrozen"), 422, "release.target_unknown")
    refuse(prepare(s, finished_fixture(s), target), 422, "release.format_missing")
    receipt = succeed(prepare(s, run, target, queuer))
    assert set(receipt) == {"sha256", "bytes"}
    assert succeed(s.browser.get(path(run), headers=reader), 200)["items"][0]["sha256"] == receipt["sha256"]
    refuse(s.browser.post(run.path, json=run.body, headers=queuer), 403, "approval.approver_not_permitted")


def test_drop_requires_exact_active_approval_and_a_person_and_is_append_only(setup, monkeypatch):
    s = setup
    run, target = target_fixture(s)
    other, other_target = target_fixture(s)
    nonapprover = client(s.app)
    csrf = sign_in(nonapprover, s.issuer, subject="two")
    _, agent = register_agent(s.owner, {s.production: ["read", "runs:queue"]})
    worker = worker_credentials(s.owner)

    def no_connection(*args, **kwargs):
        pytest.fail("Recording a manual publication must never access the pasted location")

    monkeypatch.setattr(socket.socket, "connect", no_connection)
    monkeypatch.setattr(socket, "create_connection", no_connection)
    monkeypatch.setattr(socket, "getaddrinfo", no_connection)
    first = succeed(prepare(s, run, target))
    url = path(run, "publications")
    body = {"package_sha256": first["sha256"], "location": "https://www.youtube.com/shorts/fixture",
            "published_at": (datetime.now(UTC) - timedelta(seconds=10)).isoformat()}
    refuse(s.browser.post(url, json=body, headers=s.csrf), 409, "release.approval_required")
    other_approval = succeed(s.browser.post(other.path, json=other.body, headers=s.csrf))
    succeed(prepare(s, other, other_target))
    other_package = get(s, other)
    assert other_package["package"]["release_checks"] == other_approval["release_checks"]
    assert other_package["state"] == "releasable"
    assert get(s, run)["state"] == "held"
    refuse(s.browser.post(url, json=body, headers=s.csrf), 409, "release.approval_required")
    refuse(s.browser.post(url, json={**body, "package_sha256": other_package["sha256"]}, headers=s.csrf),
           404, "not_found")
    approval = succeed(s.browser.post(run.path, json=run.body, headers=s.csrf))
    assert get(s, run)["approval_id"] == approval["id"]
    refuse(nonapprover.post(url, json=body, headers=csrf), 403, "approval.subject_not_permitted")
    refuse(s.browser.post(url, json=body, headers=agent), 403, "approval.approver_not_permitted")
    refuse(s.browser.post(url, json=body, headers=worker), 403, "approval.worker_not_permitted")

    # A historical approval for this run alone does not match a different master.
    with s.owner.begin() as conn:
        record = conn.scalar(sa.select(go_live_approvals.c.document)
                             .where(go_live_approvals.c.id == approval["id"]))
        conn.execute(go_live_approvals.update().where(go_live_approvals.c.id == approval["id"])
                     .values(document={**record, "master_sha256": "0" * 64}))
    assert get(s, run)["state"] == "held"
    refuse(s.browser.post(url, json=body, headers=s.csrf), 409, "release.approval_required")
    with s.owner.begin() as conn:
        conn.execute(go_live_approvals.update().where(go_live_approvals.c.id == approval["id"])
                     .values(document=record))

    story_path = f"/v1/stories/{s.story}"
    assert not s.browser.get(story_path).json()["published"]
    refuse(s.browser.post(url, json={**body, "location": "https://user:secret@example.invalid/"},
                          headers=s.csrf), 422, "release.location_invalid")
    refuse(s.browser.post(url, json={**body, "published_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()},
                          headers=s.csrf), 422, "release.publication_in_future")
    published = succeed(s.browser.post(url, json=body, headers=s.csrf))
    assert published["location"] == body["location"]
    assert datetime.fromisoformat(published["published_at"]) == datetime.fromisoformat(body["published_at"])
    assert published["recorded_by"] == APPROVER and published["approval_id"] == approval["id"]
    assert published["package_sha256"] == first["sha256"] and published["master_sha256"] == run.body["master_sha256"]
    assert get(s, run)["publication"]["id"] == published["id"]
    assert "recorded_by" not in get(s, run)["publication"]
    assert s.browser.get(story_path).json()["published"]
    assert [story["id"] for story in s.browser.get(s.list_path, params={"publication": "published"})
            .json()["items"]] == [s.story]
    refuse(s.browser.post(url, json=body, headers=s.csrf), 409, "release.already_published")

    withdrawn = succeed(s.browser.post(f"/v1/go-live-approvals/{approval['id']}/withdraw", headers=s.csrf))
    assert withdrawn["derived"]["publication_ids"] == [published["id"]]
    assert s.browser.get(run.path).json()["approvals"] == [withdrawn]
    assert get(s, run)["state"] == "held" and get(s, run)["publication"]["id"] == published["id"]
    assert s.browser.get(story_path).json()["published"] and get(s, other)["state"] == "releasable"
    with s.owner.connect() as conn:
        assert conn.scalar(sa.select(sa.func.count()).select_from(publications)) == 1
        assert not conn.scalar(sa.select(stories.c.published).where(stories.c.id == s.story))


@pytest.mark.parametrize("table", [release_packages, publications], ids=lambda item: item.name)
def test_runtime_cannot_edit_or_delete_release_records(engine, table):
    for statement in (table.update().values(**{table.primary_key.columns.keys()[0]: "unused"}), table.delete()):
        with pytest.raises(sa.exc.ProgrammingError) as denied, engine.begin() as conn:
            conn.execute(statement)
        assert denied.value.orig.sqlstate == "42501"
