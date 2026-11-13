"""A layered board's photo (D51, story 426): deterministic, made from named inputs,
following every one of them."""

from __future__ import annotations

import copy
import io

import numpy as np
import PIL.Image
import pytest

from haynes_studio.canonical import load_story
from haynes_studio.jsonio import thaw
from haynes_studio.layered import compose_photo, photo_inputs, reader
from haynes_studio.layered.errors import UNSUPPORTED, LayeredError
from haynes_studio.layered.photo import PhotoInputs
from tests.cache import fixtures as fx
from tests.cache.fixtures import PRODUCTION
from tests.layered import helpers as h
from tests.layered import media


def inputs(world, document, board_id=h.B1) -> PhotoInputs:
    story = load_story(copy.deepcopy(document), context="write", source="photo")
    board = next(b for b in story.boards if b.id == board_id)
    return photo_inputs(story, board, blobs=world.blobs, width=360, height=640)


def photo(world, made: PhotoInputs) -> np.ndarray:
    data = compose_photo(made, reader(world.store, [PRODUCTION]))
    with PIL.Image.open(io.BytesIO(data)) as image:
        assert image.size == (360, 640) and not image.info  # no metadata in the bytes
        return np.asarray(image.convert("RGB"))


def test_the_photo_is_the_set_and_the_cast_cutouts_in_the_layout(world):
    made = inputs(world, h.story_document())
    assert made.set == world.blobs[h.PLATE]
    assert made.cast == tuple((s, world.blobs[h.STILL[s]]) for s in "abc")
    assert thaw(made.layout) == h.LAYOUTS["trio"] and made.foreground is None and made.camera is None
    pixels = photo(world, made)
    # Each cutout's colour (red, green, blue rectangles) stands at its slot's x.
    for slot, channel in zip("abc", range(3)):
        x = round(h.LAYOUTS["trio"]["slots"][slot]["x"] * 360)
        assert pixels[480, x, channel] > 150 and pixels[480, x].argmax() == channel, slot


def test_the_same_inputs_give_the_same_bytes(world):
    made = inputs(world, h.story_document())
    read = reader(world.store, [PRODUCTION])
    assert compose_photo(made, read) == compose_photo(inputs(world, h.story_document()), read)


def test_a_changed_still_set_layout_or_framing_gives_a_new_photo(world):
    base = inputs(world, h.story_document())
    still = h.story_document()
    fx.board_of(still, h.B1)["cast"][0]["asset_version_id"] = h.STILL2["a"]
    layout = h.story_document()
    layout["layouts"]["trio"]["slots"]["b"]["x"] = 0.55
    plate = copy.deepcopy(h.story_document())
    plate["set"]["asset_version_id"] = h.STILL["c"]  # any other still as the set
    framed = h.story_document(foreground=True)
    fx.board_of(framed, h.B1)["cues"] = [
        {"id": fx.ident("cue", 1), "type": "camera", "anchor": {"at_ms": 0}, "duration_ms": 200,
         "zoom_from": 1.0, "zoom_to": 1.3, "center_px": [180, 420], "easing": "ease_out_cubic"}]
    reference = photo(world, base)
    for document in (still, layout, plate, framed):
        made = inputs(world, document)
        assert made.signature != base.signature
        assert not np.array_equal(photo(world, made), reference)
    note = h.story_document()
    fx.board_of(note, h.B1)["notes"] = [{"id": fx.ident("nte", 1), "text": "a direction"}]
    fx.board_of(note, h.B1)["seeds"]["s2v:a"] = 99  # a re-roll changes clips, not the photo
    assert inputs(world, note).signature == base.signature


def test_only_a_layered_board_with_cutouts_has_a_composed_photo(world):
    document = h.story_document()
    board = fx.board_of(document, h.B2)
    board.update(method={"layer": "whole_frame", "motion": "i2v"}, cast=[], lines=[],
                 seeds={"i2v:frame": 1}, timing={"lead_ms": None, "tail_ms": None, "hold_ms": 1000},
                 voice={"style": None, "current_version_id": None})
    with pytest.raises(LayeredError) as whole:
        inputs(world, document, h.B2)
    assert whole.value.code == UNSUPPORTED
    opaque = inputs(world, h.story_document())
    opaque = PhotoInputs(**{**opaque.__dict__, "cast": (("a", world.blobs[h.PLATE]),)})
    with pytest.raises(LayeredError) as flat:
        compose_photo(opaque, reader(world.store, [PRODUCTION]))
    assert flat.value.code == UNSUPPORTED


def test_a_photo_reads_no_clip_and_needs_no_motion_record(world):
    """The photo is composed from stills alone: a board whose cast has no loop yet
    still has its photo (the build would refuse the board, not the photo)."""
    made = inputs(world, h.story_document())
    seen = []
    base = reader(world.store, [PRODUCTION])

    def read(sha256):
        seen.append(sha256)
        return base(sha256)
    compose_photo(made, read)
    assert seen == [made.set, *(still for _, still in made.cast)]
    assert media.CLIP_W  # media is synthetic and made at test time
