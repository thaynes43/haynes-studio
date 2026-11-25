"""Exact pixel counts through real Stage observation receipts and synthetic geometry.

The fake graph returns declared rectangles. These tests measure the mapping and
pre-build behavior, without drawing conclusions about the model.
"""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO

import numpy as np
import pytest
from PIL import Image, ImageDraw

from haynes_studio.build import prebuild
from haynes_studio.build.prebuild import VisibilityReviewRequired, prepare
from haynes_studio.cache.plan import Toolchain
from haynes_studio.canonical.model import CheckPose, Line, to_document
from haynes_studio.errors import ContractError
from haynes_studio.layered import compose
from haynes_studio.layered.photo import compose_photo
from haynes_studio.layered.visibility import (
    CHECK, THRESHOLDS, PoseGeometry, PoseStill, _Occluder, _result, _visible_bounds, evaluate_visibility,
    visibility_violations,
)
from haynes_studio.layered.visibility_geometry import Projection, measure_support, set_plate_crop
from haynes_studio.library import Library, Outcome
from haynes_studio.library.model import locator_for
from haynes_studio.photo.plan import plan_photo
from haynes_studio.render.delivery_profile import fit_set_plate
from haynes_studio.segmentation.backend import Engine
from haynes_studio.segmentation.pixels import encode_mask
from haynes_studio.segmentation.profile import digest
from haynes_studio.segmentation.service import listening
from haynes_studio.stages.preflight import PreflightError
from tests.assets.test_occlusion import (
    Journal, SIZE, factory, library_image, pins, run, world,  # noqa: F401
)
from tests.build_story.fixtures import World as BuildWorld
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


def declaration(table, prop_depth, prop_box, prop_id, prop_order):
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
        focal.update(layer_order=prop_order, source_asset_version_id=prop_id)
    return {"foreground": foreground, "focal_props": [focal]}


def scene(world, *, focus=TABLE, face_alpha=255, prop_depth=None, prop_box=FACE,
          prop_order=5, camera=None, slot_crop=None, legacy=False, second_pose=False, move=(0, 0, 0),
          second_cast=False, role_order=30, role_key="table", prop_key="menu", second_prop_order=None):
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
                                             None if component is None else component.version_id, prop_order)
    if config is not None:
        for role in config["foreground"]:
            role.update(key=role_key, layer_order=role_order)
        for prop in config["focal_props"]:
            prop["key"] = prop_key
            if prop_depth == "foreground":
                prop.update(foreground_role=role_key, layer_order=role_order)
        if second_prop_order is not None:
            config["focal_props"].append({**config["focal_props"][0], "key": "card",
                                          "layer_order": second_prop_order})
    plate, rgb = library_image(store, Image.new("RGB", SIZE, (31, 90, 120)), "set", library=library,
                               config=config, production_id=fx.PRODUCTION)
    width, height = SIZE
    slot = {"x": 0.5, "height": height, "bottom": height}
    document = fx.story_document()
    document["layouts"] = {"test": {
        "slots": {"a": {**slot, **({} if slot_crop is None else {"crop": slot_crop})},
                  "b": slot, "menu": slot, "card": slot},
    }}
    cast_entries = [(key, cast.version.id) for key in ("a", "b") if key == "a" or second_cast]
    board = fx._board(fx.B1, 1, title="Visibility", lines=[], cast=cast_entries,
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
    cutouts = {key: PoseStill(version_id, rgba) for key, version_id in cast_entries}
    moves = dict.fromkeys(cutouts, move)
    if component is not None:
        for prop in config["focal_props"]:
            cutouts[prop["key"]] = component
            moves[prop["key"]] = (0, 0, 0)
    pose = PoseGeometry(0, PoseStill(plate.version.id, rgb), cutouts, moves, {},
                        hints={("face", key): box_hint(FACE) for key, _ in cast_entries})
    return story, plate.library, pose


def observations(world, story, library, pose):
    _, client, weights = world
    journal = Journal()
    config = library.version(story.set.asset_version_id).occlusion or {"foreground": [], "focal_props": []}
    wanted = [("face", entry.slot, pose.cutouts[entry.slot], None, pose.hints["face", entry.slot])
              for entry in story.boards[0].cast]
    wanted += [("foreground", layer["key"], pose.plate, layer["label"], layer.get("hint"))
               for layer in config["foreground"]]
    wanted += [("prop", prop["key"], pose.cutouts[prop["key"]] if prop["depth"] == "separate" else pose.plate,
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


def counted(check, *, upper=None):
    data = check["measured"]
    lower = data["visible_lower_pixels"]
    assert type(data["total_pixels"]) is type(lower) is type(data["visible_upper_pixels"]) is int
    assert data["visible_upper_pixels"] == (lower if upper is None else upper)
    assert check["thresholds"] == THRESHOLDS
    return data["status"], lower, data["total_pixels"]


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
    assert {"layout", "pose", "inputs", "library"} == result["artifact_refs"].keys()
    assert result["measured"]["unknown_occluders"] == []
    if expected[0] == "uncertain":
        assert result["escalation"] == {"action": "review", "check": CHECK} and not result["passed"]
    assert [v.rule for v in visibility_violations([result])] == (
        ["occlusion.hidden"] if expected[0] == "hidden" else [])


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


@pytest.mark.parametrize(("angle", "zoom"), [(15, 1), (-30, 1), (25, 1), (25, 1.35)])
def test_translated_rotated_support_matches_compositor(angle, zoom):
    frame_size = (160, 120)
    sprite_size = (76, 68)
    sprite = Image.new("RGBA", sprite_size)
    ImageDraw.Draw(sprite).rectangle((8, 8, 28, 28), fill="white")
    mask = np.asarray(sprite.getchannel("A")) > 0
    where = compose.Placement(x=37, y=20, cx=75, bottom=88)
    move = (7, -4, angle)
    cue = {"start_ms": 0, "duration_ms": 0, "zoom_from": zoom, "zoom_to": zoom, "center_px": (80, 60)}
    framing = compose.camera_box(frame_size, cue, 0) or (0, 0, *frame_size)

    plate = compose.plate(sprite, where, *frame_size)
    moved = compose.move_plate(plate, frame_size, where.pivot, move)
    rendered = np.asarray(compose.camera(moved, cue, 0).getchannel("A")) >= 128
    projection = Projection.sprite((0, 0, *sprite_size), sprite_size, where, frame_size, move)
    total, measured = measure_support(mask, projection, frame_size, framing)
    assert total >= np.count_nonzero(measured) > 0
    if zoom == 1:
        np.testing.assert_array_equal(measured, rendered)
    else:
        # Camera resampling is bicubic, while binary support uses nearest centres.
        # Allow up to 2% disagreement at the zoomed edges.
        iou = np.count_nonzero(measured & rendered) / np.count_nonzero(measured | rendered)
        assert iou >= 0.98


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


def test_a_separate_prop_does_not_supply_unrendered_occluder_alpha(world):
    story, library, pose = scene(world, focus=None, prop_depth="separate", prop_order=25, second_prop_order=15)
    checks = evaluated(world, story, library, {"still": observations(world, story, library, pose)})
    assert [check["measured"]["target"]["key"] for check in checks] == ["a", "menu", "card"]
    assert [counted(check) for check in checks] == [("visible", 400, 400)] * 3


@pytest.mark.parametrize(("options", "reason"), [
    ({"role_key": "a"}, "target_key_conflicts_with_cast"),
    ({"role_order": 15, "second_cast": True}, "invalid_foreground_order"),
    ({"role_order": 20, "second_cast": True}, "invalid_foreground_order"),
])
def test_invalid_foreground_is_unknown_only_above_its_targets(world, options, reason):
    story, library, pose = scene(world, focus=FACE, **options)
    if options.get("second_cast"):
        pose = replace(pose, moves={**pose.moves, "b": (32, 0, 0)})
    first, *rest = evaluated(world, story, library, {"still": observations(world, story, library, pose)})
    assert counted(first, upper=400) == ("uncertain", 0, 400)
    assert first["measured"]["unknown_occluders"] == [
        {"kind": "foreground", "key": options.get("role_key", "table"),
         "layer_order": options.get("role_order", 30), "reason": reason},
    ]
    for higher in rest:
        assert counted(higher) == ("visible", 400, 400)
        assert higher["measured"]["unknown_occluders"] == []


@pytest.mark.parametrize(("options", "reason"), [
    ({"prop_depth": "background", "prop_key": "a"}, "target_key_conflicts_with_cast"),
    ({"prop_depth": "separate", "prop_order": 10}, "duplicate_layer_order"),
])
def test_invalid_prop_declaration_only_invalidates_its_own_measurement(world, options, reason):
    story, library, pose = scene(world, focus=None, **options)
    supplied = observations(world, story, library, pose)
    face, prop = evaluated(world, story, library, {"still": supplied})
    assert counted(prop) == ("uncertain", 0, 0)
    assert prop["measured"]["reason"] == reason
    assert counted(face) == ("visible", 400, 400)


def test_additional_named_pose_must_supply_its_own_geometry(world):
    story, library, pose = scene(world, second_pose=True)
    pose = observations(world, story, library, pose)
    first, missing = evaluated(world, story, library, {"still": pose})
    assert counted(first) == ("visible", 400, 400)
    assert counted(missing) == ("uncertain", 0, 0)
    assert missing["measured"]["reason"] == "missing_or_wrong_pose"
    assert not missing["passed"] and visibility_violations([first, missing]) == []
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
    if fault == "input":
        assert counted(result, upper=400) == ("uncertain", 0, 400)
        assert result["measured"]["unknown_occluders"] == [
            {"kind": "foreground", "key": "table", "layer_order": 30, "reason": "invalid_input"},
        ]
    else:
        assert counted(result) == ("uncertain", 0, 0)
    assert result["escalation"]["action"] == "review"
    assert visibility_violations([result]) == []


def _prepare(world, story, library, **options):
    # The queue checks pinned metadata. The segmentation fixtures above check the actual still bytes.
    fixture = BuildWorld(world[0].root, world[0], [library.document(key) for key in library.versions])
    fixture.voice(fx.VOICE_A, 101, "af_heart")
    story = replace(story, cast=tuple(replace(entry, voice_version_id=fx.VOICE_A) for entry in story.cast),
                    narrator_voice_version_id=None)
    (entry,) = story.boards[0].cast
    still_sha = library.version(entry.asset_version_id).content.sha256
    motion = mf.version(mf.loop_block(still_sha256=still_sha), n=80, clip="a" * 64)
    motion["scope"] = {"production_id": story.production_id}
    motion["content"]["locator"] = locator_for("a" * 64, "video/mp4", story.production_id)
    fixture.docs.append(motion)
    return prepare(to_document(story), library=fixture.library(), store=None, toolchain=Toolchain(),
                   frame_size=SIZE, current_engine="Kokoro-82M v1.0", **options)


def opted_in_legacy(world, **options):
    story, library, pose = scene(world, legacy=True, **options)
    (board,) = story.boards
    board = replace(board, layout=replace(board.layout, foreground=False, check_poses=(CheckPose("still", 0),)))
    return replace(story, boards=(board,)), library, pose


def test_product_prebuild_routes_missing_geometry_to_review(world):
    story, library, _ = opted_in_legacy(world)
    before = _prepare(world, story, library)
    assert before.report.ok
    (evidence,) = before.pending_visibility
    assert counted(evidence) == ("uncertain", 0, 0)
    assert evidence["measured"]["reason"] == "missing_or_wrong_pose"
    with pytest.raises(VisibilityReviewRequired) as refused:
        before.ensure_buildable()
    assert refused.value.checks[0]["actual"] == evidence


@pytest.mark.parametrize(("move", "counts"), [((0, 0, 0), ("uncertain", 280, 400)),
                                               ((-25, 0, 0), ("hidden", 0, 400))])
def test_measured_face_build_gate_respects_only_uncertain_overrides(world, monkeypatch, move, counts):
    story, library, pose = opted_in_legacy(world, slot_crop=[0.25, 0, 1, 1], move=move)
    (evidence,) = evaluated(world, story, library, {"still": observations(world, story, library, pose)})
    assert counted(evidence) == counts
    monkeypatch.setattr(prebuild, "evaluate_visibility", lambda *args, **kwargs: [evidence])
    before = _prepare(world, story, library)
    after = _prepare(world, story, library, visibility_overrides=(evidence["artifact"],))
    if counts[0] == "hidden":
        assert [p.rule for p in after.report.blocking] == ["occlusion.hidden"]
        with pytest.raises(PreflightError):
            after.ensure_buildable()
    else:
        with pytest.raises(VisibilityReviewRequired):
            before.ensure_buildable()
        after.ensure_buildable()


def test_different_invalid_mask_bytes_require_fresh_review(world, monkeypatch):
    story, library, pose = opted_in_legacy(world)
    pose = observations(world, story, library, pose)
    target = ("face", "a")
    receipt = pose.observations[target]
    results = []
    for offset in (1, 2):
        pixels = np.zeros((SIZE[1], SIZE[0]), dtype=bool)
        pixels[10:30, 10 + offset:30] = True
        png = encode_mask(pixels)
        assert digest(png) != receipt.completion.mask.sha256
        supplied = replace(pose, observations={target: replace(receipt, png=png)})
        (result,) = evaluated(world, story, library, {"still": supplied})
        assert counted(result) == ("uncertain", 0, 0)
        assert result["measured"]["reason"] == "observation_mask_mismatch"
        results.append(result)

    first, second = results
    assert first["artifact"] != second["artifact"]
    monkeypatch.setattr(prebuild, "evaluate_visibility", lambda *args, **kwargs: [first])
    approval = (first["artifact"],)
    _prepare(world, story, library, visibility_overrides=approval).ensure_buildable()
    monkeypatch.setattr(prebuild, "evaluate_visibility", lambda *args, **kwargs: [second])
    with pytest.raises(VisibilityReviewRequired) as refused:
        _prepare(world, story, library, visibility_overrides=approval).ensure_buildable()
    assert refused.value.checks[0]["actual"] == second


def test_different_rejected_receipt_hints_require_fresh_review(world, monkeypatch):
    story, library, pose = opted_in_legacy(world)
    _, client, weights = world
    source = Outcome(library, library.version(pose.cutouts["a"].version_id), created=False)
    journal = Journal()
    with Engine(client.scratch, weights, client.profile, factory=factory) as engine, listening(client.socket, engine):
        first, second = [
            run(world, source, journal, production_id=story.production_id, kind="face", key="a",
                label=None, hint={"kind": "point", "xy": [x, 15]})
            for x in (15, 16)
        ]
    assert first.png == second.png and first.receipt != second.receipt
    # Keep the completion pin fixed in the third case to prove the supplied
    # receipt bytes are independently hashed, even for rejected observations.
    supplied = [first, second, replace(first, receipt=second.receipt)]
    checks = [evaluated(world, story, library, {
        "still": replace(pose, observations={("face", "a"): outcome}),
    })[0] for outcome in supplied]
    assert len({check["artifact"] for check in checks}) == len(supplied)
    assert {check["measured"]["reason"] for check in checks} == {"observation_pin_mismatch"}
    monkeypatch.setattr(prebuild, "evaluate_visibility", lambda *args, **kwargs: [checks[1]])
    with pytest.raises(VisibilityReviewRequired):
        _prepare(world, story, library, visibility_overrides=(checks[0]["artifact"],)).ensure_buildable()


@pytest.mark.parametrize("fault", [
    "cast move", "cast NaN", "cast bytes", "supplied frame", "set version", "prop version",
    "raw hint", "absent PNG", "absent prop move", "extra pose",
])
def test_rejected_supplied_inputs_change_the_evidence_digest(world, fault):
    story, library, pose = scene(world, focus=None,
                                 prop_depth="background" if fault == "set version" else "separate")
    pose = observations(world, story, library, pose)
    face, prop = ("face", "a"), ("prop", "menu")
    if fault in ("cast move", "cast NaN"):
        number = float("inf") if fault == "cast move" else float("nan")
        variants = [replace(pose, moves={**pose.moves, "a": (value, 0, 0)}) for value in (number, -number)]
    elif fault == "cast bytes":
        variants = [replace(pose, cutouts={**pose.cutouts, "a": replace(pose.cutouts["a"], data=data)})
                    for data in (b"bad still", b"another bad still")]
    elif fault == "supplied frame":
        variants = [replace(pose, frame=frame) for frame in (1, 2)]
    elif fault == "set version":
        variants = [replace(pose, plate=replace(pose.plate, version_id=fx.ident("asv", i))) for i in (1, 2)]
    elif fault == "prop version":
        variants = [replace(pose, cutouts={**pose.cutouts, "menu": replace(
            pose.cutouts["menu"], version_id=fx.ident("asv", i))}) for i in (1, 2)]
    elif fault == "raw hint":
        # Both malformed requests produce the same reason after text normalization.
        variants = [replace(pose, hints={face: {"kind": "text", "text": value}}) for value in (" ", "  ")]
    elif fault == "absent PNG":
        receipt = pose.observations[face]
        variants = [replace(pose, observations={**pose.observations, face: replace(receipt, png=value)})
                    for value in (None, b"")]
    elif fault == "absent prop move":
        moves = {"a": pose.moves["a"]}
        variants = [replace(pose, moves=moves), replace(pose, moves={**moves, "menu": ()})]
    else:
        variants = [pose, replace(pose, frame=2)]

    target = prop if fault in ("set version", "prop version", "absent prop move") else face
    measured = []
    for variant in variants:
        poses = {"still": variant} if fault != "extra pose" else {"still": pose, "undeclared": variant}
        checks = evaluated(world, story, library, poses)
        assert checks[0]["artifact_refs"] == checks[1]["artifact_refs"]
        measured.append(next(check for check in checks if check["measured"]["target"] ==
                             {"kind": target[0], "key": target[1]}))
    first, second = measured
    assert first["artifact"] != second["artifact"]
    if fault != "absent PNG":
        assert first["measured"] == second["measured"]
    if fault != "extra pose":
        assert counted(first) == counted(second) == ("uncertain", 0, 0)


def test_a_receipt_with_wrong_bytes_cannot_supply_usable_mask(world):
    story, library, pose = opted_in_legacy(world)
    pose = observations(world, story, library, pose)
    target = ("face", "a")
    outcome = pose.observations[target]
    pose = replace(pose, observations={target: replace(outcome, receipt=b"wrong")})
    (check,) = evaluated(world, story, library, {"still": pose})
    assert counted(check) == ("uncertain", 0, 0)
    assert check["measured"]["reason"] == "observation_receipt_mismatch"


def test_rejected_nonfinite_frame_sizes_have_distinct_serializable_evidence(world):
    story, library, pose = scene(world)
    poses = {"still": pose}
    results = [evaluated(world, story, library, poses, size=(width, 48))[0]
               for width in (float("inf"), -float("inf"))]
    assert results[0]["artifact"] != results[1]["artifact"]
    for result in results:
        assert counted(result) == ("uncertain", 0, 0)
        assert result["measured"]["reason"] == "invalid_frame_size"


def test_product_prebuild_refuses_declared_foreground_roles_even_when_disabled(world):
    story, library, _ = scene(world)
    (board,) = story.boards
    board = replace(board, layout=replace(board.layout, foreground=False))
    before = _prepare(world, replace(story, boards=(board,)), library)
    assert [p.rule for p in before.report.blocking] == ["occlusion.render_unsupported"]
    assert not before.pending_visibility
    with pytest.raises(PreflightError):
        before.ensure_buildable()


def test_legacy_boards_keep_edge_feather_rendering_and_their_layout_document(world):
    story, library, pose = scene(world, legacy=True)
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

    board = replace(board, layout=replace(board.layout, check_poses=(CheckPose("still", 0),)))
    checked = replace(story, boards=(board,))
    (check,) = evaluated(world, checked, library, {"still": observations(world, checked, library, pose)})
    assert counted(check) == ("hidden", 0, 400)


def test_separate_prop_setup_failure_keeps_the_legacy_hidden_face(world):
    story, library, pose = scene(world, focus=None, prop_depth="separate")
    story = replace(story, set=replace(story.set, foreground_edge_px=((0, 9), (64, 9)),
                                      foreground_feather_px=1))
    pose = observations(world, story, library, pose)
    face, _ = evaluated(world, story, library, {"still": pose})
    assert counted(face) == ("hidden", 0, 400)

    # Prop setup can fail in several ways while the face is still measurable.
    faults = (
        (replace(pose, cutouts={"a": pose.cutouts["a"]}), "missing_or_wrong_layer"),
        (replace(pose, cutouts={**pose.cutouts, "menu": pose.cutouts["a"]}), "missing_or_wrong_layer"),
        (replace(pose, moves={"a": pose.moves["a"]}), "missing_or_invalid_move"),
        (replace(pose, moves={**pose.moves, "menu": (10_001, 0, 0)}), "missing_or_invalid_move"),
        (replace(pose, moves={**pose.moves, "menu": (10_002, 0, 0)}), "missing_or_invalid_move"),
        (replace(pose, moves={**pose.moves, "menu": (float("inf"), 0, 0)}), "invalid_geometry"),
    )
    artifacts = set()
    for bad_pose, reason in faults:
        result = evaluated(world, story, library, {"still": bad_pose})
        hidden_face, broken_prop = result
        assert counted(hidden_face) == counted(face)
        assert counted(broken_prop) == ("uncertain", 0, 0)
        assert broken_prop["measured"]["reason"] == reason
        artifacts.add(broken_prop["artifact"])
        assert [problem.rule for problem in visibility_violations(result)] == ["occlusion.hidden"]
    assert len(artifacts) == len(faults)


def test_disjoint_legacy_foreground_keeps_the_background_menu_hidden(world):
    story, library, pose = scene(world, focus=None, prop_depth="background")
    pose = observations(world, story, library, pose)
    _, menu = evaluated(world, story, library, {"still": pose})
    assert counted(menu) == ("hidden", 0, 400)

    # Vary the slope, height and feather while keeping the redraw off the menu.
    for left, right, feather in ((36, 36, 1), (33, 42, 3), (42, 35, 4), (30, 30, 0)):
        edged = replace(story, set=replace(story.set, foreground_edge_px=((0, left), (64, right)),
                                          foreground_feather_px=feather))
        results = evaluated(world, edged, library, {"still": pose})
        assert counted(results[1]) == counted(menu)
        assert [problem.rule for problem in visibility_violations(results)] == ["occlusion.hidden"]


def test_missing_lower_cast_move_keeps_the_upper_face_hidden(world):
    story, library, pose = scene(world, legacy=True, second_cast=True)
    (board,) = story.boards
    board = replace(board, layout=replace(board.layout, check_poses=(CheckPose("still", 0),)))
    story = replace(story, boards=(board,))
    pose = observations(world, story, library, pose)
    _, upper_before = evaluated(world, story, library, {"still": pose})
    pose = replace(pose, moves={"b": pose.moves["b"]})
    lower, upper = evaluated(world, story, library, {"still": pose})
    assert counted(lower) == ("uncertain", 0, 0)
    assert lower["measured"]["reason"] == "missing_or_invalid_move"
    assert counted(upper) == counted(upper_before) == ("hidden", 0, 400)
    assert upper["measured"]["unknown_occluders"] == []
    assert [problem.rule for problem in visibility_violations([lower, upper])] == ["occlusion.hidden"]


def test_one_row_of_possible_legacy_restoration_keeps_the_menu_hidden(world):
    story, library, pose = scene(world, focus=None, prop_depth="background")
    story = replace(story, set=replace(story.set, foreground_edge_px=((0, 28), (64, 28)),
                                      foreground_feather_px=0))
    face, menu = evaluated(world, story, library, {"still": observations(world, story, library, pose)})
    assert counted(face) == ("visible", 380, 400)
    assert counted(menu, upper=20) == ("hidden", 0, 400)
    assert menu["measured"]["possible_redraw_pixels"] == 20
    assert [v.rule for v in visibility_violations([face, menu])] == ["occlusion.hidden"]


def test_legacy_redraw_does_not_restore_a_separate_prop(world):
    story, library, pose = scene(world, focus=None, prop_depth="separate")
    story = replace(story, set=replace(story.set, foreground_edge_px=((0, 28), (64, 28)),
                                      foreground_feather_px=0))
    _, menu = evaluated(world, story, library, {"still": observations(world, story, library, pose)})
    assert counted(menu) == ("hidden", 0, 400)
    assert menu["measured"]["possible_redraw_pixels"] == 0


def test_a_missing_higher_cast_move_measures_the_background_menu_bounds(world):
    story, library, pose = scene(world, focus=None, prop_depth="background")
    pose = replace(observations(world, story, library, pose), moves={})
    face, menu = evaluated(world, story, library, {"still": pose})
    assert counted(face) == ("uncertain", 0, 0)
    assert counted(menu, upper=400) == ("uncertain", 0, 400)
    assert menu["measured"]["unknown_occluders"] == [
        {"kind": "cast", "key": "a", "layer_order": 10, "reason": "missing_or_invalid_move"},
    ]


def test_generated_arrangements_preserve_visibility_bounds(world):
    story, _, _ = scene(world)
    (board,) = story.boards
    (pose,) = board.layout.check_poses
    rng = np.random.default_rng(452)
    size, order = (8, 6), 3
    framing = (0, 0, *size)
    hidden_cases = 0
    for _ in range(100):
        support = rng.random((6, 8)) < 0.9
        total = int(support.sum())
        layers = [_Occluder("cast", str(i), int(depth),
                            (rng.random(support.shape) < rng.uniform(0, 0.8)).astype(np.uint8) * 255)
                  for i, depth in enumerate(rng.integers(0, 8, size=4))]
        known_lower, known_upper, _, _ = _visible_bounds(support, order, layers)
        assert known_lower == known_upper
        before = _result(board, "face", "a", pose, size, framing, {"inputs": "a" * 64},
                         lower=known_lower, upper=known_upper, total=total)
        unknown_layer = _Occluder("foreground", "unknown", int(rng.integers(0, 8)), reason="missing")
        lower, upper, unknown, _ = _visible_bounds(support, order, [*layers, unknown_layer])
        assert 0 <= lower <= upper <= known_upper <= total
        assert unknown == ([unknown_layer.unknown()] if unknown_layer.order > order else [])
        assert lower == (0 if unknown else known_lower)
        after = _result(board, "face", "a", pose, size, framing, {"inputs": "a" * 64},
                        lower=lower, upper=upper, total=total, unknown=unknown)
        if before["measured"]["status"] == "hidden":
            hidden_cases += 1
            assert after["measured"]["status"] == "hidden"
        assert _visible_bounds(support, order, layers)[:2] == (upper, upper)
    assert hidden_cases > 0


def test_legacy_foreground_keeps_face_measurement_when_prop_depth_is_ambiguous(world):
    story, library, pose = scene(world, focus=None, prop_depth="background")
    story = replace(story, set=replace(story.set, foreground_edge_px=((0, 9), (64, 9)),
                                      foreground_feather_px=1))
    face, prop = evaluated(world, story, library, {"still": observations(world, story, library, pose)})
    assert counted(face) == ("hidden", 0, 400)
    assert counted(prop, upper=400) == ("uncertain", 0, 400)
    assert prop["measured"]["reason"] == "legacy_foreground_needs_depth_geometry"


@pytest.mark.parametrize(("source", "size"), [((80, 60), (32, 32)), ((40, 64), (64, 48)), ((64, 48), (64, 48))])
def test_cover_crop_preserves_existing_pillow_resampling(source, size):
    rng = np.random.default_rng(452)
    image = Image.fromarray(rng.integers(0, 256, (source[1], source[0], 3), dtype=np.uint8))
    assert image.resize(size, Image.Resampling.LANCZOS, box=set_plate_crop(source, size)).tobytes() == (
        fit_set_plate(image, size).tobytes())


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
    assert counted(check, upper=400) == ("uncertain", 0, 400)
    assert check["measured"]["unknown_occluders"] == [
        {"kind": "foreground", "key": "table", "layer_order": 30, "reason": "moving_plate_needs_pose_source"},
    ]


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
