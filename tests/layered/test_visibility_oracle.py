"""Compare measured coverage with pixels from the actual board photo compositor."""

from dataclasses import replace
from io import BytesIO
from itertools import permutations
from random import Random

import numpy as np
from PIL import Image

from haynes_studio.canonical.model import to_document
from haynes_studio.layered import compose
from haynes_studio.layered.photo import compose_photo, photo_inputs
from haynes_studio.layered.visibility import PoseStill
from haynes_studio.segmentation.profile import digest
from tests.assets.test_occlusion import pins, png  # noqa: F401
from tests.cache import fixtures as fx
from tests.layered.test_visibility import (
    CAMERA, FACE, SIZE, box_hint, cutout, evaluated, library_image, observations, scene, world,  # noqa: F401
)

def _tagged(source, rectangle, *, opaque=False):
    """White marks only the target's supplied mask; black marks other sources."""
    image = Image.open(BytesIO(source))
    tag = Image.new("L", image.size)
    if rectangle is not None:
        tag.paste(255, rectangle)
    if image.mode == "RGB":
        return tag.convert("RGB")
    alpha = image.getchannel("A")
    if rectangle is not None:
        alpha = tag if opaque else Image.composite(alpha, tag, tag)
    tagged = tag.convert("RGBA")
    tagged.putalpha(alpha)
    return tagged


def _render(monkeypatch, story, pose, target, box, *, baseline=False, replacement=None, edge=None):
    """Use compose_photo with traced sources, supplying resolved moves at the draw call."""
    board, = story.boards
    stills = {}
    blobs = {}

    def bind(version, image):
        data = png(image)
        sha = digest(data)
        stills[sha], blobs[version] = data, sha

    bind(pose.plate.version_id, _tagged(pose.plate.data, box if target == "menu" else None))
    for key, still in pose.cutouts.items():
        bind(still.version_id, _tagged(still.data, box if key == target else None, opaque=baseline and key == target))
    inputs = photo_inputs(story, board, blobs=blobs, width=SIZE[0], height=SIZE[1])
    moves = dict(pose.moves)
    if baseline:
        inputs = replace(inputs, cast=tuple(item for item in inputs.cast if item[0] == target), foreground=None)
    if replacement is not None:
        key, art, move = replacement
        if art is None:
            inputs = replace(inputs, cast=tuple(item for item in inputs.cast if item[0] != key))
        else:
            bind(pose.cutouts[key].version_id, art)
            inputs = replace(
                inputs, cast=tuple((slot, blobs[pose.cutouts[slot].version_id]) for slot, _ in inputs.cast),
                layout={"slots": {**inputs.layout["slots"], key: {"x": .5, "height": SIZE[1], "bottom": SIZE[1]}}},
            )
            moves[key] = move
    if edge is not None:
        inputs = replace(inputs, foreground=None if edge is False else edge)

    draw = compose.draw
    remaining = iter(moves[key] for key, _ in inputs.cast)

    def trace(frame, plate, shadow, pivot, dx, dy, angle):
        # Shadows change lighting. The traced channel follows surface coverage.
        draw(frame, plate, Image.new("RGBA", shadow.size), pivot, *next(remaining))

    with monkeypatch.context() as patch:
        patch.setattr(compose, "draw", trace)
        encoded = compose_photo(inputs, lambda sha: BytesIO(stills[sha]))
    return np.asarray(Image.open(BytesIO(encoded)).getchannel("R")) >= 128


def _assert_result(check, counts, *, exact=False):
    measured = check["measured"]
    lower, upper, total = (measured[key] for key in ("visible_lower_pixels", "visible_upper_pixels", "total_pixels"))
    assert all(0 <= lower <= count <= upper <= total for count in counts), (measured, counts)
    if exact:
        assert lower == upper == counts[0], (measured, counts)
    expected = "hidden" if upper * 100 <= total * 50 else "visible" if lower * 100 >= total * 85 else "uncertain"
    assert measured["status"] == expected
    return expected


def test_generated_scenes_match_the_renderer_and_bound_unknown_layers(world, monkeypatch):
    prop_box = (13, 14, 37, 36)
    story, library, pose = scene(world, prop_depth="background", prop_box=prop_box)
    document = to_document(story)
    boxes = {"a": FACE, "b": (15, 7, 35, 30), "c": (12, 20, 36, 40), "menu": prop_box}
    cutouts = dict(pose.cutouts)
    entries = document["boards"][0]["cast"]
    for key, alpha in (("b", 176), ("c", 214)):
        asset, data = library_image(world[0], cutout(boxes[key], alpha=alpha), "cast", library=library,
                                    key=key, production_id=story.production_id)
        library = asset.library
        cutouts[key] = PoseStill(asset.version.id, data)
        entries.append({"slot": key, "asset_version_id": asset.version.id})
    pose = replace(pose, cutouts=cutouts, hints={("face", key): box_hint(boxes[key]) for key in cutouts})
    pose = observations(world, fx.load(document), library, pose)

    rng = Random(452)
    orders = list(permutations(entries))
    verdicts = set()
    positions_with_distinct_completions = set()
    for case in range(18):
        foreground = case % 3 != 0
        document["set"]["foreground_edge_px"] = [[0, rng.randint(15, 36)], [64, rng.randint(15, 36)]]
        document["set"]["foreground_feather_px"] = rng.choice([0, 3, 8])
        board = document["boards"][0]
        board["cast"] = list(orders[case % len(orders)])
        board["layout"]["foreground"] = foreground
        zoom = [1, 1, 1.35, 2][case % 4]
        board["cues"] = [{**CAMERA, "zoom_from": zoom, "zoom_to": zoom,
                          "center_px": [rng.randrange(16, 48), rng.randrange(16, 33)]}]
        slots = document["layouts"]["test"]["slots"]
        for key in cutouts:
            slots[key] = {"x": rng.choice([.3, .5, .65]), "height": rng.choice([35, 48, 59]),
                          "bottom": rng.choice([35, 48, 52])}
            if rng.randrange(3) == 0:
                slots[key]["crop"] = [.23, 0, .86, 1]
        story = fx.load(document)
        current = replace(pose, moves={key: (rng.randrange(-8, 9), rng.randrange(-6, 7),
                                              rng.choice([0, -12, -3.5, 4, 15])) for key in cutouts})
        support = {key: _render(monkeypatch, story, current, key, box, baseline=True)
                   for key, box in boxes.items()}

        def count(key, **options):
            rendered = _render(monkeypatch, story, current, key, boxes[key], **options)
            return int(np.count_nonzero(support[key] & rendered))

        checks = evaluated(world, story, library, {"still": current})
        known_counts = {}
        for check in checks:
            key = check["measured"]["target"]["key"]
            known_counts[key] = count(key)
            verdicts.add(_assert_result(check, [known_counts[key]], exact=True))

        for index, entry in enumerate(board["cast"]):
            key = entry["slot"]
            incomplete = replace(current, moves={slot: move for slot, move in current.moves.items() if slot != key})
            checks = evaluated(world, story, library, {"still": incomplete})
            completions = [
                None, cutout((0, 0, 64, 48), color=(0, 0, 0)),
                cutout((4, 8, 35, 35), alpha=165, color=(0, 0, 0)),
                cutout((20, 15, 58, 43), alpha=220, color=(0, 0, 0)),
            ]
            completions[1].putpixel((0, 0), (0, 0, 0, 0))
            for check in checks:
                target = check["measured"]["target"]["key"]
                if target == key:
                    assert check["measured"]["reason"] == "missing_or_invalid_move"
                    continue
                counts = [known_counts[target]]
                counts.extend(count(target, replacement=(key, art, move)) for art, move in
                              zip(completions, [(0, 0, 0), (0, 0, 0), (4, 1, -5), (-3, 2, 7)]))
                if counts[1] != counts[2]:
                    positions_with_distinct_completions.add(index)
                above_target = target == "menu" or index > next(
                    i for i, item in enumerate(board["cast"]) if item["slot"] == target)
                assert bool(check["measured"]["unknown_occluders"]) == above_target
                verdicts.add(_assert_result(check, counts, exact=not above_target))

        if foreground:
            invalid = replace(story, set=replace(story.set, foreground_edge_px=((0, float("nan")), (64, 25))))
            checks = evaluated(world, invalid, library, {"still": current})
            edges = [False, {"edge_px": [(0, -1), (64, -1)], "feather_px": 0},
                     {"edge_px": [(0, 20), (64, 34)], "feather_px": 4},
                     {"edge_px": [(0, 38), (64, 18)], "feather_px": 7}]
            for check in checks:
                target = check["measured"]["target"]["key"]
                counts = [known_counts[target], *(count(target, edge=edge) for edge in edges)]
                if counts[1] != counts[2]:
                    positions_with_distinct_completions.add("foreground")
                assert [entry["kind"] for entry in check["measured"]["unknown_occluders"]] == ["foreground"]
                verdicts.add(_assert_result(check, counts))
    assert verdicts == {"hidden", "uncertain", "visible"}
    assert positions_with_distinct_completions == {0, 1, 2, "foreground"}
