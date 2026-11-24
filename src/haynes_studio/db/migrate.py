"""Alembic entry point for a one-shot migration Job."""

import argparse
import os
import re
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import SQLAlchemyError

from .engine import connect_engine


def migrate(engine: sa.Engine, direction: str = "upgrade", target: str = "head",
            *, runtime_role: str | None = None) -> None:
    if runtime_role is not None and not re.fullmatch(r"[a-z_][a-z_0-9]{0,62}", runtime_role):
        raise ValueError("STUDIO_RUNTIME_ROLE must be a lower-case PostgreSQL identifier")
    action = {"upgrade": command.upgrade, "downgrade": command.downgrade}[direction]
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).with_name("migrations")))
    config.attributes["runtime_role"] = runtime_role
    with engine.begin() as conn:
        # Serialize migration Jobs on the same database, including the first revision.
        conn.execute(sa.text("SELECT pg_advisory_xact_lock(737409)"))
        config.attributes["connection"] = conn
        action(config, target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("direction", choices=("upgrade",))
    parser.add_argument("target", choices=("head",))
    parser.parse_args()
    dsn = os.getenv("STUDIO_MIGRATION_DATABASE_URL")
    if not dsn:
        parser.error("STUDIO_MIGRATION_DATABASE_URL is required")
    engine = connect_engine(dsn, os.getenv("STUDIO_DATABASE_SCHEMA", "studio"))
    try:
        migrate(engine, runtime_role=os.getenv("STUDIO_RUNTIME_ROLE"))
    except ValueError as error:
        parser.error(str(error))
    except (SQLAlchemyError, OSError) as error:
        parser.exit(1, f"Migration failed ({type(error).__name__})\n")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
