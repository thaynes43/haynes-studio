"""A layered board's reference photo (D51, story 426): the deterministic composite of
the build's own layers. No image model, no GPU.

``poc/keyframes.py`` composed the E0 keyframes the same way: the set still fitted to
the frame, each cast cutout placed by the layout preset with its shadow (no motion), the
foreground edge, and the camera framing at its end. :func:`compose_photo` does that from
named inputs (:class:`PhotoInputs`), so a changed cast still, set, layout or framing
gives a new photo and the same inputs give the same bytes (a PNG with no metadata,
within one Pillow build). :func:`photo_inputs` takes them from a story and board;
:attr:`PhotoInputs.signature` names them, for story 407's "photo stale" state.

What the photo is not: a build input (the build never reads it, section 5), or a
promise about a frame of the film (the film's dolls move and its set may loop).
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, BinaryIO

import numpy as np
import PIL
import PIL.Image

from haynes_studio.adapters.errors import AdapterError
from haynes_studio.canonical.model import Board, CameraCue, Story
from haynes_studio.jsonio import freeze, thaw
from haynes_studio.layered import compose
from haynes_studio.layered.errors import CLIP_INVALID, LAYOUT_INVALID, UNSUPPORTED, LayeredError
from haynes_studio.layered.foreground import RoleMask, check_board_roles, draw_layers
from haynes_studio.layered.keyed import read_verified
from haynes_studio.layered.matte_size import MatteSize
from haynes_studio.matting.pixels import measure_shape
from haynes_studio.matting.profile import MatteError
from haynes_studio.render.delivery_profile import fit_set_plate
from haynes_studio.store import canonical_json

SCHEMA = "studio.layered-photo/v1"  # proposal: the photo's named inputs
COMPOSER = f"studio.layered.photo/1+pillow-{PIL.__version__}+numpy-{np.__version__}"
PNG = "image/png"


@dataclass(frozen=True)
class PhotoInputs:
    """Everything the photo is made from, by content hash and value."""

    width: int
    height: int
    set: str  # the set still's SHA-256
    cast: tuple[tuple[str, str], ...]  # (slot, cast still SHA-256) in draw order
    layout: Mapping[str, Any] = field(repr=False)  # the preset's values
    foreground: Mapping[str, Any] | None = None  # {edge_px, feather_px} or {roles}
    camera: Mapping[str, Any] | None = None  # the framing: {zoom, center_px}
    composer: str = COMPOSER
    matte_sizes: Mapping[str, Any] | None = None  # cast slot -> verified shape and target

    def document(self) -> dict[str, Any]:
        document = {"schema": SCHEMA, "width": self.width, "height": self.height, "set": self.set,
                    "cast": [{"slot": slot, "still": still} for slot, still in self.cast],
                    "layout": thaw(self.layout),
                    "foreground": None if self.foreground is None else thaw(self.foreground),
                    "camera": None if self.camera is None else thaw(self.camera),
                    "composer": self.composer}
        if self.matte_sizes:
            document["matte_sizes"] = thaw(self.matte_sizes)
        return document

    @property
    def signature(self) -> str:
        """``sha256:`` of the inputs' canonical JSON: equal exactly when the photo is."""
        return "sha256:" + hashlib.sha256(canonical_json(self.document())).hexdigest()


def photo_inputs(story: Story, board: Board, *, blobs: Mapping[str, str], width: int,
                 height: int, matte_sizes: Mapping[str, Any] | None = None,
                 roles: Sequence[RoleMask] = ()) -> PhotoInputs:
    """The photo inputs of a layered board: the story's set still, the board's cast
    stills in draw order, its layout preset's values, its foreground edge (when the
    board shows the foreground) and the end framing of its camera cue (the last one)."""
    if board.method.layer != "layered":
        raise LayeredError(UNSUPPORTED, "only a layered board's photo is composed (D51); a "
                           "whole-frame board's photo is generated", where="/method")
    if story.set is None or story.set.asset_version_id not in blobs:
        raise LayeredError(UNSUPPORTED, "the story has no set still to compose on", where="/set")
    if board.layout.preset not in story.layouts:
        raise LayeredError(UNSUPPORTED, f"layout preset {board.layout.preset!r} is not in the story")
    check_board_roles(board, roles, set_loop=bool(story.set.motion_asset_version_id))
    cast = []
    for entry in board.cast:
        if entry.asset_version_id not in blobs:
            raise LayeredError(UNSUPPORTED, f"cast still {entry.asset_version_id} is not resolved")
        cast.append((entry.slot, blobs[entry.asset_version_id]))
    foreground = None
    if board.layout.foreground and roles:
        foreground = {"roles": [role.draw_pin() for role in roles]}
    elif board.layout.foreground and story.set.foreground_edge_px is not None:
        foreground = {"edge_px": [list(p) for p in story.set.foreground_edge_px],
                      "feather_px": story.set.foreground_feather_px}
    cue = next((c for c in reversed(board.cues) if isinstance(c, CameraCue)), None)
    camera = None if cue is None else {"zoom": cue.zoom_to, "center_px": list(cue.center_px)}
    return PhotoInputs(width=width, height=height, set=blobs[story.set.asset_version_id],
                       cast=tuple(cast), layout=freeze(thaw(story.layouts[board.layout.preset])),
                       foreground=None if foreground is None else freeze(foreground),
                       camera=None if camera is None else freeze(camera),
                       matte_sizes=freeze(dict(matte_sizes)) if matte_sizes else None)


def _image(data: bytes, what: str) -> PIL.Image.Image:
    try:
        with PIL.Image.open(io.BytesIO(data)) as image:
            image.load()
            return image.copy()
    except Exception as error:  # Pillow raises its own error types for damaged files
        raise LayeredError(CLIP_INVALID, f"{what} does not decode: {type(error).__name__}") from error


def _place_still(cutout, slot, slot_name, frame_width, frame_height, matte):
    if matte is None:
        art = compose.sprite(cutout, slot)
        return art, compose.place(art.size, slot, frame_width, slot_name)
    if slot.crop is not None:
        raise LayeredError(LAYOUT_INVALID, "A size-matched cast still cannot use a layout crop")
    target = matte["target_height_px"]
    if target > frame_height:
        raise LayeredError("matting.target_exceeds_frame",
                           f"Slot {slot_name!r} target height {target} px exceeds frame height {frame_height} px")
    try:
        measured = measure_shape(np.asarray(cutout.getchannel("A")), target)
        if measured != thaw(matte["shape"]):
            raise LayeredError(CLIP_INVALID, "The cast matte differs from its pinned measurement")
        size = MatteSize.measured(measured, cutout.size, target)
    except (MatteError, AdapterError):
        raise LayeredError(CLIP_INVALID, "The cast matte has invalid silhouette geometry") from None
    art, silhouette, inset = size.sprite(cutout)
    where = compose.place(art.size, slot, frame_width, slot_name, silhouette=silhouette, inset=inset)
    if where.y < 0:
        # The plate would cut the doll at the top of the frame without saying so.
        raise LayeredError("matting.target_exceeds_frame",
                           f"Slot {slot_name!r} target height {target} px does not fit above its bottom "
                           f"line at {slot.bottom:g} px")
    return art, where


def compose_photo(inputs: PhotoInputs, read: Callable[[str], BinaryIO]) -> bytes:
    """The photo as PNG bytes. Every still and role mask is read by its pinned hash."""
    size = inputs.width, inputs.height
    still = _image(read_verified(read, inputs.set, "the set still"), "the set still")
    background = fit_set_plate(still.convert("RGB"), size)
    layout = thaw(inputs.layout)

    def dolls():
        for slot_name, digest in inputs.cast:
            cutout = _image(read_verified(read, digest, f"slot {slot_name}'s still"),
                            f"slot {slot_name}'s still").convert("RGBA")
            matte = (inputs.matte_sizes or {}).get(slot_name)
            if matte is None and cutout.getextrema()[3][0] != 0:
                raise LayeredError(UNSUPPORTED, f"slot {slot_name}'s still has no transparent pixel; "
                                   "a layered cast still is an RGBA cutout")
            slot = compose.slot_of(layout, slot_name)
            art, where = _place_still(cutout, slot, slot_name, *size, matte)
            plate = compose.plate(art, where, *size)
            yield plate, compose.shadow(plate), where.pivot, 0, 0, 0

    foreground = inputs.foreground or {}
    roles = ()
    legacy_alpha = None
    if "roles" in foreground:
        roles = draw_layers(foreground["roles"], read, still.size, size)
    elif foreground:
        legacy_alpha = compose.foreground_alpha(foreground["edge_px"], foreground.get("feather_px"), *size)
    out = compose.composite(background, dolls(), roles=roles, legacy_alpha=legacy_alpha)
    camera = inputs.camera
    if camera is not None:
        out = compose.camera(out, {"start_ms": 0, "duration_ms": 0, "zoom_from": camera["zoom"],
                                   "zoom_to": camera["zoom"], "center_px": camera["center_px"]}, 0.0)
    buffer = io.BytesIO()
    out.save(buffer, format="PNG")
    return buffer.getvalue()


def stills(inputs: PhotoInputs) -> Sequence[str]:
    """Every image the photo reads, by hash: the set, cast, then role masks."""
    roles = (inputs.foreground or {}).get("roles", ())
    return (inputs.set, *(still for _, still in inputs.cast), *(role["sha256"] for role in roles))


__all__ = ["COMPOSER", "PNG", "PhotoInputs", "SCHEMA", "compose_photo", "photo_inputs", "stills"]
