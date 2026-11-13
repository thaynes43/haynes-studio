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
import PIL.ImageOps

from haynes_studio.canonical.model import Board, CameraCue, Story
from haynes_studio.jsonio import freeze, thaw
from haynes_studio.layered import compose
from haynes_studio.layered.errors import CLIP_INVALID, UNSUPPORTED, LayeredError
from haynes_studio.layered.keyed import read_verified
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
    foreground: Mapping[str, Any] | None = None  # {edge_px, feather_px}
    camera: Mapping[str, Any] | None = None  # the framing: {zoom, center_px}
    composer: str = COMPOSER

    def document(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "width": self.width, "height": self.height, "set": self.set,
                "cast": [{"slot": slot, "still": still} for slot, still in self.cast],
                "layout": thaw(self.layout),
                "foreground": None if self.foreground is None else thaw(self.foreground),
                "camera": None if self.camera is None else thaw(self.camera),
                "composer": self.composer}

    @property
    def signature(self) -> str:
        """``sha256:`` of the inputs' canonical JSON: equal exactly when the photo is."""
        return "sha256:" + hashlib.sha256(canonical_json(self.document())).hexdigest()


def photo_inputs(story: Story, board: Board, *, blobs: Mapping[str, str], width: int,
                 height: int) -> PhotoInputs:
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
    cast = []
    for entry in board.cast:
        if entry.asset_version_id not in blobs:
            raise LayeredError(UNSUPPORTED, f"cast still {entry.asset_version_id} is not resolved")
        cast.append((entry.slot, blobs[entry.asset_version_id]))
    foreground = None
    if board.layout.foreground and story.set.foreground_edge_px is not None:
        foreground = {"edge_px": [list(p) for p in story.set.foreground_edge_px],
                      "feather_px": story.set.foreground_feather_px}
    cue = next((c for c in reversed(board.cues) if isinstance(c, CameraCue)), None)
    camera = None if cue is None else {"zoom": cue.zoom_to, "center_px": list(cue.center_px)}
    return PhotoInputs(width=width, height=height, set=blobs[story.set.asset_version_id],
                       cast=tuple(cast), layout=freeze(thaw(story.layouts[board.layout.preset])),
                       foreground=None if foreground is None else freeze(foreground),
                       camera=None if camera is None else freeze(camera))


def _image(data: bytes, what: str) -> PIL.Image.Image:
    try:
        with PIL.Image.open(io.BytesIO(data)) as image:
            image.load()
            return image.copy()
    except Exception as error:  # Pillow raises its own error types for damaged files
        raise LayeredError(CLIP_INVALID, f"{what} does not decode: {type(error).__name__}") from error


def compose_photo(inputs: PhotoInputs, read: Callable[[str], BinaryIO]) -> bytes:
    """The photo as PNG bytes (see the module docstring). ``read`` opens a still by
    hash; every still is re-hashed. A cast still with no transparent pixel is not a
    cutout (``layered.unsupported``)."""
    width, height = inputs.width, inputs.height
    background = PIL.ImageOps.fit(_image(read_verified(read, inputs.set, "the set still"), "the set still")
                                  .convert("RGB"), (width, height), method=PIL.Image.Resampling.LANCZOS)
    frame = background.convert("RGBA")
    layout = thaw(inputs.layout)
    for slot_name, still in inputs.cast:
        cutout = _image(read_verified(read, still, f"slot {slot_name}'s still"),
                        f"slot {slot_name}'s still").convert("RGBA")
        if cutout.getextrema()[3][0] != 0:
            raise LayeredError(UNSUPPORTED, f"slot {slot_name}'s still has no transparent pixel; a "
                               "layered cast still is an RGBA cutout")
        slot = compose.slot_of(layout, slot_name)
        art = compose.sprite(cutout, slot)
        where = compose.place(art.size, slot, width, slot_name)
        plate = compose.plate(art, where, width, height)
        compose.draw(frame, plate, compose.shadow(plate), where.pivot, 0, 0, 0)
    if inputs.foreground is not None:
        frame.alpha_composite(compose.foreground(background, compose.foreground_alpha(
            inputs.foreground["edge_px"], inputs.foreground.get("feather_px"), width, height)))
    out = frame.convert("RGB")
    if inputs.camera is not None:
        out = compose.camera(out, {"start_ms": 0, "duration_ms": 0, "zoom_from": inputs.camera["zoom"],
                                   "zoom_to": inputs.camera["zoom"],
                                   "center_px": inputs.camera["center_px"]}, 0.0)
    buffer = io.BytesIO()
    out.save(buffer, format="PNG")
    return buffer.getvalue()


def stills(inputs: PhotoInputs) -> Sequence[str]:
    """Every still the photo reads, by hash: the set, then the cast in draw order."""
    return (inputs.set, *(still for _, still in inputs.cast))


__all__ = ["COMPOSER", "PNG", "PhotoInputs", "SCHEMA", "compose_photo", "photo_inputs", "stills"]
