"""Exact pixel counts through real Stage observation receipts and synthetic geometry.

The fake graph returns declared rectangles. These tests measure the mapping and
pre-build behavior, without drawing conclusions about the model.
"""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageOps

from haynes_studio.build.prebuild import prepare
from haynes_studio.cache.plan import Toolchain
from haynes_studio.canonical.model import Line, to_document
from haynes_studio.errors import ContractError
from haynes_studio.layered.photo import compose_photo
from haynes_studio.layered.visibility import (
    CHECK, THRESHOLDS, PoseGeometry, PoseStill, evaluate_visibility, visibility_violations,
)
from haynes_studio.library import Library, Outcome
from haynes_studio.library.model import locator_for
from haynes_studio.photo.plan import plan_photo
from haynes_studio.render.delivery_profile import fit_set_plate
from haynes_studio.segmentation.backend import Engine
from haynes_studio.segmentation.service import listening
from haynes_studio.stages.preflight import PreflightError
from tests.assets.test_occlusion import (
    Journal, SIZE, factory, library_image, pins, run, world,  # noqa: F401
)
from tests.cache import fixtures as fx
from tests.canonical.fixtures import example
from tests.motion import fixtures as mf

FACE = (10, 10, 30, 30)
TABLE = (0, 36, 64, 48)
CAMERA = {"id": fx.ident("cue", 4), "type": "camera", "anchor": {"at_ms": 0},
          "duration_ms": 0, "zoom_from": 2, "zoom_to": 2,
          "center_px": [16, 12], "easing": "ease_out_cubic"}


def box_hint(box):
    return {"kind": "box", "xyxy": list(box)}


def cutout(box=FACE, *, alpha=255, color=(40, 90, 80)):
    still = Image.new("RGBA", SIZE)
    x0, y0, x1, y1 = box
    ImageDraw.Draw(still).rectangle((x0, y0, x1 - 1, y1 - 1), fill=(*color, alpha))
    return still


def declaration(table, prop_depth, prop_box, prop_id):
    foreground = [] if table is None else [
        {"key": "table", "label": "table", "layer_order": 30, "hint": box_hint(table)},
    ]
    if prop_depth is None:
        return {"foreground": foreground, "focal_props": []}
    focal = {"key": "menu", "label": "small menu", "depth": prop_depth, "hint": box_hint(prop_box)}
    if prop_depth == "background":
        focal["layer_order"] = 0
    elif prop_depth == "foreground":
        focal.update(layer_order=30, foreground_role="table")
    elif prop_depth == "separate":
        focal.update(layer_order=5, source_asset_version_id=prop_id)
    return {"foreground": foreground, "focal_props": [focal]}


def scene(world, *, focus=TABLE, face_alpha=255, prop_depth=None, prop_box=FACE,
          camera=None, slot_crop=None, legacy=False, second_pose=False, move=(0, 0, 0)):
    store, _, _ = world
    cast, rgba = library_image(store, cutout(alpha=face_alpha), "cast", production_id=fx.PRODUCTION)
    library = cast.library
    component = None
    if prop_depth == "separate":
        prop, prop_rgba = library_image(store, cutout(prop_box, color=(10, 40, 71)), "prop",
                                       library=library, production_id=fx.PRODUCTION)
        library = prop.library
        component = PoseStill(prop.version.id, prop_rgba)
    config = None if legacy else declaration(focus, prop_depth, prop_box,
                                             None if component is None else component.version_id)
    plate, rgb = library_image(store, Image.new("RGB", SIZE, (31, 90, 120)), "set", library=library,
                               config=config, production_id=fx.PRODUCTION)
    width, height = SIZE
    slot = {"x": 0.5, "height": height, "bottom": height}
    document = fx.story_document()
    document["layouts"] = {"test": {
        "slots": {"a": {**slot, **({} if slot_crop is None else {"crop": slot_crop})}, "menu": slot},
    }}
    board = fx._board(fx.B1, 1, title="Visibility", lines=[], cast=[("a", cast.version.id)],
                      preset="test", method=("layered", "i2v"), seeds={}, hold=1000,
                      cues=[] if camera is None else [camera])
    if not legacy:
        board["layout"]["check_poses"] = [{"key": "still", "frame": 0}]
        if second_pose:
            board["layout"]["check_poses"].append({"key": "wide", "frame": 12})
    document.update(boards=[board], board_order=[board["id"]], beds=[])
    document["set"].update(asset_version_id=plate.version.id, motion_asset_version_id=None,
                           foreground_edge_px=[[0, 9], [64, 9]] if legacy else None,
                           foreground_feather_px=1 if legacy else None)
    story = fx.load(document)
    cutouts = {"a": PoseStill(cast.version.id, rgba)}
    moves = {"a": move}
    if component is not None:
        cutouts["menu"] = component
        moves["menu"] = (0, 0, 0)
    pose = PoseGeometry(0, PoseStill(plate.version.id, rgb), cutouts, moves, {},
                        hints={("face", "a"): box_hint(FACE)})
    return story, plate.library, pose


def observations(world, story, library, pose):
    _, client, weights = world
    journal = Journal()
    config = library.version(story.set.asset_version_id).occlusion
    wanted = [("face", "a", pose.cutouts["a"], None, pose.hints["face", "a"])]
    wanted += [("foreground", layer["key"], pose.plate, layer["label"], layer.get("hint"))
               for layer in config["foreground"]]
    wanted += [("prop", prop["key"], pose.cutouts.get(prop["key"], pose.plate),
                prop["label"], prop.get("hint")) for prop in config["focal_props"]]
    ready = {}
    with Engine(client.scratch, weights, client.profile, factory=factory) as engine, listening(client.socket, engine):
        for kind, key, still, label, hint in wanted:
            version = Outcome(library, library.version(still.version_id), created=False)
            current = run(world, version, journal,
                          production_id=story.production_id, kind=kind, key=key, label=label, hint=hint)
            assert current is not None
            ready[kind, key] = current
    return replace(pose, observations=ready)


def evaluated(world, story, library, poses, *, size=SIZE):
    return evaluate_visibility(story, story.boards[0], library, frame_size=size, poses=poses,
                               profile_sha256=world[1].profile_sha256)


def counted(check):
    data = check["measured"]
    assert type(data["total_pixels"]) is type(data["visible_pixels"]) is int
    assert check["thresholds"] == THRESHOLDS
    return data["status"], data["visible_pixels"], data["total_pixels"]


@pytest.mark.parametrize(("foreground", "expected"), [
    (TABLE, ("visible", 400, 400)),
    (FACE, ("hidden", 0, 400)),
    ((10, 10, 17, 30), ("uncertain", 260, 400)),
    ((10, 10, 13, 30), ("visible", 340, 400)),
    ((10, 10, 20, 30), ("hidden", 200, 400)),
])
def test_exact_foreground_counts_and_floors(world, foreground, expected):
    story, library, pose = scene(world, focus=foreground)
    (result,) = evaluated(world, story, library, {"still": observations(world, story, library, pose)})
    assert counted(result) == expected
    assert result["measured"]["target"] == {"kind": "face", "key": "a"}
    assert result["measured"]["pose"] == {"key": "still", "frame": 0}
    assert result["measured"]["framing"] == {"size_px": [64, 48], "crop_xyxy": [0, 0, 64, 48]}
    assert {"layout", "pose", "profile", "plate", "layer:a", "foreground:table:mask",
            "foreground:table:result", "face:a:mask", "face:a:result"} == result["artifact_refs"].keys()
    if expected[0] == "uncertain":
        assert result["escalation"] == {"action": "review", "check": CHECK} and not result["passed"]
    if expected[0] != "visible":
        assert [v.rule for v in visibility_violations([result])] == [
            "occlusion.hidden" if expected[0] == "hidden" else "occlusion.review"]
    else:
        assert visibility_violations([result]) == []


@pytest.mark.parametrize(("options", "expected", "framing"), [
    ({"move": (-15, 0, 0)}, ("uncertain", 300, 400), [0, 0, 64, 48]),
    ({"move": (-10, 0, 0)}, ("visible", 400, 400), [0, 0, 64, 48]),
    ({"slot_crop": [0.25, 0, 1, 1]}, ("uncertain", 280, 400), [0, 0, 64, 48]),
    ({"camera": CAMERA}, ("uncertain", 1120, 1600), [0, 0, 32, 24]),
    ({"move": (0, -18, 0)}, ("uncertain", 240, 400), [0, 0, 64, 48]),
])
def test_clipping_subtracts_from_the_numerator_only(world, options, expected, framing):
    story, library, pose = scene(world, **options)
    (result,) = evaluated(world, story, library, {"still": observations(world, story, library, pose)})
    assert counted(result) == expected
    assert result["measured"]["framing"]["crop_xyxy"] == framing


@pytest.mark.parametrize(("alpha", "depth", "prop_box", "expected", "reason"), [
    (127, "separate", FACE, ("visible", 400, 400), None),
    (128, "separate", FACE, ("hidden", 0, 400), None),
    (255, "background", FACE, ("hidden", 0, 400), None),
    (255, "foreground", (12, 12, 28, 28), ("visible", 256, 256), None),
    (255, "foreground", (12, 12, 34, 28), ("uncertain", 0, 0), "mask_straddles_depth"),
    (255, "unspecified", FACE, ("uncertain", 0, 0), "unspecified_depth"),
])
def test_declared_prop_depth_and_alpha_without_shadows(world, alpha, depth, prop_box, expected, reason):
    story, library, pose = scene(world, focus=FACE if depth == "foreground" else None,
                                 prop_depth=depth, prop_box=prop_box, face_alpha=alpha)
    face, prop = evaluated(world, story, library, {"still": observations(world, story, library, pose)})
    assert counted(prop) == expected
    assert prop["measured"]["reason"] == reason
    if depth == "foreground":
        assert counted(face) == ("hidden", 0, 400)


def test_additional_named_pose_must_supply_its_own_geometry(world):
    story, library, pose = scene(world, second_pose=True)
    pose = observations(world, story, library, pose)
    first, missing = evaluated(world, story, library, {"still": pose})
    assert counted(first) == ("visible", 400, 400)
    assert counted(missing) == ("uncertain", 0, 0)
    assert missing["measured"]["reason"] == "missing_or_wrong_pose"
    assert not missing["passed"] and visibility_violations([first, missing])
    other = replace(pose, frame=12, moves={"a": (-25, 0, 0)})
    first, second = evaluated(world, story, library, {"still": pose, "wide": other})
    assert counted(second) == ("hidden", 100, 400)
    assert first["artifact_refs"]["pose"] != second["artifact_refs"]["pose"]
    assert second["measured"]["pose"] == {"key": "wide", "frame": 12}


@pytest.mark.parametrize("fault", ["mask", "request", "move", "pose", "input"])
def test_invalid_geometry_never_becomes_buildable(world, fault):
    story, library, pose = scene(world)
    pose = observations(world, story, library, pose)
    if fault in {"mask", "request"}:
        face = pose.observations["face", "a"]
        if fault == "mask":
            face = replace(face, png=b"corrupt")
        else:
            face = replace(face, completion=replace(
                face.completion, identity=replace(face.completion.identity, request_sha256="0" * 64)))
        pose = replace(pose, observations={**pose.observations, ("face", "a"): face})
    elif fault == "move":
        pose = replace(pose, moves={"a": (float("inf"), 0, 0)})
    elif fault == "pose":
        pose = replace(pose, frame=2)
    else:
        pose = replace(pose, plate=replace(pose.plate, data=b"wrong image"))
    (result,) = evaluated(world, story, library, {"still": pose})
    assert counted(result) == ("uncertain", 0, 0)
    assert result["escalation"]["action"] == "review"
    assert [v.rule for v in visibility_violations([result])] == ["occlusion.review"]


def _prepare(world, story, library):
    return prepare(to_document(story), library=library, store=world[0], toolchain=Toolchain(),
                   frame_size=SIZE, current_engine="Kokoro-82M v1.0")


def test_product_prebuild_blocks_opt_in_without_authoritative_evidence(world):
    story, library, _ = scene(world)
    before = _prepare(world, story, library)
    assert any(p.rule == "occlusion.review" for p in before.report.blocking)
    with pytest.raises(PreflightError):
        before.ensure_buildable()


def test_legacy_boards_keep_edge_feather_rendering_and_their_layout_document(world):
    story, library, _ = scene(world, legacy=True)
    board = story.boards[0]
    assert to_document(board.layout) == {"preset": "test", "foreground": True}
    assert evaluated(world, story, library, {}) == []
    assert not any(p.rule.startswith("occlusion.") for p in _prepare(world, story, library).report.problems)
    # Compose the same stills with and without the legacy edge. The edge replaces
    # the face pixels below it, as it did before the visibility contract existed.
    inputs = replace(plan_photo(story, board, library).layers, width=SIZE[0], height=SIZE[1])
    by_hash = {v.content.sha256: v.content.locator for v in library.versions.values()}
    read = lambda digest: world[0].open(by_hash[digest])
    with_edge = Image.open(BytesIO(compose_photo(inputs, read)))
    without_edge = Image.open(BytesIO(compose_photo(replace(inputs, foreground=None), read)))
    assert with_edge.getpixel((15, 15)) == (31, 90, 120)
    assert without_edge.getpixel((15, 15)) == (40, 90, 80)


@pytest.mark.parametrize(("source", "size"), [((80, 60), (32, 32)), ((40, 64), (64, 48)), ((64, 48), (64, 48))])
def test_cover_crop_preserves_existing_pillow_resampling(source, size):
    rng = np.random.default_rng(452)
    image = Image.fromarray(rng.integers(0, 256, (source[1], source[0], 3), dtype=np.uint8))
    assert fit_set_plate(image, size).tobytes() == ImageOps.fit(
        image, size, method=Image.Resampling.LANCZOS).tobytes()


def test_pose_keys_are_unique_and_round_trip(world):
    story, _, _ = scene(world, second_pose=True)
    document = to_document(story)
    poses = document["boards"][0]["layout"]["check_poses"]
    assert poses == [{"key": "still", "frame": 0}, {"key": "wide", "frame": 12}]
    assert to_document(fx.load(document))["boards"][0]["layout"]["check_poses"] == poses
    poses[1]["key"] = "still"
    with pytest.raises(ContractError) as error:
        fx.load(document)
    assert {p.rule for p in error.value.violations} == {"ref.duplicate"}


def test_plate_cover_crop_uses_unclipped_prop_support(world):
    story, library, pose = scene(world, focus=None, prop_depth="background",
                                 prop_box=(0, 10, 12, 30), move=(150, 0, 0))
    _, prop = evaluated(world, story, library, {"still": observations(world, story, library, pose)},
                        size=(48, 48))
    # 8 source columns fall outside the centred cover crop. Four remain in view.
    assert counted(prop) == ("hidden", 80, 240)


def test_static_plate_cannot_stand_in_for_a_promoted_set_loop(world):
    story, library, pose = scene(world)
    pose = observations(world, story, library, pose)
    plate_hash = library.version(pose.plate.version_id).content.sha256
    clip = mf.version(mf.set_block(still_sha256=plate_hash), n=60, clip="a" * 64,
                      source_key="synthetic:set-loop")
    clip["scope"] = {"production_id": story.production_id}
    clip["content"]["locator"] = locator_for(clip["content"]["sha256"], "video/mp4", story.production_id)
    fuller = Library.from_version_documents([*(library.document(v) for v in library.versions), clip])
    (check,) = evaluated(world, story, fuller, {"still": pose})
    assert counted(check) == ("uncertain", 0, 0)
    assert check["measured"]["reason"] == "moving_plate_needs_pose_source"


def test_stale_takes_cannot_set_the_visibility_pose_clock(world):
    story, library, pose = scene(world)
    pose = observations(world, story, library, pose)
    template = example("valid/asset-version-board-voice.json")
    voice = template["voice"]
    board = story.boards[0]
    lines = tuple(Line(id=take["line_id"], speaker=take["speaker"], text="Edited after recording.",
                       gap_before_ms=None if i == 0 else voice["gaps_ms"][i - 1])
                  for i, take in enumerate(voice["takes"]))
    board = replace(board, lines=lines, voice=replace(board.voice, style="cast", current_version_id=template["id"]),
                    timing=replace(board.timing, hold_ms=None, lead_ms=voice["lead_ms"], tail_ms=500))
    story = replace(story, boards=(board,))
    fuller = Library.from_version_documents([*(library.document(v) for v in library.versions), template])
    (check,) = evaluated(world, story, fuller, {"still": pose})
    assert counted(check) == ("uncertain", 0, 0)
    assert check["measured"]["reason"] == "pose_outside_board"
