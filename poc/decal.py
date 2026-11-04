"""Rigid lettering decal for a Wan doll clip (E0 experiment): Wan garbles costume text, so
track the jacket from the clip's first frame to each frame (OpenCV ECC, affine) and paste
the original lettering from the still the clip started from, warped by that motion.

    python poc/decal.py STILL.png CLIP.mp4 OUT.mp4 --box X0,Y0,X1,Y1

--box is the lettering region in clip pixels (frame 0 matches the still: Wan's start image).
The tracked region is the box grown by 40 px (the jacket around the letters). The decal is
the still's yellow letters plus a thin band of jacket (--band), feathered: a full-box paste
showed a visible rectangle because the still's cloth differs from Wan's. Before pasting,
Wan's own (garbled) lettering inside the tracked box is inpainted with jacket colour, so a
small slide of the decal never shows doubled letters (Tom saw "YELLOWBIRDSS" on D's reaction
clip at min ECC 0.72). Create-only output; writes OUT.json with per-frame tracking scores.
MIN_ECC is the starting gate: below it the clip should be re-rolled, not shipped.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS', os.environ.get('STUDIO_THREADS', '2'))
import argparse, json, subprocess, sys
from pathlib import Path
import av, cv2
import numpy as np
from PIL import Image
sys.argv, _argv = sys.argv[:1], sys.argv
from studio import ffmpeg_exe
sys.argv = _argv
cv2.setNumThreads(int(os.environ.get('STUDIO_THREADS', '2')))
MIN_ECC = 0.8  # D shocked failed Tom's eye at 0.72; A staring passed at 0.85


def summarize(scores):
    """Tracking summary with failures counted explicitly (valid JSON: no NaN)."""
    ok = [s for s in scores if s is not None]
    return {'frames_tracked': len(ok), 'failed_frames': len(scores) - len(ok),
            'min_ecc': min(ok) if ok else None, 'mean_ecc': round(sum(ok) / len(ok), 4) if ok else None}


def erase_lettering(frame, region):
    """Inpaint yellow lettering inside `region` (a 0/1 uint8 mask) with the surrounding cloth."""
    r, g, b = (frame[..., i].astype(int) for i in range(3))
    yellow = ((r > 140) & (g > 100) & (b < 100) & (r - b > 90)).astype(np.uint8) * region
    if not yellow.any():
        return frame
    yellow = cv2.dilate(yellow, np.ones((5, 5), np.uint8))
    return cv2.inpaint(np.ascontiguousarray(frame), yellow, 4, cv2.INPAINT_TELEA)


def decal_frames(still, frames, box, grow=40, band=4, feather=2, erase=True):
    """Track the jacket from frames[0] and paste the still's lettering onto every frame,
    after erasing Wan's own lettering under it (`erase`). `still` and `frames` are RGB uint8
    arrays of the same size. Returns (frames, ecc scores)."""
    x0, y0, x1, y1 = box; h, w = frames[0].shape[:2]
    gx0, gy0, gx1, gy1 = max(0, x0 - grow), max(0, y0 - grow), min(w, x1 + grow), min(h, y1 + grow)
    template = cv2.cvtColor(frames[0][gy0:gy1, gx0:gx1], cv2.COLOR_RGB2GRAY).astype(np.float32)
    sr, sg, sb = (still[..., i].astype(int) for i in range(3))
    letters = ((sr > 170) & (sg > 130) & (sb < 100) & (sr - sb > 110)).astype(np.uint8)
    keep = np.zeros((h, w), np.uint8); keep[y0:y1, x0:x1] = 1; letters *= keep
    mask = cv2.GaussianBlur(cv2.dilate(letters, np.ones((2 * band + 1, 2 * band + 1), np.uint8)).astype(np.float32), (0, 0), feather)
    full = np.zeros((h, w, 3), np.float32); full[y0:y1, x0:x1] = still[y0:y1, x0:x1]
    # Erase over the whole tracked jacket area, both where it started and where the track
    # says it is: a weak track also misplaces the erase region (D's turn left an extra "S").
    zone = np.zeros((h, w), np.uint8); zone[gy0:gy1, gx0:gx1] = 1
    warp = np.eye(2, 3, dtype=np.float32); out, scores = [], []
    for i, fr in enumerate(frames):
        if i:
            region = cv2.cvtColor(fr[gy0:gy1, gx0:gx1], cv2.COLOR_RGB2GRAY).astype(np.float32)
            try:
                cc, warp = cv2.findTransformECC(template, region, warp, cv2.MOTION_AFFINE,
                                                (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 60, 1e-4), None, 5)
            except cv2.error:
                cc = None  # a failed track is recorded, never hidden (see summarize)
            scores.append(None if cc is None else round(float(cc), 4))
        m = warp.copy(); m[0, 2] += gx0 - (m[0, 0] * gx0 + m[0, 1] * gy0); m[1, 2] += gy0 - (m[1, 0] * gx0 + m[1, 1] * gy0)
        d = cv2.warpAffine(full, m, (w, h)); k = cv2.warpAffine(mask, m, (w, h))[..., None]
        if erase:
            fr = erase_lettering(fr, zone | cv2.warpAffine(zone, m, (w, h), flags=cv2.INTER_NEAREST))
        out.append((fr.astype(np.float32) * (1 - k) + d * k).clip(0, 255).astype(np.uint8))
    return out, scores


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('still'); ap.add_argument('clip'); ap.add_argument('out')
    ap.add_argument('--box', required=True); ap.add_argument('--grow', type=int, default=40); ap.add_argument('--feather', type=int, default=2)
    ap.add_argument('--band', type=int, default=4, help='px of jacket kept around the letters')
    ap.add_argument('--no-erase', action='store_true', help="keep Wan's own lettering under the decal")
    a = ap.parse_args(); out = Path(a.out)
    if out.exists():
        raise FileExistsError(out)
    x0, y0, x1, y1 = map(int, a.box.split(','))
    c = av.open(a.clip); s = c.streams.video[0]; s.thread_count = 2
    frames = [np.asarray(f.to_image().convert('RGB')) for f in c.decode(s)]; c.close()
    h, w = frames[0].shape[:2]
    still = np.asarray(Image.open(a.still).convert('RGB').resize((w, h)))
    fixed, scores = decal_frames(still, frames, (x0, y0, x1, y1), a.grow, a.band, a.feather, erase=not a.no_erase)
    cmd = [ffmpeg_exe(), '-hide_banner', '-nostdin', '-n', '-threads', '2', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{w}x{h}',
           '-r', '24', '-i', 'pipe:0', '-c:v', 'libx264', '-threads', '2', '-crf', '16', '-pix_fmt', 'yuv420p', str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    for fr in fixed:
        proc.stdin.write(fr.tobytes())
    proc.stdin.close(); assert proc.wait(timeout=300) == 0
    with out.with_suffix('.json').open('x') as f:
        json.dump({'box': [x0, y0, x1, y1], 'grow': a.grow, 'ecc_scores': scores, **summarize(scores)}, f, indent=2)
    print(json.dumps({'out': str(out), 'frames': len(frames), **summarize(scores)}))


if __name__ == '__main__':
    main()
