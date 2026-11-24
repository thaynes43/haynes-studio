"""Runtime connection pool and isolated transactions."""

import re
from contextlib import contextmanager

import psycopg
import sqlalchemy as sa


def connect_engine(dsn: str, schema: str = "studio") -> sa.Engine:
    if not re.fullmatch(r"[a-z_][a-z_0-9]{0,62}", schema):
        raise ValueError("STUDIO_DATABASE_SCHEMA must be a lower-case PostgreSQL identifier")
    if not dsn.strip():
        raise ValueError("A PostgreSQL connection string is required")
    return sa.create_engine(
        "postgresql+psycopg://",
        creator=lambda: psycopg.connect(
            dsn, connect_timeout=5, options=f"-c search_path={schema} -c statement_timeout=30000",
        ),
        hide_parameters=True, pool_pre_ping=True, pool_size=4, max_overflow=0, pool_timeout=5,
    )


@contextmanager
def snapshot(engine: sa.Engine):
    """Use one Postgres snapshot for reads spanning several tables."""
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
        with conn.begin():
            yield conn
