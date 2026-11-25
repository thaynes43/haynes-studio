"""Canonical library and delivery persistence and the media authorization index."""

from collections.abc import Collection, Iterable

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from haynes_studio.delivery.model import MASTER_SIZES
from haynes_studio.delivery.validate import validate_delivery
from haynes_studio.errors import ContractError, Violation
from haynes_studio.library.library import Library
from haynes_studio.library.model import Asset, AssetVersion, CANDIDATE, PROMOTED, version_document
from haynes_studio.library.validate import validate_asset, validate_asset_version
from haynes_studio.store.layout import blob_locator, is_sha256, parse_locator

from .problems import NotFound, require_valid
from .schema import (
    asset_media, asset_sources, asset_versions, assets, boards, deliveries, delivery_media,
    stories, story_asset_refs,
)

# None is the human actor's access to every production.
ProductionScope = Collection[str] | None


def _in_scope(column, productions: ProductionScope):
    return sa.true() if productions is None else column.in_(productions)


def _catalog_scope(productions: ProductionScope):
    if productions is None:
        return sa.true()
    if not productions:
        return sa.false()
    return sa.or_(assets.c.production_id.is_(None), assets.c.production_id.in_(productions))


def _joined_versions():
    return sa.select(asset_versions.c.document, assets.c.document.label("asset")).join_from(
        asset_versions, assets, asset_versions.c.asset_id == assets.c.id,
    )


def _version(row):
    return version_document(AssetVersion.from_document(row.document),
                            Asset.from_document(row.asset))


def load_library(conn: sa.Connection, version_ids: Collection[str], production_id: str) -> Library:
    if not version_ids:
        return Library()
    rows = conn.execute(_joined_versions().where(
        _catalog_scope({production_id}), asset_versions.c.id.in_(version_ids),
        asset_versions.c.state != CANDIDATE,
    ))
    return Library.from_version_documents(_version(row) for row in rows)


def find_assets(conn: sa.Connection, allowed: ProductionScope, *, kind: str | None,
                labels: list[str], production_id: str | None, version_ids: Collection[str] | None,
                after: str | None, limit: int) -> list[dict]:
    stmt = _joined_versions().where(_catalog_scope(allowed), asset_versions.c.state != CANDIDATE)
    if kind is not None:
        stmt = stmt.where(assets.c.kind == kind)
    if labels:
        stmt = stmt.where(assets.c.labels.contains(labels))
    if production_id is not None:
        stmt = stmt.where(_catalog_scope({production_id}))
    if version_ids is not None:
        stmt = stmt.where(asset_versions.c.id.in_(version_ids))
    if after is not None:
        stmt = stmt.where(asset_versions.c.id > after)
    return [_version(row) for row in
            conn.execute(stmt.order_by(asset_versions.c.id).limit(limit))]


def get_asset(conn: sa.Connection, id_: str, allowed: ProductionScope, *,
              after: str | None, limit: int) -> tuple[dict, list[dict]]:
    asset = conn.scalar(sa.select(assets.c.document).where(
        assets.c.id == id_, _catalog_scope(allowed),
    ))
    if asset is None:
        raise NotFound
    stmt = _joined_versions().where(assets.c.id == id_, asset_versions.c.state != CANDIDATE)
    visible = conn.scalar(sa.select(sa.exists().where(
        asset_versions.c.asset_id == id_, asset_versions.c.state != CANDIDATE,
    )))
    if not visible:
        raise NotFound
    if after is not None:
        stmt = stmt.where(asset_versions.c.id > after)
    return asset, [_version(row) for row in
                   conn.execute(stmt.order_by(asset_versions.c.id).limit(limit))]


def _scope_error(path: str, message: str) -> ContractError:
    return ContractError("<catalog>", [Violation("asset.scope_mismatch", path, message)])


def _check_asset_scope(conn: sa.Connection, asset: Asset) -> None:
    scope = asset.scope
    if scope.story_id is not None:
        production = conn.scalar(sa.select(stories.c.production_id).where(
            stories.c.id == scope.story_id,
        ))
        if production is None or production != scope.production_id:
            raise _scope_error("/scope/story_id", "The story belongs to another production")
    if scope.board_id is not None:
        story = conn.scalar(sa.select(boards.c.story_id).where(boards.c.id == scope.board_id))
        if story is None or story != scope.story_id:
            raise _scope_error("/scope/board_id", "The board belongs to another story")


def record_asset_version(conn: sa.Connection, document: dict, *, asset: Asset | None = None,
                         received_sha256: str | None = None) -> None:
    """Register a canonical version inside the caller's transaction.

    The caller uses the library's import or creation rules to choose version identity
    and publishes bytes through the canonical store. A repeated exact record is safe.
    For D42 the server records the received-byte digest alongside the canonical
    digest of the stored, stripped content. Legacy uploads may have only the latter.
    """
    require_valid(validate_asset_version(document))
    version = AssetVersion.from_document(document)
    if received_sha256 is not None and (
        version.kind != "photo" or version.origin != "uploaded" or not is_sha256(received_sha256)
    ):
        raise ContractError("<catalog>", [Violation(
            "schema.invalid", "/received_sha256", "Expected the original hash of an uploaded photo",
        )])
    asset = asset or Asset.from_version_document(document)
    require_valid(validate_asset(asset.to_document()))
    if version_document(version, asset) != document:
        raise _scope_error("/asset_id", "The joined asset and version fields disagree")
    _check_asset_scope(conn, asset)
    scope = asset.scope
    conn.execute(insert(assets).values(
        id=asset.id, production_id=scope.production_id, story_id=scope.story_id,
        board_id=scope.board_id, kind=asset.kind, labels=list(asset.labels),
        document=asset.to_document(),
    ).on_conflict_do_nothing(index_elements=[assets.c.id]))
    # Version-number allocation/registration is serialized per asset even when
    # multiple writers are adding versions to an established asset.
    conn.execute(sa.select(sa.func.pg_advisory_xact_lock(sa.func.hashtextextended(asset.id, 411))))
    held = conn.scalar(sa.select(assets.c.document).where(assets.c.id == asset.id))
    if version_document(version, Asset.from_document(held)) != document:
        raise _scope_error("/asset_id", "The version disagrees with the stored asset")
    if version.source_key is not None:
        conn.execute(insert(asset_sources).values(source_key=version.source_key, asset_id=asset.id)
                     .on_conflict_do_nothing())
        owner = conn.scalar(sa.select(asset_sources.c.asset_id).where(
            asset_sources.c.source_key == version.source_key,
        ))
        if owner != asset.id:
            raise ContractError("<catalog>", [Violation(
                "ref.duplicate", "/provenance/source_key", "The source key names another asset",
            )])

    existing = conn.execute(sa.select(
        asset_versions.c.document, asset_versions.c.received_sha256,
    ).where(sa.or_(
        asset_versions.c.id == version.id,
        sa.and_(asset_versions.c.asset_id == asset.id, asset_versions.c.number == version.number),
    )).limit(1)).one_or_none()
    if existing is not None:
        if existing.document != document or (
            received_sha256 is not None and existing.received_sha256 != received_sha256
        ):
            raise ContractError("<catalog>", [Violation(
                "ref.duplicate", "/id", "The immutable version identity is already in use",
            )])
        return
    conn.execute(asset_versions.insert().values(id=version.id, asset_id=asset.id,
                                               number=version.number, state=version.state,
                                               received_sha256=received_sha256, document=document))
    items = []
    if version.content is not None:
        items.append((version.content.locator, version.content.sha256, version.content.bytes))
    if version.voice is not None:
        track = version.voice.track
        if track is not None:
            items.append((track.locator, track.sha256, track.bytes))
        for take in version.voice.takes:
            scope_name = scope.production_id or "library"
            items.append((blob_locator(scope_name, take.sha256, "audio/wav"), take.sha256, None))
    _index_media(conn, asset_media, "version_id", version.id, items)


def _index_media(conn, table, key: str, id_: str,
                 items: Iterable[tuple[str, str, int | None]]) -> None:
    indexed = {}
    for locator, sha256, size in items:
        # Historic metadata sometimes has a locator/hash but no byte count.
        # A null size delegates the live file length to fstat.
        entry = {key: id_, "locator": locator, "sha256": sha256, "size": size}
        if locator not in indexed or size is not None:
            indexed[locator] = entry
    if indexed:
        conn.execute(table.insert(), list(indexed.values()))


def record_delivery(conn: sa.Connection, story_id: str, document: dict) -> None:
    """Persist a verified, immutable delivery for the queue or a trusted import."""
    require_valid(validate_delivery(document))
    story = conn.execute(sa.select(stories.c.production_id, stories.c.media_kind).where(
        stories.c.id == story_id,
    )).one_or_none()
    if story is None:
        raise NotFound
    production_id = story.production_id
    master = document["master"]
    if (master["width"], master["height"]) != MASTER_SIZES[story.media_kind]:
        raise _scope_error("/master", "The delivery dimensions disagree with its story's media type")
    items = []
    for name in ("master", "proxy"):
        media = document[name]
        if media is not None and media["locator"] is not None:
            if parse_locator(media["locator"]).production_id != production_id:
                raise _scope_error(f"/{name}/locator", "The delivery is outside its production")
            items.append((media["locator"], media["sha256"], media["bytes"]))
    run_id = document["run_id"]
    inserted = conn.scalar(insert(deliveries).values(
        run_id=run_id, id=document["id"], story_id=story_id, document=document,
    ).on_conflict_do_nothing().returning(deliveries.c.run_id))
    if inserted is None:
        current = conn.execute(sa.select(deliveries.c.story_id, deliveries.c.document).where(
            deliveries.c.run_id == run_id,
        )).one_or_none()
        if current is None or current.story_id != story_id or current.document != document:
            raise ContractError("<delivery>", [Violation(
                "ref.duplicate", "/id", "This run or delivery ID is already in use",
            )])
        return
    _index_media(conn, delivery_media, "run_id", run_id, items)


def get_delivery(conn: sa.Connection, run_id: str):
    return conn.execute(sa.select(stories.c.production_id, deliveries.c.document)
                        .join_from(deliveries, stories).where(deliveries.c.run_id == run_id)).one_or_none()


def media_for_hash(conn: sa.Connection, sha256: str, allowed: ProductionScope):
    """Resolve only from production-linked records. The filesystem is not an index."""
    delivery = sa.select(delivery_media.c.locator, delivery_media.c.size).select_from(
        delivery_media.join(deliveries).join(stories),
    ).where(delivery_media.c.sha256 == sha256, _in_scope(stories.c.production_id, allowed))
    referenced = sa.exists(sa.select(1).select_from(story_asset_refs.join(stories)).where(
        story_asset_refs.c.version_id == asset_versions.c.id,
        _in_scope(stories.c.production_id, allowed),
    ))
    production_asset = sa.and_(assets.c.production_id.is_not(None),
                               _in_scope(assets.c.production_id, allowed))
    asset = sa.select(asset_media.c.locator, asset_media.c.size).select_from(
        asset_media.join(asset_versions).join(assets),
    ).where(asset_media.c.sha256 == sha256, asset_versions.c.state != CANDIDATE,
            sa.or_(production_asset, sa.and_(assets.c.production_id.is_(None), referenced)))
    indexed = delivery.union(asset).subquery()
    return conn.execute(sa.select(indexed).order_by(indexed.c.locator)).all()


def build_library(conn: sa.Connection, story: dict, version_ids: Collection[str]) -> Library:
    """The explicit pins and relevant promoted motion alternatives for a snapshot."""
    production_id = story["production_id"]
    library = load_library(conn, version_ids, production_id)
    if not any(board["method"]["layer"] == "layered" for board in story["boards"]):
        return library
    stills = {v.content.sha256 for v in library.versions.values()
              if v.content is not None and v.content.media_type.startswith("image/")}
    if not stills:
        return library
    rows = conn.execute(_joined_versions().where(
        _catalog_scope({production_id}), assets.c.kind == "motion",
        sa.or_(assets.c.story_id.is_(None), assets.c.story_id == story["id"]),
        sa.or_(assets.c.board_id.is_(None), assets.c.board_id.in_(story["board_order"])),
        asset_versions.c.state == PROMOTED,
        asset_versions.c.document["motion"]["still_sha256"].astext.in_(stills),
        asset_versions.c.id.not_in(version_ids),
    ))
    documents = [version_document(v, library.asset_of(v.id)) for v in library.versions.values()]
    return Library.from_version_documents([*documents, *(_version(row) for row in rows)])
