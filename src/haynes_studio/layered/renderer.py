"""The layered segment renderer (story 426): a board's frames from its set, its keyed
doll layers and its voice, on the board clock.

:class:`LayeredRenderer` implements :class:`~haynes_studio.render.base.SegmentRenderer`
for ``layered`` + ``s2v`` and ``layered`` + ``i2v`` boards. From the segment key document
alone (no film frame, no neighbouring board, P-06) it:

1. refuses what it does not draw (:func:`check_segment`): another method, an unknown
   input, a layer that names no pinned record, a cue it cannot run, no set;
2. reads every keyed artifact, the set loop or plate and the voice track by hash,
   re-hashed; a missing one is ``time.source_short``;
3. maps every board frame to a source frame of every layer (the table below) and fails
   a short clip before the first frame (``time.source_short``, P-05: nothing is held);
4. applies the decal gate of every keyed layer with a decal, over the source frames the
   board shows: a track below the layer's floor fails the segment before any frame is
   drawn (``layered.decal_weak``), and the check result is kept in
   :attr:`LayeredRenderer.checks`;
5. yields exactly the board's frames: set, then each doll in draw order (shadow, body,
   motion), then the foreground edge, then the camera.

| Layer | Clock | Board frame ``n`` shows | Clip longer than the board | Clip shorter |
|---|---|---|---|---|
| Doll loop, set loop (TIME-8a) | board | ``trim_start + pingpong(n + phase, N)`` | ping-pong (never trimmed) | ping-pong (never short) |
| S2V layer, library timed clip (TIME-8) | board | ``trim_start + floor(n * fs / 24)`` | extra frames trimmed (reported) | fails, ``time.source_short`` |
| Set plate | none | the plate, fitted to the frame | | |

``procedural_stream`` is accepted and draws nothing: the layered method has no
procedural layer (legacy fire is the rigid renderer's).
"""

from __future__ import annotations

import io
import wave
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import PIL
import PIL.Image
import PIL.ImageOps

from haynes_studio.cache.keys import check_result_key
from haynes_studio.layered import compose, keying
from haynes_studio.layered.errors import (
    CLIP_INVALID,
    DECAL_WEAK,
    METHOD_UNAVAILABLE,
    SOURCE_SHORT,
    UNSUPPORTED,
    LayeredError,
)
from haynes_studio.layered.keyed import decode_png, frame_pngs, read_record, read_verified
from haynes_studio.render.base import SegmentRenderer, SegmentRequest
from haynes_studio.render.clock import loop_frame, source_frame
from haynes_studio.render.encode import decode_frames
from haynes_studio.timebase import DELIVERY_FPS

# Proposal: the segment key's compositor digest; it names the builds that draw pixels.
COMPOSITOR = f"studio.layered/1+pillow-{PIL.__version__}+numpy-{np.__version__}"
LOOP, TIMED = "loop", "timed"
DECAL_CHECK, DECAL_CHECK_VERSION = "layered.decal_gate", "1"

# Every input of a segment key document, and what this renderer does with it.
SEGMENT_INPUTS = {
    "kind": "draw", "scheme": "draw", "method": "draw", "frames": "draw", "width": "draw",
    "height": "draw", "fps": "draw", "layout": "draw", "layers": "draw", "set_layer": "draw",
    "motion_style": "draw", "voice_envelope": "draw", "talk": "draw", "cues": "draw",
    "foreground": "draw", "compositor": "draw", "encoder": "draw", "procedural_stream": "none",
    "whole_frame_clip": "absent",
}
LAYER_FIELDS = ("slot", "still", "clip", "keyed", "role", "phase", "play", "trim_start",
                "trim_frames", "source_fps", "clip_frames", "decal_min_ecc")


def _int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def check_segment(inputs: Mapping[str, Any]) -> None:
    """Refuse a segment this renderer cannot draw exactly (module docstring)."""
    method = inputs.get("method") or {}
    layer, motion = method.get("layer"), method.get("motion")
    if (layer, motion) == ("whole_frame", "s2v"):
        raise LayeredError(METHOD_UNAVAILABLE, "whole-frame speech-to-video has no adapter",
                           where="/method")
    if layer != "layered" or motion not in ("s2v", "i2v"):
        raise LayeredError(UNSUPPORTED, f"method {layer}+{motion} is not a layered board", where="/method")
    unknown = sorted(set(inputs) - set(SEGMENT_INPUTS))
    if unknown:
        raise LayeredError(UNSUPPORTED, f"unknown segment inputs {unknown}", where="(root)")
    if inputs.get("whole_frame_clip") is not None:
        raise LayeredError(UNSUPPORTED, "a layered board draws no whole-frame clip", where="/whole_frame_clip")
    if inputs.get("fps") != DELIVERY_FPS:
        raise LayeredError(UNSUPPORTED, f"fps {inputs.get('fps')!r} is not {DELIVERY_FPS}", where="/fps")
    if not isinstance(inputs.get("layout"), Mapping):
        raise LayeredError(UNSUPPORTED, "a layered board names its layout preset", where="/layout")
    layers = inputs.get("layers") or []
    if not layers:
        raise LayeredError(UNSUPPORTED, "a layered board has at least one cast layer", where="/layers")
    for index, item in enumerate(layers):
        missing = [name for name in LAYER_FIELDS if name not in item]
        if missing or item.get("play") not in (LOOP, TIMED) or not item.get("keyed"):
            raise LayeredError(UNSUPPORTED, f"layer {index} names no pinned motion record and keyed "
                               f"frames (missing {missing or ['play', 'keyed']}); plan with motion "
                               "records", where=f"/layers/{index}")
        if item["play"] == LOOP and not (_int(item["phase"]) and _int(item["trim_frames"])
                                         and item["trim_frames"] >= 1):
            raise LayeredError(UNSUPPORTED, f"loop layer {index} names no phase or N", where=f"/layers/{index}")
        if item["play"] == TIMED and not (_int(item["source_fps"]) and item["source_fps"] >= 1):
            raise LayeredError(UNSUPPORTED, f"timed layer {index} names no source fps", where=f"/layers/{index}")
    set_layer = inputs.get("set_layer")
    if not isinstance(set_layer, Mapping) or not (set_layer.get("plate") or set_layer.get("loop")):
        raise LayeredError(UNSUPPORTED, "a layered board draws on a set plate or set loop", where="/set_layer")
    if set_layer.get("loop") and not (_int(set_layer.get("phase")) and _int(set_layer.get("trim_frames"))):
        raise LayeredError(UNSUPPORTED, "the set loop names no phase or N", where="/set_layer")
    check_style(inputs.get("motion_style"))
    slots = {item["slot"] for item in layers}
    cameras = 0
    for index, cue in enumerate(inputs.get("cues") or []):
        if cue.get("type") == "move":
            if cue.get("slot") not in slots:
                raise LayeredError(UNSUPPORTED, f"move cue {index} moves slot {cue.get('slot')!r}, "
                                   "which is not on the board", where=f"/cues/{index}")
        elif cue.get("type") == "camera":
            cameras += 1
            if cue.get("easing") not in compose.EASINGS or not cue.get("zoom_from") or not cue.get("zoom_to"):
                raise LayeredError(UNSUPPORTED, f"camera cue {index} has an easing or zoom this "
                                   "renderer does not draw", where=f"/cues/{index}")
        else:
            raise LayeredError(UNSUPPORTED, f"cue {index} of type {cue.get('type')!r} is not a "
                               "picture cue", where=f"/cues/{index}")
    if cameras > 1:
        raise LayeredError(UNSUPPORTED, "one camera cue per board, as legacy (proposal)", where="/cues")


def check_style(style: Any) -> None:
    """A motion style names only the PoC's four settings, each a finite number."""
    if style is None:
        return
    if not isinstance(style, Mapping) or set(style) - set(compose.STYLE_DEFAULTS) or any(
            isinstance(v, bool) or not isinstance(v, int | float) or v != v or v in (float("inf"), float("-inf"))
            for v in style.values()):
        raise LayeredError(UNSUPPORTED, f"motion style {style!r} is not numbers for "
                           f"{', '.join(compose.STYLE_DEFAULTS)}", where="/motion_style")


def decal_check(keyed_sha256: str, record: Mapping[str, Any], floor: float | None,
                shown: set[int] | None = None) -> dict[str, Any] | None:
    """The decal gate's check result for one keyed artifact (None without a decal),
    over the source frames the board shows (``shown``; all when None). Frame 0 is the
    track's template and has no score (**proposal**: the PoC gated every frame, also
    the ones a board trims)."""
    decal = record.get("decal")
    if decal is None:
        return None
    floor = keying.MIN_ECC if floor is None else floor
    scores = decal["scores"]
    if shown is not None:
        scores = [scores[i - 1] for i in sorted(shown) if 1 <= i <= len(scores)]
    summary = {**keying.summarize(scores), "frames_gated": len(scores)}
    thresholds = {"min_ecc": floor}
    return {"check": DECAL_CHECK, "version": DECAL_CHECK_VERSION, "artifact": keyed_sha256,
            "key": check_result_key(artifact=keyed_sha256, check=DECAL_CHECK,
                                    version=DECAL_CHECK_VERSION, thresholds=thresholds).value,
            "thresholds": thresholds, "result": summary,
            "passed": keying.gate(summary, floor)}


@dataclass
class _Layer:
    item: Mapping[str, Any]
    record: Mapping[str, Any]
    pngs: list[bytes]
    slot: compose.Slot
    puppet: compose.Puppet
    placement: compose.Placement | None = None
    size: tuple[int, int] | None = None
    shadow: PIL.Image.Image | None = None

    def index(self, n: int) -> int:
        item = self.item
        if item["play"] == LOOP:
            return item["trim_start"] + loop_frame(n, item["phase"], item["trim_frames"])
        return item["trim_start"] + source_frame(n, item["source_fps"], DELIVERY_FPS)


@dataclass(frozen=True)
class LayeredReport:
    """What one render used, per layer: the clip and keyed hashes, how it plays, the
    source frames it showed and how many it trimmed. Not a cache input; the run
    records it (story 406)."""

    key: str
    layers: tuple[Mapping[str, Any], ...]
    set: Mapping[str, Any]
    checks: tuple[Mapping[str, Any], ...]

    def to_document(self) -> dict[str, Any]:
        return {"segment_key": self.key, "layers": [dict(x) for x in self.layers],
                "set": dict(self.set), "checks": [dict(c) for c in self.checks]}


@dataclass
class LayeredRenderer(SegmentRenderer):
    """Draws layered boards from their keyed layers (see the module docstring).
    ``checks`` holds every decal check result by segment key, kept even when the gate
    fails; ``reports`` is written only after the last frame."""

    compositor: str = COMPOSITOR
    reports: dict[str, LayeredReport] = field(default_factory=dict)
    checks: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def render(self, request: SegmentRequest) -> Iterator[np.ndarray]:
        inputs = request.inputs
        check_segment(inputs)
        width, height, frames = request.width, request.height, request.frames
        layout = inputs["layout"]
        single = compose.is_single(layout)
        checks: list[dict[str, Any]] = []
        self.checks[request.key] = checks
        layers: list[_Layer] = []
        for k, item in enumerate(inputs["layers"]):
            data = _read(request, item["keyed"], f"layer {item['slot']}'s keyed frames")
            record = read_record(data)
            if item["clip_frames"] is not None and record["frames"] != item["clip_frames"]:
                raise LayeredError(SOURCE_SHORT if record["frames"] < item["clip_frames"] else CLIP_INVALID,
                                   f"slot {item['slot']}: keyed {record['frames']} frames of a "
                                   f"{item['clip_frames']}-frame clip", where=item["keyed"])
            slot = compose.slot_of(layout, item["slot"])
            box = record["box"]
            size = compose.sprite_size((box[2] - box[0], box[3] - box[1]), slot)
            layer = _Layer(item=item, record=record, pngs=frame_pngs(data, record), slot=slot,
                           puppet=compose.Puppet(item["slot"], k, single), size=size,
                           placement=compose.place(size, slot, width, item["slot"]))
            last = max(layer.index(n) for n in _extremes(item, frames))
            if last >= len(layer.pngs):
                raise LayeredError(SOURCE_SHORT, f"slot {item['slot']}: board frame {frames - 1} needs "
                                   f"source frame {last}; the clip has {len(layer.pngs)} (TIME-8, "
                                   "nothing is held)", where=item["keyed"])
            shown = {layer.index(n) for n in range(frames)}
            check = decal_check(item["keyed"], record, item["decal_min_ecc"], shown)
            if check is not None:
                checks.append({"slot": item["slot"], **check})
                if not check["passed"]:
                    raise LayeredError(DECAL_WEAK, f"slot {item['slot']}: the decal track is too weak "
                                       f"(min {check['result']['min_ecc']}, "
                                       f"{check['result']['failed_frames']} failed; floor "
                                       f"{check['thresholds']['min_ecc']}); re-roll the clip or "
                                       "record a lower decal_min_ecc", where=item["keyed"], check=check)
            layers.append(layer)
        background = _Set(request, inputs["set_layer"], frames, width, height)
        talks: tuple[compose.Talk, ...] = ()
        if inputs.get("voice_envelope") and inputs.get("talk"):
            talks = _talks(_read(request, inputs["voice_envelope"], "the board voice track"),
                           inputs["talk"])
        moves = [cue for cue in inputs.get("cues") or [] if cue["type"] == "move"]
        camera = next((cue for cue in inputs.get("cues") or [] if cue["type"] == "camera"), None)
        fg = inputs.get("foreground")
        fg_alpha = None if not fg else compose.foreground_alpha(fg["edge_px"], fg.get("feather_px"),
                                                                width, height)
        return self._frames(request, layers, background, talks, moves, camera, fg_alpha,
                            inputs.get("motion_style"), checks)

    def _frames(self, request: SegmentRequest, layers: list[_Layer], background: _Set,
                talks: tuple[compose.Talk, ...], moves: list[Mapping[str, Any]],
                camera: Mapping[str, Any] | None, fg_alpha: PIL.Image.Image | None,
                style: Mapping[str, Any] | None, checks: list[dict[str, Any]]) -> Iterator[np.ndarray]:
        width, height = request.width, request.height
        used: list[set[int]] = [set() for _ in layers]
        for n in range(request.frames):
            bg = background.frame(n)
            frame = bg.convert("RGBA")
            for i, layer in enumerate(layers):
                index = layer.index(n)
                used[i].add(index)
                image = PIL.Image.fromarray(decode_png(layer.pngs[index]), "RGBA")
                art = compose.sprite(image, layer.slot)
                if art.size != layer.size:
                    raise LayeredError(CLIP_INVALID, f"slot {layer.item['slot']}: keyed frames differ "
                                       "in size")
                assert layer.placement is not None
                plate = compose.plate(art, layer.placement, width, height)
                if layer.shadow is None:  # one soft shadow per doll per board (the PoC's)
                    layer.shadow = compose.shadow(plate)
                dx, dy, angle = compose.motion(layer.puppet, n, style, talks, moves)
                compose.draw(frame, plate, layer.shadow, layer.placement.pivot, dx, dy, angle)
            if fg_alpha is not None:
                frame.alpha_composite(compose.foreground(bg, fg_alpha))
            yield np.asarray(compose.camera(frame.convert("RGB"), camera, n / DELIVERY_FPS))
        self.reports[request.key] = LayeredReport(
            key=request.key, checks=tuple(checks), set=background.report(),
            layers=tuple({"slot": layer.item["slot"], "role": layer.item["role"],
                          "play": layer.item["play"], "clip": layer.item["clip"],
                          "keyed": layer.item["keyed"], "phase": layer.item["phase"],
                          "source_frames": len(layer.pngs), "first": layer.index(0),
                          "last": layer.index(request.frames - 1), "distinct": len(used[i]),
                          "trimmed": (len(layer.pngs) - 1 - layer.index(request.frames - 1)
                                      if layer.item["play"] == TIMED else 0)}
                         for i, layer in enumerate(layers)))


def _extremes(item: Mapping[str, Any], frames: int) -> tuple[int, ...]:
    """Board frames whose source frames bound a layer's: the last frame of a timed
    clip (monotonic), every frame of a loop's first period (at most ``2N - 2``)."""
    if item["play"] == TIMED:
        return (frames - 1,)
    return tuple(range(min(frames, max(1, 2 * item["trim_frames"] - 2))))


def _read(request: SegmentRequest, sha256: str, what: str) -> bytes:
    try:
        return read_verified(request.open, sha256, what)
    except LookupError as error:  # a request with no input reader
        raise LayeredError(SOURCE_SHORT, f"{what} cannot be read: {error}", where=sha256) from error


def _talks(data: bytes, talk: list[Mapping[str, Any]]) -> tuple[compose.Talk, ...]:
    try:
        with wave.open(io.BytesIO(data), "rb") as track:
            rate, width, channels = track.getframerate(), track.getsampwidth(), track.getnchannels()
            pcm = track.readframes(track.getnframes())
    except (wave.Error, EOFError, ValueError) as error:
        raise LayeredError(CLIP_INVALID, f"the voice track is not a PCM WAV ({type(error).__name__})") from error
    if width != 2 or rate % compose.POSE_HZ:
        raise LayeredError(UNSUPPORTED, f"the voice track is {8 * width}-bit at {rate} Hz; the "
                           "envelope reads 16-bit PCM at a rate of whole 1/12 s hops")
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float64).reshape(-1, channels).mean(axis=1) / 32768
    return compose.envelope(samples, rate, talk)


class _Set:
    """The board's set: a set loop on the board clock (TIME-8a), else the plate."""

    def __init__(self, request: SegmentRequest, layer: Mapping[str, Any], frames: int,
                 width: int, height: int):
        self.layer, self.size = layer, (width, height)
        self.loop: list[np.ndarray] | None = None
        self.plate: PIL.Image.Image | None = None
        if layer.get("loop"):
            data = _read(request, layer["loop"], "the set loop")
            try:
                self.loop = list(decode_frames(data))
            except Exception as error:  # PyAV raises its own error types for damaged media
                raise LayeredError(CLIP_INVALID, f"the set loop does not decode: "
                                   f"{type(error).__name__}") from error
            have, need = len(self.loop), layer["trim_start"] + layer["trim_frames"]
            expected = layer.get("clip_frames")
            if have < need or (expected is not None and have < expected):
                raise LayeredError(SOURCE_SHORT, f"the set loop decodes to {have} frames; its record "
                                   f"needs {max(need, expected or 0)}", where=layer["loop"])
            if expected is not None and have != expected:
                raise LayeredError(CLIP_INVALID, f"the set loop decodes to {have} frames, its record "
                                   f"says {expected}", where=layer["loop"])
            sh, sw = self.loop[0].shape[:2]
            if sw * height != sh * width:
                raise LayeredError(UNSUPPORTED, f"a {sw}x{sh} set loop is not the {width}x{height} "
                                   "board's aspect; it is neither cropped nor padded")
        else:
            data = _read(request, layer["plate"], "the set plate")
            try:
                with PIL.Image.open(io.BytesIO(data)) as image:
                    self.plate = PIL.ImageOps.fit(image.convert("RGB"), self.size,
                                                  method=PIL.Image.Resampling.LANCZOS)
            except Exception as error:
                raise LayeredError(CLIP_INVALID, f"the set plate does not decode: "
                                   f"{type(error).__name__}") from error
        self.used: set[int] = set()

    def index(self, n: int) -> int:
        layer = self.layer
        return layer["trim_start"] + loop_frame(n, layer["phase"], layer["trim_frames"])

    def frame(self, n: int) -> PIL.Image.Image:
        if self.loop is None:
            assert self.plate is not None
            return self.plate
        index = self.index(n)
        self.used.add(index)
        image = PIL.Image.fromarray(self.loop[index])
        return image if image.size == self.size else image.resize(self.size, PIL.Image.Resampling.LANCZOS)

    def report(self) -> dict[str, Any]:
        if self.loop is None:
            return {"plate": self.layer["plate"], "fit": "lanczos fit (cover, centred)"}
        return {"loop": self.layer["loop"], "phase": self.layer["phase"], "play": LOOP,
                "source_frames": len(self.loop), "distinct": len(self.used)}


__all__ = ["COMPOSITOR", "DECAL_CHECK", "LayeredRenderer", "LayeredReport", "SEGMENT_INPUTS",
           "check_segment", "check_style", "decal_check"]
