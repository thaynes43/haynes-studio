"""Full layered film (E0.3): every doll in every shot is a keyed Wan doll-on-green clip for
her expression, composited over a Wan set loop with the manifest's layouts, talk bounce,
scripted moves and camera, then muxed with a soundtrack.

    python poc/layered_film.py MANIFEST JOB_DIR CLIPMAP.json SET_CLIP TIMELINE.json SOUNDTRACK.wav OUT.mp4

CLIPMAP maps a cutout file (as named in the manifest's shots) to a doll clip, plus optional
eye-protect boxes in clip pixels: {"cutouts/a-proud.png": {"clip": "clips/layer-a-green.mp4",
"protect": [[240,400,440,600]]}, ...}. Optional "still" and "decal_box" (lettering box in clip pixels) paste the still's correct
lettering back onto every frame before keying (poc/decal.py). Keyed frames are cached under
JOB/keyed/<clip>/.
Doll clips ping-pong, each doll offset so they do not bob in unison. Create-only output.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')
import argparse, json, subprocess, sys
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

    def __init__(self, job, clip, protect, pad=24, still=None, decal_box=None):
        import hashlib
        # The cache is keyed by everything that shapes the keyed frames, and only reused
        # once a completion marker exists (a crashed run leaves no marker).
        settings = {'clip_sha256': hashlib.sha256((job / clip).read_bytes()).hexdigest(), 'protect': protect,
                    'still_sha256': hashlib.sha256((job / still).read_bytes()).hexdigest() if still else None,
                    'decal_box': decal_box, 'key': [20, 70]}
        tag = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:12]
        self.dir = job / 'keyed' / f'{Path(clip).stem}-{tag}'; marker = self.dir / 'complete.json'
        src = None; self.n = 0
        if marker.exists():
            self.n = json.loads(marker.read_text())['frames']
        else:
            self.dir.mkdir(parents=True, exist_ok=True)
            src = frames(job / clip)
            if decal_box:  # Wan garbles costume text: paste the still's lettering back, tracked
                import numpy as np
                from decal import decal_frames
                st = np.asarray(Image.open(job / still).convert('RGB').resize(src[0].size))
                from decal import summarize
                fixed, scores = decal_frames(st, [np.asarray(im) for im in src], decal_box)
                src = [Image.fromarray(f) for f in fixed]
                (self.dir / 'decal.json').write_text(json.dumps({'box': decal_box, **summarize(scores), 'ecc': scores}))
            for i, im in enumerate(src):
                key(im, 20, 70, [tuple(b) for b in protect]).save(self.dir / f'{i:04d}.png')
            self.n = len(src)
            marker.write_text(json.dumps({**settings, 'frames': self.n}))
        first = Image.open(self.dir / '0000.png')
        x0, y0, x1, y1 = first.getchannel('A').point(lambda v: 255 if v > 8 else 0).getbbox()
        self.box = (max(0, x0 - pad), max(0, y0 - pad), min(first.width, x1 + pad), min(first.height, y1 + pad))

    def frame(self, i):
        return Image.open(self.dir / f'{pingpong(self.n, i):04d}.png').crop(self.box)


def main():
    ap = argparse.ArgumentParser()
    for n in ('manifest', 'job', 'clipmap', 'set_clip', 'timeline', 'soundtrack', 'out'):
        ap.add_argument(n)
    a = ap.parse_args(); job = Path(a.job); m = load_manifest(a.manifest); m['_job'] = job
    out = Path(a.out)
    if out.exists():
        raise FileExistsError(out)
    W, H, FPS = m['frame']['width'], m['frame']['height'], m['frame']['fps']
    cmap = json.loads(Path(a.clipmap).read_text()); spans = json.loads(Path(a.timeline).read_text())['shots']
    clips = {k: DollClip(job, v['clip'], v.get('protect', []), still=v.get('still'), decal_box=v.get('decal_box'))
             for k, v in cmap.items()}
    sets = frames(a.set_clip); fg_cache = {}
    picture = out.with_suffix('.picture.mp4')
    cmd = [ffmpeg_exe(), '-hide_banner', '-nostdin', '-n', '-threads', '2', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
           '-s', f'{W}x{H}', '-r', str(FPS), '-i', 'pipe:0', '-an', '-c:v', 'libx264', '-threads', '2', '-preset', 'fast',
           '-crf', '18', '-pix_fmt', 'yuv420p', str(picture)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL); film = 0
    try:
        for shot, span in zip(m['shots'], spans):
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
            print(f"shot {shot['id']}: {span['frames']} frames", file=sys.stderr, flush=True)
        proc.stdin.close(); assert proc.wait(timeout=600) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
    ffmpeg(['-i', str(picture), '-i', a.soundtrack, '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac',
            '-b:a', '192k', '-t', f"{spans[-1]['end_s']:.4f}", '-movflags', '+faststart', str(out)])
    print(out)


if __name__ == '__main__':
    main()
