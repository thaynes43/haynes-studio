"""Set foreground and focal-prop visibility for explicitly named board poses."""

from __future__ import annotations

import json
import math
import struct
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass

import numpy as np
from PIL import Image, ImageChops

from haynes_studio.assets.occlusion import SegmentationIdentity, VerifiedObservation, decode_still, make_request
from haynes_studio.canonical.derive import board_clock, resolve_anchor
from haynes_studio.canonical.model import Board, CameraCue, CheckPose, Story, to_document
from haynes_studio.checks._evidence import result_document
from haynes_studio.errors import ContractError, Violation, pointer
from haynes_studio.layered import compose
from haynes_studio.layered.errors import LayeredError
from haynes_studio.layered.photo import foreground_inputs, still_geometry
from haynes_studio.layered.visibility_geometry import Projection, frame_bounds, measure_support, set_plate_crop
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
ROLE_UNSUPPORTED = "occlusion.render_unsupported"
SEPARATE_PROP_UNSUPPORTED = "occlusion.separate_prop_unsupported"
LAYOUT_UNSUPPORTED = "occlusion.layout_unsupported"
UNSUPPORTED_COMPONENTS = {
    ROLE_UNSUPPORTED: ("/set/asset_version_id", "This set declares foreground roles the renderer cannot draw"),
    SEPARATE_PROP_UNSUPPORTED: ("/set/asset_version_id", "This set declares separate props the renderer cannot draw"),
    LAYOUT_UNSUPPORTED: ("/method", "Visibility requires the layered compositor"),
}
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
    moves: Mapping[str, tuple[float, float, float] | list[float]]
    observations: Mapping[tuple[str, str], VerifiedObservation]
    hints: Mapping[tuple[str, str], Mapping] = field(default_factory=dict)


@dataclass(frozen=True)
class _Layer:
    order: int
    version: AssetVersion
    image: Image.Image
    projection: Projection
    placement: compose.Placement | None = None

    def alpha(self, size, source):
        """Use the compositor's sprite filters, padded plate and held pose."""
        if self.placement is None:
            return fit_set_plate(source, size)
        sprite = Image.new("RGBA", source.size)
        sprite.putalpha(source)
        x0, y0, x1, y1 = self.projection.placed_box
        sprite = sprite.crop(self.projection.source_box).resize((x1 - x0, y1 - y0), Image.Resampling.LANCZOS)
        plate = compose.plate(sprite, self.placement, *size)
        return compose.move_plate(plate, size, self.placement.pivot, self.projection.move).getchannel("A")


@dataclass(frozen=True)
class _Occluder:
    kind: str
    key: str
    order: int
    alpha: Image.Image | None = None
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
        if type(outcome) is not VerifiedObservation:
            raise _Review("unverified_observation")
        completion = outcome.completion
        source = {"sha256": layer.version.content.sha256,
                  "width": layer.image.width, "height": layer.image.height}
        request = make_request(source, kind=kind, key=key, label=label,
                               hint=self.geometry.hints.get((kind, key), hint))
        identity = SegmentationIdentity(self.production_id, layer.version.id,
                                        digest(canonical_json(request)), self.profile_sha256)
        if completion.identity != identity:
            raise _Review("observation_pin_mismatch")
        _, mask = describe_mask(outcome.png, layer.image.size)
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


def _cast_move(value):
    if (not isinstance(value, (tuple, list)) or len(value) != 3
            or any(isinstance(n, bool) or not isinstance(n, (int, float, np.integer, np.floating))
                   for n in value)):
        raise _Review("missing_or_invalid_move")
    if any(not -10_000 <= n <= 10_000 or not math.isfinite(n) for n in value):
        raise _Review("missing_or_invalid_move")
    return tuple(float(n) for n in value)


def _cutout(library, stage, order, preset, story, entry):
    geometry = stage.geometry
    key = entry.slot
    still = geometry.cutouts.get(key)
    if still is None or still.version_id != entry.asset_version_id:
        raise _Review("missing_or_wrong_layer")
    move = _cast_move(geometry.moves.get(key))
    version, image = _layer_image(library, still, stage.production_id, "cast", "rgba_cutout")
    slot = compose.slot_of(preset, key)
    width, height = stage.size
    if slot.height > 2 * height or abs(slot.bottom) > 2 * height:
        raise _Review("invalid_slot_geometry")
    matte = cast_matte_size(story, entry, version)
    crop, dimensions, where = still_geometry(image, slot, key, width, height, matte)
    if max(dimensions) > 2 * max(stage.size):
        raise _Review("invalid_slot_geometry")
    projection = Projection.sprite(crop, dimensions, where, stage.size, move)
    return _Layer(order, version, image, projection, where)


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


def _require(value):
    if isinstance(value, str):
        raise _Review(value)
    return value


def _assemble(story, board, library, set_id, preset, stage):
    """Resolve each rendered layer independently in the compositor's draw order."""
    cast, occluders = {}, []
    for index, entry in enumerate(board.cast, start=1):
        key, order = entry.slot, index * CAST_ORDER_STEP
        try:
            layer = _cutout(library, stage, order, preset, story, entry)
            alpha = layer.alpha(stage.size, layer.image.getchannel("A"))
        except _GEOMETRY_ERRORS as error:
            cast[key] = _reason(error)
            occluders.append(_Occluder("cast", key, order, reason=cast[key]))
        else:
            cast[key] = layer
            occluders.append(_Occluder("cast", key, order, alpha))

    try:
        background = _background(story, library, set_id, stage)
    except _GEOMETRY_ERRORS as error:
        background = _reason(error)
    order = (len(board.cast) + 1) * CAST_ORDER_STEP
    try:
        foreground = foreground_inputs(story, board)
        if foreground is not None:
            _require(background)
            edge, feather = foreground["edge_px"], foreground["feather_px"]
            if (any(len(point) != 2 or any(not math.isfinite(n) for n in point) for point in edge)
                    or any(a[0] >= b[0] for a, b in zip(edge, edge[1:]))
                    or feather is not None and (not math.isfinite(feather) or feather < 0)):
                raise _Review("invalid_foreground_geometry")
            alpha = compose.foreground_alpha(edge, feather, *stage.size)
            occluders.append(_Occluder("foreground", "legacy", order, alpha))
    except _GEOMETRY_ERRORS as error:
        occluders.append(_Occluder("foreground", "legacy", order, reason=_reason(error)))
    return cast, background, occluders


def _unsupported_target(board, config, kind, key, prop, cast_orders):
    if prop is not None and prop["depth"] == "separate":
        return SEPARATE_PROP_UNSUPPORTED
    if config["foreground"]:
        return ROLE_UNSUPPORTED
    if board.method.layer != "layered":
        return LAYOUT_UNSUPPORTED
    order = cast_orders.get(key, 0) if kind == "face" else 0
    if any(item["depth"] == "separate" and item["layer_order"] >= order
           for item in config["focal_props"]):
        return SEPARATE_PROP_UNSUPPORTED
    return None


def _subject(stage, kind, key, prop, cast, background):
    if kind == "face":
        layer = _require(cast[key])
        return stage.mask(layer, kind, key), layer
    if kind == "set":
        _require(background)
        raise _Review("missing_observation")
    if key in cast:
        raise _Review("target_key_conflicts_with_cast")
    if prop["depth"] == "unspecified":
        raise _Review("unspecified_depth")
    layer = _require(background)
    return stage.mask(layer, kind, key, prop["label"], prop.get("hint")), layer


def _visible_bounds(marker, support, order, occluders, framing):
    """Composite lower and upper target contributions in the renderer's order."""
    lower, upper = marker.copy(), marker.copy()
    unknown = []
    black = Image.new("L", marker.size)
    for layer in occluders:
        if layer.order <= order:
            continue
        # The legacy foreground redraws the same set pixels. A face has no
        # contribution on the set plate.
        source = marker if layer.kind == "foreground" and order == 0 else black
        if layer.alpha is None:
            unknown.append(layer.unknown())
            lower = ImageChops.darker(lower, source)
            upper = ImageChops.lighter(upper, source)
        else:
            lower.paste(source, mask=layer.alpha)
            upper.paste(source, mask=layer.alpha)
    lo, hi = frame_bounds(lower, upper, framing)
    return (int(np.count_nonzero(support & (lo >= OCCLUDING_ALPHA))),
            int(np.count_nonzero(support & (hi >= OCCLUDING_ALPHA))), unknown)


def _measure(stage, mask, layer, occluders):
    total, kept = measure_support(mask, layer.projection, stage.size, stage.framing)
    source = Image.fromarray(mask.astype(np.uint8) * 255)
    unoccluded = layer.alpha(stage.size, source)
    support = np.asarray(compose.frame_crop(unoccluded, stage.framing)) >= OCCLUDING_ALPHA
    # The denominator includes support clipped out of the target, in addition to
    # the support rasterized through the actual compositor inside the frame.
    total += int(np.count_nonzero(support)) - int(np.count_nonzero(kept))
    if not total:
        raise _Review("no_sampled_support")
    marker = unoccluded
    if layer.placement is not None:
        source_alpha = ImageChops.darker(source, layer.image.getchannel("A"))
        if ImageChops.difference(source, source_alpha).getbbox() is not None:
            marker = layer.alpha(stage.size, source_alpha)
    lower, upper, unknown = _visible_bounds(marker, support, layer.order, occluders, stage.framing)
    return lower, upper, total, unknown


def _supplied_sha256(value) -> str:
    """Hash supplied data, preserving mapping order, code points and numeric representation."""
    def encode(item):
        if item is None or isinstance(item, bool):
            return item
        if isinstance(item, np.generic):
            dtype = item.dtype
            data = encode(item.tolist()) if dtype.hasobject else item.tobytes().hex()
            return ["numpy.scalar", encode(dtype.descr), data]
        if isinstance(item, np.ndarray):
            data = encode(item.tolist()) if item.dtype.hasobject else item.tobytes().hex()
            return ["numpy.array", encode(item.dtype.descr), encode(item.shape), data]
        if isinstance(item, str):
            # JSON's ASCII escapes otherwise conflate a supplementary code point
            # with the two literal surrogate code points.
            return ["str", item.encode("utf-8", errors="surrogatepass").hex()]
        if isinstance(item, bytes):
            return ["bytes", digest(item)]
        if isinstance(item, int):
            return ["int", hex(item)]
        if isinstance(item, float):
            return ["float", struct.pack(">d", item).hex()]
        if isinstance(item, Mapping):
            return ["mapping", [[encode(key), encode(value)] for key, value in item.items()]]
        if isinstance(item, (tuple, list)):
            return ["tuple" if isinstance(item, tuple) else "list", [encode(value) for value in item]]
        if is_dataclass(item):
            cls = type(item)
            return ["record", cls.__module__, cls.__qualname__,
                    [[field.name, encode(getattr(item, field.name))] for field in fields(item)]]
        raise TypeError(f"Unsupported evidence input type: {type(item).__name__}")

    return digest(json.dumps(encode(value), ensure_ascii=True, separators=(",", ":")).encode("ascii"))


def evidence_sha256(evidence: dict) -> str:
    """Bind a review to the whole measurement, including its floors and input hashes."""
    return digest(canonical_json({key: value for key, value in evidence.items() if key != "artifact"}))


def _result(board, kind, key, pose, size, framing, refs, *, lower=0, upper=0, total=0,
            unknown=(), reason=None):
    if reason in UNSUPPORTED_COMPONENTS:
        status = "unsupported"
    elif not total:
        status = "uncertain"
    elif upper * 100 <= total * HIDDEN_MAX_PERCENT:
        status = "hidden"
    elif lower * 100 >= total * VISIBLE_MIN_PERCENT:
        status = "visible"
    else:
        status = "uncertain"
        if unknown:
            reason = "unknown_occluders"
        else:
            reason = "visibility_between_floors"
    evidence = result_document(
        CHECK, VERSION, refs,
        {"visible": "pass", "hidden": "fail", "uncertain": "uncertain", "unsupported": "fail"}[status],
        thresholds=dict(THRESHOLDS),
        measured={"board_id": board.id, "target": {"kind": kind, "key": key}, "pose": to_document(pose),
                  "framing": {"size_px": None if size is None else list(size),
                              "crop_xyxy": None if framing is None else list(framing)},
                  "visible_lower_pixels": lower, "visible_upper_pixels": upper, "total_pixels": total,
                  "unknown_occluders": list(unknown),
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
    cast_orders = {entry.slot: index * CAST_ORDER_STEP for index, entry in enumerate(board.cast, start=1)}
    targets = [("face", entry.slot, None) for entry in board.cast]
    targets.extend(("prop", prop["key"], prop) for prop in config["focal_props"])
    if not targets:
        targets = [("set", "set", None)]
    targets = [(*target, _unsupported_target(board, config, *target, cast_orders)) for target in targets]
    if config["foreground"] and all(reason != ROLE_UNSUPPORTED for _, _, _, reason in targets):
        targets.append(("set", "set", None, ROLE_UNSUPPORTED))
    requirements = board.layout.check_poses or (CheckPose("unspecified", 0),)
    results = []
    for pose in requirements:
        geometry = poses.get(pose.key)
        pose_refs = {**refs, "pose": _supplied_sha256((pose, pose_pins.get(pose.key)))}
        framing = None
        if all(reason is not None for _, _, _, reason in targets):
            results.extend(_result(board, kind, key, pose, size, framing, pose_refs, reason=reason)
                           for kind, key, _, reason in targets)
            continue
        try:
            if board.layout.check_poses is None:
                raise _Review("missing_pose_declaration")
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
            results.extend(_result(board, kind, key, pose, size, framing, pose_refs, reason=reason or _reason(error))
                           for kind, key, _, reason in targets)
            continue

        stage = _Frame(size, framing, geometry, story.production_id, profile_sha256)
        cast, background, occluders = _assemble(story, board, library, set_id, preset, stage)
        for kind, key, prop, reason in targets:
            try:
                if reason is not None:
                    raise _Review(reason)
                mask, layer = _subject(stage, kind, key, prop, cast, background)
                lower, upper, total, unknown = _measure(stage, mask, layer, occluders)
                result = _result(board, kind, key, pose, size, framing, pose_refs,
                                 lower=lower, upper=upper, total=total, unknown=unknown)
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
        elif tested["status"] == "unsupported":
            rule = tested["reason"]
            if not any(violation.rule == rule for violation in out):
                path, message = UNSUPPORTED_COMPONENTS[rule]
                out.append(Violation(rule, path, message))
    return out
