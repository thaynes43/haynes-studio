"""Target checks for the disposable Postgres fixture.

The fixture may only ever touch a database whose name starts with ``studio_test``,
so it cannot reach ``database/postgres16``. The name is checked twice: in the URL
before connecting, and on the open connection before the first statement. The
fixture creates one fresh schema per session and drops only that schema.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field

URL_ENV = "STUDIO_TEST_DATABASE_URL"
DATABASE_PREFIX = "studio_test"
SCHEMA_PREFIX = "studio_test_"
SKIP_REASON = (
    f"db: {URL_ENV} is unset; the db suite needs a disposable PostgreSQL 16 database "
    f"whose name starts with {DATABASE_PREFIX} (docs/process/testing.md)"
)
_SCHEMA_NAME = re.compile(rf"^{SCHEMA_PREFIX}[0-9a-f]{{16}}$")


class RefusedTarget(Exception):
    """The URL or connection is not a disposable studio test database."""


@dataclass(frozen=True)
class StudioTestDatabase:
    """The session's database target. The URL never appears in its repr."""

    dbname: str
    schema: str
    url: str = field(repr=False)


def check_url(url: str) -> str:
    """Return the database name in url, or raise RefusedTarget. Never echoes the URL."""
    from psycopg.conninfo import conninfo_to_dict

    try:
        params = conninfo_to_dict(url)
    except Exception:
        raise RefusedTarget(f"{URL_ENV} is not a valid connection string") from None
    dbname = params.get("dbname")
    if not dbname:
        raise RefusedTarget(
            f"{URL_ENV} names no database; libpq would fall back to PGDATABASE or the "
            "user name, so the fixture refuses it"
        )
    check_dbname(str(dbname))
    return str(dbname)


def check_dbname(dbname: str) -> None:
    if not dbname.startswith(DATABASE_PREFIX):
        raise RefusedTarget(
            f"database {dbname!r} does not start with {DATABASE_PREFIX!r}; "
            "the db fixture only touches disposable test databases"
        )


def check_connection(conn) -> None:
    """Re-check the database the server actually connected to (no statement sent)."""
    check_dbname(conn.info.dbname)


def new_schema_name() -> str:
    return SCHEMA_PREFIX + secrets.token_hex(8)


def check_schema_name(name: str) -> None:
    if not _SCHEMA_NAME.match(name):
        raise RefusedTarget(f"schema {name!r} is not a fixture schema")
