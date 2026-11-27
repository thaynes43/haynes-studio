"""Independent pixel regressions through the production photo and film paths."""

import hashlib
import io
from dataclasses import replace

import numpy as np
import pytest
from PIL import Image

from haynes_studio.layered.keyed import SCHEMA, _frame_png, write_apng
from haynes_studio.layered.photo import PhotoInputs, compose_photo
from haynes_studio.layered.renderer import LayeredRenderer
from haynes_studio.render.base import SegmentRequest

SIZE = (64, 48)
RED_BOX = (10, 10, 34, 30)


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


def scene(*, right, order=30, source_size=SIZE, red_box=RED_BOX, green_box=None, camera=None, interior=False):
    images = Images()
    background = images.add(png(Image.new("RGB", source_size)))
    red = Image.new("RGBA", SIZE)
    red.paste((255, 0, 0, 255), red_box)
    cast = [("a", images.add(png(red)))]
    if green_box is not None:
        green = Image.new("RGBA", SIZE)
        green.paste((0, 220, 0, 255), green_box)
        cast.append(("b", images.add(png(green))))
    mask = Image.new("L", source_size)
    mask.paste(255, (15, 15, 20, 20) if interior else (0, 0, right, source_size[1]))
    pin = {"key": "table", "layer_order": order, "sha256": images.add(png(mask)),
           "width": source_size[0], "height": source_size[1]}
    layout = {"height": SIZE[1], "bottom": SIZE[1],
              "slots": {slot: {"x": .5} for slot, _ in cast}}
    return images, PhotoInputs(*SIZE, background, tuple(cast), layout, {"roles": [pin]}, camera)


def photo_and_film(images, inputs):
    """Use identical still and keyed pixels, without a visibility measurement path."""
    layers = []
    for slot, still in inputs.cast:
        with Image.open(images.open(still)) as image:
            header, pixels = _frame_png(np.asarray(image))
        record = {"schema": SCHEMA, "box": [0, 0, *SIZE], "frames": 1}
        keyed = images.add(write_apng([pixels], header, record, 24))
        layers.append({"slot": slot, "still": still, "clip": keyed, "keyed": keyed,
                       "decal_min_ecc": None, "role": "doll", "phase": 0, "play": "loop",
                       "trim_start": 0, "trim_frames": 1, "source_fps": 24, "clip_frames": 1})
    camera = inputs.camera
    cues = [] if camera is None else [{
        "type": "camera", "start_ms": 0, "duration_ms": 0,
        "zoom_from": camera["zoom"], "zoom_to": camera["zoom"],
        "center_px": camera["center_px"], "easing": "ease_out_cubic",
    }]
    request = SegmentRequest(key="role-fixture", inputs={
        "method": {"layer": "layered", "motion": "i2v"}, "fps": 24, "frames": 1,
        "width": SIZE[0], "height": SIZE[1], "layers": layers, "layout": inputs.layout,
        "set_layer": {"plate": inputs.set}, "motion_style": {"idle_scale": 0},
        "foreground": inputs.foreground, "cues": cues,
    }, open_input=images.open)
    renderer = LayeredRenderer()
    [film] = renderer.render(request)
    with Image.open(io.BytesIO(compose_photo(inputs, images.open))) as photo:
        photo_pixels = np.asarray(photo)
    assert np.array_equal(film, photo_pixels)
    # Rendering roles changes pixels and cache inputs, not the persisted report shape.
    assert "foreground_roles" not in renderer.reports[request.key].set
    return photo_pixels, film


@pytest.mark.parametrize(("kwargs", "expected"), [
    # The 24 × 20 red rectangle is in front of this lower role.
    ({"right": 34, "order": 5}, 480),
    # The role covers nine columns: fifteen columns of twenty pixels remain.
    ({"right": 19}, 300),
    ({"right": 19, "interior": True}, 455),
    ({"right": 34}, 0),
    # The role covers one red column; the later green cast draws above the role.
    ({"right": 11, "order": 15, "green_box": (0, 10, 11, 30)}, 460),
    # An 80-wide set crops eight pixels on either side; its mask ends at frame x=22.
    ({"right": 30, "source_size": (80, 48)}, 240),
    # The 17 × 6 rectangle doubles in both dimensions with the camera framing.
    ({"right": 5, "red_box": (10, 10, 27, 16),
      "camera": {"zoom": 2, "center_px": [16, 12]}}, 408),
], ids=["role-behind-cast", "partial-cover", "interior-mask", "complete-cover", "role-between-cast",
        "cover-fit", "camera-framing"])
def test_synthetic_layouts_match_direct_photo_and_film_pixel_counts(kwargs, expected):
    images, inputs = scene(**kwargs)
    for rendered in photo_and_film(images, inputs):
        assert int(np.count_nonzero(rendered[..., 0] >= 128)) == expected


@pytest.mark.parametrize(("order", "expected_green"), [(10, 300), (20, 20)])
def test_a_role_at_cast_depth_draws_in_front_of_that_cast(order, expected_green):
    images, inputs = scene(right=34, order=order, green_box=(20, 10, 35, 30))
    for rendered in photo_and_film(images, inputs):
        assert int(np.count_nonzero(rendered[..., 0] >= 128)) == 0
        assert int(np.count_nonzero(rendered[..., 1] >= 128)) == expected_green


def test_photo_and_film_match_with_two_roles_at_different_depths():
    images, inputs = scene(right=19, order=10, green_box=(20, 10, 35, 30))
    mask = Image.new("L", SIZE)
    mask.paste(255, (30, 0, SIZE[0], SIZE[1]))
    second = {"key": "rail", "layer_order": 20, "sha256": images.add(png(mask)),
              "width": SIZE[0], "height": SIZE[1]}
    inputs = replace(inputs, foreground={"roles": [second, *inputs.foreground["roles"]]})
    photo, _ = photo_and_film(images, inputs)
    assert int(np.count_nonzero(photo[..., 0] >= 128)) == 20
    assert int(np.count_nonzero(photo[..., 1] >= 128)) == 200
