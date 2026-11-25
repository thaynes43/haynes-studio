"""Set foreground and focal-prop visibility for explicitly named board poses."""

from __future__ import annotations

import json
import struct
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass

import numpy as np
from PIL import Image

from haynes_studio.assets.occlusion import SegmentationIdentity, SegmentationOutcome, decode_still, make_request
from haynes_studio.canonical.derive import board_clock, resolve_anchor
from haynes_studio.canonical.model import Board, CameraCue, CheckPose, Story, to_document
from haynes_studio.checks._evidence import result_document
from haynes_studio.errors import ContractError, Violation, pointer
from haynes_studio.layered import compose
from haynes_studio.layered.errors import LayeredError
from haynes_studio.layered.photo import still_geometry
from haynes_studio.layered.visibility_geometry import Projection, frame_alpha, measure_support, set_plate_crop
from haynes_studio.library import AssetVersion, Library
from haynes_studio.motion.record import LOOP, SET
from haynes_studio.motion.resolve import candidates
from haynes_studio.photo.plan import cast_matte_size
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


@dataclass(frozen=True)
class _Occluder:
    kind: str
    key: str
    order: int
    alpha: np.ndarray | None = None
    reason: str | None = None

    def unknown(self):
        return {"kind": self.kind, "key": self.key, "layer_order": self.order, "reason": self.reason}


class _Review(ValueError):
    pass


@dataclass
class _Frame:
    size: tuple[int, int]
    framing: tuple[int, int, int, int]
    geometry: PoseGeometry
    production_id: str
    profile_sha256: str

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
        if (completion.result.sha256 != digest(outcome.receipt)
                or completion.result.bytes != len(outcome.receipt)
                or completion.result.media_type != "application/json"):
            raise _Review("observation_receipt_mismatch")
        if completion.status != "ready" or completion.mask is None or outcome.png is None:
            raise _Review(completion.reason or "missing_observation")
        descriptor, mask = describe_mask(outcome.png, layer.image.size)
        if (descriptor["sha256"] != completion.mask.sha256
                or descriptor["bytes"] != completion.mask.bytes
                or completion.mask.media_type != "image/png"):
            raise _Review("observation_mask_mismatch")
        if layer.order and (mask & (np.asarray(layer.image.getchannel("A")) == 0)).any():
            raise _Review("observation_mask_mismatch")
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


def _cutout(library, stage, key, order, source_id, kind, preset, *, story=None, entry=None):
    geometry = stage.geometry
    still = geometry.cutouts.get(key)
    move = geometry.moves.get(key, ())
    if still is None or still.version_id != source_id:
        raise _Review("missing_or_wrong_layer")
    version, image = _layer_image(library, still, stage.production_id, kind, "rgba_cutout")
    slot = compose.slot_of(preset, key)
    width, height = stage.size
    if slot.height > 2 * height or abs(slot.bottom) > 2 * height:
        raise _Review("invalid_slot_geometry")
    matte = cast_matte_size(story, entry, version) if entry is not None else None
    if matte is not None and matte["target_height_px"] > slot.bottom:
        raise _Review("invalid_slot_geometry")
    crop, dimensions, where = still_geometry(image, slot, key, width, height, matte)
    if max(dimensions) > 2 * max(stage.size):
        raise _Review("invalid_slot_geometry")
    if len(move) != 3 or any(abs(compose._number(n, "move value")) > 10_000 for n in move):
        raise _Review("missing_or_invalid_move")
    projection = Projection.sprite(crop, dimensions, where, stage.size, move)
    return _Layer(order, version, image, projection), crop, dimensions, where


def _background(story, library, set_id, stage):
    if stage.geometry.plate.version_id != set_id:
        raise _Review("missing_or_wrong_plate")
    version, image = _layer_image(library, stage.geometry.plate, stage.production_id, "set", "opaque_plate")
    if story.set.motion_asset_version_id is not None or candidates(
        library, use=LOOP, subject=SET, still_sha256=version.content.sha256,
        production_id=stage.production_id,
    ):
        raise _Review("moving_plate_needs_pose_source")
    return _Layer(0, version, image, Projection.plate(set_plate_crop(image.size, stage.size), stage.size))


def _role_mask(stage, background, role, cast):
    if role["key"] in cast:
        raise _Review("target_key_conflicts_with_cast")
    if role["layer_order"] <= len(cast) * CAST_ORDER_STEP:
        raise _Review("invalid_foreground_order")
    return stage.mask(_require(background), "foreground", role["key"], role["label"], role.get("hint"))


def _require(value):
    if isinstance(value, str):
        raise _Review(value)
    return value


def _assemble(story, board, library, config, set_id, preset, stage):
    """Resolve each layer independently so only higher occluders affect a target's bounds."""
    cast, roles, occluders = {}, {}, []
    width, height = stage.size
    for index, entry in enumerate(board.cast, start=1):
        key, order = entry.slot, index * CAST_ORDER_STEP
        try:
            layer, crop, dimensions, where = _cutout(
                library, stage, key, order, entry.asset_version_id, "cast", preset, story=story, entry=entry,
            )
        except _GEOMETRY_ERRORS as error:
            cast[key] = _reason(error)
            occluders.append(_Occluder("cast", key, order, reason=cast[key]))
            continue
        cast[key] = layer
        try:
            sprite = layer.image.crop(crop).resize(dimensions, Image.Resampling.LANCZOS)
            plate = compose.plate(sprite, where, width, height)
            posed = compose.move_plate(plate, stage.size, where.pivot, layer.projection.move)
            alpha = frame_alpha(posed.getchannel("A"), stage.size, stage.framing)
            occluders.append(_Occluder("cast", key, order, alpha))
        except _GEOMETRY_ERRORS as error:
            occluders.append(_Occluder("cast", key, order, reason=_reason(error)))

    try:
        background = _background(story, library, set_id, stage)
    except _GEOMETRY_ERRORS as error:
        background = _reason(error)
    for role in config["foreground"]:
        key, order = role["key"], role["layer_order"]
        try:
            mask = _role_mask(stage, background, role, cast)
        except _GEOMETRY_ERRORS as error:
            roles[key] = _reason(error)
        else:
            roles[key] = mask
        if board.layout.foreground:
            try:
                alpha = fit_set_plate(Image.fromarray(_require(roles[key]).astype(np.uint8) * 255), stage.size)
                occluders.append(_Occluder("foreground", key, order, frame_alpha(alpha, stage.size, stage.framing)))
            except _GEOMETRY_ERRORS as error:
                occluders.append(_Occluder("foreground", key, order, reason=_reason(error)))

    legacy = None
    if (board.layout.foreground and not config["foreground"] and story.set is not None
            and story.set.foreground_edge_px is not None):
        order = 1 + max([len(board.cast) * CAST_ORDER_STEP,
                         *(prop.get("layer_order", 0) for prop in config["focal_props"])])
        try:
            alpha = compose.foreground_alpha(story.set.foreground_edge_px, story.set.foreground_feather_px,
                                             width, height)
            legacy = _Occluder("foreground", "legacy", order, frame_alpha(alpha, stage.size, stage.framing))
        except _GEOMETRY_ERRORS as error:
            legacy = _Occluder("foreground", "legacy", order, reason=_reason(error))
    return cast, background, roles, occluders, legacy


def _subject(stage, board, kind, key, prop, library, preset, cast, background, roles):
    if kind == "face":
        layer = _require(cast[key])
        return stage.mask(layer, kind, key), layer, layer.order
    if key in cast:
        raise _Review("target_key_conflicts_with_cast")
    depth = prop["depth"]
    if depth == "unspecified":
        raise _Review("unspecified_depth")
    if depth == "separate":
        order = prop["layer_order"]
        if order in range(CAST_ORDER_STEP, (len(cast) + 1) * CAST_ORDER_STEP, CAST_ORDER_STEP):
            raise _Review("duplicate_layer_order")
        layer, *_ = _cutout(library, stage, key, order, prop["source_asset_version_id"], "prop", preset)
        return stage.mask(layer, kind, key, prop["label"], prop.get("hint")), layer, order
    layer = _require(background)
    mask = stage.mask(layer, kind, key, prop["label"], prop.get("hint"))
    assigned_role = prop.get("foreground_role")
    if assigned_role is not None and (mask & ~_require(roles[assigned_role])).any():
        raise _Review("mask_straddles_depth")
    order = prop["layer_order"] if assigned_role and board.layout.foreground else 0
    return mask, layer, order


def _visible_bounds(kept, order, occluders, *, redraw=None):
    """Count support with known coverage, possible coverage and possible plate restoration."""
    visible = kept.copy()
    unknown = []
    for layer in occluders:
        if layer.order <= order:
            continue
        if layer.alpha is None:
            unknown.append(layer.unknown())
        else:
            visible &= layer.alpha < OCCLUDING_ALPHA
    known = int(np.count_nonzero(visible))
    # An unresolved occluder has no proven extent, so it may cover all kept support.
    lower = 0 if unknown else known
    if redraw is not None:
        if redraw.alpha is None:
            unknown.append(redraw.unknown())
            visible = kept
        else:
            visible |= kept & (redraw.alpha > 0)
    upper = int(np.count_nonzero(visible))
    return lower, upper, unknown, upper - known


def _supplied_sha256(value) -> str:
    """Hash supported input values before validation, preserving exact bytes and IEEE floats."""
    def encode(item):
        if item is None or isinstance(item, (bool, str)):
            return item
        if isinstance(item, bytes):
            return ["bytes", digest(item)]
        if isinstance(item, int):
            return ["int", hex(item)]
        if isinstance(item, float):
            return ["float", struct.pack(">d", item).hex()]
        if isinstance(item, Mapping):
            pairs = [(encode(key), encode(value)) for key, value in item.items()]
            return ["mapping", sorted(pairs, key=lambda pair: json.dumps(pair[0], ensure_ascii=True))]
        if isinstance(item, (tuple, list)):
            return [type(item).__name__, [encode(value) for value in item]]
        if is_dataclass(item):
            return [type(item).__qualname__, [[field.name, encode(getattr(item, field.name))]
                                              for field in fields(item)]]
        raise TypeError(f"Unsupported evidence input type: {type(item).__name__}")

    return digest(json.dumps(encode(value), ensure_ascii=True, separators=(",", ":")).encode("ascii"))


def evidence_sha256(evidence: dict) -> str:
    """Bind a review to the whole measurement, including its floors and input hashes."""
    return digest(canonical_json({key: value for key, value in evidence.items() if key != "artifact"}))


def _result(board, kind, key, pose, size, framing, refs, *, lower=0, upper=0, total=0,
            unknown=(), restored=0, reason=None):
    if not total:
        status = "uncertain"
    elif upper * 100 <= total * HIDDEN_MAX_PERCENT:
        status = "hidden"
    elif lower * 100 >= total * VISIBLE_MIN_PERCENT:
        status = "visible"
    else:
        status = "uncertain"
        if unknown:
            reason = "unknown_occluders"
        elif restored:
            reason = "legacy_foreground_needs_depth_geometry"
        else:
            reason = "visibility_between_floors"
    evidence = result_document(
        CHECK, VERSION, refs, {"visible": "pass", "hidden": "fail", "uncertain": "uncertain"}[status],
        thresholds=dict(THRESHOLDS),
        measured={"board_id": board.id, "target": {"kind": kind, "key": key}, "pose": to_document(pose),
                  "framing": {"size_px": None if size is None else list(size),
                              "crop_xyxy": None if framing is None else list(framing)},
                  "visible_lower_pixels": lower, "visible_upper_pixels": upper, "total_pixels": total,
                  "unknown_occluders": list(unknown), "possible_redraw_pixels": restored,
                  "status": status, "reason": reason},
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
    preset = story.layouts.get(board.layout.preset)
    # Capture even undeclared poses and rejected inputs once, before resolving any target.
    pose_pins = {key: _supplied_sha256(geometry) for key, geometry in poses.items()}
    refs = {"layout": _supplied_sha256((story, board, config)),
            "inputs": _supplied_sha256((frame_size, profile_sha256, pose_pins))}
    if poses:
        refs["library"] = _supplied_sha256(library.documents())
    size = None
    if (isinstance(frame_size, (tuple, list)) and len(frame_size) == 2
            and all(type(n) is int and 0 < n <= 1920 for n in frame_size)):
        size = tuple(frame_size)
    targets = [("face", entry.slot, None) for entry in board.cast]
    targets.extend(("prop", prop["key"], prop) for prop in config["focal_props"])
    if not targets:
        targets = [("set", "set", None)]
    requirements = board.layout.check_poses or (CheckPose("unspecified", 0),)
    results = []
    for pose in requirements:
        geometry = poses.get(pose.key)
        pose_refs = {**refs, "pose": _supplied_sha256((pose, pose_pins.get(pose.key)))}
        framing = None
        try:
            if board.layout.check_poses is None:
                raise _Review("missing_pose_declaration")
            if board.method.layer != "layered":
                raise _Review("unsupported_layout_method")
            if geometry is None or type(geometry.frame) is not int or geometry.frame != pose.frame:
                raise _Review("missing_or_wrong_pose")
            clock = board_clock(board, library.facts(to_document(story)))
            if clock is None or not 0 <= pose.frame < clock.frames:
                raise _Review("pose_outside_board")
            if not is_sha256(profile_sha256):
                raise _Review("missing_profile_pin")
            if size is None:
                raise _Review("invalid_frame_size")
            framing = _camera_box(size, board, clock, pose.frame)
        except _GEOMETRY_ERRORS as error:
            results.extend(_result(board, kind, key, pose, size, framing, pose_refs, reason=_reason(error))
                           for kind, key, _ in targets)
            continue

        stage = _Frame(size, framing, geometry, story.production_id, profile_sha256)
        cast, background, roles, occluders, legacy = _assemble(story, board, library, config, set_id, preset, stage)
        for kind, key, prop in targets:
            try:
                if kind == "set":
                    _require(background)
                    raise _Review("missing_observation")
                mask, layer, order = _subject(stage, board, kind, key, prop, library, preset, cast, background, roles)
                total, kept = measure_support(mask, layer.projection, size, framing)
                if prop is not None and prop["depth"] == "background":
                    lower, upper, unknown, restored = _visible_bounds(kept, order, occluders, redraw=legacy)
                else:
                    higher = occluders if legacy is None else [*occluders, legacy]
                    lower, upper, unknown, restored = _visible_bounds(kept, order, higher)
                result = _result(board, kind, key, pose, size, framing, pose_refs,
                                 lower=lower, upper=upper, total=total, unknown=unknown, restored=restored)
            except _GEOMETRY_ERRORS as error:
                result = _result(board, kind, key, pose, size, framing, pose_refs, reason=_reason(error))
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
