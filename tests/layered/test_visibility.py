"""Compare renderer measurements with independently counted film pixels."""

from hashlib import sha256
import json
from types import SimpleNamespace

import numpy as np
from PIL import Image
import pytest

from haynes_studio.build.visibility import visibility_check
from haynes_studio.cache import ArtifactCache, make_key
from haynes_studio.cache.build import PictureBuilder
from haynes_studio.cache.errors import CacheError
from haynes_studio.cache.keys import SEGMENT
from haynes_studio.layered.keyed import SCHEMA, _frame_png, write_apng
from haynes_studio.layered.renderer import COMPOSITOR, LayeredRenderer
from haynes_studio.render.base import SegmentRequest
from haynes_studio.render.encode import EncoderSettings
from haynes_studio.render.visibility import VISIBILITY_VERSION, verdict
from haynes_studio.store import LocalStore
from tests.build_story import fixtures as f
from tests.layered.test_foreground_roles import Images, RED_BOX, SIZE, png


def segment(cover=None, *, cover_next=None, x=.5, mask=None, camera=False):
    images = Images()
    plate = images.add(png(Image.new("RGB", SIZE)))

    def cast(slot, boxes, color):
        frames = []
        for box in boxes:
            art = Image.new("RGBA", SIZE)
            art.paste(color, box)
            header, pixels = _frame_png(np.asarray(art))
            frames.append(pixels)
        count = len(frames)
        record = {"schema": SCHEMA, "box": [0, 0, *SIZE], "frames": count}
        keyed = images.add(write_apng(frames, header, record, 24))
        still = Image.new("RGBA", SIZE)
        # In slot b, the reference still stays clear even when its keyed frame hides a.
        still.paste(color, boxes[0] if slot == "a" else (0, 0, 5, 5))
        return {"slot": slot, "still": images.add(png(still)), "clip": keyed, "keyed": keyed,
                "decal_min_ecc": None, "role": "doll", "phase": 0, "play": "loop",
                "trim_start": 0, "trim_frames": count, "source_fps": 24, "clip_frames": count}

    layers = [cast("a", (RED_BOX,), (255, 0, 0, 255))]
    if cover is not None:
        boxes = (cover,) if cover_next is None else (cover, cover_next)
        layers.append(cast("b", boxes, (0, 220, 0, 255)))
    foreground = None
    if mask is not None:
        alpha = Image.new("L", SIZE)
        alpha.paste(255, mask)
        foreground = {"roles": [{"key": "rail", "layer_order": 30, "sha256": images.add(png(alpha)),
                                  "width": SIZE[0], "height": SIZE[1]}]}
    cues = [] if not camera else [{
        "type": "camera", "start_ms": 0, "duration_ms": 0, "zoom_from": 2, "zoom_to": 2,
        "center_px": [16, 12], "easing": "ease_out_cubic",
    }]
    return SegmentRequest(key="visibility-fixture", inputs={
        "method": {"layer": "layered", "motion": "i2v"}, "fps": 24, "frames": 3,
        "width": SIZE[0], "height": SIZE[1], "layers": layers,
        "layout": {"height": SIZE[1], "bottom": SIZE[1], "slots": {"a": {"x": x}, "b": {"x": .5}}},
        "set_layer": {"plate": plate}, "motion_style": {"idle_scale": 0},
        "foreground": foreground, "cues": cues,
    }, open_input=images.open)


@pytest.mark.parametrize(("options", "expected"), [
    ({}, (480, 480)),
    ({"cover": (0, 0, 17, 48)}, (480, 340)),
    ({"cover": (0, 0, 35, 48)}, (480, 0)),
    ({"mask": (0, 0, 22, 48)}, (480, 240)),
    ({"x": .25, "cover": (0, 0, 7, 48)}, (360, 220)),
    ({"x": -.2}, (0, 0)),
    ({"camera": True, "mask": (0, 0, 15, 48)}, (1232, 952)),
], ids=["visible", "keyed-part", "keyed-hidden", "foreground-mask", "edge", "offscreen", "camera"])
def test_counts_match_the_film_and_the_same_frame_with_only_the_target(options, expected):
    original = segment(**options)
    inputs = original.inputs
    declaration = {"slot": "a", "frames": [2, 0], "version": VISIBILITY_VERSION}
    request = SegmentRequest(original.key, {**inputs, "visibility": declaration}, original.open_input)
    renderer = LayeredRenderer()
    actual = list(renderer.render(request))
    counted = json.loads(renderer.visibility_evidence(request.key))
    baseline = list(LayeredRenderer().render(original))
    assert all(np.array_equal(measured, legacy) for measured, legacy in zip(actual, baseline, strict=True))
    alone = list(LayeredRenderer().render(SegmentRequest(
        original.key, {**inputs, "layers": inputs["layers"][:1], "foreground": None},
        original.open_input,
    )))
    assert [row["frame"] for row in counted] == [0, 2]
    for row in counted:
        frame = row["frame"]
        oracle = (np.count_nonzero(alone[frame][..., 0] >= 128), np.count_nonzero(actual[frame][..., 0] >= 128))
        assert oracle == expected
        assert (row["unoccluded_pixels"], row["visible_pixels"]) == oracle
        assert row["frame_sha256"] == sha256(actual[frame].tobytes()).hexdigest()


def test_adjacent_board_frames_can_draw_different_keyed_pixels():
    original = segment(cover=(0, 0, 5, 48), cover_next=(0, 0, 35, 48))
    inputs = {**original.inputs, "visibility": {"slot": "a", "frames": [0, 1], "version": VISIBILITY_VERSION}}
    renderer = LayeredRenderer()
    frames = list(renderer.render(SegmentRequest(original.key, inputs, original.open_input)))
    measured = json.loads(renderer.visibility_evidence(original.key))
    expected = [(0, 480), (1, 0)]
    assert [(row["frame"], row["visible_pixels"]) for row in measured] == expected
    assert [(n, np.count_nonzero(frames[n][..., 0] >= 128)) for n, _ in expected] == expected


@pytest.mark.parametrize(("support", "lower", "upper", "expected"), [
    (100, 0, 50, "hidden"),
    (100, 85, 100, "visible"),
    (100, 84, 100, "uncertain"),
    (100, 0, 51, "uncertain"),
    (100, 60, 60, "uncertain"),
    (0, 0, 0, "uncertain"),
])
def test_verdict_bounds(support, lower, upper, expected):
    assert verdict(support, lower, upper) == expected


def test_cached_segment_carries_its_visibility_evidence(tmp_path):
    store = LocalStore(tmp_path)
    original = segment(cover=(0, 0, 17, 48))
    key = make_key(SEGMENT, {
        **original.inputs, "compositor": COMPOSITOR, "encoder": EncoderSettings().key_inputs(),
        "visibility": {"slot": "a", "frames": [0], "version": VISIBILITY_VERSION},
    })
    cache = ArtifactCache(store, production_id=f.PRODUCTION, run_id=f.ident("run", 93))
    builder = PictureBuilder(cache, LayeredRenderer(), open_input=original.open_input)
    made = builder.segment(key)
    with pytest.raises(CacheError, match="visibility evidence"):
        cache.commit(key, b"segment without its evidence", "video/mp4")
    other = ArtifactCache(store, production_id=f.PRODUCTION, run_id=f.ident("run", 94),
                          earlier_runs=(cache.run_id,))
    assert other.lookup(key, "video/mp4").hit
    board = SimpleNamespace(board_id=f.ident("brd", 95), segment=SimpleNamespace(key=key, content=made.sha256))
    check = visibility_check(other, board, {})
    assert check["result"] == "fail" and check["measured"]["verdict"] == "uncertain"
    assert check["measured"]["poses"][0]["lower_visible_pixels"] == 340
