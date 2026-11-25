"""CR-18 uniqueness, including Postgres contention and pre-existing collisions."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg
import pytest
import sqlalchemy as sa
from psycopg import sql

from haynes_studio.canonical.ids import Minter
from haynes_studio.db.engine import connect_engine
from haynes_studio.db.migrate import migrate
from haynes_studio.db.schema import draft_names, media_types, productions, stories
from tests.db.test_studio_api import (
    client, engine, new_production, owner_engine, runtime_db, runtime_role, service, sign_in,
)
from tests.support.database import new_schema_name

pytestmark = pytest.mark.db


@pytest.mark.parametrize("entity", ["production", "story"])
def test_concurrent_create_refuses_duplicate_with_winners_id(service, engine, entity):
    app, _, issuer = service
    browsers = [client(app), client(app)]
    headers = [sign_in(browser, issuer) for browser in browsers]
    if entity == "production":
        path, field, inserted = "/v1/productions", "name", "productions"
    else:
        production = new_production(browsers[0], headers[0])
        path, field, inserted = f"/v1/productions/{production}/media-types/short/stories", "title", "stories"
    barrier = Barrier(2)

    def on_insert(conn, cursor, statement, params, context, executemany):
        if statement.startswith(f"INSERT INTO {inserted} "):
            barrier.wait(timeout=10)

    sa.event.listen(engine, "before_cursor_execute", on_insert)
    try:
        suffix = "- " + Minter().mint("prd")
        titles = ["\ufeff  CAFE\u0301 ΟΣ " + suffix + "\xa0", "café ος " + suffix]
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(browser.post, path, headers=csrf, json={field: title})
                       for browser, csrf, title in zip(browsers, headers, titles, strict=True)]
            results = [future.result(timeout=15) for future in futures]
    finally:
        sa.event.remove(engine, "before_cursor_execute", on_insert)
    accepted, refusal = sorted(results, key=lambda response: response.status_code)
    assert accepted.status_code == 201 and refusal.status_code == 409, [r.text for r in results]
    error = refusal.json()["error"]
    assert error["code"] == f"{entity}.{field}_duplicate"
    assert error["path"] == f"/{field}" and error["existing_entity_id"] == accepted.json()["id"]


def test_title_scope_and_conflicting_edit(service):
    app, _, issuer = service
    browser = client(app)
    csrf = sign_in(browser, issuer)
    first, other = [new_production(browser, csrf) for _ in range(2)]
    response = browser.put(f"/v1/productions/{first}/media-types/video", headers={**csrf, "If-Match": "2"})
    assert response.status_code == 200

    def create(production, kind, title):
        response = browser.post(f"/v1/productions/{production}/media-types/{kind}/stories",
                                headers=csrf, json={"title": title})
        assert response.status_code == 201, response.text
        return response.json()["id"]

    existing = create(first, "short", "Á Test")
    create(other, "short", "Á Test")
    create(first, "video", "Á Test")
    edited = create(first, "short", "Distinct")
    response = browser.patch(f"/v1/stories/{edited}", headers={**csrf, "If-Match": "1"},
                             json={"title": " a\u0301 TEST "})
    assert response.status_code == 409
    assert response.json()["error"]["existing_entity_id"] == existing
    assert browser.get(f"/v1/stories/{edited}").json()["title"] == "Distinct"
    move = browser.patch(f"/v1/stories/{existing}", headers={**csrf, "If-Match": "1"},
                         json={"title": "Moved"})
    assert move.status_code == 200
    create(first, "short", "Á Test")


def test_migration_retains_reports_and_reserves_every_existing_collision(studio_db, caplog):
    name = new_schema_name()
    with psycopg.connect(studio_db.url) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
    engine = connect_engine(studio_db.url, name)
    pair = sorted(Minter().mint("prd") for _ in range(2))
    colliding_titles = sorted(Minter().mint("sty") for _ in range(2))
    try:
        migrate(engine, target="0003_studio_run_queue")
        with engine.begin() as conn:
            for id_, display in zip(pair, [" Trimmed ", "TRIMMED"], strict=True):
                conn.execute(productions.insert().values(id=id_, document={"name": display}))
            conn.execute(media_types.insert().values(production_id=pair[0], kind="short", document={}))
            for id_, display in zip(colliding_titles, [" TeSt ", "test"], strict=True):
                conn.exec_driver_sql("INSERT INTO stories (id, production_id, media_kind, document) "
                                     "VALUES (%s, %s, 'short', jsonb_build_object('title', %s::text))",
                                     (id_, pair[0], display))
        migrate(engine)
        messages = caplog.text
        assert "retained duplicate production names" in messages
        assert "retained duplicate story (" in messages
        assert all(id_ in messages for id_ in [*pair, *colliding_titles])
        with engine.begin() as conn:
            assert list(conn.scalars(sa.select(productions.c.document["name"].astext)
                                     .order_by(productions.c.id))) == [" Trimmed ", "TRIMMED"]
            assert list(conn.scalars(sa.select(stories.c.document["title"].astext)
                                     .order_by(stories.c.id))) == [" TeSt ", "test"]
            conn.execute(productions.update().where(productions.c.id == pair[0]).values(
                document={"name": "Moved"}))
            assert conn.scalar(sa.select(draft_names.c.entity_ids).where(
                draft_names.c.name_key == "trimmed")) == [pair[1]]
        with pytest.raises(sa.exc.IntegrityError) as conflict, engine.begin() as conn:
            conn.execute(productions.insert().values(id=Minter().mint("prd"), document={"name": "trimmed"}))
        assert conflict.value.orig.diag.message_detail == pair[1]
        with engine.begin() as conn:
            conn.execute(productions.delete().where(productions.c.id == pair[1]))
            conn.execute(productions.insert().values(id=Minter().mint("prd"), document={"name": "trimmed"}))
    finally:
        engine.dispose()
        with psycopg.connect(studio_db.url) as admin:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))
