"""Rasterize unoccluded support through the layered compositor's coordinate mapping."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image

from haynes_studio.layered import compose

MAX_MEASUREMENT_PIXELS = 16_777_216


@dataclass(frozen=True)
class Projection:
    source_box: tuple[float, float, float, float]
    placed_box: tuple[float, float, float, float]
    pre_motion_clip: tuple[float, float, float, float]
    pivot: tuple[float, float] = (0, 0)
    move: tuple[float, float, float] = (0, 0, 0)

    @classmethod
    def plate(cls, crop, size):
        frame = (0, 0, *size)
        return cls(crop, frame, frame)

    @classmethod
    def sprite(cls, crop, sprite_size, where: compose.Placement, frame_size, move):
        left, top = where.x, where.y
        right, bottom = left + sprite_size[0], top + sprite_size[1]
        width, height = frame_size
        clip = (max(-compose.PAD, left), max(0, top), min(width + compose.PAD, right),
                min(height, bottom))
        return cls(crop, (left, top, right, bottom), clip,
                   (where.cx, where.pivot[1]), move)


def frame_alpha(alpha: Image.Image, size: tuple[int, int], framing) -> np.ndarray:
    """A rendered layer's alpha with the camera applied, before any compositing."""
    full_frame = (0, 0, *size)
    if framing != full_frame:
        alpha = alpha.crop(framing).resize(size, Image.Resampling.BICUBIC)
    return np.asarray(alpha)


def _map_box(source, destination):
    """Map the edges of one box to another, preserving pixel-centre coordinates."""
    x0, y0, x1, y1 = source
    left, top, right, bottom = destination
    sx, sy = (right - left) / (x1 - x0), (bottom - top) / (y1 - y0)
    return np.array(((sx, 0, left - sx * x0), (0, sy, top - sy * y0), (0, 0, 1)))


def _unmove(projection):
    dx, dy, angle = projection.move
    x, y = projection.pivot
    radians = math.radians(angle % 360)
    cosine, sine = round(math.cos(radians), 15), round(math.sin(radians), 15)
    return np.array(((cosine, -sine, x - cosine * (x + dx) + sine * (y + dy)),
                     (sine, cosine, y - sine * (x + dx) - cosine * (y + dy)), (0, 0, 1)))


def measure_support(mask: np.ndarray, projection: Projection, size: tuple[int, int], framing):
    """Return exact counts on the framed pixel grid before clips, and kept support.

    The same affine map continues outside the crop and frame for the denominator.
    Binary geometry uses nearest-neighbour pixel centres. Only higher layers use
    the compositor's interpolated alpha.
    """
    image = Image.fromarray(mask)
    x0, y0, x1, y1 = image.getbbox()
    full_frame = (0, 0, *size)
    to_before_move = _unmove(projection) @ _map_box(full_frame, framing)
    inverse = _map_box(projection.placed_box, projection.source_box) @ to_before_move
    corners = np.linalg.solve(inverse, np.array(((x0, x1, x0, x1), (y0, y0, y1, y1), (1, 1, 1, 1))))
    left, top = np.floor(corners[:2].min(axis=1)).astype(int)
    right, bottom = np.ceil(corners[:2].max(axis=1)).astype(int)
    if (not (0 < right - left <= MAX_MEASUREMENT_PIXELS and 0 < bottom - top <= MAX_MEASUREMENT_PIXELS)
            or (right - left) * (bottom - top) > MAX_MEASUREMENT_PIXELS):
        raise ValueError("the unoccluded projection exceeds the measurement budget")
    offset = np.array(((1, 0, left), (0, 1, top), (0, 0, 1)))
    raster = image.transform((int(right - left), int(bottom - top)), Image.Transform.AFFINE,
                             tuple((inverse @ offset)[:2].ravel()), Image.Resampling.NEAREST)
    support = np.asarray(raster)
    total = int(np.count_nonzero(support))
    if not total:
        raise ValueError("the unoccluded projection has no sampled support")

    width, height = size
    start_x, start_y = max(0, left), max(0, top)
    end_x, end_y = min(width, right), min(height, bottom)
    kept = np.zeros((height, width), dtype=bool)
    if start_x >= end_x or start_y >= end_y:
        return total, kept

    xs = np.arange(start_x, end_x)[None, :] + 0.5
    ys = np.arange(start_y, end_y)[:, None] + 0.5
    pre_x = to_before_move[0, 0] * xs + to_before_move[0, 1] * ys + to_before_move[0, 2]
    pre_y = to_before_move[1, 0] * xs + to_before_move[1, 1] * ys + to_before_move[1, 2]
    clip_x, clip_y, clip_right, clip_bottom = projection.pre_motion_clip
    kept[start_y:end_y, start_x:end_x] = (
        support[start_y - top:end_y - top, start_x - left:end_x - left]
        & (clip_x <= pre_x) & (pre_x < clip_right) & (clip_y <= pre_y) & (pre_y < clip_bottom)
    )
    return total, kept
