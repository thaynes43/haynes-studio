"""Pixel evidence from the production photo and film entry points."""

import hashlib
import io
from dataclasses import replace

import numpy as np
import pytest
from PIL import Image

from haynes_studio.canonical.model import Board
from haynes_studio.layered import visibility
from haynes_studio.layered.keyed import SCHEMA, _frame_png, write_apng
from haynes_studio.layered.photo import PhotoInputs, PhotoScene, compose_photo
from haynes_studio.layered.renderer import LayeredRenderer
from haynes_studio.render.base import SegmentRequest
from tests.build_story.fixtures import B2, story_document

SIZE = (64, 48)
BOX = (10, 10, 30, 30)


def png(image):
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


class Images(dict):
    def add(self, data):
        digest = hashlib.sha256(data).hexdigest()
        self[digest] = data
        return digest

    def open(self, digest):
        return io.BytesIO(self[digest])


def scene(*, foreground_right, order=30, zoom=None, translucent=False, two=False, set_size=SIZE):
    images = Images()
    background = images.add(png(Image.new("RGB", set_size)))
    a = Image.new("RGBA", SIZE)
    if translucent:
        a.paste((0, 0, 0, 211), (5, 6, 36, 39))
    a.paste((255, 0, 0, 133 if translucent else 255), BOX)
    cast = [("a", images.add(png(a)))]
    if two:
        b = Image.new("RGBA", SIZE)
        b.paste((0, 0, 0, 255), (20, 10, 35, 30))
        cast.append(("b", images.add(png(b))))
    foreground = None
    if foreground_right is not None:
        mask = Image.new("L", set_size)
        mask.paste(255, (0, 0, foreground_right, set_size[1]))
        pin = {"key": "table", "layer_order": order, "sha256": images.add(png(mask))}
        foreground = {"roles": [pin]}
    layout = {"height": 41 if translucent else 48, "bottom": 46 if translucent else 48,
              "slots": {slot: {"x": .5} for slot, _ in cast}}
    camera = None if zoom is None else {"zoom": zoom, "center_px": [16, 12]}
    inputs = PhotoInputs(*SIZE, background, tuple(cast), layout, foreground, camera=camera)
    doc = next(board for board in story_document()["boards"] if board["id"] == B2)
    doc["cast"] = doc["cast"][: len(cast)]
    doc["layout"]["check_poses"] = [
        {"key": "reference", "frame": 0, "targets": [{"slot": "a", "box_xyxy": list(BOX)}]},
    ]
    return images, inputs, Board.from_document(doc)


@pytest.mark.parametrize(("right", "order", "zoom", "two", "source_size", "status"), [
    (16, 30, None, False, SIZE, "uncertain"),
    (32, 30, None, False, SIZE, "hidden"),
    (32, 5, None, False, SIZE, "visible"),
    (14, 15, None, True, SIZE, "hidden"),
    (24, 15, 2, False, (80, 48), "uncertain"),
    (9, 30, .8, False, SIZE, "visible"),
])
def test_bounds_match_unmodified_photo_pixels(right, order, zoom, two, source_size, status):
    images, inputs, board = scene(foreground_right=right, order=order, zoom=zoom, two=two,
                                  set_size=source_size)
    [result] = visibility.measure(PhotoScene(inputs, images.open), board)
    with Image.open(io.BytesIO(compose_photo(inputs, images.open))) as frame:
        rgb = np.asarray(frame)
        count = int((rgb[..., 0] >= visibility.PIXEL_FLOOR).sum())
        assert hashlib.sha256(frame.tobytes()).hexdigest() == result["reference_rgb_sha256"]
    assert result["lower_visible_px"] == result["upper_visible_px"] == count
    assert result["status"] == status


def test_photo_keeps_source_alpha_outside_the_target_and_uses_its_stock_shadows():
    images, inputs, board = scene(foreground_right=None, translucent=True)
    [result] = visibility.measure(PhotoScene(inputs, images.open), board)
    with Image.open(io.BytesIO(compose_photo(inputs, images.open))) as frame:
        count = int((np.asarray(frame)[..., 0] >= visibility.PIXEL_FLOOR).sum())
    assert count == result["lower_visible_px"] == result["upper_visible_px"] == 222
    assert result["target_px"] == 289
    assert result["status"] == "uncertain"


def test_reference_photo_ignores_cast_moves_and_uses_the_camera_end():
    images, inputs, board = scene(foreground_right=None, zoom=2)
    from haynes_studio.canonical import load_story
    from haynes_studio.layered.photo import photo_inputs
    document = story_document()
    chosen = next(item for item in document["boards"] if item["id"] == B2)
    chosen["cues"] = [
        {"id": "cue_01JB4060000000000000000001", "type": "move", "slot": "a",
         "anchor": {"at_ms": 0}, "duration_ms": 300, "dx_px": -64, "dy_px": 0,
         "angle_deg": 20, "steps": 3},
        {"id": "cue_01JB4060000000000000000002", "type": "camera", "anchor": {"at_ms": 0},
         "duration_ms": 300, "zoom_from": 1, "zoom_to": 2, "center_px": [16, 12],
         "easing": "ease_out_cubic"},
    ]
    chosen["cast"] = chosen["cast"][:1]
    document["layouts"]["pair"] = inputs.layout
    story = load_story(document)
    moving = next(item for item in story.boards if item.id == B2)
    planned = photo_inputs(story, moving, blobs={
        story.set.asset_version_id: inputs.set, moving.cast[0].asset_version_id: inputs.cast[0][1],
    }, width=SIZE[0], height=SIZE[1])
    assert planned.camera["zoom"] == 2
    [check] = visibility.measure(PhotoScene(planned, images.open), board)
    with Image.open(io.BytesIO(compose_photo(planned, images.open))) as frame:
        assert int((np.asarray(frame)[..., 0] >= visibility.PIXEL_FLOOR).sum()) == check["lower_visible_px"]
    assert check["lower_visible_px"] > 400


def test_film_renderer_draws_the_same_role_between_cast_layers():
    images, inputs, _ = scene(foreground_right=24, order=15, two=True, set_size=(80, 48))
    # Give the higher cast a distinct opaque colour to verify the depth ordering.
    b = Image.new("RGBA", SIZE)
    b.paste((0, 220, 0, 255), (20, 10, 35, 30))
    inputs = replace(inputs, cast=(inputs.cast[0], ("b", images.add(png(b)))))
    layers = []
    for slot, still in inputs.cast:
        with Image.open(images.open(still)) as image:
            header, pixels = _frame_png(np.asarray(image))
        record = {"schema": SCHEMA, "box": [0, 0, *SIZE], "frames": 1}
        keyed = images.add(write_apng([pixels], header, record, 24))
        layers.append({"slot": slot, "still": still, "clip": keyed, "keyed": keyed,
                       "decal_min_ecc": None, "role": "doll", "phase": 0, "play": "loop",
                       "trim_start": 0, "trim_frames": 1, "source_fps": 24, "clip_frames": 1})
    request = SegmentRequest(key="role-fixture", inputs={
        "method": {"layer": "layered", "motion": "i2v"}, "fps": 24, "frames": 1,
        "width": SIZE[0], "height": SIZE[1], "layers": layers, "layout": inputs.layout,
        "set_layer": {"plate": inputs.set}, "motion_style": {"idle_scale": 0},
        "foreground": inputs.foreground,
    }, open_input=images.open)
    [rendered] = LayeredRenderer().render(request)
    with Image.open(io.BytesIO(compose_photo(inputs, images.open))) as photo:
        assert np.array_equal(rendered, np.asarray(photo))
    assert rendered[16, 25, 1] == 220
    assert rendered[16, 12, 0] == 0
    assert rendered[16, 18, 0] > 240


@pytest.mark.parametrize(("lower", "upper", "verdict"), [
    (0, 200, "hidden"), (0, 201, "uncertain"),
    (340, 390, "visible"), (339, 400, "uncertain"),
])
def test_verdict_uses_conservative_inclusive_bounds(lower, upper, verdict):
    assert visibility.verdict(lower, upper, 400) == verdict


def test_matte_support_uses_the_same_original_crop_and_handles_transparent_padding():
    from haynes_studio.matting.pixels import measure_shape

    images, inputs, board = scene(foreground_right=None)
    matte = Image.new("RGBA", (96, 96))
    matte.paste((255, 0, 0, 255), (16, 16, 80, 80))
    shape = measure_shape(np.asarray(matte.getchannel("A")), 64)
    inputs = replace(inputs, cast=(("a", images.add(png(matte))),), width=96, height=96,
                     layout={"height": 64, "bottom": 80, "x": .5},
                     matte_sizes={"a": {"target_height_px": 64, "shape": shape}})
    pose = {"key": "padding", "frame": 0, "targets": [{"slot": "a", "box_xyxy": [0, 0, 8, 8]}]}
    board = replace(board, layout=replace(board.layout, check_poses=(pose,)))
    [result] = visibility.measure(PhotoScene(inputs, images.open), board)
    assert result["status"] == "hidden"
    assert result["target_px"] == result["upper_visible_px"] == 0
