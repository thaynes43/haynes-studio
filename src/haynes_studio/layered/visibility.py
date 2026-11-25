"""Set foreground and focal-prop visibility for explicitly named board poses."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image

from haynes_studio.assets.occlusion import SegmentationIdentity, SegmentationOutcome, decode_still, make_request
from haynes_studio.canonical.derive import board_clock, resolve_anchor
from haynes_studio.canonical.model import Board, CameraCue, CheckPose, Story, to_document
from haynes_studio.checks._evidence import result_document
from haynes_studio.errors import ContractError, Violation, pointer
from haynes_studio.jsonio import thaw
from haynes_studio.layered import compose
from haynes_studio.layered.errors import LayeredError
from haynes_studio.layered.photo import still_geometry
from haynes_studio.layered.visibility_geometry import Projection, frame_alpha, measure_support, set_plate_crop
from haynes_studio.library import AssetVersion, Library
from haynes_studio.motion.record import LOOP, SET
from haynes_studio.motion.resolve import candidates
from haynes_studio.render.delivery_profile import fit_set_plate
from haynes_studio.segmentation.pixels import describe_mask
from haynes_studio.segmentation.profile import SegmentationError, digest
from haynes_studio.store import canonical_json
from haynes_studio.store.layout import is_sha256
from haynes_studio.timebase import DELIVERY_FPS

CHECK = "occlusion.visibility"
REVIEW_REQUIRED = "occlusion.review"
VERSION = "1"
VISIBLE_MIN_PERCENT = 85
HIDDEN_MAX_PERCENT = 50
OCCLUDING_ALPHA = 128
CAST_ORDER_STEP = 10
THRESHOLDS = {
    "visible_min_percent": VISIBLE_MIN_PERCENT, "hidden_max_percent": HIDDEN_MAX_PERCENT,
    "occluding_alpha": OCCLUDING_ALPHA,
}


@dataclass(frozen=True)
class PoseStill:
    version_id: str
    data: bytes


@dataclass(frozen=True)
class PoseGeometry:
    """The worker's render inputs for a named delivery frame.

    Moves are the layout's resolved dx, dy and angle. Inputs and observations
    are frozen by the caller to the same pose, before compositing.
    """

    frame: int
    plate: PoseStill
    cutouts: Mapping[str, PoseStill]
    moves: Mapping[str, tuple[float, float, float]]
    observations: Mapping[tuple[str, str], SegmentationOutcome]
    hints: Mapping[tuple[str, str], Mapping] = field(default_factory=dict)


@dataclass(frozen=True)
class _Layer:
    order: int
    version: AssetVersion
    image: Image.Image
    projection: Projection


class _Review(ValueError):
    pass


@dataclass
class _Frame:
    size: tuple[int, int]
    framing: tuple[int, int, int, int]
    geometry: PoseGeometry
    production_id: str
    profile_sha256: str
    refs: dict[str, str]
    layers: dict[str, _Layer] = field(default_factory=dict)
    foreground: dict[str, np.ndarray] = field(default_factory=dict)
    coverage: dict[int, np.ndarray] = field(default_factory=dict)
    legacy_foreground: bool = False

    def mask(self, layer, kind, key, label=None, hint=None):
        outcome = self.geometry.observations.get((kind, key))
        if outcome is None:
            raise _Review("missing_observation")
        completion = outcome.completion
        source = {"sha256": layer.version.content.sha256,
                  "width": layer.image.width, "height": layer.image.height}
        request = make_request(source, kind=kind, key=key, label=label,
                               hint=self.geometry.hints.get((kind, key), hint))
        identity = SegmentationIdentity(self.production_id, layer.version.id,
                                        digest(canonical_json(request)), self.profile_sha256)
        if completion.identity != identity:
            raise _Review("observation_pin_mismatch")
        self.refs[f"{kind}:{key}:result"] = completion.result.sha256
        if completion.status != "ready" or completion.mask is None or outcome.png is None:
            raise _Review(completion.reason or "missing_observation")
        descriptor, mask = describe_mask(outcome.png, layer.image.size)
        if (descriptor["sha256"] != completion.mask.sha256
                or descriptor["bytes"] != completion.mask.bytes
                or completion.mask.media_type != "image/png"):
            raise _Review("observation_mask_mismatch")
        if layer.order and (mask & (np.asarray(layer.image.getchannel("A")) == 0)).any():
            raise _Review("observation_mask_mismatch")
        self.refs[f"{kind}:{key}:mask"] = descriptor["sha256"]
        return mask


def _layer_image(library, still, production_id, kind, capability):
    version = library.get(still.version_id)
    if version is None or version.content is None or version.recorded_without_media:
        raise _Review("missing_layer_image")
    owner = library.asset_of(version.id).scope
    if (version.kind != kind or not version.has(capability)
            or owner.production_id not in (None, production_id)
            or owner.story_id is not None or owner.board_id is not None):
        raise _Review("layer_image_pin_mismatch")
    return version, decode_still(version.content, still.data, plate=capability == "opaque_plate")


def _camera_box(size, board, clock, frame):
    cues = [cue for cue in board.cues if isinstance(cue, CameraCue)]
    if not cues:
        return (0, 0, *size)
    if len(cues) != 1 or cues[0].easing not in compose.EASINGS:
        raise _Review("invalid_framing")
    camera = cues[0]
    cue = {"start_ms": resolve_anchor(camera.anchor, clock), "duration_ms": camera.duration_ms,
           "zoom_from": camera.zoom_from, "zoom_to": camera.zoom_to, "center_px": camera.center_px}
    box = compose.camera_box(size, cue, frame / DELIVERY_FPS) or (0, 0, *size)
    if not (0 <= box[0] < box[2] <= size[0] and 0 <= box[1] < box[3] <= size[1]):
        raise _Review("invalid_framing")
    return box


def _cutout(library, stage, key, order, source_id, kind, preset, matte):
    geometry = stage.geometry
    still = geometry.cutouts.get(key)
    if still is None or still.version_id != source_id:
        raise _Review("missing_or_wrong_layer")
    version, image = _layer_image(library, still, stage.production_id, kind, "rgba_cutout")
    slot = compose.slot_of(preset, key)
    width, height = stage.size
    if slot.height > 2 * height or abs(slot.bottom) > 2 * height:
        raise _Review("invalid_slot_geometry")
    crop, dimensions, where = still_geometry(image, slot, key, width, height, matte)
    if max(dimensions) > 2 * max(stage.size):
        raise _Review("invalid_slot_geometry")
    move = geometry.moves.get(key, ())
    if len(move) != 3 or any(abs(compose._number(n, "move value")) > 10_000 for n in move):
        raise _Review("missing_or_invalid_move")
    projection = Projection.sprite(crop, dimensions, where, stage.size, move)
    if any(layer.order == order for layer in stage.layers.values()):
        raise _Review("duplicate_layer_order")
    stage.layers[key] = _Layer(order, version, image, projection)
    if kind == "cast":
        sprite = image.crop(crop).resize(dimensions, Image.Resampling.LANCZOS)
        plate = compose.plate(sprite, where, width, height)
        posed = compose.move_plate(plate, stage.size, where.pivot, move)
        stage.coverage[order] = frame_alpha(posed.getchannel("A"), stage.size, stage.framing)
    stage.refs[f"layer:{key}"] = version.content.sha256


def _assemble(story, board, library, config, set_id, stage):
    # Use the same size and pin checks as the board photo, including D51 matte placement.
    from haynes_studio.photo.plan import plan_photo

    stage.refs["plate"] = digest(stage.geometry.plate.data)
    if stage.geometry.plate.version_id != set_id:
        raise _Review("missing_or_wrong_plate")
    version, image = _layer_image(library, stage.geometry.plate, stage.production_id, "set", "opaque_plate")
    if story.set.motion_asset_version_id is not None or candidates(
        library, use=LOOP, subject=SET, still_sha256=version.content.sha256,
        production_id=stage.production_id,
    ):
        # The single frozen plate can certify only its own geometry. A moving
        # set needs per-frame source binding from the future render integration.
        raise _Review("moving_plate_needs_pose_source")
    background = _Layer(0, version, image, Projection.plate(set_plate_crop(image.size, stage.size), stage.size))
    photo = plan_photo(story, board, library)
    sizes = photo.layers.matte_sizes or {}
    preset = story.layouts.get(board.layout.preset)
    cast_keys = {entry.slot for entry in board.cast}
    if any(target["key"] in cast_keys for group in ("foreground", "focal_props") for target in config[group]):
        raise _Review("target_key_conflicts_with_cast")
    for index, entry in enumerate(board.cast, start=1):
        _cutout(library, stage, entry.slot, index * CAST_ORDER_STEP, entry.asset_version_id,
                "cast", preset, sizes.get(entry.slot))
    for prop in config["focal_props"]:
        if prop["depth"] == "separate":
            _cutout(library, stage, prop["key"], prop["layer_order"], prop["source_asset_version_id"],
                    "prop", preset, None)

    for role in config["foreground"]:
        order = role["layer_order"]
        if order <= len(board.cast) * CAST_ORDER_STEP or any(layer.order == order for layer in stage.layers.values()):
            raise _Review("invalid_foreground_order")
        mask = stage.mask(background, "foreground", role["key"], role["label"], role.get("hint"))
        stage.foreground[role["key"]] = mask
        if board.layout.foreground:
            alpha = fit_set_plate(Image.fromarray(mask.astype(np.uint8) * 255), stage.size)
            stage.coverage[order] = frame_alpha(alpha, stage.size, stage.framing)
    if board.layout.foreground and not config["foreground"] and story.set.foreground_edge_px is not None:
        alpha = compose.foreground_alpha(story.set.foreground_edge_px, story.set.foreground_feather_px, *stage.size)
        order = max((layer.order for layer in stage.layers.values()), default=0) + 1
        stage.coverage[order] = frame_alpha(alpha, stage.size, stage.framing)
        stage.legacy_foreground = True
    return background


def _subject(stage, background, board, kind, key, prop):
    if kind == "face":
        layer = stage.layers[key]
        return stage.mask(layer, kind, key), layer, layer.order
    depth = prop["depth"]
    if depth == "unspecified":
        raise _Review("unspecified_depth")
    if depth == "background" and stage.legacy_foreground:
        raise _Review("legacy_foreground_needs_depth_geometry")
    layer = stage.layers[key] if depth == "separate" else background
    mask = stage.mask(layer, kind, key, prop["label"], prop.get("hint"))
    if depth == "separate":
        return mask, layer, layer.order

    assigned_role = prop.get("foreground_role")
    for role, support in stage.foreground.items():
        if (mask & (~support if role == assigned_role else support)).any():
            raise _Review("mask_straddles_depth")
    order = prop["layer_order"] if assigned_role and board.layout.foreground else 0
    return mask, layer, order


def evidence_sha256(evidence: dict) -> str:
    """Bind a review to the whole measurement, including its floors and input hashes."""
    return digest(canonical_json({key: value for key, value in evidence.items() if key != "artifact"}))


def _result(board, kind, key, pose, size, framing, refs, *, visible=0, total=0, reason=None):
    if reason is not None:
        status = "uncertain"
    elif visible * 100 >= total * VISIBLE_MIN_PERCENT:
        status = "visible"
    elif visible * 100 <= total * HIDDEN_MAX_PERCENT:
        status = "hidden"
    else:
        status, reason = "uncertain", "visibility_between_floors"
    evidence = result_document(
        CHECK, VERSION, dict(refs), {"visible": "pass", "hidden": "fail", "uncertain": "uncertain"}[status],
        thresholds=dict(THRESHOLDS),
        measured={"board_id": board.id, "target": {"kind": kind, "key": key}, "pose": to_document(pose),
                  "framing": {"size_px": list(size), "crop_xyxy": None if framing is None else list(framing)},
                  "visible_pixels": visible, "total_pixels": total, "status": status, "reason": reason},
        issues=[] if reason is None else [reason],
        escalation={"action": "review", "check": CHECK} if status == "uncertain" else None,
    )
    evidence["artifact"] = evidence_sha256(evidence)
    return evidence


def _reason(error):
    if isinstance(error, _Review):
        return str(error)
    if isinstance(error, SegmentationError):
        return error.reason
    return "invalid_geometry"


_GEOMETRY_ERRORS = (LayeredError, ContractError, SegmentationError, ValueError, TypeError,
                    KeyError, AttributeError, IndexError, OverflowError, np.linalg.LinAlgError)


def evaluate_visibility(
    story: Story, board: Board, library: Library, *, frame_size: tuple[int, int],
    poses: Mapping[str, PoseGeometry], profile_sha256: str | None = None,
) -> list[dict]:
    """Measure all named poses and targets from verified observations.

    This is the source check the future worker calls with its own frozen pose
    inputs. Missing/invalid evidence yields the existing review escalation.
    """
    set_id = None if story.set is None else story.set.asset_version_id
    set_version = library.get(set_id) if set_id is not None else None
    config = None if set_version is None else set_version.occlusion
    if config is None and board.layout.check_poses is None:
        return []
    config = config or {"foreground": (), "focal_props": ()}
    refs = {"layout": digest(canonical_json({
        "board": board.id, "story": story.id, "set": to_document(story.set),
        "layout": to_document(board.layout), "preset": thaw(story.layouts.get(board.layout.preset)),
        "cast": to_document(board.cast), "cues": to_document(board.cues),
        "motion_style": thaw(story.motion_style), "roles": thaw(config),
    }))}
    targets = [("face", entry.slot, None) for entry in board.cast]
    targets.extend(("prop", prop["key"], prop) for prop in config["focal_props"])
    if not targets:
        targets = [("set", "set", None)]
    requirements = board.layout.check_poses or (CheckPose("unspecified", 0),)
    clock = board_clock(board, library.facts(to_document(story))) if poses else None
    results = []
    for pose in requirements:
        geometry = poses.get(pose.key)
        framing = None
        stage = None
        try:
            if board.layout.check_poses is None:
                raise _Review("missing_pose_declaration")
            if board.method.layer != "layered":
                raise _Review("unsupported_layout_method")
            if geometry is None or type(geometry.frame) is not int or geometry.frame != pose.frame:
                raise _Review("missing_or_wrong_pose")
            if clock is None or not 0 <= pose.frame < clock.frames:
                raise _Review("pose_outside_board")
            if not is_sha256(profile_sha256):
                raise _Review("missing_profile_pin")
            width, height = frame_size
            if type(width) is not int or type(height) is not int or not (0 < min(frame_size)
                                                                         and max(frame_size) <= 1920):
                raise _Review("invalid_frame_size")
            framing = _camera_box(frame_size, board, clock, pose.frame)
            pose_refs = {**refs, "profile": profile_sha256, "pose": digest(canonical_json({
                "key": pose.key, "frame": pose.frame, "frame_size": frame_size, "framing": framing,
                "moves": thaw(geometry.moves),
            }))}
            stage = _Frame(frame_size, framing, geometry, story.production_id, profile_sha256, pose_refs)
            background = _assemble(story, board, library, config, set_id, stage)
        except _GEOMETRY_ERRORS as error:
            for kind, key, _ in targets:
                results.append(_result(board, kind, key, pose, frame_size, framing, refs if stage is None else stage.refs,
                                       reason=_reason(error)))
            continue

        common_refs = dict(stage.refs)
        for kind, key, prop in targets:
            stage.refs = dict(common_refs)
            try:
                mask, layer, order = _subject(stage, background, board, kind, key, prop)
                total, kept = measure_support(mask, layer.projection, frame_size, framing)
                for above, alpha in stage.coverage.items():
                    if above > order:
                        kept &= alpha < OCCLUDING_ALPHA
                result = _result(board, kind, key, pose, frame_size, framing, stage.refs,
                                 visible=int(np.count_nonzero(kept)), total=total)
            except _GEOMETRY_ERRORS as error:
                result = _result(board, kind, key, pose, frame_size, framing, stage.refs, reason=_reason(error))
            results.append(result)
    return results


def visibility_violations(evidence: list[dict]) -> list[Violation]:
    """Return hard pre-build refusals. Uncertain checks go to run review."""
    out = []
    for check in evidence:
        tested = check["measured"]
        if tested["status"] == "hidden":
            key, pose = tested["target"]["key"], tested["pose"]["key"]
            out.append(Violation("occlusion.hidden", pointer("layout", "check_poses"),
                                 f"{key} is hidden at pose {pose}"))
    return out
