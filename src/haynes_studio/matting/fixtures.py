"""Bounded synthetic inputs and region-specific scores for the install smoke."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt

from .pixels import linear_srgb, srgb_bytes

WIDTH, HEIGHT = 384, 512
SUBPIXELS = 4
EYES = ((154, 179), (230, 179))
GREEN = (36, 180, 60)
GREY = (148, 148, 148)


@dataclass(frozen=True)
class Fixture:
    rgb: np.ndarray
    alpha: np.ndarray
    strands: np.ndarray
    lashes: tuple[np.ndarray, np.ndarray]
    irises: tuple[np.ndarray, np.ndarray]


def _scaled(coords):
    return tuple(value * SUBPIXELS for value in coords)


def _annotation(layer: Image.Image) -> np.ndarray:
    return np.array(layer.resize((WIDTH, HEIGHT), Image.Resampling.BOX))


def bust(*, green: bool = False, smaller: bool = False) -> Fixture:
    size = _scaled((WIDTH, HEIGHT))
    layer = Image.new("RGBA", size)
    draw = ImageDraw.Draw(layer)
    draw.ellipse(_scaled((60, 272, 324, 434)), fill=(64, 71, 90, 255))
    draw.ellipse(_scaled((104, 280, 272, 420)), fill=(83, 92, 116, 255))
    draw.ellipse(_scaled((100, 88, 284, 296)), fill=(211, 155, 128, 255))
    draw.ellipse(_scaled((112, 101, 253, 260)), fill=(228, 177, 150, 255))
    draw.ellipse(_scaled((124, 138, 144, 174)), fill=(240, 199, 180, 255))
    draw.ellipse(_scaled((167, 227, 213, 243)), fill=(134, 69, 66, 255))
    hair = (40, 27, 33, 255)
    draw.ellipse(_scaled((91, 70, 293, 153)), fill=hair)
    draw.ellipse(_scaled((92, 100, 121, 228)), fill=hair)
    draw.ellipse(_scaled((263, 102, 292, 229)), fill=hair)

    strand_layer = Image.new("L", size)
    strands = ImageDraw.Draw(strand_layer)
    for side in (-1, 1):
        for index in range(4):
            points = [
                _scaled((192 + side * (66 + 66 * step / 24),
                         93 + 10 * index - 79 * step / 24 + 64 * (step / 24)**2))
                for step in range(25)
            ]
            width = (1 + index % 3) * SUBPIXELS
            draw.line(points, fill=hair, width=width)
            strands.line(points, fill=255, width=width)

    lash_layers, iris_layers = [], []
    for index, (x, y) in enumerate(EYES):
        bounds = (x - 13, y - 11, x + 13, y + 9)
        draw.ellipse(_scaled(bounds), fill=(246, 234, 218, 255))
        draw.ellipse(_scaled((x - 9, y - 6, x + 9, y + 6)),
                     fill=(*(GREEN if green else (51, 71, 83)), 255))
        lash_layer = Image.new("L", size)
        width = (2 - index) * SUBPIXELS
        draw.arc(_scaled(bounds), 190, 350, fill=hair, width=width)
        ImageDraw.Draw(lash_layer).arc(_scaled(bounds), 190, 350, fill=255, width=width)
        lash_layers.append(lash_layer)
        iris_layer = Image.new("L", size)
        ImageDraw.Draw(iris_layer).ellipse(_scaled((x - 9, y - 6, x + 9, y + 6)), fill=255)
        iris_layers.append(iris_layer)
    if smaller:
        reduced = layer.resize(tuple(3 * edge // 4 for edge in size), Image.Resampling.BOX)
        layer = Image.new("RGBA", size)
        layer.paste(reduced, tuple(edge // 8 for edge in size))

    rgba = _annotation(layer)
    alpha = rgba[..., 3]
    coverage = alpha[..., None] / 255
    rgb = srgb_bytes(coverage * linear_srgb(rgba[..., :3])
                     + (1 - coverage) * linear_srgb(np.asarray(GREEN if green else GREY)))
    return Fixture(rgb, alpha, _annotation(strand_layer),
                   tuple(_annotation(image) for image in lash_layers),
                   tuple(_annotation(image) for image in iris_layers))


def _metric(value: float, threshold: float, *, minimum: bool = True) -> dict:
    passed = value >= threshold if minimum else value <= threshold
    return {
        "value": round(float(value), 6), "threshold": threshold,
        "comparison": ">=" if minimum else "<=", "passed": bool(passed),
    }


def score_shape(fixture: Fixture, alpha: np.ndarray) -> dict:
    true_silhouette, silhouette = fixture.alpha >= 128, alpha >= 128
    core = (fixture.alpha == 255) & (distance_transform_edt(fixture.alpha == 255) >= 4)
    fringe = (fixture.strands > 0) & (fixture.alpha >= 0.05 * 255) & (fixture.alpha <= 0.9 * 255)
    outside = ~true_silhouette & (distance_transform_edt(~true_silhouette) <= 4)
    difference = np.abs(alpha[fringe].astype(np.int16) - fixture.alpha[fringe]) / 255
    return {
        "silhouette_iou": _metric((true_silhouette & silhouette).sum() / (true_silhouette | silhouette).sum(), 0.92),
        "core_coverage": _metric((alpha[core] >= 243).mean(), 0.98),
        "strand_mae": _metric(difference.mean(), 0.20, minimum=False),
        "lash_left": _metric((alpha[fixture.lashes[0] == 255] >= 243).mean(), 0.80),
        "lash_right": _metric((alpha[fixture.lashes[1] == 255] >= 243).mean(), 0.80),
        "outside_band_mean_alpha": _metric(alpha[outside].mean() / 255, 0.08, minimum=False),
    }


def score_eyes(fixture: Fixture, cutout: np.ndarray) -> dict:
    alpha = cutout[..., 3]
    outside = ~ (fixture.alpha >= 128)
    remote = outside & (distance_transform_edt(outside) >= 8)
    metrics = {"remote_background": _metric((alpha[remote] <= 8).mean(), 0.99)}
    for name, iris in zip(("left", "right"), fixture.irises):
        interior = distance_transform_edt(iris == 255) > 1
        retained = interior & (alpha >= 243)
        metrics[name + "_coverage"] = _metric(retained.sum() / interior.sum(), 0.95)
        change = np.abs(cutout[retained, :3].astype(np.int16) - fixture.rgb[retained])
        metrics[name + "_rgb_error"] = _metric(change.max(initial=0), 0, minimum=False)
    return metrics


def score_size(true_shape: dict, base_shape: dict, small_true_shape: dict, small_shape: dict) -> dict:
    metrics = {}
    for name, truth, shape in (("base", true_shape, base_shape), ("small", small_true_shape, small_shape)):
        bounds_error = max(abs(measured - actual)
                           for measured, actual in zip(shape["bbox_xyxy"], truth["bbox_xyxy"]))
        scale = shape["scale"]
        height = shape["bbox_height_px"] * scale["numerator"] / scale["denominator"]
        metrics[name + "_bounds_error_px"] = _metric(bounds_error, 3, minimum=False)
        metrics[name + "_height_error_px"] = _metric(abs(height - true_shape["bbox_height_px"]),
                                                    1, minimum=False)
    ratio = (small_shape["scale"]["numerator"] / small_shape["scale"]["denominator"]
             / (base_shape["scale"]["numerator"] / base_shape["scale"]["denominator"]))
    metrics["scale_ratio_relative_error"] = _metric(abs(ratio / (4 / 3) - 1), 0.03, minimum=False)
    return metrics
