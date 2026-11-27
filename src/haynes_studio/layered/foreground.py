"""Resolve and project foreground role masks on the same cover fit as the set still."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from io import BytesIO
from typing import BinaryIO

import numpy as np
from PIL import Image

from haynes_studio.canonical.model import Board
from haynes_studio.layered.errors import LayeredError
from haynes_studio.layered.keyed import read_verified
from haynes_studio.library import Library
from haynes_studio.library.model import PROMOTED, AssetVersion, Content
from haynes_studio.render.delivery_profile import fit_set_plate
from haynes_studio.store import BLOB_MISSING, HASH_MISMATCH, Store, StoreError

MASK_MISSING = "occlusion.mask_missing"
MASK_STALE = "occlusion.mask_stale"
MASK_NOT_READY = "occlusion.mask_not_ready"
MASK_SIZE = "occlusion.mask_size"
MASK_INVALID = "occlusion.mask_invalid"
FOREGROUND_REQUIRED = "occlusion.foreground_required"
UNSUPPORTED = "occlusion.unsupported"
MAX_MASK_BYTES = 20 * 1024 * 1024
MAX_MASK_PIXELS = 16 * 1024 * 1024


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

    def pin(self) -> dict:
        return {"version_id": self.version_id, **self.draw_pin()}

    def snapshot_entry(self) -> dict[str, str]:
        return {"id": self.version_id, "kind": self.kind, "sha256": self.content.sha256}


def declarations(version: AssetVersion | None) -> tuple[Mapping, ...]:
    return () if version is None or version.occlusion is None else version.occlusion.get("foreground", ())


def recorded_source_ids(provenance: Mapping) -> tuple[str, ...]:
    generator = provenance.get("generator") or {}
    return tuple(generator.get("source_asset_version_ids") or ())


def check_picture(version: AssetVersion | None, board: Board | None, *, uses_loop: bool) -> None:
    if not declarations(version):
        return
    if board is None or board.method.layer != "layered" or uses_loop:
        raise LayeredError(UNSUPPORTED, "Foreground role masks need a layered board with a static set still",
                           where="/set/occlusion")
    if not board.layout.foreground:
        raise LayeredError(FOREGROUND_REQUIRED,
                           "Enable layout.foreground or select a set version without role masks",
                           where="/layout/foreground")


def check_loop(loop: AssetVersion | None, declaring_ids: Collection[str]) -> None:
    if loop is not None and loop.has("set_loop") and any(
        id_ in declaring_ids for id_ in recorded_source_ids(loop.provenance)
    ):
        raise LayeredError(UNSUPPORTED, "The set loop's recorded provenance names a set version with foreground roles",
                           where="/set/motion_asset_version_id")


def _role_mask(role: Mapping, version: AssetVersion, content: Content) -> RoleMask:
    pin = role["mask"]
    return RoleMask(role["key"], role["layer_order"], version.id, version.kind,
                    content, (pin["width"], pin["height"]))


def roles_from_pins(pins: Collection[Mapping], library: Library) -> tuple[RoleMask, ...]:
    """Read an already recorded role decision from its exact content pins."""
    roles = []
    for pin in pins:
        version = library.get(pin["version_id"])
        if version is None or version.content is None or version.content.sha256 != pin["sha256"]:
            raise ValueError("The recorded foreground mask no longer matches its content pin")
        roles.append(RoleMask(pin["key"], pin["layer_order"], version.id, version.kind,
                              version.content, (pin["width"], pin["height"])))
    return tuple(roles)


def admit_masks(version: AssetVersion | None, library: Library, production_id: str,
                store: Store) -> tuple[RoleMask, ...]:
    roles = []
    for index, role in enumerate(declarations(version)):
        path = f"/set/occlusion/foreground/{index}/mask"
        pin = role["mask"]
        asset_version = library.get(pin["version_id"])
        if asset_version is None:
            raise LayeredError(MASK_MISSING, "no such mask version is available", where=path)
        scope = library.asset_of(asset_version.id).scope
        if scope.production_id not in (None, production_id) or scope.story_id or scope.board_id:
            raise LayeredError(MASK_MISSING, "no such mask version is available", where=path)
        content = asset_version.content
        if (asset_version.state != PROMOTED or asset_version.recorded_without_media
                or asset_version.occlusion is not None
                or not asset_version.has("mask") or content is None or content.media_type != "image/png"):
            raise LayeredError(MASK_NOT_READY, "the role needs a promoted PNG mask with content", where=path)
        if (pin["sha256"] != content.sha256 or asset_version.segmentation is not None
                and asset_version.segmentation["still_sha256"] != pin["still_sha256"]):
            raise LayeredError(MASK_STALE, "the mask or source still hash differs from the declaration", where=path)
        size = pin["width"], pin["height"]
        check_size(size, (version.content.width, version.content.height), where=path)
        check_size(size, (content.width, content.height), where=path)
        check_mask_limits(size, content.bytes, where=path)
        roles.append(_role_mask(role, asset_version, content))
    if roles:
        check_role_images(version.content, roles, store)
    return tuple(roles)


def check_size(declared: tuple[int, int], size: tuple[int | None, int | None], *, where: str) -> None:
    if any(held is not None and expected is not None and held != expected
           for held, expected in zip(declared, size, strict=True)):
        raise LayeredError(MASK_SIZE, "the mask dimensions differ from the set still", where=where)


def check_mask_limits(size: tuple[int, int], byte_count: int | None, *, where: str) -> None:
    if size[0] * size[1] > MAX_MASK_PIXELS:
        raise LayeredError(MASK_INVALID, "the mask PNG exceeds the pixel limit", where=where)
    if byte_count is not None and not 0 < byte_count <= MAX_MASK_BYTES:
        raise LayeredError(MASK_INVALID, "the mask PNG is empty or exceeds the byte limit", where=where)


def check_role_images(content: Content, roles: list[RoleMask], store: Store) -> None:
    try:
        still = read_verified(lambda _: store.open(content.locator), content.sha256, "the set still")
    except LayeredError as error:
        raise LayeredError(UNSUPPORTED, error.message, where="/set/occlusion") from error
    except StoreError as error:
        if error.code != HASH_MISMATCH:
            raise
        raise LayeredError(MASK_STALE, "The set still differs from the pinned hash", where="/set/occlusion") from error
    try:
        with Image.open(BytesIO(still)) as image:
            size = image.size
            image.load()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise LayeredError(UNSUPPORTED, "The set still cannot be decoded", where="/set/occlusion") from None
    for index, role in enumerate(roles):
        path = f"/set/occlusion/foreground/{index}/mask"
        check_size(role.size, size, where=path)
        read_mask(lambda _, locator=role.content.locator: store.open(locator),
                  role.content.sha256, size, where=path)


def read_mask(read: Callable[[str], BinaryIO], sha256: str, size: tuple[int, int], *,
              where: str) -> Image.Image:
    check_mask_limits(size, None, where=where)
    try:
        with read(sha256) as stream:
            data = stream.read(MAX_MASK_BYTES + 1)
    except (LookupError, FileNotFoundError):
        raise LayeredError(MASK_MISSING, "the pinned mask bytes are missing", where=where) from None
    except StoreError as error:
        if error.code != BLOB_MISSING:
            raise
        raise LayeredError(MASK_MISSING, "the pinned mask bytes are missing", where=where) from None
    check_mask_limits(size, len(data), where=where)
    if hashlib.sha256(data).hexdigest() != sha256:
        raise LayeredError(MASK_STALE, "the mask bytes differ from the pinned hash", where=where)
    try:
        with Image.open(BytesIO(data), formats=["PNG"]) as image:
            if image.size != size:
                raise LayeredError(MASK_SIZE, "the mask dimensions differ from the set still", where=where)
            if (image.mode != "L"
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
