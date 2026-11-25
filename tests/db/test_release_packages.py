"""Exercise private package and publication boundaries through the real API."""

import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from threading import Event

import pytest
import sqlalchemy as sa

from haynes_studio.build.provenance import Use
from haynes_studio.canonical.ids import Minter
from haynes_studio.db import runs
from haynes_studio.db.catalog import record_delivery
from haynes_studio.db.migrate import migrate
from haynes_studio.db.schema import go_live_approvals, publications, release_packages
from haynes_studio.formats.recipe import recipe_hash
from haynes_studio.golive import packages, records
from haynes_studio.golive.checks import licence_register
from haynes_studio.model_register import load_model_register
from haynes_studio.store import blob_locator, canonical_json
from tests.canonical.fixtures import example
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


def download_path(run, digest):
    return f"{path(run)}/{digest}/download"


def copy_path(s, digest):
    return Path(s.app.state.store.root) / blob_locator(s.production, digest, "application/json")


def publish(s, run, body, key="fixture-drop", *, headers=None, browser=None):
    return (browser or s.browser).post(path(run, "publications"), json=body, headers={
        **(s.csrf if headers is None else headers), "Idempotency-Key": key,
    })


def succeed(response, code=201):
    assert response.status_code == code, response.text
    return response.json()


def refuse(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
    return response.json()["error"]


def alternate_package(conn, document):
    data = canonical_json({**document, "description": "Updated fixture evidence"})
    digest = sha256(data).hexdigest()
    conn.execute(release_packages.insert().values(
        sha256=digest, run_id=document["run_id"], target_id=document["target"]["id"],
        bytes=len(data), document_bytes=data,
    ))
    return digest


def test_package_bytes_are_stable_and_approval_rechecks_common_evidence(setup, monkeypatch):
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

    approval = succeed(s.browser.post(run.path, json=run.body, headers=s.csrf))
    assert approval["release_checks"] == package["release_checks"]
    assert "package_evidence_older" not in approval
    assert get(s, run)["state"] == "releasable"


@pytest.mark.parametrize("damage", ["missing", "length", "hash"])
def test_share_copy_integrity_does_not_block_approval_or_listing(setup, damage):
    s = setup
    run, target = target_fixture(s)
    receipt = succeed(prepare(s, run, target))
    digest = receipt["sha256"]
    copy = copy_path(s, digest)
    url = download_path(run, digest)
    original = copy.read_bytes()
    initial = s.browser.get(url)
    assert initial.status_code == 200 and initial.content == original
    assert initial.headers["content-disposition"] == f'attachment; filename="{digest}.json"'
    assert initial.headers["cache-control"] == "private, no-store"
    if damage == "missing":
        copy.unlink()
        code = "release.store_unavailable"
    else:
        damaged = original + b" " if damage == "length" else b" " + original[1:]
        copy.chmod(0o644)
        copy.write_bytes(damaged)
        copy.chmod(0o444)
        code = "release.package_changed"
    refuse(s.browser.get(url), 503, code)
    approval = succeed(s.browser.post(run.path, json=run.body, headers=s.csrf))
    item = get(s, run)
    assert item["sha256"] == digest and item["state"] == "releasable"
    assert canonical_json(item["package"]) == original
    assert approval["release_checks"] == item["package"]["release_checks"]
    if damage != "missing":
        refuse(prepare(s, run, target), 503, "release.package_changed")
        assert copy.read_bytes() == damaged
        copy.unlink()
    assert succeed(prepare(s, run, target), 200) == receipt
    assert s.browser.get(url).content == copy.read_bytes() == original


def test_canonical_record_integrity_blocks_reads_and_approval(setup):
    s = setup
    run, target = target_fixture(s)
    receipt = succeed(prepare(s, run, target))
    digest = receipt["sha256"]
    copy = copy_path(s, digest)
    document = get(s, run)["package"]
    changed = canonical_json({**document, "description": "X" + document["description"][1:]})
    assert len(changed) == receipt["bytes"]
    with s.owner.begin() as conn:
        conn.execute(release_packages.update().where(release_packages.c.sha256 == digest)
                     .values(document_bytes=changed))
    assert copy.read_bytes() == canonical_json(document)
    refuse(s.browser.get(path(run)), 503, "release.package_record_changed")
    refuse(s.browser.get(download_path(run, digest)), 503, "release.package_record_changed")
    refuse(s.browser.post(run.path, json=run.body, headers=s.csrf), 503, "release.package_record_changed")
    assert s.browser.get(run.path).json()["approvals"] == []


def test_runtime_cannot_insert_a_package_with_the_wrong_byte_count(setup, engine):
    run, target = target_fixture(setup)
    data = canonical_json({"run_id": run.id, "target": {"id": target}})
    with pytest.raises(sa.exc.IntegrityError) as rejected, engine.begin() as conn:
        conn.execute(release_packages.insert().values(
            sha256=sha256(data).hexdigest(), run_id=run.id, target_id=target, bytes=len(data) + 1, document_bytes=data,
        ))
    assert rejected.value.orig.diag.constraint_name == "release_packages_document_length"


def test_runtime_publication_is_unique_and_bound_to_its_package(setup, engine):
    s = setup
    run, target = target_fixture(s)
    other = finished_fixture(s)
    receipt = succeed(prepare(s, run, target))
    approval = succeed(s.browser.post(run.path, json=run.body, headers=s.csrf))
    publication = succeed(publish(s, run, {"package_sha256": receipt["sha256"], "location": "Fixture publication"}))
    document = get(s, run)["package"]
    with engine.begin() as conn:
        new_digest = alternate_package(conn, document)

    for run_id, target_id, constraint in (
        (run.id, target, "publications_run_target_key"),
        (run.id, target + "-wrong", "publications_package_run_target_fkey"),
        (other.id, target, "publications_package_run_target_fkey"),
    ):
        with pytest.raises(sa.exc.IntegrityError) as rejected, engine.begin() as conn:
            conn.execute(publications.insert().values(
                id=Minter().mint("pub"), package_sha256=new_digest, approval_id=approval["id"],
                run_id=run_id, target_id=target_id, idempotency_actor="fixture",
                idempotency_key="direct-insert", document={},
            ))
        assert rejected.value.orig.diag.constraint_name == constraint
    with engine.connect() as conn:
        assert conn.execute(sa.select(publications.c.id, publications.c.target_id)
                            .where(publications.c.run_id == run.id)).one() == (publication["id"], target)


@pytest.mark.parametrize("duplicate", [False, True], ids=["backfill", "duplicate"])
def test_upgrade_populated_publication_history(setup, runtime_role, duplicate):
    s = setup
    run, target = target_fixture(s)
    receipt = succeed(prepare(s, run, target))
    approval = succeed(s.browser.post(run.path, json=run.body, headers=s.csrf))
    body = {"package_sha256": receipt["sha256"], "location": "Fixture publication"}
    publication = succeed(publish(s, run, body))
    item = get(s, run)
    competing_id = Minter().mint("pub")
    migrate(s.owner, "downgrade", "-1")
    try:
        if duplicate:
            with s.owner.begin() as conn:
                digest = alternate_package(conn, item["package"])
                conn.execute(publications.insert().values(
                    id=competing_id, package_sha256=digest, approval_id=approval["id"], run_id=run.id,
                    idempotency_actor="fixture", idempotency_key="legacy-duplicate",
                    document={**publication, "id": competing_id, "package_sha256": digest},
                ))
            with pytest.raises(ValueError, match="multiple publications share a run and target"):
                migrate(s.owner, runtime_role=runtime_role[0])
            with s.owner.connect() as conn:
                assert "target_id" not in {col["name"] for col in sa.inspect(conn).get_columns("publications")}
                assert set(conn.scalars(sa.select(publications.c.id).where(publications.c.run_id == run.id))) == {
                    publication["id"], competing_id,
                }
    finally:
        if duplicate:
            # Restore the shared fixture after verifying both legacy records survived.
            with s.owner.begin() as conn:
                conn.execute(publications.delete().where(publications.c.id == competing_id))
        migrate(s.owner, runtime_role=runtime_role[0])

    with s.owner.connect() as conn:
        assert conn.execute(sa.select(publications.c.target_id, publications.c.document)
                            .where(publications.c.id == publication["id"])).one() == (target, publication)
    assert get(s, run)["publication"] == item["publication"]
    assert succeed(publish(s, run, body), 200) == publication


@pytest.mark.parametrize("changed", ["engine-removed", "file-removed", "file-pin"])
def test_owner_refuses_agent_package_when_current_register_fails(setup, tmp_path, monkeypatch, changed):
    s = setup
    run, target = target_fixture(s)
    _, agent = register_agent(s.owner, {s.production: ["runs:queue"]})
    register = load_model_register()
    override = tmp_path / "register.json"
    override.write_bytes(canonical_json(register))
    monkeypatch.setenv("STUDIO_MODEL_REGISTER", str(override))
    receipt = succeed(prepare(s, run, target, agent))
    video_file = next(entry for entry in register["files"] if entry["engine"] == "wan-ti2v")
    if changed == "engine-removed":
        register["engines"] = [entry for entry in register["engines"] if entry["key"] != "wan-ti2v"]
    elif changed == "file-removed":
        register["files"].remove(video_file)
    else:
        video_file["sha256"] = "1" * 64
    override.write_bytes(canonical_json(register))

    error = refuse(s.browser.post(run.path, json=run.body, headers=s.csrf), 422, "approval.licence_missing")
    assert error["evidence"]["package_stale"] is True
    assert error["evidence"]["rows"]
    assert s.browser.get(run.path).json()["approvals"] == []
    item = get(s, run)
    assert item["sha256"] == receipt["sha256"]
    assert item["state"] == "held" and item["evidence_status"] == "stale"
    assert item["held_reason"] == "approval.licence_missing"
    refuse(prepare(s, run, target), 422, "approval.licence_missing")


def test_approval_records_new_eligible_evidence_and_can_prepare_a_new_package(setup, tmp_path, monkeypatch):
    s = setup
    run, target = target_fixture(s)
    old = succeed(prepare(s, run, target))
    old_document = get(s, run)["package"]
    register = load_model_register()
    video = next(entry for entry in register["engines"] if entry["key"] == "wan-ti2v")
    video["licence"]["note"] = "Updated terms, reviewed in this fixture."
    override = tmp_path / "register.json"
    override.write_bytes(canonical_json(register))
    monkeypatch.setenv("STUDIO_MODEL_REGISTER", str(override))

    approval = succeed(s.browser.post(run.path, json=run.body, headers=s.csrf))
    assert approval["package_evidence_older"] is True
    assert approval["release_checks"] != old_document["release_checks"]
    assert approval["release_checks"] == s.browser.get(run.path).json()["approvals"][0]["release_checks"]
    item = get(s, run)
    assert item["evidence_status"] == "older" and item["state"] == "releasable"
    assert item["sha256"] == old["sha256"] and item["package"] == old_document
    new = succeed(prepare(s, run, target))
    assert new["sha256"] != old["sha256"] and get(s, run)["sha256"] == new["sha256"]
    assert get(s, run)["evidence_status"] == "current"
    assert get(s, run)["package"]["release_checks"] == approval["release_checks"]
    assert succeed(prepare(s, run, target), 200) == new
    copy_path(s, old["sha256"]).unlink()
    restore = {"target_id": target, "package_sha256": old["sha256"]}
    refuse(s.browser.post(path(run), json={**restore, "target_id": "wrong-target"}, headers=s.csrf),
           404, "not_found")
    assert succeed(s.browser.post(path(run), json=restore, headers=s.csrf), 200) == old
    assert s.browser.get(download_path(run, old["sha256"])).content == canonical_json(old_document)
    body = {"package_sha256": new["sha256"], "location": "Fixture publication",
            "published_at": (datetime.now(UTC) + timedelta(minutes=4)).isoformat()}
    register["engines"].remove(video)
    override.write_bytes(canonical_json(register))
    assert get(s, run)["state"] == "held"
    refuse(publish(s, run, body), 422, "approval.licence_missing")
    register["engines"].append(video)
    override.write_bytes(canonical_json(register))
    succeed(publish(s, run, body))
    refuse(publish(s, run, {**body, "package_sha256": old["sha256"]}, key="second-drop"), 409,
           "release.already_published")


@pytest.mark.parametrize(("guard", "code"), [
    ("provenance", "approval.provenance_missing"),
    ("run_disclosure", "approval.ai_label_missing"),
    ("platform_setting", "approval.ai_label_missing"),
])
def test_approval_rechecks_provenance_and_disclosure_after_preparation(setup, guard, code):
    s = setup
    run, target = target_fixture(s)
    succeed(prepare(s, run, target))
    body = dict(run.body)
    if guard == "platform_setting":
        del body["platform_setting"]
    else:
        with s.owner.begin() as conn:
            row = runs.get(conn, run.id)
            document = row["document"]
            if guard == "provenance":
                del document["provenance"]["toolchain"]
            else:
                document["provenance"]["public"]["ai_generated"] = False
            runs._save(conn, row, document=document)
    refuse(s.browser.post(run.path, json=body, headers=s.csrf), 422, code)
    assert s.browser.get(run.path).json()["approvals"] == []


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
    url = download_path(run, receipt["sha256"])
    assert s.browser.get(url, headers=reader).status_code == 200
    refuse(s.browser.get(url, headers=outsider), 404, "not_found")
    refuse(s.browser.get(url, headers=queuer), 404, "not_found")
    refuse(s.browser.post(run.path, json=run.body, headers=queuer), 403, "approval.approver_not_permitted")


def test_delivery_only_legacy_preparation_checks_scope_first(setup):
    s = setup
    delivery = example("valid/delivery-legacy-r4.json")
    delivery.update(id=Minter().mint("dlv"), run_id=Minter().mint("run"))
    with s.owner.begin() as conn:
        record_delivery(conn, s.story, delivery)
    other = new_production(s.browser, s.csrf)
    _, outsider = register_agent(s.owner, {other: ["runs:queue"]})
    _, queuer = register_agent(s.owner, {s.production: ["runs:queue"]})
    url = f"/v1/runs/{delivery['run_id']}/release-packages"
    body = {"target_id": "fixture"}
    refuse(s.browser.post(url, json=body, headers=outsider), 404, "not_found")
    refuse(s.browser.post(url, json=body, headers=queuer), 422, "approval.legacy_run")


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
    body = {"package_sha256": first["sha256"], "location": "https://www.youtube.com/shorts/fixture"}
    refuse(publish(s, run, body), 409, "release.approval_required")
    other_approval = succeed(s.browser.post(other.path, json=other.body, headers=s.csrf))
    succeed(prepare(s, other, other_target))
    other_package = get(s, other)
    assert other_package["package"]["release_checks"] == other_approval["release_checks"]
    assert other_package["state"] == "releasable"
    assert get(s, run)["state"] == "held"
    refuse(publish(s, run, body), 409, "release.approval_required")
    refuse(publish(s, run, {**body, "package_sha256": other_package["sha256"]}), 404, "not_found")
    approval = succeed(s.browser.post(run.path, json=run.body, headers=s.csrf))
    assert get(s, run)["approval_id"] == approval["id"]
    refuse(publish(s, run, body, headers=csrf, browser=nonapprover), 403, "approval.subject_not_permitted")
    refuse(publish(s, run, body, headers=agent), 403, "approval.approver_not_permitted")
    refuse(publish(s, run, body, headers=worker), 403, "approval.worker_not_permitted")

    # A historical approval for this run alone does not match a different master.
    with s.owner.begin() as conn:
        record = conn.scalar(sa.select(go_live_approvals.c.document)
                             .where(go_live_approvals.c.id == approval["id"]))
        conn.execute(go_live_approvals.update().where(go_live_approvals.c.id == approval["id"])
                     .values(document={**record, "master_sha256": "0" * 64}))
    assert get(s, run)["state"] == "held"
    refuse(publish(s, run, body), 409, "release.approval_required")
    with s.owner.begin() as conn:
        conn.execute(go_live_approvals.update().where(go_live_approvals.c.id == approval["id"])
                     .values(document=record))

    story_path = f"/v1/stories/{s.story}"
    with s.owner.begin() as conn:
        conn.execute(sa.text("UPDATE stories SET published = true WHERE id = :id"), {"id": s.story})
    assert s.browser.get(story_path).json()["published"] is False
    assert s.browser.get(s.list_path, params={"publication": "published"}).json()["items"] == []
    assert [story["id"] for story in s.browser.get(s.list_path, params={"publication": "unpublished"})
            .json()["items"]] == [s.story]
    with s.owner.begin() as conn:
        conn.execute(sa.text("UPDATE stories SET published = false WHERE id = :id"), {"id": s.story})
    refuse(publish(s, run, {**body, "location": "https://user:secret@example.invalid/"}),
           422, "release.location_invalid")
    approved_at = datetime.fromisoformat(approval["approved_at"])
    refuse(publish(s, run, {**body, "published_at": (approved_at - timedelta(microseconds=1)).isoformat()}),
           422, "release.publication_before_approval")
    refuse(publish(s, run, {**body, "published_at": (datetime.now(UTC) + timedelta(minutes=6)).isoformat()}),
           422, "release.publication_in_future")
    body["published_at"] = approval["approved_at"]
    published = succeed(publish(s, run, body))
    assert published["location"] == body["location"]
    assert datetime.fromisoformat(published["published_at"]) == datetime.fromisoformat(body["published_at"])
    assert published["recorded_by"] == APPROVER and published["approval_id"] == approval["id"]
    assert published["package_sha256"] == first["sha256"] and published["master_sha256"] == run.body["master_sha256"]
    assert get(s, run)["publication"]["id"] == published["id"]
    assert get(s, run)["publication"]["recorded_by_display_name"] == approval["approver_display_name"]
    agent_item = succeed(s.browser.get(path(run), headers=agent), 200)["items"][0]
    assert agent_item["state"] == "releasable" and agent_item["sha256"] == first["sha256"]
    assert agent_item["publication"]["id"] == published["id"]
    assert "approval_id" not in agent_item
    assert {"recorded_by", "recorded_by_display_name", "approval_id"}.isdisjoint(agent_item["publication"])
    assert s.browser.get(story_path).json()["published"]
    assert [story["id"] for story in s.browser.get(s.list_path, params={"publication": "published"})
            .json()["items"]] == [s.story]
    assert succeed(publish(s, run, body), 200) == published
    refuse(publish(s, run, {**body, "location": "Another public location"}), 422, "idempotency.mismatch")
    refuse(publish(s, run, body, key="another-drop"), 409, "release.already_published")

    withdrawn = succeed(s.browser.post(f"/v1/go-live-approvals/{approval['id']}/withdraw", headers=s.csrf))
    assert withdrawn["derived"]["publication_ids"] == [published["id"]]
    assert s.browser.get(run.path).json()["approvals"] == [withdrawn]
    assert get(s, run)["state"] == "held" and get(s, run)["publication"]["id"] == published["id"]
    assert succeed(publish(s, run, body), 200) == published
    assert s.browser.get(story_path).json()["published"] and get(s, other)["state"] == "releasable"
    with s.owner.connect() as conn:
        assert conn.scalar(sa.select(sa.func.count()).select_from(publications)
                           .where(publications.c.run_id == run.id)) == 1
        assert conn.scalar(sa.text("SELECT published FROM stories WHERE id = :id"), {"id": s.story}) is False


@pytest.mark.parametrize("first", ["publication", "withdrawal"])
def test_publication_and_withdrawal_serialize_on_the_run(setup, monkeypatch, first):
    s = setup
    run, target = target_fixture(s)
    receipt = succeed(prepare(s, run, target))
    approval = succeed(s.browser.post(run.path, json=run.body, headers=s.csrf))
    other_browser = client(s.app)
    other_csrf = sign_in(other_browser, s.issuer)
    body = {"package_sha256": receipt["sha256"], "location": "Fixture publication"}
    withdraw_path = f"/v1/go-live-approvals/{approval['id']}/withdraw"

    staged = Event()
    finish = Event()
    guarded_module, guarded_name = (
        (packages, "record_publication") if first == "publication" else (records, "record_withdrawal")
    )
    insert = getattr(guarded_module, guarded_name)
    get_run = runs.get

    def pause_before_insert(*args, **kwargs):
        staged.set()
        assert finish.wait(10)
        return insert(*args, **kwargs)

    lock_errors = []

    def bound_competing_read(conn, run_id, **kwargs):
        if run_id != run.id or not staged.is_set() or finish.is_set():
            return get_run(conn, run_id, **kwargs)
        conn.exec_driver_sql("SET LOCAL lock_timeout = '250ms'")
        try:
            return get_run(conn, run_id, **kwargs)
        except sa.exc.OperationalError as error:
            # Capture the run read's error so an insert/FK lock cannot satisfy the test.
            lock_errors.append(error.orig.sqlstate)
            raise

    def withdraw():
        return other_browser.post(withdraw_path, headers=other_csrf)

    def record():
        return publish(s, run, body)

    first_write, second_write = (record, withdraw) if first == "publication" else (withdraw, record)

    monkeypatch.setattr(guarded_module, guarded_name, pause_before_insert)
    monkeypatch.setattr(runs, "get", bound_competing_read)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first_response = pool.submit(first_write)
        try:
            assert staged.wait(5)
            refuse(second_write(), 503, "database.failed")
            assert lock_errors == ["55P03"]
        finally:
            finish.set()
        first_result = succeed(first_response.result(timeout=10))
    second_response = second_write()
    if first == "publication":
        withdrawn = succeed(second_response)
        assert first_result["approval_id"] == approval["id"]
        assert datetime.fromisoformat(first_result["recorded_at"]) <= datetime.fromisoformat(
            withdrawn["derived"]["withdrawal"]["withdrawn_at"],
        )
        assert withdrawn["derived"]["publication_ids"] == [first_result["id"]]
    else:
        refuse(second_response, 409, "release.approval_required")
        assert first_result["derived"]["publication_ids"] == []
    with s.owner.connect() as conn:
        count = conn.scalar(sa.select(sa.func.count()).select_from(publications)
                            .where(publications.c.run_id == run.id))
        assert count == (1 if first == "publication" else 0)


@pytest.mark.parametrize("table", [release_packages, publications], ids=lambda item: item.name)
def test_runtime_cannot_edit_or_delete_release_records(engine, table):
    for statement in (table.update().values(**{table.primary_key.columns.keys()[0]: "unused"}), table.delete()):
        with pytest.raises(sa.exc.ProgrammingError) as denied, engine.begin() as conn:
            conn.execute(statement)
        assert denied.value.orig.sqlstate == "42501"
