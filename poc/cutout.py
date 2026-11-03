"""Chroma-key a doll rendered on flat green into an RGBA cutout (runbook stage 2).

    ~/.cache/studio-venv/bin/python poc/cutout.py IN.png OUT.png [--resize WxH] [--protect X0,Y0,X1,Y1]

Green dominance (G minus the larger of R and B) decides transparency: at or above
--hi is fully transparent, at or below --lo fully opaque, linear between. Only green
regions touching the frame edge, large enclosed pockets, and strongly green islands (gaps
in frizzy hair) count as background. Painted green eyes are the same green as those gaps,
so pass --protect boxes around them; olive props like moss are not green enough to key. In a band around the background, the key color is
subtracted out of semi-transparent pixels and the rest despilled. The alpha is shrunk
by one pixel and feathered slightly, and the result is cropped to the doll with padding. Output is
create-only, and the frame border is guaranteed fully transparent, as the editor
requires.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')  # CPU rule in AGENTS.md; set before numpy loads
import argparse, hashlib, json
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage


def key(img, lo, hi, protect=(), band_px=24, pocket_px=3000, gap_dominance=45):
    a = np.asarray(img.convert('RGB')).astype(np.float32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    dominance = g - np.maximum(r, b)
    raw = 1 - np.clip((dominance - lo) / (hi - lo), 0, 1)
    # Background = green regions touching the frame edge, or enclosed pockets (between an
    # arm and the body) bigger than pocket_px. Small green islands (eyes, moss) stay solid.
    # Gaps inside frizzy hair are small but strongly green, so they count too, unless they
    # sit inside a --protect box (painted green eyes are the same green as the gaps).
    labels, n = ndimage.label(raw < 0.5)
    index = np.arange(n + 1)
    sizes = ndimage.sum_labels(np.ones_like(raw), labels, index)
    greenness = ndimage.median(dominance, labels, index)
    edge = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])))
    boxes = ndimage.find_objects(labels)
    def protected(i):
        y, x = boxes[i - 1]
        return any(x0 <= x.start and x.stop <= x1 and y0 <= y.start and y.stop <= y1 for x0, y0, x1, y1 in protect)
    keep = np.array([i != 0 and (i in edge or ((sizes[i] > pocket_px or greenness[i] >= gap_dominance)
                                              and not protected(i))) for i in range(n + 1)])
    background = keep[labels]
    band = ndimage.binary_dilation(background, iterations=band_px)
    alpha = np.where(band, raw, 1.0)
    # Unmix: remove the key color's share from semi-transparent edge pixels, then
    # despill what is left (green clamped to the mean of red and blue) in the band.
    key_rgb = np.median(np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]]), axis=0)
    w = np.clip(alpha, 0.05, 1)[..., None]
    unmixed = np.where(band[..., None], (a - (1 - w) * key_rgb) / w, a).clip(0, 255)
    ur, ug, ub = unmixed[..., 0], unmixed[..., 1], unmixed[..., 2]
    unmixed[..., 1] = np.where(band, np.minimum(ug, (ur + ub) / 2), ug)
    mask = Image.fromarray((alpha * 255).astype(np.uint8))
    mask = mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
    out = Image.fromarray(unmixed.astype(np.uint8)).convert('RGBA')
    out.putalpha(mask)
    return out


def crop(img, pad=24):
    box = img.getchannel('A').point(lambda v: 255 if v > 8 else 0).getbbox()
    if box is None:
        raise ValueError('Nothing left after keying')
    x0, y0, x1, y1 = box
    canvas = Image.new('RGBA', (x1 - x0 + 2 * pad, y1 - y0 + 2 * pad))
    canvas.alpha_composite(img.crop(box), (pad, pad))
    return canvas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src'); ap.add_argument('dst')
    ap.add_argument('--lo', type=float, default=20); ap.add_argument('--hi', type=float, default=70)
    ap.add_argument('--resize', metavar='WxH',
                    help='scale the source first, e.g. an edit output (about 1 MP) back to its base size')
    ap.add_argument('--protect', action='append', default=[], metavar='X0,Y0,X1,Y1',
                    help='source-pixel box whose green islands stay solid (eyes); repeatable')
    a = ap.parse_args()
    dst = Path(a.dst)
    protect = [tuple(int(v) for v in box.split(',')) for box in a.protect]
    src = Image.open(a.src)
    if a.resize:
        src = src.convert('RGB').resize(tuple(int(v) for v in a.resize.split('x')), Image.Resampling.LANCZOS)
    out = crop(key(src, a.lo, a.hi, protect))
    assert out.getextrema()[3][0] == 0
    with dst.open('xb') as f:
        out.save(f, format='PNG')
    print(json.dumps({'src': Path(a.src).name, 'dst': dst.name, 'size': out.size, 'lo': a.lo, 'hi': a.hi, 'protect': protect, 'resize': a.resize,
                      'sha256': hashlib.sha256(dst.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
