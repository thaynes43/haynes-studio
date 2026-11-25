"""Append-only format and version records in caller-owned transactions."""

from dataclasses import replace

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from haynes_studio.canonical.ids import Minter
from haynes_studio.canonical.jsonvalues import normalize
from haynes_studio.db.problems import NotFound, require_valid
from haynes_studio.db.schema import format_versions, formats
from haynes_studio.delivery.model import MASTER_SIZES
from haynes_studio.errors import Violation

from .recipe import PIN_PATH, recipe_hash, validate_recipe


def _insert_version(conn: sa.Connection, format_id: str, number: int, recipe: dict) -> dict:
    version = {"id": Minter().mint("fmv"), "format_id": format_id, "number": number,
               "recipe": recipe, "sha256": recipe_hash(recipe)}
    conn.execute(format_versions.insert().values(**version))
    return version


def _validated_recipe(recipe: dict, path: str = "") -> dict:
    document = normalize(recipe)
    require_valid(replace(issue, path=path + issue.path) for issue in validate_recipe(document))
    return document


def create(conn: sa.Connection, format_id: str, name: str, recipe: dict) -> dict | None:
    recipe = _validated_recipe(recipe, "/recipe")
    inserted = conn.scalar(insert(formats).values(id=format_id, name=name)
                           .on_conflict_do_nothing().returning(formats.c.id))
    if inserted is None:
        return None
    return _insert_version(conn, format_id, 1, recipe)


def add_version(conn: sa.Connection, format_id: str, recipe: dict) -> dict:
    recipe = _validated_recipe(recipe)
    # Serialize appends per format in READ COMMITTED, without granting UPDATE to the app.
    conn.execute(sa.select(sa.func.pg_advisory_xact_lock(sa.func.hashtextextended(format_id, 447))))
    if conn.scalar(sa.select(formats.c.id).where(formats.c.id == format_id)) is None:
        raise NotFound
    latest = conn.scalar(sa.select(sa.func.max(format_versions.c.number)).where(
        format_versions.c.format_id == format_id,
    ))
    return _insert_version(conn, format_id, latest + 1, recipe)


def list_formats(conn: sa.Connection, after: str | None, limit: int) -> list[dict]:
    query = sa.select(formats)
    if after is not None:
        query = query.where(formats.c.id > after)
    return [dict(row) for row in conn.execute(query.order_by(formats.c.id).limit(limit)).mappings()]


def list_versions(conn: sa.Connection, format_id: str, after: str | None, limit: int) -> list[dict]:
    if conn.scalar(sa.select(formats.c.id).where(formats.c.id == format_id)) is None:
        raise NotFound
    table = format_versions.c
    query = sa.select(table.id, table.format_id, table.number, table.sha256).where(
        table.format_id == format_id,
    )
    if after is not None:
        query = query.where(table.id > after)
    return [dict(row) for row in conn.execute(query.order_by(table.id).limit(limit)).mappings()]


def version(conn: sa.Connection, id_: str | None) -> dict | None:
    if id_ is None:
        return None
    row = conn.execute(sa.select(format_versions).where(format_versions.c.id == id_)).mappings().one_or_none()
    return None if row is None else dict(row)


def require_pin(conn: sa.Connection, id_: str | None, media_kind: str) -> None:
    if id_ is None:
        return
    pinned = version(conn, id_)
    if pinned is None:
        require_valid([Violation("ref.unknown", PIN_PATH, "That format version does not exist")])
    frame = pinned["recipe"]["frame"]
    if (frame["width"], frame["height"]) != MASTER_SIZES[media_kind]:
        require_valid([Violation("format.frame_mismatch", PIN_PATH,
                                 "That format's frame size does not match the story's media kind")])
