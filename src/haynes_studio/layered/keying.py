"""The chroma key and the tracked lettering decal, ported from the PoC (story 426).

- :func:`key` is ``poc/cutout.py key`` (the keyer E0's motion records name, ``legacy:poc/
  cutout.py key``): green dominance ``G - max(R, B)`` gives the alpha between ``lo``
  (opaque) and ``hi`` (transparent); background is the green touching the frame edge,
  enclosed pockets over 3000 px and strongly green islands outside the protect boxes;
  in a 24 px band around it the key colour is unmixed and the rest despilled; the alpha
  is shrunk by a pixel and feathered by 0.8 px. Same arithmetic, same constants.
- :func:`decal_frames` is ``poc/decal.py decal_frames`` with ``erase`` on (decal version
  ``erase-v2``, legacy ``DollClip.cache_dir``): the jacket is tracked from frame 0 by
  OpenCV ECC (affine, 60 iterations, eps 1e-4, Gaussian 5) inside the decal box grown
  by 40 px, the clip's own lettering is inpainted, and the still's yellow letters (plus
  a 4 px band, feathered by 2 px) are pasted back, warped by the track. A failed track
  is a ``None`` score, never hidden (:func:`summarize`).

It works one frame at a time (a generator), so a clip is never held whole in memory.
OpenCV runs at two threads, as the PoC set it (``cv2.setNumThreads(2)``); scipy and
numpy here are single-threaded. Pure functions of their inputs: no file, clock or
service is read.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from typing import Any

import cv2
import numpy as np
import PIL.Image
import PIL.ImageFilter
import scipy.ndimage as ndimage

cv2.setNumThreads(2)  # AGENTS.md: two threads in a session pod; poc/decal.py does the same

# The keyer and decal this module implements, by the names a motion record gives them.
KEYERS = ("legacy:poc/cutout.py key", "studio.layered.keyer/1")
DECAL_VERSIONS = ("erase-v2",)
MIN_ECC = 0.8  # poc/decal.py MIN_ECC: the decal gate unless a record sets decal_min_ecc

# poc/cutout.py key() defaults and poc/decal.py decal_frames() defaults, as the PoC
# called them (layered_film.DollClip: key(im, 20, 70, protect); decal_frames(st, src, box)).
BAND_PX, POCKET_PX, GAP_DOMINANCE = 24, 3000, 45
GROW, BAND, FEATHER = 40, 4, 2
ECC_ITERATIONS, ECC_EPS, ECC_GAUSS = 60, 1e-4, 5
CROP_PAD = 24  # DollClip: the first frame's doll plus 24 px, one box for every frame


def key(rgb: np.ndarray, lo: float, hi: float, protect: Sequence[Sequence[int]] = (),
        band_px: int = BAND_PX, pocket_px: int = POCKET_PX,
        gap_dominance: float = GAP_DOMINANCE) -> np.ndarray:
    """An RGB ``uint8`` frame on green as RGBA ``uint8`` (``poc/cutout.py key``)."""
    a = np.asarray(rgb, dtype=np.uint8)[..., :3].astype(np.float32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    dominance = g - np.maximum(r, b)
    raw = 1 - np.clip((dominance - lo) / (hi - lo), 0, 1)
    labels, n = ndimage.label(raw < 0.5)
    index = np.arange(n + 1)
    sizes = ndimage.sum_labels(np.ones_like(raw), labels, index)
    greenness = ndimage.median(dominance, labels, index)
    edge = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])))
    boxes = ndimage.find_objects(labels)
    boxes_protected = [tuple(int(v) for v in box) for box in protect]

    def protected(i: int) -> bool:
        y, x = boxes[i - 1]
        return any(x0 <= x.start and x.stop <= x1 and y0 <= y.start and y.stop <= y1
                   for x0, y0, x1, y1 in boxes_protected)

    keep = np.array([i != 0 and (i in edge or ((sizes[i] > pocket_px or greenness[i] >= gap_dominance)
                                              and not protected(i))) for i in range(n + 1)])
    background = keep[labels]
    band = ndimage.binary_dilation(background, iterations=band_px)
    alpha = np.where(band, raw, 1.0)
    key_rgb = np.median(np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]]), axis=0)
    w = np.clip(alpha, 0.05, 1)[..., None]
    unmixed = np.where(band[..., None], (a - (1 - w) * key_rgb) / w, a).clip(0, 255)
    ur, ug, ub = unmixed[..., 0], unmixed[..., 1], unmixed[..., 2]
    unmixed[..., 1] = np.where(band, np.minimum(ug, (ur + ub) / 2), ug)
    mask = PIL.Image.fromarray((alpha * 255).astype(np.uint8))
    mask = mask.filter(PIL.ImageFilter.MinFilter(3)).filter(PIL.ImageFilter.GaussianBlur(0.8))
    out = PIL.Image.fromarray(unmixed.astype(np.uint8)).convert("RGBA")
    out.putalpha(mask)
    return np.asarray(out)


def summarize(scores: Sequence[float | None]) -> dict[str, Any]:
    """The tracking summary with failures counted (``poc/decal.py summarize``)."""
    ok = [s for s in scores if s is not None]
    return {"frames_tracked": len(ok), "failed_frames": len(scores) - len(ok),
            "min_ecc": min(ok) if ok else None,
            "mean_ecc": round(sum(ok) / len(ok), 4) if ok else None}


def erase_lettering(frame: np.ndarray, region: np.ndarray) -> np.ndarray:
    """Inpaint yellow lettering inside ``region`` (a 0/1 ``uint8`` mask)."""
    r, g, b = (frame[..., i].astype(int) for i in range(3))
    yellow = ((r > 140) & (g > 100) & (b < 100) & (r - b > 90)).astype(np.uint8) * region
    if not yellow.any():
        return frame
    yellow = cv2.dilate(yellow, np.ones((5, 5), np.uint8))
    return cv2.inpaint(np.ascontiguousarray(frame), yellow, 4, cv2.INPAINT_TELEA)


def decal_frames(still: np.ndarray, frames: Iterable[np.ndarray], box: Sequence[int], *,
                 grow: int = GROW, band: int = BAND, feather: int = FEATHER,
                 erase: bool = True) -> Iterator[tuple[np.ndarray, float | None]]:
    """Each frame with the still's lettering pasted back, and its ECC score (``None``
    for frame 0, which is the template, and for a failed track). ``still`` and every
    frame are RGB ``uint8`` arrays of one size (``poc/decal.py decal_frames``)."""
    x0, y0, x1, y1 = (int(v) for v in box)
    template = None
    for i, fr in enumerate(frames):
        fr = np.ascontiguousarray(fr)
        if template is None:
            h, w = fr.shape[:2]
            gx0, gy0, gx1, gy1 = max(0, x0 - grow), max(0, y0 - grow), min(w, x1 + grow), min(h, y1 + grow)
            template = cv2.cvtColor(fr[gy0:gy1, gx0:gx1], cv2.COLOR_RGB2GRAY).astype(np.float32)
            sr, sg, sb = (still[..., c].astype(int) for c in range(3))
            letters = ((sr > 170) & (sg > 130) & (sb < 100) & (sr - sb > 110)).astype(np.uint8)
            keep = np.zeros((h, w), np.uint8)
            keep[y0:y1, x0:x1] = 1
            letters *= keep
            kernel = np.ones((2 * band + 1, 2 * band + 1), np.uint8)
            mask = cv2.GaussianBlur(cv2.dilate(letters, kernel).astype(np.float32), (0, 0), feather)
            full = np.zeros((h, w, 3), np.float32)
            full[y0:y1, x0:x1] = still[y0:y1, x0:x1]
            zone = np.zeros((h, w), np.uint8)
            zone[gy0:gy1, gx0:gx1] = 1
            warp = np.eye(2, 3, dtype=np.float32)
            score: float | None = None
        else:
            region = cv2.cvtColor(fr[gy0:gy1, gx0:gx1], cv2.COLOR_RGB2GRAY).astype(np.float32)
            try:
                cc, warp = cv2.findTransformECC(
                    template, region, warp, cv2.MOTION_AFFINE,
                    (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, ECC_ITERATIONS, ECC_EPS),
                    None, ECC_GAUSS)
                score = round(float(cc), 4)
            except cv2.error:
                score = None  # a failed track is recorded, never hidden (summarize)
        m = warp.copy()
        m[0, 2] += gx0 - (m[0, 0] * gx0 + m[0, 1] * gy0)
        m[1, 2] += gy0 - (m[1, 0] * gx0 + m[1, 1] * gy0)
        d = cv2.warpAffine(full, m, (w, h))
        k = cv2.warpAffine(mask, m, (w, h))[..., None]
        if erase:
            fr = erase_lettering(fr, zone | cv2.warpAffine(zone, m, (w, h), flags=cv2.INTER_NEAREST))
        yield (fr.astype(np.float32) * (1 - k) + d * k).clip(0, 255).astype(np.uint8), score


def alpha_box(rgba: np.ndarray, pad: int = CROP_PAD) -> tuple[int, int, int, int] | None:
    """The doll's box in a keyed frame (alpha over 8) grown by ``pad`` and kept in the
    frame (``DollClip``'s crop), or None when nothing is left after keying."""
    alpha = rgba[..., 3] > 8
    if not alpha.any():
        return None
    ys, xs = np.nonzero(alpha)
    h, w = alpha.shape
    return (max(0, int(xs.min()) - pad), max(0, int(ys.min()) - pad),
            min(w, int(xs.max()) + 1 + pad), min(h, int(ys.max()) + 1 + pad))


def gate(summary: dict[str, Any], floor: float) -> bool:
    """The decal gate (``DollClip``): no failed frame and the lowest score at or above
    ``floor``. A clip with one frame has nothing to track and passes."""
    if summary["failed_frames"]:
        return False
    return summary["min_ecc"] is None or summary["min_ecc"] >= floor


__all__ = ["CROP_PAD", "DECAL_VERSIONS", "KEYERS", "MIN_ECC", "alpha_box", "decal_frames",
           "erase_lettering", "gate", "key", "summarize"]
