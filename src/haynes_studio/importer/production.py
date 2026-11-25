"""Migration-role import of a finished production into the API database and store."""

import json
import os
from pathlib import Path
import sys
import warnings

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from haynes_studio.build.validate import validate_run
from haynes_studio.canonical.jsonvalues import normalize
from haynes_studio.db import catalog, drafts, runs
from haynes_studio.db.engine import connect_engine
from haynes_studio.db.problems import NotFound, require_valid
from haynes_studio.db.schema import deliveries, run_lane
from haynes_studio.db.schema import runs as run_rows
from haynes_studio.errors import ContractError
from haynes_studio.store import MISMATCH, PRESENT, LocalStore, StagingLeftoverWarning, StoreError

from .production_archive import Archive, ImportProblem, verify_archive

IMPORT_ACTOR = "studio.archive_import"

def add_arguments(parser) -> None:
    parser.add_argument("archive", type=Path, metavar="ARCHIVE")
    parser.add_argument("--receipt", required=True, type=Path, metavar="FILE",
                        help="Independent JSON inventory of archive member sizes and SHA-256 hashes")
    parser.add_argument("--name", required=True, help="Production name")
    parser.add_argument("--media-type", required=True, choices=sorted(drafts.MEDIA_KINDS))
    parser.add_argument("--recovered", action="store_true",
                        help="Use the five-file recovery layout with no original snapshot")


def _require_migrator(conn: sa.Connection) -> None:
    # Revision 0003's API role already has many of the same DML grants. Restrict
    # this offline command to the migration identity by checking schema ownership.
    if not conn.scalar(sa.text("""
        SELECT nspowner = current_user::regrole
        FROM pg_namespace
        WHERE nspname = current_schema()
    """)):
        raise ImportProblem("migration_role_required")


def _production(archive: Archive, name: str, kind: str) -> dict:
    story = archive.story
    aspect, width, height = drafts.MEDIA_KINDS[kind]
    return {
        "schema": "studio.production/v1", "id": archive.production_id, "revision": 1,
        "name": name, "labels": [], "created_by": story["created_by"],
        "created_at": story["created_at"], "updated_at": story["created_at"],
        "media_types": [{
            "kind": kind, "aspect": aspect, "width": width, "height": height, "fps": 24,
            "enabled_at": story["created_at"],
        }],
    }


def _check_production(conn: sa.Connection, expected: dict) -> None:
    try:
        current = drafts.production(conn, expected["id"])
    except NotFound:
        return
    want = expected["media_types"][0]
    profile = next((item for item in current["media_types"] if item["kind"] == want["kind"]), None)
    if (current["name"] != expected["name"] or profile is None
            or any(profile[key] != want[key] for key in ("aspect", "width", "height", "fps"))):
        raise ImportProblem("identity_conflict")


def _draft_document(archive: Archive) -> dict:
    # import_draft stores the canonical editable fields and derives the views
    # on read. The frozen snapshot itself is kept verbatim.
    story = normalize(archive.story)
    story.pop("derived", None)
    for board in story["boards"]:
        board.pop("derived", None)
    return story


def _imported_run(archive: Archive, imported_at: str) -> dict:
    return {**archive.run, "provenance": {
        **archive.run["provenance"], "archive_import": {**archive.marker, "imported_at": imported_at},
    }}


def _already_imported(conn: sa.Connection, archive: Archive, row) -> bool:
    if row is None:
        return False
    run = row["document"]
    mark = (run.get("provenance") or {}).get("archive_import")
    if (not isinstance(mark, dict) or "imported_at" not in mark
            or run != _imported_run(archive, mark["imported_at"])
            or row["production_id"] != archive.production_id
            or row["story_id"] != archive.story["id"]
            or row["number"] != run["number"]
            or row["idempotency_actor"] != IMPORT_ACTOR
            or row["idempotency_key"] != run["id"]
            or row["snapshot"] != archive.snapshot
            or row["frozen_library"] != archive.versions):
        raise ImportProblem("identity_conflict")
    delivery = conn.execute(sa.select(deliveries.c.story_id, deliveries.c.document).where(
        deliveries.c.run_id == run["id"],
    )).one_or_none()
    if delivery is None or delivery.story_id != row["story_id"] or delivery.document != archive.delivery:
        raise ImportProblem("identity_conflict")
    return True


def _persist(conn: sa.Connection, archive: Archive, production: dict) -> None:
    story = _draft_document(archive)
    # The trusted import takes its usual advisory locks and also handles an
    # existing story with the same source key. Compare under those locks.
    draft = drafts.import_draft(conn, production, story, archive.versions)
    _check_production(conn, production)
    if draft.exchange() != story:
        raise ImportProblem("identity_conflict")
    # import_draft returns an existing draft intact. Register its pins as well,
    # with the catalog's immutable identity and scope checks.
    for version in sorted(archive.versions, key=lambda item: (item["asset_id"], item["number"])):
        catalog.record_asset_version(conn, version)

    # Allocate from the same lane as enqueue, after locking the story. A
    # terminal run gets a pagination position but no claim or Wan attempts.
    position = conn.scalar(sa.select(run_lane.c.next_position).with_for_update())
    if position is None:
        raise ImportProblem("schema_required")
    document = _imported_run(archive, runs.timestamp(runs.database_time(conn)))
    require_valid(validate_run(document))
    conn.execute(run_rows.insert().values(
        id=document["id"], story_id=story["id"], production_id=archive.production_id,
        number=document["number"], position=position, idempotency_actor=IMPORT_ACTOR,
        idempotency_key=document["id"], snapshot=archive.snapshot, frozen_library=archive.versions,
        estimate_methods=[], document=document,
    ))
    conn.execute(run_lane.update().values(next_position=position + 1))
    catalog.record_delivery(conn, story["id"], archive.delivery)


def _store_for(archive: Archive, root: Path) -> LocalStore:
    root = root.resolve()
    targets = [root, root / ".staging", *(root / p for p, _ in archive.publications.values())]
    if any(target.is_relative_to(archive.directory) for target in targets):
        raise ImportProblem("store_overlaps_archive")
    return LocalStore(root)


def _publish(store: LocalStore, archive: Archive, *, replay: bool) -> None:
    publications = archive.publications
    for member, (locator, _) in publications.items():
        state = store.verify(locator, archive.receipt[member]["sha256"])
        if state == MISMATCH:
            raise ImportProblem("store_conflict", member)
        if replay and state != PRESENT:
            raise ImportProblem("store_missing", member)
    if replay:
        return
    for member, (locator, media_type) in publications.items():
        source, facts = archive.members[member], archive.receipt[member]
        source.seek(0)
        blob = store.publish(source, scope=archive.production_id, media_type=media_type,
                             expected_sha256=facts["sha256"])
        if blob.locator != locator or blob.bytes != facts["bytes"]:
            raise ImportProblem("store_conflict", member)


def _import(conn: sa.Connection, archive: Archive, root: Path, name: str, kind: str) -> bool:
    _require_migrator(conn)
    # Serialize repeats before inspecting the run. The draft helper separately
    # serializes story/production imports and the lane orders concurrent enqueues.
    run_id = archive.run["id"]
    conn.execute(sa.select(sa.func.pg_advisory_xact_lock(sa.func.hashtextextended(run_id, 957))))
    row = conn.execute(sa.select(run_rows).where(run_rows.c.id == run_id)).mappings().one_or_none()
    replay = _already_imported(conn, archive, row)
    production = _production(archive, name, kind)
    _check_production(conn, production)
    store = _store_for(archive, root)
    if not replay:
        _persist(conn, archive, production)
    # Complete all DB identity checks first. The transaction becomes visible
    # only after the create-only blobs are durable.
    _publish(store, archive, replay=replay)
    return replay


def run(options) -> int:
    """Return a redacted machine-readable result after committing the import."""
    dsn = os.getenv("STUDIO_MIGRATION_DATABASE_URL")
    root = os.getenv("STUDIO_STORE_ROOT")
    engine = None
    try:
        if not dsn:
            raise ImportProblem("migration_dsn_required")
        if not root:
            raise ImportProblem("store_root_required")
        with verify_archive(options.archive, options.receipt, name=options.name, kind=options.media_type,
                            recovered=options.recovered) as archive:
            engine = connect_engine(dsn, os.getenv("STUDIO_DATABASE_SCHEMA", "studio"))
            # A completed publish may warn about its staging name. Report only
            # the count so the CLI never exposes a destination path.
            with warnings.catch_warnings(record=True) as notices, engine.begin() as conn:
                warnings.simplefilter("always", StagingLeftoverWarning)
                replay = _import(conn, archive, Path(root), options.name, options.media_type)
            result = {
                "status": "already_imported" if replay else "imported",
                "production_id": archive.production_id, "story_id": archive.story["id"],
                "run_id": archive.run["id"], "delivery_id": archive.delivery["id"],
                "boards": len(archive.story["boards"]), "asset_versions": len(archive.versions),
                "files": len(archive.receipt), "bytes": sum(f["bytes"] for f in archive.receipt.values()),
                "media": {role: {key: archive.delivery[role][key] for key in ("sha256", "bytes")}
                          for role in ("master", "proxy")},
            }
            leftovers = sum(issubclass(notice.category, StagingLeftoverWarning) for notice in notices)
            if leftovers:
                result["staging_leftovers"] = leftovers
    except ImportProblem as error:
        print(str(error), file=sys.stderr)
        return 1
    except (IntegrityError, NotFound, ContractError):
        print("import_production.identity_conflict", file=sys.stderr)
        return 1
    except (SQLAlchemyError, StoreError, OSError, ValueError, RecursionError):
        print("import_production.failed", file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    print(json.dumps(result, separators=(",", ":")))
    return 0
