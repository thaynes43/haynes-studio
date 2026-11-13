"""db suite smoke: write and read back a row in the session's own schema."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.db


def test_round_trip(db_conn, studio_db):
    assert db_conn.info.dbname.startswith("studio_test")
    assert db_conn.execute("SELECT current_schema()").fetchone() == (studio_db.schema,)
    db_conn.execute("CREATE TABLE smoke (id integer PRIMARY KEY, label text NOT NULL)")
    db_conn.execute("INSERT INTO smoke (id, label) VALUES (%s, %s)", (1, "round trip"))
    assert db_conn.execute("SELECT label FROM smoke WHERE id = %s", (1,)).fetchall() == [
        ("round trip",)
    ]
    found = db_conn.execute(
        "SELECT table_schema FROM information_schema.tables WHERE table_name = 'smoke'"
    ).fetchall()
    assert found == [(studio_db.schema,)]


def test_server_is_postgres_16(db_conn):
    assert db_conn.info.server_version // 10000 == 16
