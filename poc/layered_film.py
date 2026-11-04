"""Full layered film (E0.3): every doll in every shot is a keyed Wan doll-on-green clip for
her expression, composited over a Wan set loop with the manifest's layouts, talk bounce,
scripted moves and camera, then muxed with a soundtrack.

    python poc/layered_film.py MANIFEST JOB_DIR CLIPMAP.json SET_CLIP TIMELINE.json SOUNDTRACK.wav OUT.mp4

CLIPMAP maps a cutout file (as named in the manifest's shots) to a doll clip, plus optional
eye-protect boxes in clip pixels: {"cutouts/a-proud.png": {"clip": "clips/layer-a-green.mp4",
"protect": [[240,400,440,600]]}, ...}. Optional "still" and "decal_box" (lettering box in clip pixels) paste the still's correct
lettering back onto every frame before keying (poc/decal.py); a track below decal.MIN_ECC
(or the entry's "decal_min_ecc") stops the render. Keyed frames are cached under
JOB/keyed/<clip>/.
Doll clips ping-pong, each doll offset so they do not bob in unison. Create-only output.

--workers N keys the doll clips and renders the shots in N processes (each shot is
independent given its first film frame), then joins the shot segments without re-encoding.
Use 1 in a session pod (2-thread rule); the studio-render worker on talosw01 allows 24.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
import argparse, json, subprocess, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import av
from PIL import Image, ImageFilter
sys.argv, _argv = sys.argv[:1], sys.argv
import edit
from cutout import key
from studio import load_manifest, ffmpeg, ffmpeg_exe
sys.argv = _argv


def frames(path):
    c = av.open(str(path)); s = c.streams.video[0]; s.thread_count = 2
    out = [f.to_image().convert('RGB') for f in c.decode(s)]; c.close(); return out


def pingpong(n, i):
    period = 2 * n - 2; j = i % period
    return j if j < n else period - j


class DollClip:
    """Keyed frames of one doll clip, cropped to one fixed box (the first frame's doll plus
    padding) so the doll keeps a constant size across frames."""

    @staticmethod
    def cache_dir(job, clip, protect, still=None, decal_box=None):
        """The keyed-frame directory for these settings (everything that shapes the frames)."""
        import hashlib
        settings = {'clip_sha256': hashlib.sha256((job / clip).read_bytes()).hexdigest(), 'protect': protect or [],
                    'still_sha256': hashlib.sha256((job / still).read_bytes()).hexdigest() if still else None,
                    'decal_box': decal_box, 'decal': 'erase-v2', 'key': [20, 70]}
        tag = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:12]
        return job / 'keyed' / f'{Path(clip).stem}-{tag}', settings

    def __init__(self, job, clip, protect, pad=24, still=None, decal_box=None, min_ecc=None):
        # The cache is only reused once a completion marker exists (a crashed run leaves none).
        self.dir, settings = self.cache_dir(job, clip, protect, still, decal_box); marker = self.dir / 'complete.json'
        protect = protect or []; src = None; self.n = 0
        if marker.exists():
            self.n = json.loads(marker.read_text())['frames']
        else:
            self.dir.mkdir(parents=True, exist_ok=True)
            src = frames(job / clip)
            if decal_box:  # Wan garbles costume text: paste the still's lettering back, tracked
                import numpy as np
                from decal import decal_frames, summarize
                st = np.asarray(Image.open(job / still).convert('RGB').resize(src[0].size))
                fixed, scores = decal_frames(st, [np.asarray(im) for im in src], decal_box)
                src = [Image.fromarray(f) for f in fixed]
                (self.dir / 'decal.json').write_text(json.dumps({'box': decal_box, **summarize(scores), 'ecc': scores}))
            for i, im in enumerate(src):
                key(im, 20, 70, [tuple(b) for b in protect]).save(self.dir / f'{i:04d}.png')
            self.n = len(src)
            marker.write_text(json.dumps({**settings, 'frames': self.n}))
        if decal_box:  # gate on every use, cached or not: re-roll the clip, don't ship it
            from decal import MIN_ECC
            summary = json.loads((self.dir / 'decal.json').read_text())
            floor = MIN_ECC if min_ecc is None else min_ecc
            if summary['failed_frames'] or summary['min_ecc'] < floor:
                raise RuntimeError(f"{clip}: decal track too weak (min {summary['min_ecc']}, "
                                   f"{summary['failed_frames']} failed); re-roll the clip or set decal_min_ecc")
        first = Image.open(self.dir / '0000.png')
        x0, y0, x1, y1 = first.getchannel('A').point(lambda v: 255 if v > 8 else 0).getbbox()
        self.box = (max(0, x0 - pad), max(0, y0 - pad), min(first.width, x1 + pad), min(first.height, y1 + pad))

    def frame(self, i):
        return Image.open(self.dir / f'{pingpong(self.n, i):04d}.png').crop(self.box)


def build_clip(args):
    job, v = args
    return DollClip(job, v['clip'], v.get('protect', []), still=v.get('still'), decal_box=v.get('decal_box'), min_ecc=v.get('decal_min_ecc')).n


def render_shot(args):
    """Render one shot to its own segment, starting at film frame `film`."""
    manifest, job, clipmap, set_clip, timeline, idx, film, seg = args
    m = load_manifest(manifest); m['_job'] = job
    W, H, FPS = m['frame']['width'], m['frame']['height'], m['frame']['fps']
    cmap = json.loads(Path(clipmap).read_text()); span = json.loads(Path(timeline).read_text())['shots'][idx]
    shot = m['shots'][idx]
    clips = {k: DollClip(job, v['clip'], v.get('protect', []), still=v.get('still'), decal_box=v.get('decal_box'), min_ecc=v.get('decal_min_ecc'))
             for k, v in cmap.items() if k in shot['dolls'].values()}
    sets = frames(set_clip)
    cmd = [ffmpeg_exe(), '-hide_banner', '-nostdin', '-n', '-threads', '2', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
           '-s', f'{W}x{H}', '-r', str(FPS), '-i', 'pipe:0', '-an', '-c:v', 'libx264', '-threads', '2', '-preset', 'fast',
           '-crf', '18', '-pix_fmt', 'yuv420p', str(seg)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        lay = m['layouts'][shot['layout']]; env = edit.speech_envelope(m, shot); placed = []
        for k, (doll, image) in enumerate(shot['dolls'].items()):
            slot = lay['slots'][doll] if 'slots' in lay else {}
            slot = {'x': slot} if isinstance(slot, (int, float)) else slot
            placed.append({'doll': doll, 'clip': clips[image], 'slot': slot, 'k': k,
                           'height': slot.get('height', lay.get('height')), 'bottom': slot.get('bottom', lay.get('bottom')),
                           'cx': slot.get('x', lay.get('x')) * W, 'sign': 1 if k % 2 == 0 else -1,
                           'factor': 1.4 if shot['layout'] == 'single' else 0.8, 'phase': 0.37 * k})
        shadows = {}
        for i in range(span['frames']):
            t = i / FPS
            bg = sets[pingpong(len(sets), film)].resize((W, H), Image.Resampling.LANCZOS)
            frame = bg.convert('RGBA')
            for p in placed:
                sprite = p['clip'].frame(film + 37 * p['k'])
                if 'crop' in p['slot']:
                    fx0, fy0, fx1, fy1 = p['slot']['crop']
                    sprite = sprite.crop((round(fx0 * sprite.width), round(fy0 * sprite.height),
                                          round(fx1 * sprite.width), round(fy1 * sprite.height)))
                sprite = sprite.resize((round(sprite.width * p['height'] / sprite.height), p['height']), Image.Resampling.LANCZOS)
                x, y = round(p['cx'] - sprite.width / 2), p['bottom'] - sprite.height
                plate = Image.new('RGBA', (W + 2 * edit.PAD, H))
                plate.alpha_composite(sprite.crop((0, 0, sprite.width, max(0, min(sprite.height, H - y)))), (x + edit.PAD, y))
                if p['doll'] not in shadows:  # one soft shadow per doll per shot (blurring every frame is slow)
                    sh = Image.new('RGBA', plate.size, (28, 24, 18, 0))
                    sh.putalpha(plate.getchannel('A').filter(ImageFilter.GaussianBlur(22)).point(lambda v: round(v * .16)))
                    shadows[p['doll']] = sh
                dx, dy, angle = edit.motion(m, shot, {**p, 'pivot': None}, t, env)
                edit.draw(frame, {'plate': plate, 'shadow': shadows[p['doll']], 'pivot': (p['cx'] + edit.PAD, p['bottom'] - 80)},
                          dx, dy, angle)
            if shot.get('foreground', True):
                frame.alpha_composite(edit.foreground_layer(m, bg))
            frame = edit.camera(shot, frame.convert('RGB'), t)
            proc.stdin.write(frame.tobytes()); film += 1
        proc.stdin.close(); assert proc.wait(timeout=600) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
    return shot['id'], span['frames']


def main():
    ap = argparse.ArgumentParser()
    for n in ('manifest', 'job', 'clipmap', 'set_clip', 'timeline', 'soundtrack', 'out'):
        ap.add_argument(n)
    ap.add_argument('--workers', type=int, default=1)
    a = ap.parse_args(); job = Path(a.job); m = load_manifest(a.manifest)
    out = Path(a.out); picture = out.with_suffix('.picture.mp4'); parts = out.with_suffix('.parts')
    if out.exists() or picture.exists() or parts.exists():
        raise FileExistsError(out)
    cmap = json.loads(Path(a.clipmap).read_text()); spans = json.loads(Path(a.timeline).read_text())['shots']
    assert len(spans) == len(m['shots']), 'timeline and manifest disagree on the shot count'
    # Build each keyed directory once, before the shots read it: dedupe by the cache directory
    # itself, so no two workers ever build the same one at once.
    distinct = {DollClip.cache_dir(job, v['clip'], v.get('protect', []), v.get('still'), v.get('decal_box'))[0]: v
                for v in cmap.values()}
    starts = [sum(s['frames'] for s in spans[:i]) for i in range(len(spans))]
    parts.mkdir()
    jobs = [(a.manifest, job, a.clipmap, a.set_clip, a.timeline, i, starts[i], parts / f'{i:03d}.mp4')
            for i in range(len(spans))]
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        list(pool.map(build_clip, [(job, v) for v in distinct.values()]))
        for sid, n in pool.map(render_shot, jobs):
            print(f'shot {sid}: {n} frames', file=sys.stderr, flush=True)
    lst = parts / 'list.txt'
    lst.write_text(''.join(f"file '{j[-1].name}'\n" for j in jobs))
    ffmpeg(['-f', 'concat', '-safe', '0', '-i', str(lst), '-c', 'copy', str(picture)])
    ffmpeg(['-i', str(picture), '-i', a.soundtrack, '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac',
            '-b:a', '192k', '-t', f"{spans[-1]['end_s']:.4f}", '-movflags', '+faststart', str(out)])
    print(out)


if __name__ == '__main__':
    main()
