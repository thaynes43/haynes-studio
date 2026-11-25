"""Storage for immutable staging records and their version chains."""

import hashlib

import sqlalchemy as sa

from haynes_studio.canonical.ids import Minter
from haynes_studio.store import canonical_json

from .problems import NotFound
from .runs import actor_key
from .schema import archive_records as records
from .schema import archive_versions as versions

VERSION_FIELDS = tuple(column for column in versions.c
                       if column.name not in {"text", "request_key_sha256", "request_sha256"})
VERSION_METADATA = sa.select(*VERSION_FIELDS)


def production_records(conn, production_id, after, limit):
    newest = (sa.select(versions.c.id)
              .where(versions.c.record_id == records.c.id)
              .order_by(versions.c.number.desc()).limit(1).scalar_subquery())
    stmt = sa.select(records, newest.label("head_version_id")).where(records.c.production_id == production_id)
    if after is not None:
        stmt = stmt.where(records.c.id > after)
    return list(conn.execute(stmt.order_by(records.c.id).limit(limit)).mappings())


def _scoped_record(conn, stmt, production_ids):
    if production_ids is not None:
        stmt = stmt.where(records.c.production_id.in_(production_ids))
    row = conn.execute(stmt).mappings().one_or_none()
    if row is None:
        raise NotFound
    return row


def record(conn, record_id, production_ids=None):
    return _scoped_record(conn, sa.select(records).where(records.c.id == record_id), production_ids)


def head(conn, record_id):
    return conn.execute(VERSION_METADATA.where(versions.c.record_id == record_id)
                        .order_by(versions.c.number.desc()).limit(1)).mappings().one()


def history(conn, record_id, after, limit):
    stmt = VERSION_METADATA.where(versions.c.record_id == record_id)
    if after is not None:
        number = conn.scalar(sa.select(versions.c.number).where(
            versions.c.record_id == record_id, versions.c.id == after,
        ))
        if number is None:
            raise NotFound
        stmt = stmt.where(versions.c.number < number)
    return list(conn.execute(stmt.order_by(versions.c.number.desc()).limit(limit)).mappings())


def version_record(conn, version_id, production_ids=None):
    stmt = sa.select(records).join(versions).where(versions.c.id == version_id)
    return _scoped_record(conn, stmt, production_ids)


def version(conn, version_id):
    return conn.execute(VERSION_METADATA.add_columns(versions.c.text)
                        .where(versions.c.id == version_id)).mappings().one()


def ancestors(conn, version, stamped_ids):
    if not stamped_ids:
        return set()
    # Appends use the latest version as parent and increment its number under
    # the record lock. In that linear chain every lower number is an ancestor.
    return set(conn.scalars(sa.select(versions.c.id).where(
        versions.c.id.in_(stamped_ids), versions.c.record_id == version["record_id"],
        versions.c.number < version["number"],
    )))


def request_key(operation, target_id, principal, key):
    return hashlib.sha256(canonical_json([operation, target_id, actor_key(principal), key])).hexdigest()


def lock(conn, target):
    # Serialize a create retry or the append to a particular record. Key and
    # record locks are disjoint, and the chain needs no mutable head row.
    conn.execute(sa.select(sa.func.pg_advisory_xact_lock(
        sa.func.hashtextextended("studio.archive:" + target, 0))))


def previous_request(conn, key_hash):
    return conn.execute(VERSION_METADATA.add_columns(versions.c.request_sha256)
                        .where(versions.c.request_key_sha256 == key_hash)).mappings().one_or_none()


def create_record(conn, production_id, kind, title):
    return conn.execute(records.insert().values(
        id=Minter().mint("arc"), production_id=production_id, kind=kind, title=title,
    ).returning(records)).mappings().one()


def append(conn, record_id, *, number, previous, payload, data, principal, key_hash, request_hash):
    return conn.execute(versions.insert().values(
        id=Minter().mint("arv"), record_id=record_id, number=number, revises_version_id=previous,
        **payload, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), written_by=principal,
        written_at=sa.func.clock_timestamp(), request_key_sha256=key_hash, request_sha256=request_hash,
    ).returning(*VERSION_FIELDS)).mappings().one()
