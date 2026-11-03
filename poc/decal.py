"""Rigid lettering decal for a Wan doll clip (E0 experiment): Wan garbles costume text, so
track the jacket from the clip's first frame to each frame (OpenCV ECC, affine) and paste
the original lettering from the still the clip started from, warped by that motion.

    python poc/decal.py STILL.png CLIP.mp4 OUT.mp4 --box X0,Y0,X1,Y1

--box is the lettering region in clip pixels (frame 0 matches the still: Wan's start image).
The tracked region is the box grown by 40 px (the jacket around the letters). The decal is
the still's yellow letters plus a thin band of jacket (--band), feathered: a full-box paste
showed a visible rectangle because the still's cloth differs from Wan's. Create-only output; writes OUT.json with per-frame tracking scores.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')
import argparse, json, subprocess, sys
from pathlib import Path
import av, cv2
import numpy as np
from PIL import Image
sys.argv, _argv = sys.argv[:1], sys.argv
from studio import ffmpeg_exe
sys.argv = _argv
cv2.setNumThreads(2)


def decal_frames(still, frames, box, grow=40, band=4, feather=2):
    """Track the jacket from frames[0] and paste the still's lettering onto every frame.
    `still` and `frames` are RGB uint8 arrays of the same size. Returns (frames, ecc scores)."""
    x0, y0, x1, y1 = box; h, w = frames[0].shape[:2]
    gx0, gy0, gx1, gy1 = max(0, x0 - grow), max(0, y0 - grow), min(w, x1 + grow), min(h, y1 + grow)
    template = cv2.cvtColor(frames[0][gy0:gy1, gx0:gx1], cv2.COLOR_RGB2GRAY).astype(np.float32)
    sr, sg, sb = (still[..., i].astype(int) for i in range(3))
    letters = ((sr > 170) & (sg > 130) & (sb < 100) & (sr - sb > 110)).astype(np.uint8)
    keep = np.zeros((h, w), np.uint8); keep[y0:y1, x0:x1] = 1; letters *= keep
    mask = cv2.GaussianBlur(cv2.dilate(letters, np.ones((2 * band + 1, 2 * band + 1), np.uint8)).astype(np.float32), (0, 0), feather)
    full = np.zeros((h, w, 3), np.float32); full[y0:y1, x0:x1] = still[y0:y1, x0:x1]
    warp = np.eye(2, 3, dtype=np.float32); out, scores = [], []
    for i, fr in enumerate(frames):
        if i:
            region = cv2.cvtColor(fr[gy0:gy1, gx0:gx1], cv2.COLOR_RGB2GRAY).astype(np.float32)
            try:
                cc, warp = cv2.findTransformECC(template, region, warp, cv2.MOTION_AFFINE,
                                                (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 60, 1e-4), None, 5)
            except cv2.error:
                cc = float('nan')
            scores.append(round(float(cc), 4))
        m = warp.copy(); m[0, 2] += gx0 - (m[0, 0] * gx0 + m[0, 1] * gy0); m[1, 2] += gy0 - (m[1, 0] * gx0 + m[1, 1] * gy0)
        d = cv2.warpAffine(full, m, (w, h)); k = cv2.warpAffine(mask, m, (w, h))[..., None]
        out.append((fr.astype(np.float32) * (1 - k) + d * k).clip(0, 255).astype(np.uint8))
    return out, scores


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('still'); ap.add_argument('clip'); ap.add_argument('out')
    ap.add_argument('--box', required=True); ap.add_argument('--grow', type=int, default=40); ap.add_argument('--feather', type=int, default=2)
    ap.add_argument('--band', type=int, default=4, help='px of jacket kept around the letters')
    a = ap.parse_args(); out = Path(a.out)
    if out.exists():
        raise FileExistsError(out)
    x0, y0, x1, y1 = map(int, a.box.split(','))
    c = av.open(a.clip); s = c.streams.video[0]; s.thread_count = 2
    frames = [np.asarray(f.to_image().convert('RGB')) for f in c.decode(s)]; c.close()
    h, w = frames[0].shape[:2]
    still = np.asarray(Image.open(a.still).convert('RGB').resize((w, h)))
    gx0, gy0, gx1, gy1 = max(0, x0 - a.grow), max(0, y0 - a.grow), min(w, x1 + a.grow), min(h, y1 + a.grow)
    template = cv2.cvtColor(frames[0][gy0:gy1, gx0:gx1], cv2.COLOR_RGB2GRAY).astype(np.float32)
    decal = still[y0:y1, x0:x1].astype(np.float32)
    # Letter-shaped mask: the still's yellow letters plus a thin band of jacket around them,
    # feathered. A full-box paste showed a visible rectangle (the still's cloth != Wan's).
    sr, sg, sb = (still[..., i].astype(int) for i in range(3))
    letters = ((sr > 170) & (sg > 130) & (sb < 100) & (sr - sb > 110)).astype(np.uint8)
    box = np.zeros((h, w), np.uint8); box[y0:y1, x0:x1] = 1; letters *= box
    mask = cv2.dilate(letters, np.ones((2 * a.band + 1, 2 * a.band + 1), np.uint8)).astype(np.float32)
    mask = cv2.GaussianBlur(mask, (0, 0), a.feather)
    warp = np.eye(2, 3, dtype=np.float32); scores = []
    cmd = [ffmpeg_exe(), '-hide_banner', '-nostdin', '-n', '-threads', '2', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{w}x{h}',
           '-r', '24', '-i', 'pipe:0', '-c:v', 'libx264', '-threads', '2', '-crf', '16', '-pix_fmt', 'yuv420p', str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    full_decal = np.zeros((h, w, 3), np.float32); full_decal[y0:y1, x0:x1] = decal
    for i, fr in enumerate(frames):
        if i:
            region = cv2.cvtColor(fr[gy0:gy1, gx0:gx1], cv2.COLOR_RGB2GRAY).astype(np.float32)
            try:  # frame-to-first-frame affine of the jacket area, warm-started from the last frame
                cc, warp = cv2.findTransformECC(template, region, warp, cv2.MOTION_AFFINE,
                                                (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 60, 1e-4), None, 5)
            except cv2.error:
                cc = float('nan')
            scores.append(round(float(cc), 4))
        # warp maps template coords -> frame-region coords; shift into full-frame coords
        m = warp.copy(); m[0, 2] += gx0 - (m[0, 0] * gx0 + m[0, 1] * gy0); m[1, 2] += gy0 - (m[1, 0] * gx0 + m[1, 1] * gy0)
        d = cv2.warpAffine(full_decal, m, (w, h)); k = cv2.warpAffine(mask, m, (w, h))[..., None]
        composed = fr.astype(np.float32) * (1 - k) + d * k
        proc.stdin.write(composed.clip(0, 255).astype(np.uint8).tobytes())
    proc.stdin.close(); assert proc.wait(timeout=300) == 0
    (out.with_suffix('.json')).open('x').write(json.dumps({'box': [x0, y0, x1, y1], 'grow': a.grow, 'ecc_scores': scores,
                                                          'min_ecc': min(scores) if scores else None}, indent=2))
    print(json.dumps({'out': str(out), 'frames': len(frames), 'min_ecc': min(scores) if scores else None,
                      'mean_ecc': round(float(np.nanmean(scores)), 4) if scores else None}))


if __name__ == '__main__':
    main()
