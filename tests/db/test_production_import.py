"""Exercise the import CLI, real PostgreSQL grants and the real media API."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import stat
import warnings

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest
import sqlalchemy as sa

from haynes_studio.api.key_admin import run as admin
from haynes_studio.api.oidc import random_secret
from haynes_studio.canonical.ids import Minter
from haynes_studio.db import drafts, runs
from haynes_studio.db.engine import connect_engine
from haynes_studio.db.migrate import migrate
from haynes_studio.db.schema import asset_media, asset_versions, deliveries, productions, run_lane, stories
from haynes_studio.db.schema import runs as run_rows
from haynes_studio.drafting.declaration import READ_TOKEN_HEADER
from haynes_studio.importer import production as production_import
from haynes_studio.store import LocalStore, StagingLeftoverWarning, blob_locator, canonical_json
from tests.build_story.fixtures import OPERATOR, example
from tests.db.test_studio_api import (
    client, engine, new_production, register_agent, runtime_role, service, sign_in,
)
from tests.db.test_media_jobs import PROVENANCE, image_file
from tests.importer.production_fixture import FRAMES, make_archive
from tests.motion.fixtures import still_version
from tests.queue.fake_wan import Clock
from tests.support.database import new_schema_name

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def migration_db(studio_db, runtime_role):
    schema = new_schema_name()
    role, password = f"{schema}_migrator", random_secret()
    with psycopg.connect(studio_db.url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE ROLE {} LOGIN NOINHERIT PASSWORD {}")
                     .format(sql.Identifier(role), sql.Literal(password)))
        try:
            conn.execute(sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}")
                         .format(sql.Identifier(schema), sql.Identifier(role)))
            yield replace(studio_db, schema=schema,
                          url=make_conninfo(studio_db.url, user=role, password=password))
        finally:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


@pytest.fixture(scope="module")
def owner_engine(migration_db, runtime_role):
    engine = connect_engine(migration_db.url, migration_db.schema)
    try:
        migrate(engine, runtime_role=runtime_role[0])
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def runtime_db(studio_db, migration_db, owner_engine, runtime_role):
    role, password = runtime_role
    return replace(migration_db, url=make_conninfo(studio_db.url, user=role, password=password))


@pytest.fixture
def operator(migration_db, service, monkeypatch):
    _, store, _ = service
    monkeypatch.setenv("STUDIO_MIGRATION_DATABASE_URL", migration_db.url)
    monkeypatch.setenv("STUDIO_DATABASE_SCHEMA", migration_db.schema)
    monkeypatch.setenv("STUDIO_STORE_ROOT", store.root)


def file_paths(store):
    return {path.relative_to(store.root) for path in Path(store.root).rglob("*")}


def assert_private_ranges(browser, headers, wrong_headers, media, expected_bytes):
    url = f'/v1/media/{media["sha256"]}'
    size = media["bytes"]
    head = browser.head(url, headers=headers)
    assert head.status_code == 200 and head.headers["content-length"] == str(size)
    assert head.headers["accept-ranges"] == "bytes"
    assert head.content == b""
    midpoint = size // 2
    chunks = []
    for start, end in ((0, midpoint), (midpoint, size)):
        range_header = {"Range": f"bytes={start}-{end - 1 if end != size else ''}"}
        response = browser.get(url, headers={**headers, **range_header})
        assert response.status_code == 206
        assert response.headers["content-range"] == f"bytes {start}-{end - 1}/{size}"
        assert response.headers["content-length"] == str(end - start)
        assert response.content == expected_bytes[start:end]
        chunks.append(response.content)
        for auth, status in ((wrong_headers, 404), ({}, 401)):
            denied = browser.get(url, headers={**auth, **range_header})
            assert denied.status_code == status
            assert "content-range" not in denied.headers
            assert denied.headers["content-type"].startswith("application/json")
    assert hashlib.sha256(b"".join(chunks)).hexdigest() == media["sha256"]
    tail = browser.get(url, headers={**headers, "Range": "bytes=-31"})
    assert tail.status_code == 206 and tail.content == expected_bytes[-31:]


@pytest.mark.parametrize("recovered", [False, True])
def test_import_replay_and_production_scoped_media(operator, service, owner_engine, tmp_path, capsys,
                                                   recovered):
    app, store, issuer = service
    fixture = make_archive(tmp_path / "job", recovered=recovered)
    before = fixture.files()
    assert admin(fixture.args()) == 0
    first = capsys.readouterr()
    result = json.loads(first.out)
    assert first.err == "" and result["status"] == "imported"
    assert result["production_id"] == fixture.production_id
    assert result["story_id"] == fixture.run["story_id"]
    assert result["run_id"] == fixture.run["id"]
    assert result["delivery_id"] == fixture.delivery_id
    assert result["files"] == (5 if recovered else 10)
    assert result["bytes"] == sum(f["bytes"] for f in before.values())
    assert result["boards"] == result["asset_versions"] == (0 if recovered else 1)
    assert str(tmp_path) not in first.out

    browser = client(app)
    app.state.oidc.settings = replace(issuer.settings(), go_live_approver_subjects=frozenset({"one"}))
    with client(app) as owner:
        csrf = sign_in(owner, issuer)
        other = new_production(owner, csrf)
        approval_path = f'/v1/runs/{result["run_id"]}/go-live-approvals'
        review = owner.get(approval_path)
        assert review.status_code == 200
        approval = owner.post(approval_path, headers=csrf,
                              json={"master_sha256": before["final.mp4"]["sha256"],
                                    "platform_setting": True})
        assert approval.status_code == 422
        assert approval.json()["error"]["code"] == "approval.legacy_run"
        assert review.json()["approve"] == {"allowed": False, "code": approval.json()["error"]["code"]}
        candidate = owner.post(f'/v1/runs/{result["run_id"]}/candidates',
                               headers=csrf, json={"target_id": "fixture-target"})
        assert candidate.status_code == 422
        assert candidate.json()["error"]["code"] == "candidate.legacy_run"
        release = owner.post(f'/v1/runs/{result["run_id"]}/release-packages',
                             headers=csrf, json={"target_id": "fixture-target"})
        assert release.status_code == 422
        assert release.json()["error"]["code"] == "approval.legacy_run"
    _, headers = register_agent(owner_engine, {fixture.production_id: ["read"]})
    _, wrong = register_agent(owner_engine, {other: ["read"]})
    production = browser.get(f'/v1/productions/{result["production_id"]}', headers=headers)
    assert production.status_code == 200 and production.json()["name"] == fixture.name
    source = browser.get(f'/v1/stories/{result["story_id"]}', headers=headers)
    assert source.status_code == 200
    assert len(source.json()["board_order"]) == result["boards"]
    run = browser.get(f'/v1/runs/{result["run_id"]}', headers=headers)
    assert run.status_code == 200
    doc = run.json()
    marker = doc["legacy"]["archive_import"]
    assert doc["status"] == "succeeded" and doc["number"] == fixture.run["number"]
    assert doc["snapshot"] == fixture.run["snapshot"]
    assert doc["provenance"] == fixture.run["provenance"]
    assert marker["source_directory"] == fixture.root.name and marker["imported_at"].endswith("Z")
    assert marker["source_kind"] == ("recovered" if recovered else "canonical")
    snapshot = browser.get(f'/v1/runs/{result["run_id"]}/snapshot', headers=headers)
    if recovered:
        assert snapshot.status_code == 404 and snapshot.json()["error"]["code"] == "run.snapshot_missing"
    else:
        assert snapshot.status_code == 200
        assert snapshot.content == (fixture.root / "snapshot.json").read_bytes()
        assert snapshot.headers["etag"] == f'"{before["snapshot.json"]["sha256"]}"'
    response = browser.get(f'/v1/runs/{result["run_id"]}/delivery', headers=headers)
    assert response.status_code == 200
    delivery = response.json()
    if recovered:
        assert "decoded_frames" not in delivery["verification"]
        assert delivery["verification"]["recovered_container_metadata_only"] == {
            "frames": FRAMES, "ledger_id": "a" * 32, "ledger_sha256": before["ledger.json"]["sha256"],
        }
    for role, name in (("master", "final.mp4"), ("proxy", "proxy.mp4")):
        assert {k: delivery[role][k] for k in ("sha256", "bytes")} == before[name]
        assert_private_ranges(browser, headers, wrong, delivery[role], (fixture.root / name).read_bytes())
    if not recovered:
        asset = browser.get(f'/v1/assets/{fixture.asset["asset_id"]}', headers=headers).json()
        assert asset["versions"] == [{**fixture.asset, "recorded_without_media": True}]
    before_paths = file_paths(store)
    with owner_engine.connect() as conn:
        previous = dict(runs.get(conn, result["run_id"]))
        assert previous["snapshot"] == (None if recovered else fixture.snapshot)
        assert previous["frozen_library"] == ([] if recovered else [fixture.asset])
        lane = conn.scalar(sa.select(run_lane.c.next_position))
    assert admin(fixture.args()) == 0
    assert json.loads(capsys.readouterr().out) == {**result, "status": "already_imported"}
    with owner_engine.connect() as conn:
        assert dict(runs.get(conn, result["run_id"])) == previous
        assert conn.scalar(sa.select(run_lane.c.next_position)) == lane
    assert file_paths(store) == before_paths
    assert fixture.files() == before


def test_upload_replacement_for_imported_recorded_only_photo(operator, service, owner_engine, tmp_path, capsys):
    app, _, _ = service
    archived_agent = {"kind": "agent", "key_id": Minter().mint("key")}
    fixture = make_archive(tmp_path / "job", board_creator=archived_agent)
    assert admin(fixture.args()) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "imported"
    _, auth = register_agent(owner_engine, {fixture.production_id: ["read", "draft:write", "assets:upload"]})
    api = client(app)
    path = f'/v1/boards/{fixture.asset["scope"]["board_id"]}'
    read = api.get(path, headers=auth)
    assert read.status_code == 200
    held = read.json()
    assert held["drafted_by"] == archived_agent and "created_by" not in held
    assert held["photo"]["current_version_id"] == fixture.asset["id"]
    headers = {**auth, "If-Match": read.headers["etag"], "Content-Type": "image/png"}
    photo = image_file(tmp_path)
    with_missing_source = {**PROVENANCE, "source_asset_version_ids": [fixture.asset["id"]]}
    refused = api.post(path + "/photo-versions", content=photo,
                       headers={**headers, "X-Studio-Photo-Provenance": json.dumps(with_missing_source)})
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "asset.recorded_without_media"

    uploaded = api.post(path + "/photo-versions", content=photo,
                        headers={**headers, "X-Studio-Photo-Provenance": json.dumps(PROVENANCE)})
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["selected"] is False
    assert api.get(path, headers=auth).json() == held
    replacement = {**held["photo"], "current_version_id": uploaded.json()["version"]["id"]}
    write = {**auth, "If-Match": read.headers["etag"]}
    result = api.patch(path, json={"photo": replacement}, headers=write)
    assert result.status_code == 409 and result.json()["error"]["code"] == "draft.protected"
    result = api.patch(path, json={"photo": replacement, "acknowledge_person_edit": {
        "board_revision": held["revision"], "read_token": read.headers[READ_TOKEN_HEADER],
    }}, headers=write)
    assert result.status_code == 200, result.text
    assert result.json()["photo"] == replacement


def test_replay_after_production_rename(operator, owner_engine, service, tmp_path, capsys):
    _, store, _ = service
    fixture = make_archive(tmp_path / "job", recovered=True)
    assert admin(fixture.args()) == 0
    original = json.loads(capsys.readouterr().out)
    with owner_engine.begin() as conn:
        row = dict(runs.get(conn, fixture.run["id"]))
        production = conn.scalar(sa.select(productions.c.document).where(
            productions.c.id == fixture.production_id))
        renamed = {**production, "name": "Renamed after import", "revision": 2}
        conn.execute(productions.update().where(productions.c.id == fixture.production_id)
                     .values(document=renamed))
        lane = conn.scalar(sa.select(run_lane.c.next_position))
    paths = file_paths(store)
    assert admin(fixture.args()) == 0
    assert json.loads(capsys.readouterr().out) == {**original, "status": "already_imported"}
    with owner_engine.connect() as conn:
        assert drafts.production(conn, fixture.production_id)["name"] == renamed["name"]
        assert dict(runs.get(conn, fixture.run["id"])) == row
        assert conn.scalar(sa.select(run_lane.c.next_position)) == lane
    assert file_paths(store) == paths


def test_matching_production_collision_leaves_existing_production_alone(
        operator, service, owner_engine, tmp_path, capsys):
    _, store, _ = service
    fixture = make_archive(tmp_path / "job")
    with owner_engine.begin() as conn:
        held = seed_matching_production(conn, fixture)
        lane = conn.scalar(sa.select(run_lane.c.next_position))
    assert admin(fixture.args()) == 1
    assert capsys.readouterr().err.strip() == "import_production.identity_conflict"
    assert file_paths(store) == set()
    with owner_engine.connect() as conn:
        assert drafts.production(conn, fixture.production_id) == held
        assert conn.scalar(sa.select(stories.c.id).where(stories.c.production_id == fixture.production_id)) is None
        assert conn.scalar(sa.select(run_lane.c.next_position)) == lane


def seed_matching_production(conn, fixture):
    # Use an ordinary production document with a matching ID, name and media profile.
    document = {**example("production.json"), "id": fixture.production_id, "name": fixture.name}
    document["media_types"] = [item for item in document["media_types"] if item["kind"] == "short"]
    assert document["media_types"]
    drafts._insert_production(conn, document)
    return document


@pytest.mark.parametrize("collision", [
    "story_id", "story_source_key", "board_id", "board_source_key", "note_id",
    "asset_id", "asset_version_id", "asset_source_key", "directory", "receipt",
])
def test_conflicting_archive_identities_refused_before_publication(
        operator, service, owner_engine, tmp_path, capsys, collision):
    _, store, _ = service
    ids = Minter()
    identities = {
        "story_id": ids.mint("sty"), "board_id": ids.mint("brd"), "note_id": ids.mint("nte"),
        "asset_id": ids.mint("ast"), "asset_version_id": ids.mint("asv"),
        "story_source_key": f'fixture:{ids.mint("sty")}',
        "board_source_key": f'fixture:{ids.mint("brd")}',
        "asset_source_key": f'fixture:{ids.mint("ast")}',
    }
    same_identity = {collision: identities[collision]} if collision in identities else {}
    first = make_archive(tmp_path / "first", **same_identity)
    assert admin(first.args()) == 0
    capsys.readouterr()
    before = file_paths(store)
    if collision == "directory":
        first.root = first.root.rename(first.root.with_name("different-cut"))
        another = first
    elif collision == "receipt":
        (first.root / "wan-clip.json").write_text('{"changed":true}')
        first.receipt.write_text(json.dumps(first.files()))
        another = first
    else:
        another = make_archive(tmp_path / "another", **same_identity)
    with owner_engine.connect() as conn:
        row = dict(runs.get(conn, first.run["id"]))
        lane = conn.scalar(sa.select(run_lane.c.next_position))
    assert admin(another.args()) == 1
    assert capsys.readouterr().err.strip() == "import_production.identity_conflict"
    with owner_engine.connect() as conn:
        assert dict(runs.get(conn, first.run["id"])) == row
        assert conn.scalar(sa.select(run_lane.c.next_position)) == lane
    assert file_paths(store) == before


def test_imported_pins_are_private_and_block_rebuild(operator, service, owner_engine, tmp_path, capsys):
    app, _, issuer = service
    fixture = make_archive(tmp_path / "job", with_shared_asset=True)
    assert admin(fixture.args()) == 0
    capsys.readouterr()
    version_ids = [fixture.asset["id"], fixture.shared_asset["id"]]
    with owner_engine.connect() as conn:
        assert runs.get(conn, fixture.run["id"])["frozen_library"] == [fixture.asset, fixture.shared_asset]
        assert conn.scalars(sa.select(asset_media.c.version_id).where(
            asset_media.c.version_id.in_(version_ids))).all() == []
    with client(app) as browser:
        csrf = sign_in(browser, issuer)
        other = new_production(browser, csrf)
        _, right = register_agent(owner_engine, {fixture.production_id: ["read", "runs:queue"]})
        _, wrong = register_agent(owner_engine, {other: ["read"]})
        url = f'/v1/assets/{fixture.shared_asset["asset_id"]}'
        response = browser.get(url, headers=right)
        assert response.status_code == 200
        scoped = {"production_id": fixture.production_id}
        assert response.json()["asset"]["scope"] == scoped
        assert response.json()["versions"] == [
            {**fixture.shared_asset, "scope": scoped, "recorded_without_media": True},
        ]
        assert browser.get(url, headers=wrong).status_code == 404
        url = f'/v1/stories/{fixture.run["story_id"]}'
        estimate = browser.get(f"{url}/estimate", headers=right)
        assert estimate.status_code == 200
        assert {p["rule"] for p in estimate.json()["problems"]} == {"asset.recorded_without_media"}
        assert {p["asset_version_id"] for p in estimate.json()["problems"]} == set(version_ids)
        assert all(p["message"].endswith("was recorded without media") for p in estimate.json()["problems"])
        queued = browser.post(f"{url}/runs", headers={**right, "Idempotency-Key": "blocked-rebuild",
                                                      "If-Match": str(fixture.snapshot["story"]["revision"])})
        assert queued.status_code == 422


@pytest.mark.parametrize("declaring_set", [False, True], ids=["role-free", "historical-unmasked-run"])
def test_archive_import_preserves_recorded_run_while_new_build_checks_masks(
    operator, service, owner_engine, tmp_path, capsys, declaring_set,
):
    app, store, _ = service
    fixture = make_archive(tmp_path / "job")
    versions = [fixture.asset]
    if declaring_set:
        plate = still_version(73, "c" * 64, kind="set")
        plate.update(id=Minter().mint("asv"), asset_id=Minter().mint("ast"),
                     scope={"production_id": fixture.production_id}, legacy=None)
        plate["provenance"]["source_key"] = None
        plate["content"].update(width=64, height=32, locator=blob_locator(
            fixture.production_id, "c" * 64, "image/png",
        ))
        plate["occlusion"] = {"foreground": [{
            "key": "table", "layer_order": 20,
            "mask": {"version_id": Minter().mint("asv"), "sha256": "b" * 64,
                     "still_sha256": "c" * 64, "width": 64, "height": 32},
        }]}
        # The whole-frame historical run carries the set declaration and no mask pin.
        fixture.snapshot["story"]["set"] = {"asset_version_id": plate["id"], "motion_asset_version_id": None,
                                             "foreground_edge_px": None, "foreground_feather_px": None,
                                             "legacy_fire": None}
        fixture.snapshot["resolved_asset_versions"].append({"id": plate["id"], "kind": "set", "sha256": "c" * 64})
        versions.append(plate)
        snapshot_data = canonical_json(fixture.snapshot)
        digest = hashlib.sha256(snapshot_data).hexdigest()
        fixture.run["snapshot"].update(sha256=digest, locator=blob_locator(
            fixture.production_id, digest, "application/json",
        ))
        (fixture.root / "snapshot.json").write_bytes(snapshot_data)
        (fixture.root / "run.json").write_bytes(canonical_json(fixture.run))
        (fixture.root / "asset-versions.json").write_bytes(canonical_json(versions))
        fixture.receipt.write_bytes(canonical_json(fixture.files()))

    assert admin(fixture.args()) == 0
    imported = json.loads(capsys.readouterr().out)
    assert imported["asset_versions"] == len(versions)
    assert imported["boards"] == 1
    run_id = fixture.run["id"]
    with owner_engine.connect() as conn:
        row = runs.get(conn, run_id)
        assert row["document"]["status"] == "succeeded"
        assert row["snapshot"] == fixture.snapshot
        assert row["frozen_library"] == versions
        assert row["document"]["outputs"] == fixture.run["outputs"]
        assert drafts.get_draft(conn, fixture.run["story_id"]).story.get("set") == fixture.snapshot["story"]["set"]
    with store.open(fixture.run["snapshot"]["locator"]) as handle:
        assert handle.read() == (fixture.root / "snapshot.json").read_bytes()
    for role, name in (("master", "final.mp4"), ("proxy", "proxy.mp4")):
        locator = blob_locator(fixture.production_id, fixture.run["outputs"][f"{role}_sha256"], "video/mp4")
        with store.open(locator) as handle:
            assert handle.read() == (fixture.root / name).read_bytes()
    _, auth = register_agent(owner_engine, {fixture.production_id: ["read", "runs:queue"]})
    with client(app) as browser:
        queued = browser.post(f'/v1/stories/{fixture.run["story_id"]}/runs', headers={
            **auth, "If-Match": str(fixture.snapshot["story"]["revision"]), "Idempotency-Key": "new-from-archive",
        })
    assert queued.status_code == 422, queued.text
    expected = "occlusion.unsupported" if declaring_set else "asset.recorded_without_media"
    assert queued.json()["error"]["code"] == expected
    with owner_engine.connect() as conn:
        assert [row["id"] for row in runs.list_story(conn, fixture.run["story_id"], None, 10)] == [run_id]


def test_delivery_identity_collision_rolls_back_new_rows_and_store(operator, service, owner_engine,
                                                                   tmp_path, capsys):
    _, store, _ = service
    first = make_archive(tmp_path / "first")
    assert admin(first.args()) == 0
    capsys.readouterr()
    another = make_archive(tmp_path / "another", delivery_id=first.delivery_id)
    before = file_paths(store)
    with owner_engine.connect() as conn:
        lane = conn.scalar(sa.select(run_lane.c.next_position))
    assert admin(another.args()) == 1
    assert capsys.readouterr().err.strip() == "import_production.identity_conflict"
    with owner_engine.connect() as conn:
        for table, identity in ((productions, another.production_id), (stories, another.run["story_id"]),
                                (run_rows, another.run["id"]), (asset_versions, another.asset["id"])):
            assert conn.scalar(sa.select(table.c.id).where(table.c.id == identity)) is None
        assert conn.scalar(sa.select(deliveries.c.run_id).where(deliveries.c.id == first.delivery_id)) == first.run["id"]
        assert conn.scalar(sa.select(run_lane.c.next_position)) == lane
    assert file_paths(store) == before


def test_queue_can_claim_and_enqueue_during_publication(operator, owner_engine, monkeypatch,
                                                        tmp_path, capsys):
    fixture = make_archive(tmp_path / "job")
    monkeypatch.setattr(runs, "database_time", Clock().db_time)
    with owner_engine.begin() as conn:
        production = drafts.create_production(conn, "Queue fixture", [], OPERATOR)
        drafts.enable_media_type(conn, production["id"], "short", production["revision"])
        draft = drafts.create_story(conn, production["id"], "short", {"title": "Queue draft"}, OPERATOR)
        existing = enqueue_fixture(conn, draft, "before-publication")

    publish = LocalStore.publish
    enqueued = []

    def slow_publish(self, source, *, scope, media_type, expected_sha256):
        class PausedCopy:
            sent_first_chunk = False

            def read(self, size):
                if not self.sent_first_chunk:
                    self.sent_first_chunk = True
                    return source.read(32)
                if not enqueued:
                    with owner_engine.begin() as other:
                        other.exec_driver_sql("SET LOCAL lock_timeout = '250ms'")
                        claim = runs.claim(other, "fixture-worker")
                        enqueued.append(enqueue_fixture(other, draft, "during-publication"))
                        assert claim is not None and claim["run"]["id"] == existing["id"]
                        assert other.scalar(sa.select(stories.c.id).where(
                            stories.c.id == fixture.run["story_id"])) is None
                return source.read(size)

        stream = source if enqueued else PausedCopy()
        return publish(self, stream, scope=scope, media_type=media_type, expected_sha256=expected_sha256)

    monkeypatch.setattr(LocalStore, "publish", slow_publish)
    assert admin(fixture.args()) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "imported"
    with owner_engine.connect() as conn:
        assert runs.get(conn, existing["id"])["document"]["status"] == "running"
        assert runs.get(conn, fixture.run["id"])["position"] == enqueued[0]["position"] + 1


def enqueue_fixture(conn, draft, key):
    return runs.enqueue(conn, snapshot={"story": draft.exchange()}, snapshot_sha256="f" * 64,
                        library=[], actor=OPERATOR, key=key, estimate={"estimate": None, "methods": []})


def test_same_archive_committed_during_publication_is_a_replay(
        operator, owner_engine, monkeypatch, tmp_path, capsys):
    fixture = make_archive(tmp_path / "job")
    publish = production_import._publish
    with owner_engine.connect() as conn:
        lane = conn.scalar(sa.select(run_lane.c.next_position))

    def publish_after_another_import(*args, **kwargs):
        with monkeypatch.context() as patch:
            patch.setattr(production_import, "_publish", publish)
            assert admin(fixture.args()) == 0
        return publish(*args, **kwargs)

    monkeypatch.setattr(production_import, "_publish", publish_after_another_import)
    assert admin(fixture.args()) == 0
    first, second = map(json.loads, capsys.readouterr().out.splitlines())
    assert first["status"] == "imported"
    assert second == {**first, "status": "already_imported"}
    with owner_engine.connect() as conn:
        assert conn.scalar(sa.select(run_lane.c.next_position)) == lane + 1


@pytest.mark.parametrize("window", ["during_publication", "after_final_check"])
def test_import_refuses_production_collision_after_initial_check(
        operator, service, owner_engine, monkeypatch, tmp_path, capsys, window):
    _, store, _ = service
    fixture = make_archive(tmp_path / "job")
    persist = production_import._persist
    publish = production_import._publish
    held = []

    def occupy_production():
        with owner_engine.begin() as other:
            other.exec_driver_sql("SET LOCAL lock_timeout = '250ms'")
            held.append(seed_matching_production(other, fixture))

    def publish_then_compete(*args, **kwargs):
        publish(*args, **kwargs)
        if window == "during_publication":
            occupy_production()

    def persist_with_race(*args, **kwargs):
        assert window == "after_final_check", "final identity check must refuse before insertion"
        occupy_production()
        persist(*args, **kwargs)

    monkeypatch.setattr(production_import, "_publish", publish_then_compete)
    monkeypatch.setattr(production_import, "_persist", persist_with_race)
    with owner_engine.connect() as conn:
        lane = conn.scalar(sa.select(run_lane.c.next_position))
    assert admin(fixture.args()) == 1
    assert capsys.readouterr().err.strip() == "import_production.identity_conflict"
    with owner_engine.connect() as conn:
        assert drafts.production(conn, fixture.production_id) == held[0]
        for table, identity in ((stories, fixture.run["story_id"]), (run_rows, fixture.run["id"]),
                                (deliveries, fixture.delivery_id), (asset_versions, fixture.asset["id"])):
            assert conn.scalar(sa.select(table.c.id).where(table.c.id == identity)) is None
        assert conn.scalar(sa.select(run_lane.c.next_position)) == lane
    assert len(list(Path(store.root).rglob("*.mp4"))) == 2


def test_runtime_role_refused(operator, runtime_db, service, owner_engine, monkeypatch, tmp_path, capsys):
    _, store, _ = service
    fixture = make_archive(tmp_path / "job")
    monkeypatch.setenv("STUDIO_MIGRATION_DATABASE_URL", runtime_db.url)
    assert admin(fixture.args()) == 1
    assert capsys.readouterr().err.strip() == "import_production.migration_role_required"
    with owner_engine.connect() as conn, pytest.raises(drafts.NotFound):
        drafts.production(conn, fixture.production_id)
    assert file_paths(store) == set()


def test_retry_after_store_failure(operator, service, owner_engine, monkeypatch, tmp_path, capsys):
    _, store, _ = service
    fixture = make_archive(tmp_path / "job")
    files = fixture.files()
    publish = LocalStore.publish

    def interrupted(self, source, *, scope, media_type, expected_sha256):
        if expected_sha256 == files["proxy.mp4"]["sha256"]:
            raise OSError("fixture stopped after publishing the master")
        return publish(self, source, scope=scope, media_type=media_type, expected_sha256=expected_sha256)

    with monkeypatch.context() as patch:
        patch.setattr(LocalStore, "publish", interrupted)
        assert admin(fixture.args()) == 1
    assert capsys.readouterr().err.strip() == "import_production.failed"
    assert len(list(Path(store.root).rglob("*.mp4"))) == 1
    with owner_engine.connect() as conn, pytest.raises(drafts.NotFound):
        drafts.production(conn, fixture.production_id)

    def publish_with_warning(self, source, *, scope, media_type, expected_sha256):
        blob = publish(self, source, scope=scope, media_type=media_type, expected_sha256=expected_sha256)
        if expected_sha256 == files["proxy.mp4"]["sha256"]:
            warnings.warn(StagingLeftoverWarning(f"temporary file left under {self.root}"), stacklevel=1)
        return blob

    with monkeypatch.context() as patch:
        patch.setattr(LocalStore, "publish", publish_with_warning)
        assert admin(fixture.args()) == 0
    result = capsys.readouterr()
    assert result.err == "" and store.root not in result.out
    assert json.loads(result.out)["status"] == "imported"
    assert json.loads(result.out)["staging_leftovers"] == 1
    assert len(list(Path(store.root).rglob("*.mp4"))) == 2
    assert fixture.files() == files


def test_in_place_media_change_after_archive_verification(
        operator, service, owner_engine, monkeypatch, tmp_path, capsys):
    _, store, _ = service
    fixture = make_archive(tmp_path / "job")
    publish = LocalStore.publish
    master = fixture.root / "final.mp4"
    original_inode = master.stat().st_ino
    original = master.read_bytes()
    changed = original[:-1] + bytes([original[-1] ^ 1])

    def change_then_publish(self, source, *, scope, media_type, expected_sha256):
        assert os.fstat(source.fileno()).st_ino == original_inode
        master.write_bytes(changed)
        assert master.stat().st_ino == original_inode
        return publish(self, source, scope=scope, media_type=media_type, expected_sha256=expected_sha256)

    with monkeypatch.context() as patch:
        patch.setattr(LocalStore, "publish", change_then_publish)
        assert admin(fixture.args()) == 1
    assert capsys.readouterr().err.strip() == "import_production.failed"
    assert not list(Path(store.root).rglob("*.mp4"))
    with owner_engine.connect() as conn, pytest.raises(drafts.NotFound):
        drafts.production(conn, fixture.production_id)
    master.write_bytes(original)
    assert admin(fixture.args()) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "imported"


def test_import_from_read_only_archive(operator, tmp_path, capsys):
    fixture = make_archive(tmp_path / "job")
    original = fixture.files()
    members = list(fixture.root.iterdir())
    modes = {path: stat.S_IMODE(path.stat().st_mode) for path in [fixture.root, *members]}
    try:
        for path, mode in modes.items():
            path.chmod(mode & ~0o222)
        assert admin(fixture.args()) == 0
        assert json.loads(capsys.readouterr().out)["status"] == "imported"
        assert fixture.files() == original
        assert all(stat.S_IMODE(path.stat().st_mode) == (mode & ~0o222) for path, mode in modes.items())
    finally:
        for path, mode in modes.items():
            path.chmod(mode)
