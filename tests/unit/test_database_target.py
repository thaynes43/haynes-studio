"""The db fixture's target checks run without a database."""

from __future__ import annotations

import pytest

from tests.support import database


@pytest.mark.parametrize("url", [
    "postgresql://postgres@localhost:5432/studio_test",
    "postgresql://postgres@localhost/studio_test_ci",
    "host=localhost dbname=studio_test_424 user=postgres",
])
def test_accepts_disposable_test_databases(url):
    assert database.check_url(url).startswith("studio_test")


@pytest.mark.parametrize(("url", "reason"), [
    ("postgresql://postgres@localhost:5432/postgres", "does not start with 'studio_test'"),
    ("postgresql://postgres@postgres16-rw.database.svc/studio", "does not start with"),
    ("postgresql://postgres@localhost/studiotest", "does not start with"),
    ("postgresql://postgres@localhost:5432/", "names no database"),
    ("host=localhost user=postgres", "names no database"),
    ("not a conninfo string with secret=hunter22", "not a valid connection string"),
])
def test_refuses_anything_else(url, reason):
    with pytest.raises(database.RefusedTarget, match=reason) as refused:
        database.check_url(url)
    assert "hunter22" not in str(refused.value)


def test_schema_names_are_fresh_and_checked():
    names = {database.new_schema_name() for _ in range(3)}
    assert len(names) == 3
    for name in names:
        database.check_schema_name(name)
        assert len(name) <= 63
    with pytest.raises(database.RefusedTarget):
        database.check_schema_name("public")


def test_repr_never_shows_the_url():
    target = database.StudioTestDatabase(
        dbname="studio_test", schema="studio_test_0123456789abcdef",
        url="postgresql://u:hunter22@h/studio_test",
    )
    assert "hunter22" not in repr(target)
