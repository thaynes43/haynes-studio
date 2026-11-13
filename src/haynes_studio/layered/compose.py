"""Drawing a layered board, ported from the PoC's ``poc/edit.py`` and
``poc/layered_film.py`` (story 426): placement by layout preset, crops, the soft
shadow, the rigid motion (idle wobble, talk bounce, scripted moves), the foreground edge
and the camera push-in. The renderer (:mod:`.renderer`) and the board photo
(:mod:`.photo`) share it.

What differs from the PoC, and why:

- **Time is the board clock, exact.** A pose is held for two delivery frames, so the
  pose time of board frame ``n`` is ``(n // 2) / 12`` s (the PoC's ``floor(t * 12) / 12``
  with ``t = n / 24``), and a line's or move's position in it is computed in fractions
  of milliseconds, so no float rounding moves a held step (contract section 3: floats
  never carry time). The PoC's float arithmetic could take a step one pose early.
- **Anchors are resolved** before drawing: a move or camera cue starts at its
  ``start_ms`` on the board (the PoC's ``at`` or ``after_line``), and the camera push
  starts at its cue, not at the shot's first frame. ``steps`` is the cue's (legacy 3).
- **"Single" framing** (the PoC's ``shot['layout'] == 'single'``: motion factor 1.4,
  full idle and hop) is read from the preset's values, not its name: a preset with no
  ``slots`` (one doll placed by the preset's own ``x``, ``height``, ``bottom``)
  is single (**proposal**; r4's ``single`` is its only preset without slots).
- **Refusals instead of asserts:** a slot the preset does not place, a field that is
  not a number, or a doll more than 240 px off the frame is ``layered.layout_invalid``.

Constants are the PoC's: the 240 px plate margin, the 22 px shadow blur at 16 %
opacity offset (12, 6), the pivot 80 px above the slot's bottom, the trajectory knots,
the motion style defaults (idle 0.3, hop 34, tilt 3.2, shuffle 7), 12 poses a second.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from fractions import Fraction
from dataclasses import dataclass
from typing import Any

import numpy as np
import PIL.Image
import PIL.ImageFilter

from haynes_studio.layered.errors import LAYOUT_INVALID, UNSUPPORTED, LayeredError

PAD = 240  # edit.PAD: the off-frame margin on each side of a doll plate
POSE_HZ = 12  # edit.POSE_HZ: every movement is held for two 24 fps frames
SHADOW_RGB = (28, 24, 18)
SHADOW_BLUR, SHADOW_OPACITY, SHADOW_OFFSET = 22, 0.16, (12, 6)
PIVOT_ABOVE = 80
STYLE_DEFAULTS = {"idle_scale": 0.3, "talk_hop": 34, "talk_tilt": 3.2, "talk_shuffle": 7}
KNOTS = [(0, 0, 16, 0), (.25, -12, -12, -1.6), (.5, 2, 0, .5), (1.1, 8, -6, 1.2),
         (1.4, -7, 3, -.8), (2.0, 4, -8, .8), (2.35, -9, 1, -1.2), (2.8, 5, -5, .5),
         (3.3, -3, 2, -.4), (3.8, 0, 0, 0), (5, 0, 0, 0)]
EASINGS = ("ease_out_cubic",)


def _number(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise LayeredError(LAYOUT_INVALID, f"{what} is not a number: {value!r}")
    return value


def is_single(layout: Mapping[str, Any]) -> bool:
    """The PoC's "single" framing: a preset without ``slots`` (module docstring)."""
    return "slots" not in layout


@dataclass(frozen=True)
class Slot:
    """Where a preset places one doll: height and bottom in frame pixels, centre x as a
    fraction of the frame width, an optional crop of the cutout (fractions)."""

    height: int
    bottom: float
    x: float
    crop: tuple[float, float, float, float] | None


def slot_of(layout: Mapping[str, Any], slot: str) -> Slot:
    """The preset's placement of ``slot`` (``edit.place``): the slot's own values, else
    the preset's; a bare number is the slot's ``x``."""
    if not isinstance(layout, Mapping):
        raise LayeredError(LAYOUT_INVALID, "the layout preset is not an object")
    spec: Any = {}
    if "slots" in layout:
        slots = layout["slots"]
        if not isinstance(slots, Mapping) or slot not in slots:
            raise LayeredError(LAYOUT_INVALID, f"the layout preset places no slot {slot!r}")
        spec = slots[slot]
    if isinstance(spec, int | float) and not isinstance(spec, bool):
        spec = {"x": spec}
    if not isinstance(spec, Mapping):
        raise LayeredError(LAYOUT_INVALID, f"slot {slot!r} of the layout preset is not an object")
    height = _number(spec.get("height", layout.get("height")), f"slot {slot!r} height")
    if height != int(height) or height < 1:
        raise LayeredError(LAYOUT_INVALID, f"slot {slot!r} height {height!r} is not whole pixels")
    crop = spec.get("crop")
    if crop is not None:
        if not isinstance(crop, Sequence) or len(crop) != 4:
            raise LayeredError(LAYOUT_INVALID, f"slot {slot!r} crop is not [x0, y0, x1, y1]")
        crop = tuple(_number(v, f"slot {slot!r} crop") for v in crop)
        if not (0 <= crop[0] < crop[2] <= 1 and 0 <= crop[1] < crop[3] <= 1):
            raise LayeredError(LAYOUT_INVALID, f"slot {slot!r} crop {list(crop)} is not inside 0..1")
    return Slot(height=int(height), bottom=_number(spec.get("bottom", layout.get("bottom")),
                                                   f"slot {slot!r} bottom"),
                x=_number(spec.get("x", layout.get("x")), f"slot {slot!r} x"), crop=crop)


def sprite(image: PIL.Image.Image, slot: Slot) -> PIL.Image.Image:
    """The doll as drawn: cropped by the slot's fractions, scaled to its height
    (Lanczos), as the PoC did for every frame."""
    if slot.crop is not None:
        fx0, fy0, fx1, fy1 = slot.crop
        image = image.crop((round(fx0 * image.width), round(fy0 * image.height),
                            round(fx1 * image.width), round(fy1 * image.height)))
    if image.height < 1 or image.width < 1:
        raise LayeredError(LAYOUT_INVALID, "the slot's crop leaves nothing of the doll")
    width = max(1, round(image.width * slot.height / image.height))
    return image.resize((width, slot.height), PIL.Image.Resampling.LANCZOS)


def sprite_size(size: tuple[int, int], slot: Slot) -> tuple[int, int]:
    """The size :func:`sprite` gives an image of ``size``, without drawing it."""
    width, height = size
    if slot.crop is not None:
        fx0, fy0, fx1, fy1 = slot.crop
        width = round(fx1 * width) - round(fx0 * width)
        height = round(fy1 * height) - round(fy0 * height)
    if width < 1 or height < 1:
        raise LayeredError(LAYOUT_INVALID, "the slot's crop leaves nothing of the doll")
    return max(1, round(width * slot.height / height)), slot.height


@dataclass(frozen=True)
class Placement:
    """A doll's place on a board: its sprite's top-left corner, its centre and bottom
    (in frame pixels) and the pivot it rocks around (in plate pixels)."""

    x: int
    y: int
    cx: float
    bottom: float

    @property
    def pivot(self) -> tuple[float, float]:
        return (self.cx + PAD, self.bottom - PIVOT_ABOVE)


def place(size: tuple[int, int], slot: Slot, width: int, slot_name: str) -> Placement:
    """Where a sprite of ``size`` goes on a frame ``width`` wide; more than
    :data:`PAD` off the frame is ``layered.layout_invalid`` (``edit.place``)."""
    cx = slot.x * width
    x, y = round(cx - size[0] / 2), round(slot.bottom - size[1])
    if x + PAD < 0 or x + size[0] > width + PAD:
        raise LayeredError(LAYOUT_INVALID, f"slot {slot_name!r} puts the doll more than {PAD} px "
                           "off the frame")
    return Placement(x=x, y=y, cx=cx, bottom=slot.bottom)


def plate(image: PIL.Image.Image, where: Placement, width: int, height: int) -> PIL.Image.Image:
    """A full-height plate wider than the frame by :data:`PAD` each side, the sprite
    cut at the frame's bottom (``edit.place``)."""
    out = PIL.Image.new("RGBA", (width + 2 * PAD, height))
    top = max(0, -where.y)  # a doll taller than the frame is cut at the top too
    keep = max(0, min(image.height, height - where.y))
    if keep > top:
        out.alpha_composite(image.crop((0, top, image.width, keep)), (where.x + PAD, where.y + top))
    return out


def shadow(plate_image: PIL.Image.Image) -> PIL.Image.Image:
    """The doll's soft shadow from its plate (``edit.place``)."""
    out = PIL.Image.new("RGBA", plate_image.size, (*SHADOW_RGB, 0))
    out.putalpha(plate_image.getchannel("A").filter(PIL.ImageFilter.GaussianBlur(SHADOW_BLUR))
                 .point(lambda v: round(v * SHADOW_OPACITY)))
    return out


def draw(frame: PIL.Image.Image, plate_image: PIL.Image.Image, shadow_image: PIL.Image.Image,
         pivot: tuple[float, float], dx: float, dy: float, angle: float) -> None:
    """Composite one doll, shadow then body, moved by (dx, dy, angle) (``edit.draw``)."""
    width, height = frame.size
    for layer, off in ((shadow_image, (dx + SHADOW_OFFSET[0], dy + SHADOW_OFFSET[1])),
                       (plate_image, (dx, dy))):
        moved = layer.rotate(angle, resample=PIL.Image.Resampling.BICUBIC, center=pivot, translate=off)
        frame.alpha_composite(moved.crop((PAD, 0, PAD + width, height)))


def foreground_alpha(edge_px: Sequence[Sequence[float]], feather_px: float | None,
                     width: int, height: int) -> PIL.Image.Image:
    """The foreground's alpha: opaque below the measured edge (a polyline), feathered
    above it (``edit.foreground_layer``)."""
    points = np.array(edge_px, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 2:
        raise LayeredError(UNSUPPORTED, "the foreground edge is not a polyline of [x, y] points")
    feather = feather_px or 0
    edge = np.interp(np.arange(width), points[:, 0], points[:, 1])[None, :]
    ramp = np.clip((np.arange(height)[:, None] - (edge - feather)) / max(feather, 1), 0, 1)
    return PIL.Image.fromarray((ramp * 255).astype(np.uint8))


def foreground(background: PIL.Image.Image, alpha: PIL.Image.Image) -> PIL.Image.Image:
    layer = background.convert("RGBA")
    layer.putalpha(alpha)
    return layer


def camera(frame: PIL.Image.Image, cue: Mapping[str, Any] | None, t: float) -> PIL.Image.Image:
    """The push-in of a camera cue at board time ``t`` s (``edit.camera``): from
    ``zoom_from`` at the cue's start to ``zoom_to`` after ``duration_ms``, eased out
    (cubic), toward ``center_px``; before the cue, ``zoom_from``."""
    if cue is None:
        return frame
    start, over = cue["start_ms"] / 1000, cue["duration_ms"] / 1000
    u = 0.0 if t < start else 1.0 if over <= 0 else min(1.0, (t - start) / over)
    u = 1 - (1 - u) ** 3
    z = cue["zoom_from"] + (cue["zoom_to"] - cue["zoom_from"]) * u
    if abs(z - 1) < 1e-3:
        return frame
    width, height = frame.size
    cx, cy = cue["center_px"]
    w, h = width / z, height / z
    x0, y0 = min(max(cx - w / 2, 0), width - w), min(max(cy - h / 2, 0), height - h)
    return frame.crop((round(x0), round(y0), round(x0 + w), round(y0 + h))).resize(
        (width, height), PIL.Image.Resampling.BICUBIC)


def trajectory(t: float, sign: int, factor: float, phase: float = 0.0) -> tuple[float, float, float]:
    """OP345's held-pose rock (``edit.trajectory``)."""
    q = math.floor((t + phase) * POSE_HZ) / POSE_HZ % 5
    for lo, hi in zip(KNOTS, KNOTS[1:]):
        if lo[0] <= q <= hi[0]:
            u = (q - lo[0]) / (hi[0] - lo[0])
            u = u * u * (3 - 2 * u)
            x = lo[1] + u * (hi[1] - lo[1])
            y = lo[2] + u * (hi[2] - lo[2])
            a = lo[3] + u * (hi[3] - lo[3])
            return sign * x * factor, y * 1.45, sign * a * factor
    return 0.0, 0.0, 0.0


@dataclass(frozen=True)
class Talk:
    """One line's bounce curve: who speaks, from when (ms on the board), and the
    loudness at 12 poses a second scaled 0..1 (``edit.speech_envelope``)."""

    speaker: str
    start_ms: int
    curve: tuple[float, ...]


def envelope(samples: np.ndarray, rate: int, talk: Sequence[Mapping[str, Any]]) -> tuple[Talk, ...]:
    """Each line's curve from the board voice track (mono, from board time 0): the
    RMS of every 1/12 s of the line's span, scaled by its loudest."""
    hop = rate // POSE_HZ
    out = []
    for item in talk:
        start, end = item["start_ms"] * rate // 1000, item["end_ms"] * rate // 1000
        audio = samples[start:end]
        values = np.array([math.sqrt(float(np.mean(audio[i:i + hop] ** 2)))
                           for i in range(0, len(audio), hop)] or [0.0])
        out.append(Talk(item["speaker"], item["start_ms"],
                        tuple(float(v) for v in values / max(float(values.max()), 1e-8))))
    return tuple(out)


@dataclass(frozen=True)
class Puppet:
    """One placed doll's motion inputs: slot, draw index ``k`` (sign and phase), the
    framing's factor (1.4 single, else 0.8)."""

    slot: str
    k: int
    single: bool

    @property
    def sign(self) -> int:
        return 1 if self.k % 2 == 0 else -1

    @property
    def factor(self) -> float:
        return 1.4 if self.single else 0.8

    @property
    def phase(self) -> float:
        return 0.37 * self.k


def motion(puppet: Puppet, n: int, style: Mapping[str, Any] | None, talks: Sequence[Talk],
           moves: Sequence[Mapping[str, Any]]) -> tuple[float, float, float]:
    """The doll's offset at board frame ``n`` (``edit.motion``): idle wobble, a hop and
    tilt on each syllable while she speaks, and her moves, in order, each in ``steps``
    held steps. Quantized to 12 poses a second on the board clock."""
    pose = n // 2  # the pose index; its time is pose / 12 s
    q = Fraction(pose, POSE_HZ)
    style = {**STYLE_DEFAULTS, **(style or {})}
    idle = style["idle_scale"] * (1.0 if puppet.single else 0.6)
    dx, dy, angle = trajectory(pose / POSE_HZ, puppet.sign, puppet.factor * idle, puppet.phase)
    dy *= idle
    for talk in talks:
        if talk.speaker != puppet.slot:
            continue
        k = int(round((q - Fraction(talk.start_ms, 1000)) * POSE_HZ))
        if 0 <= k < len(talk.curve):
            e = talk.curve[k]
            hop = style["talk_hop"] * (1.0 if puppet.single else 0.7)
            dy -= hop * e
            angle += style["talk_tilt"] * e * (1 if (k // 2) % 2 == 0 else -1)
            dx += style["talk_shuffle"] * e * (1 if (k // 3) % 2 == 0 else -1)
    for move in moves:
        at = Fraction(move["start_ms"], 1000)
        if move["slot"] != puppet.slot or q < at:
            continue
        duration = Fraction(move["duration_ms"], 1000)
        u = Fraction(1) if duration == 0 else min(Fraction(1), (q - at) / duration)
        steps = move["steps"]
        u = math.ceil(u * steps) / steps
        dx += move["dx_px"] * u
        dy += move["dy_px"] * u
        angle += move["angle_deg"] * u
    return dx, dy, angle


__all__ = ["EASINGS", "PAD", "POSE_HZ", "Placement", "Puppet", "STYLE_DEFAULTS", "Slot", "Talk",
           "camera", "draw", "envelope", "foreground", "foreground_alpha", "is_single", "motion",
           "place", "plate", "shadow", "slot_of", "sprite", "sprite_size", "trajectory"]
