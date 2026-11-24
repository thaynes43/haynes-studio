"""Append immutable board-photo versions and publish their content create-only."""
from __future__ import annotations

from collections.abc import Callable

from haynes_studio.canonical.ids import Minter
from haynes_studio.canonical.model import Principal, to_document
from haynes_studio.errors import ContractError, blocking
from haynes_studio.jsonio import freeze
from haynes_studio.library import Library
from haynes_studio.library.library import Outcome
from haynes_studio.library.model import BOARD, Asset, AssetVersion, Content, locator_for, version_document
from haynes_studio.library.resolve import SCOPE_MISMATCH
from haynes_studio.library.validate import LOCATOR_INVALID, validate_asset, validate_asset_version

from .build import PROVENANCE_INVALID, PreparedPhoto
from .validation import PNG, error, sha256

Publish = Callable[[bytes, str], tuple[str, str]]


def record_photo(prepared: PreparedPhoto, library: Library, *, publish: Publish,
                 by: Principal, now: str, minter: Minter | None = None) -> Outcome:
    """Validate and append one version against the latest library in the write transaction.

    The caller serializes writes to this board's asset and owns operation idempotency.
    Byte-identical photos can name the same blob while retaining separate provenance.
    """
    minter = minter or Minter()
    plan = prepared.plan
    scope = plan.scope
    key = f"board-photo:{scope.board_id}"
    asset = library.by_source_key(key)
    if asset is None and plan.selected_version_id:
        selected = library.get(plan.selected_version_id)
        if selected is not None and selected.kind == "photo":
            candidate = library.asset(selected.asset_id)
            if candidate.scope == scope:
                asset = candidate
    if asset is None:
        asset_id = minter.mint("ast")
        if asset_id in library.assets:
            raise error("ref.duplicate", "/asset_id", "photo asset ID is already in use")
        asset = Asset(asset_id, "photo", "Board reference photo", scope, (), freeze({}),
                      created_at=now, updated_at=now, created_by=by)
    if asset.kind != "photo" or asset.scope != scope:
        raise error(SCOPE_MISMATCH, "/scope", "the board-photo asset is in another scope")

    if prepared.external is not None:
        if by.kind != "agent" or prepared.external["agent"]["key_id"] != by.key_id:
            raise error(PROVENANCE_INVALID, "/provenance/created_by",
                        "the upload must be recorded for its authenticated agent")
    image = prepared.image
    digest = sha256(image.png)
    locator = locator_for(digest, PNG, scope.production_id)
    version = AssetVersion(
        id=minter.mint("asv"), asset_id=asset.id, kind="photo", state=BOARD,
        number=max((item.number for item in library.versions_of(asset.id)), default=0) + 1,
        capabilities=("opaque_photo",),
        content=Content(digest, len(image.png), PNG, locator, image.width, image.height),
        provenance=freeze({
            "origin": prepared.origin, "generator": prepared.generator,
            "external": prepared.external, "source_key": key,
            "created_by": to_document(by), "created_at": now,
        }),
        licence=prepared.licence,
    )
    problems = blocking(validate_asset(asset.to_document(), context="write"))
    problems += blocking(validate_asset_version(version_document(version, asset), context="write"))
    if problems:
        raise ContractError(version.id, problems)
    assets = {**library.assets, asset.id: asset}
    updated = Library.build(assets.values(), (*library.versions.values(), version))
    stored_digest, stored_locator = publish(image.png, PNG)
    if stored_digest != digest:
        raise error("store.hash_mismatch", "/content/sha256", "the store returned another SHA-256")
    if stored_locator != locator:
        raise error(LOCATOR_INVALID, "/content/locator", "the store returned another locator")
    return Outcome(updated, version, created=True)
