"""Exercise the import CLI, real PostgreSQL grants and the real media API."""

import hashlib
import json
from pathlib import Path
from dataclasses import replace
import warnings

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest
import sqlalchemy as sa

from haynes_studio.api.key_admin import run as admin
from haynes_studio.api.oidc import random_secret
from haynes_studio.db import drafts, runs
from haynes_studio.db.engine import connect_engine
from haynes_studio.db.migrate import migrate
from haynes_studio.db.schema import asset_versions, deliveries, productions, run_lane, stories
from haynes_studio.db.schema import runs as run_rows
from haynes_studio.store import LocalStore, StagingLeftoverWarning
from tests.db.test_studio_api import (
    client, engine, new_production, register_agent, runtime_role, service, sign_in,
)
from tests.importer.production_fixture import NAME, make_archive
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
    with client(app) as owner:
        other = new_production(owner, sign_in(owner, issuer))
    _, headers = register_agent(owner_engine, {fixture.production_id: ["read"]})
    _, wrong = register_agent(owner_engine, {other: ["read"]})
    production = browser.get(f'/v1/productions/{result["production_id"]}', headers=headers)
    assert production.status_code == 200 and production.json()["name"] == NAME
    source = browser.get(f'/v1/stories/{result["story_id"]}', headers=headers)
    assert source.status_code == 200
    assert len(source.json()["board_order"]) == result["boards"]
    run = browser.get(f'/v1/runs/{result["run_id"]}', headers=headers)
    assert run.status_code == 200
    doc = run.json()
    marker = doc["provenance"]["archive_import"]
    assert doc["status"] == "succeeded" and doc["number"] == fixture.run["number"]
    assert doc["snapshot"] == fixture.run["snapshot"]
    assert marker["source_directory"] == fixture.root.name and marker["imported_at"].endswith("Z")
    assert marker["source_kind"] == ("recovered" if recovered else "canonical")
    response = browser.get(f'/v1/runs/{result["run_id"]}/delivery', headers=headers)
    assert response.status_code == 200
    delivery = response.json()
    for role, name in (("master", "final.mp4"), ("proxy", "proxy.mp4")):
        assert {k: delivery[role][k] for k in ("sha256", "bytes")} == before[name]
        assert_private_ranges(browser, headers, wrong, delivery[role], (fixture.root / name).read_bytes())
    if not recovered:
        asset = browser.get(f'/v1/assets/{fixture.asset["asset_id"]}', headers=headers).json()
        assert asset["versions"] == [fixture.asset]
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
