"""Freeze the board inputs that determine whether a photo is current."""
from __future__ import annotations

import unicodedata
from collections.abc import Collection, Mapping
from dataclasses import dataclass

from haynes_studio.canonical.facts import Facts, PhotoVersionFacts
from haynes_studio.canonical.model import Board, Story
from haynes_studio.delivery.model import MASTER_SIZES
from haynes_studio.errors import ContractError
from haynes_studio.jsonio import thaw
from haynes_studio.layered import compose
from haynes_studio.layered.errors import LayeredError
from haynes_studio.layered.foreground import RoleMask, admit_masks, check_loop, check_picture, roles_from_pins
from haynes_studio.layered.matte_size import ENGINE, SIZE_POLICY
from haynes_studio.layered.photo import SCHEMA as COMPOSITE_SCHEMA
from haynes_studio.layered.photo import PhotoInputs, photo_inputs
from haynes_studio.library import Library
from haynes_studio.library.library import require_media
from haynes_studio.library.model import BOARD, PROMOTED, AssetVersion, Content, Scope, signature
from haynes_studio.library.resolve import BYTES_MISSING, KIND_MISMATCH, SCOPE_MISMATCH
from haynes_studio.store import Store

from .validation import IMAGE_TYPES, error, text_is_encodable

SIGNATURE_SCHEME = "studio.board-photo-inputs/v1"
WHOLE_FRAME = "whole_frame"
LAYERED = "layered"


def _photo_signature(*, board_id: str | None, layer: str, size: list[int], prompt: str | None,
                     sources: list[dict[str, str]], composite_signature: str | None) -> str:
    return signature({
        "schema": SIGNATURE_SCHEME, "board_id": board_id,
        "layer": layer, "size": size, "prompt": prompt,
        "sources": sources, "composite_signature": composite_signature,
    })


@dataclass(frozen=True)
class PhotoSource:
    version_id: str
    content: Content

    def pin(self) -> dict[str, str]:
        return {"version_id": self.version_id, "sha256": self.content.sha256}


@dataclass(frozen=True)
class PhotoPlan:
    scope: Scope
    layer: str
    size: tuple[int, int]
    prompt: str | None
    sources: tuple[PhotoSource, ...]
    selected_version_id: str | None
    layers: PhotoInputs | None = None
    roles: tuple[RoleMask, ...] = ()

    @property
    def input_signature(self) -> str:
        return _photo_signature(
            board_id=self.scope.board_id, layer=self.layer, size=list(self.size), prompt=self.prompt,
            sources=[source.pin() for source in self.sources],
            composite_signature=None if self.layers is None else self.layers.signature,
        )


def sources_for(library: Library, scope: Scope, ids: tuple[str, ...],
                path: str, *, images_only: bool = True, metadata_only: bool = False) -> tuple[PhotoSource, ...]:
    sources = []
    for index, version_id in enumerate(ids):
        at = f"{path}/{index}"
        version = library.get(version_id)
        if version is None:
            raise error("ref.unknown", at, "no such source asset version")
        owner = library.asset(version.asset_id).scope
        if (owner.production_id not in (None, scope.production_id)
                or owner.story_id not in (None, scope.story_id)
                or owner.board_id not in (None, scope.board_id)):
            raise error(SCOPE_MISMATCH, at, "the source belongs to another production, story or board")
        if not metadata_only:
            require_media(version, at)
        if version.content is None:
            raise error(BYTES_MISSING, at, "the source has no content")
        if images_only and version.content.media_type not in IMAGE_TYPES:
            raise error(KIND_MISMATCH, at, "the photo source must be an image")
        sources.append(PhotoSource(version_id, version.content))
    return tuple(sources)


def admit_photo(story: Story, board: Board, library: Library, *, store: Store,
                declaring_sources: Collection[str]) -> PhotoPlan:
    """Check the new request before its library and signature are frozen."""
    version = library.get(story.set.asset_version_id) if story.set is not None else None
    loop_id = story.set.motion_asset_version_id if story.set is not None else None
    check_picture(version, board, uses_loop=loop_id is not None)
    if board.method.layer == LAYERED:
        check_loop(library.get(loop_id), declaring_sources)
    elif board.method.layer == WHOLE_FRAME:
        for index, version_id in enumerate(board.photo.input_asset_version_ids):
            try:
                check_picture(library.get(version_id), None, uses_loop=False)
            except LayeredError as error:
                raise LayeredError(error.code, error.message,
                                   where=f"/photo/input_asset_version_ids/{index}") from error
    roles = admit_masks(version, library, story.production_id, store)
    return plan_photo(story, board, library, roles=roles)


def plan_photo(story: Story, board: Board, library: Library, *, metadata_only: bool = False,
               roles: tuple[RoleMask, ...] = ()) -> PhotoPlan:
    """Take canonical story and board values and the relevant library records.

    The plan owns all generation inputs. Its signature excludes the currently selected
    version, which is held separately to fence concurrent selection.
    """
    if board.story_id != story.id or board.id not in story.board_order:
        raise error("ref.unknown", "/board_id", "the board is not in this story")
    scope = Scope(story.production_id, story.id, board.id)
    size = MASTER_SIZES[story.media_kind]
    selected = board.photo.current_version_id
    if board.method.layer == LAYERED:
        ids = tuple(entry.asset_version_id for entry in board.cast)
        if story.set is not None:
            ids = (story.set.asset_version_id, *ids)
        sources = sources_for(library, scope, ids, "/layers", metadata_only=metadata_only)
        blobs = {source.version_id: source.content.sha256 for source in sources}
        sources += tuple(PhotoSource(role.version_id, role.content) for role in roles)
        matte_sizes = {}
        for entry in board.cast:
            version = library.version(entry.asset_version_id)
            generator = version.provenance.get("generator") or {}
            if generator.get("engine") != ENGINE:
                continue
            if version.state != PROMOTED:
                raise error("ref.unpromoted", "/layers", "A cast matte needs library promotion before use")
            params = generator.get("params", {})
            target = params.get("normalization", {})
            height = target.get("target_height_px")
            if (target.get("policy") != SIZE_POLICY or target.get("slot") != entry.slot
                    or target.get("format_version_id") != story.format_version_id
                    or type(height) is not int or not 1 <= height <= 2048):
                raise error("matting.slot_mismatch", "/layers",
                            "The cast matte needs the pinned format and slot it was sized for")
            matte_sizes[entry.slot] = {"target_height_px": height,
                                       "shape": thaw(params.get("receipt", {}).get("shape"))}
        layers = photo_inputs(story, board, blobs=blobs, width=size[0], height=size[1],
                              matte_sizes=matte_sizes, roles=roles)
        for slot_name, matte in matte_sizes.items():
            try:
                bottom = compose.slot_of(thaw(layers.layout), slot_name).bottom
            except LayeredError:
                continue  # the composer reports an invalid layout itself
            if matte["target_height_px"] > bottom:
                # Refuse before a build is queued; the composer repeats the check
                # with the sprite's fringe included.
                raise error("matting.target_exceeds_frame", "/layers",
                            "The cast matte is taller than the space above its slot's bottom line")
        return PhotoPlan(scope, LAYERED, size, None, sources, selected, layers, roles)

    prompt = board.photo.prompt
    if prompt is not None:
        if not text_is_encodable(prompt):
            raise error("schema.invalid", "/photo/prompt", "the photo prompt must be Unicode text")
        prompt = unicodedata.normalize("NFC", prompt)
    return PhotoPlan(
        scope, WHOLE_FRAME, size, prompt,
        sources_for(library, scope, board.photo.input_asset_version_ids, "/photo/input_asset_version_ids",
                    metadata_only=metadata_only),
        selected,
    )


def _latest(story: Story | None, board: Board | None, library: Library,
            roles: tuple[RoleMask, ...]) -> PhotoPlan | None:
    if story is None or board is None:
        return None
    try:
        # Archive pins retain enough metadata to describe historical photo currency.
        return plan_photo(story, board, library, metadata_only=True,
                          roles=roles if board.layout.foreground else ())
    except (ContractError, LayeredError):
        return None


def _matches(version: AssetVersion, current: PhotoPlan) -> bool:
    params = version.provenance["generator"].get("params", {})
    return params.get("input_signature") == current.input_signature


def can_select_photo(version: AssetVersion, plan: PhotoPlan, story: Story | None,
                     board: Board | None, library: Library) -> bool:
    """Compare against the latest draft and selection inside the caller's write fence."""
    current = _latest(story, board, library, plan.roles)
    if current is None or version.kind != "photo" or version.state != BOARD:
        return False
    return (library.get(version.id) == version
            and current.scope == plan.scope == library.asset(version.asset_id).scope
            and current.input_signature == plan.input_signature
            and current.selected_version_id == plan.selected_version_id
            and _matches(version, current))


def photo_role_pins(version: AssetVersion, board_id: str) -> tuple[Mapping, ...]:
    """Read pins only from the typed composite covered by the board photo's signature."""
    if version.kind != "photo" or version.provenance.get("origin") != "derived":
        return ()
    generator = version.provenance.get("generator")
    if not isinstance(generator, Mapping) or generator.get("role") != "composite":
        return ()
    params = generator.get("params")
    if not isinstance(params, Mapping):
        return ()
    composite = params.get("composite")
    if not isinstance(composite, Mapping) or composite.get("schema") != COMPOSITE_SCHEMA:
        return ()
    foreground = composite.get("foreground")
    pins = foreground.get("roles") if isinstance(foreground, Mapping) else None
    if not isinstance(pins, tuple) or not pins:
        return ()
    try:
        expected = _photo_signature(
            board_id=board_id, layer=LAYERED, size=[composite["width"], composite["height"]],
            prompt=None, sources=thaw(params["source_assets"]), composite_signature=signature(thaw(composite)),
        )
    except (KeyError, TypeError, ValueError):
        return ()
    if params.get("input_signature") != expected:
        return ()
    return tuple(pin for pin in pins if isinstance(pin, Mapping) and isinstance(pin.get("version_id"), str))


def photo_facts(story: Story, library: Library) -> Facts:
    """Currency for selected photos in an embedded story, to merge into canonical Facts.

    Older unsigned versions lack a freshness proof and are stale when selected.
    """
    photos = []
    for board in story.boards or ():
        version = library.get(board.photo.current_version_id) if board.photo.current_version_id else None
        if version is None or version.kind != "photo":
            continue
        try:
            roles = roles_from_pins(photo_role_pins(version, board.id), library)
        except (KeyError, TypeError, ValueError):
            roles = None
        current = None if roles is None else _latest(story, board, library, roles)
        matches = (current is not None
                   and current.scope == library.asset(version.asset_id).scope
                   and _matches(version, current))
        photos.append(PhotoVersionFacts(version.id, matches_board=matches))
    return Facts.build(photos=photos)
