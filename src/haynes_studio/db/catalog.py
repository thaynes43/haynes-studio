"""Canonical library and delivery persistence and the media authorization index."""

from collections.abc import Collection, Iterable

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from haynes_studio.canonical.model import to_document
from haynes_studio.delivery.model import MASTER_SIZES
from haynes_studio.delivery.validate import validate_delivery
from haynes_studio.errors import ContractError, Violation
from haynes_studio.layered.foreground import declarations, recorded_source_ids
from haynes_studio.library.library import Library, promote
from haynes_studio.library.model import BOARD, CANDIDATE, PROMOTED, Asset, AssetVersion, Content, version_document
from haynes_studio.library.validate import (
    focal_prop_source_ids, focal_prop_source_problems, validate_asset, validate_asset_version,
)
from haynes_studio.store.layout import blob_locator, is_sha256, parse_locator

from .problems import NotFound, require_valid
from .schema import (
    asset_media, asset_promotions, asset_sources, asset_versions, assets, boards, deliveries, delivery_media,
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


def _version_state():
    promoted = sa.exists(sa.select(1).where(
        asset_promotions.c.version_id == asset_versions.c.id,
    )).correlate(asset_versions)
    state = asset_versions.c.state
    return sa.case((sa.and_(state == CANDIDATE, promoted), PROMOTED), else_=state)


def _joined_versions():
    return sa.select(asset_versions.c.document, assets.c.document.label("asset"),
                     _version_state().label("state")).join_from(
        asset_versions, assets, asset_versions.c.asset_id == assets.c.id,
    )


def _version(row):
    return version_document(AssetVersion.from_document({**row.document, "state": row.state}),
                            Asset.from_document(row.asset))


def load_library(conn: sa.Connection, version_ids: Collection[str], production_id: str) -> Library:
    if not version_ids:
        return Library()
    rows = conn.execute(_joined_versions().where(
        _catalog_scope({production_id}), asset_versions.c.id.in_(version_ids),
        _version_state() != CANDIDATE,
    ))
    return Library.from_version_documents(_version(row) for row in rows)


def with_foreground_masks(conn, library: Library, set_id: str | None, production_id: str) -> Library:
    """Load only the mask versions named by the selected still."""
    ids = {role["mask"]["version_id"] for role in declarations(library.get(set_id))}
    return with_mask_versions(conn, library, ids, production_id)


def with_mask_versions(conn, library: Library, ids: set[str], production_id: str) -> Library:
    if not (missing := ids.difference(library.versions)):
        return library
    rows = conn.execute(_joined_versions().where(
        _catalog_scope({production_id}), asset_versions.c.id.in_(missing),
        assets.c.story_id.is_(None), assets.c.board_id.is_(None),
    ))
    masks = Library.from_version_documents(_version(row) for row in rows)
    return Library.build({**library.assets, **masks.assets}.values(),
                         {**library.versions, **masks.versions}.values())


def declaring_loop_sources(conn, library: Library, loop_ids: Collection[str]) -> set[str]:
    """Check recorded provenance for admission without adding source sets to frozen inputs."""
    ids = {id_ for loop_id in loop_ids if (loop := library.get(loop_id)) is not None
           and loop.has("set_loop") for id_ in recorded_source_ids(loop.provenance)}
    if not ids:
        return set()
    return set(conn.scalars(sa.select(asset_versions.c.id).join(
        assets, assets.c.id == asset_versions.c.asset_id,
    ).where(
        assets.c.kind == "set", asset_versions.c.id.in_(ids),
        asset_versions.c.document["occlusion"].has_key("foreground"),
    )))


def find_assets(conn: sa.Connection, allowed: ProductionScope, *, kind: str | None,
                labels: list[str], production_id: str | None, version_ids: Collection[str] | None,
                after: str | None, limit: int) -> list[dict]:
    stmt = _joined_versions().where(_catalog_scope(allowed), _version_state() != CANDIDATE)
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
    stmt = _joined_versions().where(assets.c.id == id_, _version_state() != CANDIDATE)
    visible = conn.scalar(sa.select(sa.exists().where(
        asset_versions.c.asset_id == id_, _version_state() != CANDIDATE,
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


def _check_focal_prop_sources(conn, version):
    sources = focal_prop_source_ids(version.occlusion)
    # Either side can be registered first. Both writers serialize on the source
    # version ID before reading the other side under Read Committed.
    for source in sorted(sources | {version.id}):
        conn.execute(sa.select(sa.func.pg_advisory_xact_lock(sa.func.hashtextextended(source, 412))))
    if sources:
        documents = conn.scalars(sa.select(asset_versions.c.document).where(
            asset_versions.c.id.in_(sources),
        ))
        for document in documents:
            require_valid(focal_prop_source_problems(
                version.occlusion, document["id"], document["kind"], document["capabilities"],
                Content.from_document(document["content"]),
            ))
    declarations = conn.scalars(sa.select(asset_versions.c.document["occlusion"]).where(
        asset_versions.c.document.contains({"occlusion": {"focal_props": [{"source_asset_version_id": version.id}]}}),
    ))
    for declaration in declarations:
        require_valid(focal_prop_source_problems(
            declaration, version.id, version.kind, version.capabilities, version.content,
        ))


def record_asset_version(conn: sa.Connection, document: dict, *, asset: Asset | None = None,
                         received_sha256: str | None = None) -> None:
    """Register a canonical version inside the caller's transaction.

    The caller uses the library's import or creation rules to choose version identity
    and publishes bytes through the canonical store. A repeated exact record is safe.
    For D42 the server records the received-byte digest alongside the canonical
    digest of the stored, stripped content. Legacy uploads may have only the latter.
    """
    if "occlusion" in document:
        require_valid(validate_asset_version(document, context="write"))
        document = AssetVersion.canonical_document(document)
    else:
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
    _check_focal_prop_sources(conn, version)
    conn.execute(asset_versions.insert().values(id=version.id, asset_id=asset.id,
                                               number=version.number, state=version.state,
                                               received_sha256=received_sha256, document=document))
    # An archive's locators describe historical inputs. Index only assets
    # whose own import or creation path registers media.
    if version.recorded_without_media:
        return
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
    ).where(asset_media.c.sha256 == sha256, _version_state() != CANDIDATE,
            sa.or_(sa.and_(production_asset, assets.c.board_id.is_(None)),
                   sa.and_(sa.or_(production_asset, assets.c.production_id.is_(None)), referenced)))
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
        _version_state() == PROMOTED,
        asset_versions.c.document["motion"]["still_sha256"].astext.in_(stills),
        asset_versions.c.id.not_in(version_ids),
    ))
    documents = [version_document(v, library.asset_of(v.id)) for v in library.versions.values()]
    return Library.from_version_documents([*documents, *(_version(row) for row in rows)])


def board_library(conn, library: Library, board_id: str, *kinds: str) -> Library:
    rows = conn.execute(_joined_versions().where(
        assets.c.board_id == board_id, assets.c.kind.in_(kinds),
        _version_state() != CANDIDATE,
    ))
    documents = {v.id: version_document(v, library.asset_of(v.id)) for v in library.versions.values()}
    for row in rows:
        doc = _version(row)
        documents[doc["id"]] = doc
    return Library.from_version_documents(documents.values())


def board_versions(conn, board_id, kind, after, limit):
    stmt = _joined_versions().where(assets.c.board_id == board_id, assets.c.kind == kind,
                                    _version_state() != CANDIDATE)
    if after is not None:
        stmt = stmt.where(asset_versions.c.id > after)
    return [_version(row) for row in conn.execute(stmt.order_by(asset_versions.c.id).limit(limit))]


def version_library(conn, *, version_id=None, version_ids=None, asset_id=None, source_key=None):
    stmt = _joined_versions()
    identities = []
    if source_key is not None:
        source = sa.select(asset_sources.c.asset_id).where(asset_sources.c.source_key == source_key)
        identities.append(assets.c.id.in_(source))
    if asset_id is not None:
        identities.append(assets.c.id == asset_id)
    if identities:
        stmt = stmt.where(sa.or_(*identities))
    if version_id is not None:
        stmt = stmt.where(asset_versions.c.id == version_id)
    if version_ids is not None:
        stmt = stmt.where(asset_versions.c.id.in_(version_ids))
    return Library.from_version_documents(_version(row) for row in conn.execute(stmt))


def preview_media(conn, version_id: str, sha256: str, allowed: ProductionScope, *, job=None):
    stmt = sa.select(asset_media.c.locator, asset_media.c.size).select_from(
        asset_media.join(asset_versions).join(assets),
    ).where(asset_media.c.version_id == version_id, asset_media.c.sha256 == sha256,
            _catalog_scope(allowed))
    if job is not None:
        stmt = stmt.where(assets.c.production_id.is_not_distinct_from(job["production_id"]))
    if job is None or job["kind"] not in ("asset_candidate", "matte", "occlusion"):
        stmt = stmt.where(sa.or_(_version_state() == CANDIDATE,
                                assets.c.kind.in_(("photo", "board_voice"))))
    return conn.execute(stmt).all()


def promote_version(conn, version_id, by, now):
    # Serialize on the immutable source ID, including creation of a board photo's
    # new library version, which uses a derived source key.
    conn.execute(sa.select(sa.func.pg_advisory_xact_lock(sa.func.hashtextextended(version_id, 430))))
    library = version_library(conn, version_id=version_id)
    original = library.get(version_id)
    if original is None:
        raise NotFound
    if original.kind == "photo" and original.state == BOARD:
        result = version_library(conn, source_key=f"promote:{version_id}")
        library = Library.build((*library.assets.values(), *result.assets.values()),
                                (*library.versions.values(), *result.versions.values()))
    outcome = promote(library, version_id, by=by, now=now)
    version = outcome.version
    document = version_document(version, outcome.library.asset_of(version.id))
    if outcome.created:
        if version.id == version_id:
            conn.execute(asset_promotions.insert().values(
                version_id=version_id, promoted_by=to_document(by), promoted_at=now,
            ))
        else:
            record_asset_version(conn, document)
    return document
