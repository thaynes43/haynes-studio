"""Synthetic lettering, edge, face and subpixel-motion evidence."""

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw

GLYPHS = {
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
}
BANDS = ((2, (20, 20, 20), (230, 230, 230)),
         (3, (240, 240, 240), (26, 26, 26)),
         (4, (250, 229, 70), (28, 49, 112)))
MOTION = (110, 225, 460, 450)
STATIC = (650, 280, 746, 376)
FEATURES = {
    "left_highlight": (704, 670), "right_highlight": (874, 674),
    "left_lash": (729, 635), "right_lash": (906, 628),
}
EDGE_ROWS = (1150, 1380)
FLAT = (680, 1470, 920, 1670)


def luma(rgb):
    a = np.asarray(rgb, dtype=np.float32)
    return a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722


def _template(glyph, scale):
    bits = np.array([[cell == "1" for cell in row] for row in GLYPHS[glyph]])
    return bits.repeat(scale, axis=0).repeat(scale, axis=1)


def _glyph(gray, y, x, scale):
    return gray[y:y + 7 * scale, x:x + 5 * scale]


def _edge_x(y):
    return 535 + (y - EDGE_ROWS[0]) / 9


def portrait(shift=0) -> Image.Image:
    canvas = Image.new("RGB", (1080, 1920), (92, 71, 88))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((620, 250, 780, 410), fill=(73, 99, 122))
    draw.rectangle((90 + shift, 180, 485 + shift, 475), fill=(130, 90, 42))
    for i, (scale, fg, bg) in enumerate(BANDS):
        y = 230 + i * 57
        draw.rectangle((130 + shift, y - 4, 342 + shift, y + 7 * scale + 4), fill=bg)
        for j, glyph in enumerate(GLYPHS):
            x = 165 + j * 41 + shift
            bits = _template(glyph, scale)
            for dy, dx in zip(*np.nonzero(bits)):
                draw.point((x + int(dx), y + int(dy)), fill=fg)
    for x in range(137, 421, 7):
        draw.rectangle((x + shift, 411, x + shift + 1, 438), fill=(201, 165, 101))
    draw.ellipse((610, 565, 990, 1005), fill=(221, 162, 137))
    draw.ellipse((680, 640, 762, 705), fill=(28, 37, 41))
    draw.ellipse((838, 637, 945, 712), fill=(37, 32, 42))
    draw.ellipse((700, 666, 708, 674), fill=(252, 252, 252))
    draw.rectangle((871, 670, 877, 678), fill=(245, 245, 245))
    draw.line((713, 653, *FEATURES["left_lash"]), fill=(10, 19, 16), width=3)
    draw.line((891, 651, *FEATURES["right_lash"]), fill=(10, 19, 16), width=3)
    draw.arc((744, 812, 871, 887), 0, 170, fill=(129, 58, 63), width=7)
    for y in range(1090, 1440):
        boundary = int(_edge_x(y))
        draw.line((50, y, boundary, y), fill=(32, 32, 32))
        draw.line((boundary + 1, y, 1010, y), fill=(224, 224, 224))
    draw.rectangle((645, 1435, 955, 1705), fill=(128, 128, 128))
    return canvas


def _crossing(offsets, values, level):
    crossing = np.flatnonzero((values[:-1] < level) & (values[1:] >= level))
    if not len(crossing):
        return None
    i = min(crossing, key=lambda j: abs(offsets[j]))
    return offsets[i] + (level - values[i]) * (offsets[i + 1] - offsets[i]) / (values[i + 1] - values[i])


def _edge(gray):
    spreads, undershoot, overshoot = [], 0.0, 0.0
    for y in range(*EDGE_ROWS):
        boundary = _edge_x(y)
        # Use samples at pixel centers to interpolate each crossing once.
        first, last = int(np.ceil(boundary - 8)), int(np.floor(boundary + 8))
        samples = np.arange(first, last + 1) - boundary
        values = gray[y, first:last + 1]
        low = _crossing(samples, values, 32 + 0.1 * 192)
        high = _crossing(samples, values, 32 + 0.9 * 192)
        if low is not None and high is not None and high > low:
            spreads.append(high - low)
        undershoot = max(undershoot, 32.0 - values.min())
        overshoot = max(overshoot, values.max() - 224.0)
    return {
        "median_spread_px": float(np.median(spreads)) if len(spreads) == EDGE_ROWS[1] - EDGE_ROWS[0] else None,
        "dark_undershoot": float(undershoot / 255),
        "light_overshoot": float(overshoot / 255),
        "overshoot": float(max(undershoot, overshoot) / 255),
        "scanlines": len(spreads),
    }


def _text(actual, truth):
    output = []
    for i, (scale, fg, bg) in enumerate(BANDS):
        y = 230 + i * 57
        fg_y, bg_y = map(float, luma(np.asarray([fg, bg])))
        templates = {g: np.where(_template(g, scale), fg_y, bg_y) for g in GLYPHS}
        correct = ambiguous = 0
        for j, glyph in enumerate(GLYPHS):
            cell = _glyph(actual, y, 165 + j * 41, scale)
            scores = sorted((float(np.mean((cell - template) ** 2)), label) for label, template in templates.items())
            correct += scores[0][1] == glyph and scores[0][0] != scores[1][0]
            ambiguous += scores[0][0] == scores[1][0]
        roi = np.s_[y:y + 7 * scale, 161:319]
        output.append({"cap_height_px": 7 * scale, "correct": correct, "ambiguous": ambiguous,
                       "luma_mae": float(np.abs(actual[roi] - truth[roi]).mean() / 255)})
    return output


def _feature_position(gray, center, highlight):
    x, y = center
    roi = gray[y - 7:y + 8, x - 7:x + 8]
    points = np.argwhere(roi >= 200 if highlight else roi <= 90)
    if not len(points):
        return None
    if highlight:
        py, px = points.mean(axis=0)
    else:
        # The endpoint is the uppermost extent, perpendicular to the dark lash.
        tips = points[points[:, 0] == points[0, 0]]
        py, px = tips.mean(axis=0)
    return np.array([x + px - 7, y + py - 7])


def _face(actual, truth):
    distances = {}
    for name, center in FEATURES.items():
        highlight = name.endswith("highlight")
        seen = _feature_position(actual, center, highlight)
        reference = _feature_position(truth, center, highlight)
        distances[name] = float(np.linalg.norm(seen - reference)) if seen is not None else None
    return distances


def _roi(pixels, box, shift=0):
    x0, y0, x1, y1 = box
    return pixels[y0:y1, x0 + shift:x1 + shift]


def scores(rgb, reference):
    gray, truth = luma(rgb), luma(reference)
    flat = _roi(gray, FLAT)
    flat_rgb = _roi(np.asarray(rgb), FLAT).astype(np.int16)
    return {
        "edge": _edge(gray), "text": _text(gray, truth), "face_displacement_px": _face(gray, truth),
        "flat": {"std": float(flat.std() / 255), "mean_shift": float(abs(flat.mean() - 128) / 255),
                 "max_channel_span": int(np.ptp(flat_rgb, axis=2).max())},
    }


@dataclass
class Motion:
    previous: np.ndarray | None = None
    background: bytes | None = None
    identical_background: bool = True
    worst_mean: float = 0.0
    worst_p95: float = 0.0

    def add(self, rgb, reference, index):
        residual = (_roi(luma(rgb), MOTION, index) - _roi(luma(reference), MOTION, index)) / 255
        if self.previous is not None:
            delta = np.abs(residual - self.previous)
            self.worst_mean = max(self.worst_mean, float(delta.mean()))
            self.worst_p95 = max(self.worst_p95, float(np.percentile(delta, 95)))
        self.previous = residual
        background = _roi(np.asarray(rgb), STATIC).tobytes()
        if self.background is None:
            self.background = background
        self.identical_background &= background == self.background

    def report(self) -> dict:
        return {"worst_mean": self.worst_mean, "worst_p95": self.worst_p95,
                "identical_background": self.identical_background}


def baseline_meets_former_caps(baseline):
    return {
        "edge_overshoot": baseline["edge"]["overshoot"] <= 12 / 255,
        "motion_residual": baseline["motion"]["worst_mean"] <= 2 / 255,
    }


def verdicts(baseline, learned):
    edge, lanczos_edge = learned["edge"], baseline["edge"]
    spread, lanczos_spread = edge["median_spread_px"], lanczos_edge["median_spread_px"]
    flat = learned["flat"]
    motion, lanczos_motion = learned["motion"], baseline["motion"]
    text_weights = [band["cap_height_px"] for band in learned["text"]]
    text_mae = sum(weight * band["luma_mae"] for weight, band in zip(text_weights, learned["text"], strict=True))
    lanczos_text_mae = sum(weight * band["luma_mae"]
                          for weight, band in zip(text_weights, baseline["text"], strict=True))
    return {
        "edge_spread": spread is not None and lanczos_spread is not None and spread <= 0.90 * lanczos_spread,
        "edge_overshoot": edge["overshoot"] <= lanczos_edge["overshoot"] + 2 / 255,
        "glyphs": all(band["correct"] == 4 for band in learned["text"][1:]),
        "text_error": text_mae <= lanczos_text_mae,
        "face_geometry": all(d is not None and d <= 1 for d in learned["face_displacement_px"].values()),
        "flat_texture": flat["std"] <= 1 / 255 and flat["mean_shift"] <= 2 / 255 and flat["max_channel_span"] <= 2,
        "motion_residual": (motion["worst_mean"] <= lanczos_motion["worst_mean"] + 0.5 / 255
                            and motion["worst_p95"] <= lanczos_motion["worst_p95"] + 2 / 255),
        "static_background": motion["identical_background"] and lanczos_motion["identical_background"],
    }
