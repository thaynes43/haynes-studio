"""Resolve and project foreground role masks on the same cover fit as the set still."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from io import BytesIO
from typing import BinaryIO

import numpy as np
from PIL import Image

from haynes_studio.layered.errors import LayeredError
from haynes_studio.layered.keyed import read_verified
from haynes_studio.library.model import PROMOTED, Content
from haynes_studio.render.delivery_profile import fit_set_plate
from haynes_studio.store import StoreError
from haynes_studio.store.errors import BLOB_MISSING

MASK_MISSING = "occlusion.mask_missing"
MASK_STALE = "occlusion.mask_stale"
MASK_NOT_READY = "occlusion.mask_not_ready"
MASK_SIZE = "occlusion.mask_size"
MASK_INVALID = "occlusion.mask_invalid"
FOREGROUND_REQUIRED = "occlusion.foreground_required"
UNSUPPORTED = "occlusion.unsupported"
MAX_MASK_BYTES = 20 * 1024 * 1024
MAX_MASK_PIXELS = 16 * 1024 * 1024
STILL_TYPES = {"image/png", "image/jpeg", "image/webp"}


@dataclass(frozen=True)
class RoleMask:
    key: str
    layer_order: int
    version_id: str
    kind: str
    content: Content
    size: tuple[int, int]

    def draw_pin(self) -> dict:
        return {"key": self.key, "layer_order": self.layer_order, "sha256": self.content.sha256,
                "width": self.size[0], "height": self.size[1]}

    def snapshot_entry(self) -> dict[str, str]:
        return {"id": self.version_id, "kind": self.kind, "sha256": self.content.sha256}


def role_version_ids(document: Mapping) -> set[str]:
    return {role["mask"]["version_id"] for role in (document.get("occlusion") or {}).get("foreground", ())}


def resolve_roles(story, version, library) -> tuple[RoleMask, ...]:
    """Resolve immutable set declarations in the caller's production scope."""
    block = None if version is None else version.occlusion
    if not block:
        return ()
    if version.content is not None and version.content.media_type not in STILL_TYPES:
        raise LayeredError(UNSUPPORTED, "foreground roles need a static set still", where="/set/occlusion")
    roles = []
    for index, role in enumerate(block.get("foreground", ())):
        path = f"/set/occlusion/foreground/{index}/mask"
        pin = role["mask"]
        if version.content is None or pin["still_sha256"] != version.content.sha256:
            raise LayeredError(MASK_STALE, "the role mask was pinned for a different set still", where=path)
        asset_version = library.get(pin["version_id"])
        if asset_version is None:
            raise LayeredError(MASK_MISSING, "no such mask version is available", where=path)
        scope = library.asset_of(asset_version.id).scope
        if scope.production_id not in (None, story.production_id) or scope.story_id or scope.board_id:
            raise LayeredError(MASK_MISSING, "no such mask version is available", where=path)
        content = asset_version.content
        if (asset_version.state != PROMOTED or asset_version.recorded_without_media
                or asset_version.occlusion is not None
                or not asset_version.has("mask") or content is None or content.media_type != "image/png"):
            raise LayeredError(MASK_NOT_READY, "the role needs a promoted PNG mask with content", where=path)
        if pin["sha256"] != content.sha256:
            raise LayeredError(MASK_STALE, "the mask content hash differs from the declaration", where=path)
        size = pin["width"], pin["height"]
        check_size(size, (version.content.width, version.content.height), where=path)
        check_size(size, (content.width, content.height), where=path)
        roles.append(RoleMask(role["key"], role["layer_order"], asset_version.id,
                              asset_version.kind, content, size))
    return tuple(roles)


def check_size(declared: tuple[int, int], size: tuple[int | None, int | None], *, where: str) -> None:
    if any(held is not None and expected is not None and held != expected
           for held, expected in zip(declared, size, strict=True)):
        raise LayeredError(MASK_SIZE, "the mask dimensions differ from the set still", where=where)


def check_board_roles(board, roles, *, set_loop=False) -> None:
    if not roles:
        return
    if not board.layout.foreground:
        raise LayeredError(FOREGROUND_REQUIRED,
                           "Enable layout.foreground or select a set version without role masks",
                           where="/layout/foreground")
    if board.method.layer != "layered" or set_loop:
        raise LayeredError(UNSUPPORTED, "Foreground role masks need a layered board with a static set still",
                           where="/set/occlusion")


def check_role_images(content: Content, roles: tuple[RoleMask, ...], store) -> None:
    still = read_verified(lambda _: store.open(content.locator), content.sha256, "the set still")
    try:
        with Image.open(BytesIO(still)) as image:
            size = image.size
            image.load()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise LayeredError(UNSUPPORTED, "The set still cannot be decoded", where="/set/occlusion") from None
    for role in roles:
        path = f"/set/occlusion/foreground/{role.key}/mask"
        check_size(role.size, size, where=path)
        read_mask(lambda _, locator=role.content.locator: store.open(locator),
                  role.content.sha256, size, where=path)


def read_mask(read: Callable[[str], BinaryIO], sha256: str, size: tuple[int, int], *,
              where: str) -> Image.Image:
    try:
        with read(sha256) as stream:
            data = stream.read(MAX_MASK_BYTES + 1)
    except (LookupError, FileNotFoundError):
        raise LayeredError(MASK_MISSING, "the pinned mask bytes are missing", where=where) from None
    except StoreError as error:
        if error.code != BLOB_MISSING:
            raise
        raise LayeredError(MASK_MISSING, "the pinned mask bytes are missing", where=where) from None
    if not data:
        raise LayeredError(MASK_INVALID, "the mask PNG is empty", where=where)
    if len(data) > MAX_MASK_BYTES:
        raise LayeredError(MASK_INVALID, "the mask PNG exceeds the byte limit", where=where)
    if hashlib.sha256(data).hexdigest() != sha256:
        raise LayeredError(MASK_STALE, "the mask bytes differ from the pinned hash", where=where)
    try:
        with Image.open(BytesIO(data), formats=["PNG"]) as image:
            if image.size != size:
                raise LayeredError(MASK_SIZE, "the mask dimensions differ from the set still", where=where)
            if (image.width * image.height > MAX_MASK_PIXELS or image.mode != "L"
                    or getattr(image, "n_frames", 1) != 1 or "transparency" in image.info
                    or image.getexif().get(274, 1) != 1):
                raise ValueError("expected a single grayscale frame")
            pixels = np.asarray(image)
            if not (pixels == 255).any() or ((pixels != 0) & (pixels != 255)).any():
                raise ValueError("expected a nonempty binary mask")
            return image.copy()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise LayeredError(MASK_INVALID, "the role mask needs a nonempty binary grayscale PNG",
                           where=where) from None


def draw_layers(pins, read, source_size, frame_size) -> tuple[tuple[int, Image.Image], ...]:
    """The fitted alpha images consumed by the production compositor."""
    layers = []
    for role in sorted(pins, key=lambda role: role["layer_order"]):
        path = f"/set/occlusion/foreground/{role['key']}/mask"
        check_size((role["width"], role["height"]), source_size, where=path)
        alpha = read_mask(read, role["sha256"], source_size, where=path)
        layers.append((role["layer_order"], fit_set_plate(alpha, frame_size)))
    return tuple(layers)
