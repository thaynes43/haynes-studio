"""Freeze the board inputs that determine whether a photo is current."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from haynes_studio.canonical.facts import Facts, PhotoVersionFacts
from haynes_studio.canonical.model import Board, Story
from haynes_studio.delivery.model import MASTER_SIZES
from haynes_studio.errors import ContractError
from haynes_studio.jsonio import thaw
from haynes_studio.layered import compose
from haynes_studio.layered.errors import UNSUPPORTED, LayeredError
from haynes_studio.layered.foreground import resolve_picture_roles
from haynes_studio.layered.matte_size import ENGINE, SIZE_POLICY
from haynes_studio.layered.photo import PhotoInputs, photo_inputs
from haynes_studio.library import Library
from haynes_studio.library.library import require_media
from haynes_studio.library.model import BOARD, PROMOTED, AssetVersion, Content, Scope, signature
from haynes_studio.library.resolve import BYTES_MISSING, KIND_MISMATCH, SCOPE_MISMATCH

from .validation import IMAGE_TYPES, error, text_is_encodable

SIGNATURE_SCHEME = "studio.board-photo-inputs/v1"
WHOLE_FRAME = "whole_frame"
LAYERED = "layered"


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

    @property
    def input_signature(self) -> str:
        return signature({
            "schema": SIGNATURE_SCHEME, "board_id": self.scope.board_id,
            "layer": self.layer, "size": list(self.size), "prompt": self.prompt,
            "sources": [source.pin() for source in self.sources],
            "composite_signature": None if self.layers is None else self.layers.signature,
        })


def sources_for(library: Library, scope: Scope, ids: tuple[str, ...],
                path: str, *, images_only: bool = True, metadata_only: bool = False,
                composited_set_id: str | None = None) -> tuple[PhotoSource, ...]:
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
        if version.id != composited_set_id:
            resolve_picture_roles(version, None, library, production_id=scope.production_id)
        if not metadata_only:
            require_media(version, at)
        if version.content is None:
            raise error(BYTES_MISSING, at, "the source has no content")
        if images_only and version.content.media_type not in IMAGE_TYPES:
            raise error(KIND_MISMATCH, at, "the photo source must be an image")
        sources.append(PhotoSource(version_id, version.content))
    return tuple(sources)


def plan_photo(story: Story, board: Board, library: Library, *, metadata_only: bool = False) -> PhotoPlan:
    """Take canonical story and board values and the relevant library records.

    The plan owns all generation inputs. Its signature excludes the currently selected
    version, which is held separately to fence concurrent selection.
    """
    if board.story_id != story.id or board.id not in story.board_order:
        raise error("ref.unknown", "/board_id", "the board is not in this story")
    scope = Scope(story.production_id, story.id, board.id)
    size = MASTER_SIZES[story.media_kind]
    selected = board.photo.current_version_id
    set_id = None if story.set is None else story.set.asset_version_id
    set_version = None if set_id is None else library.get(set_id)
    if set_id is not None and set_version is None:
        raise error("ref.unknown", "/set/asset_version_id", "no such selected set version")
    roles = resolve_picture_roles(
        set_version, board, library, production_id=story.production_id,
        set_loop=story.set is not None and story.set.motion_asset_version_id is not None,
    )
    if board.method.layer == LAYERED:
        if set_version is None:
            raise LayeredError(UNSUPPORTED, "the story has no set still to compose on", where="/set")
        ids = tuple(entry.asset_version_id for entry in board.cast)
        sources = sources_for(library, scope, (set_id, *ids), "/layers", metadata_only=metadata_only,
                              composited_set_id=set_id)
        sources += tuple(PhotoSource(role.version_id, role.content) for role in roles)
        blobs = {source.version_id: source.content.sha256 for source in sources}
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
                              set_sha256=blobs[set_id], matte_sizes=matte_sizes, roles=roles)
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
        return PhotoPlan(scope, LAYERED, size, None, sources, selected, layers)

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


def _latest(story: Story | None, board: Board | None, library: Library) -> PhotoPlan | None:
    if story is None or board is None:
        return None
    try:
        # Archive pins retain enough metadata to describe historical photo currency.
        return plan_photo(story, board, library, metadata_only=True)
    except (ContractError, LayeredError):
        return None


def _matches(version: AssetVersion, current: PhotoPlan) -> bool:
    params = version.provenance["generator"].get("params", {})
    return params.get("input_signature") == current.input_signature


def can_select_photo(version: AssetVersion, plan: PhotoPlan, story: Story | None,
                     board: Board | None, library: Library) -> bool:
    """Compare against the latest draft and selection inside the caller's write fence."""
    current = _latest(story, board, library)
    if current is None or version.kind != "photo" or version.state != BOARD:
        return False
    return (library.get(version.id) == version
            and current.scope == plan.scope == library.asset(version.asset_id).scope
            and current.input_signature == plan.input_signature
            and current.selected_version_id == plan.selected_version_id
            and _matches(version, current))


def photo_facts(story: Story, library: Library) -> Facts:
    """Currency for selected photos in an embedded story, to merge into canonical Facts.

    Older unsigned versions lack a freshness proof and are stale when selected.
    """
    photos = []
    for board in story.boards or ():
        version = library.get(board.photo.current_version_id) if board.photo.current_version_id else None
        if version is None or version.kind != "photo":
            continue
        current = _latest(story, board, library)
        matches = (current is not None
                   and current.scope == library.asset(version.asset_id).scope
                   and _matches(version, current))
        photos.append(PhotoVersionFacts(version.id, matches_board=matches))
    return Facts.build(photos=photos)
