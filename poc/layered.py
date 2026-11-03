"""Layered Wan shot (E0.3): Wan set loop as the background, a Wan doll-on-green clip keyed
per frame as the doll, placed with the title's layout, plus the editor's syllable-synced
talk bounce and the log pasted back over the waist. One shot, one doll.

    python poc/layered.py MANIFEST SHOT_ID JOB_DIR SET_CLIP DOLL_CLIP OUT.mp4 \
        [--protect X0,Y0,X1,Y1] [--doll-height-px 745]

--protect is an eye box in doll-clip pixels (a green-eyed doll keys like the backdrop).
Clips shorter than the shot ping-pong. Create-only output; picture only (mux separately).
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')
import argparse, json, subprocess, sys
from pathlib import Path
import av
import numpy as np
from PIL import Image, ImageFilter
sys.argv, _argv = sys.argv[:1], sys.argv
import edit
from cutout import key
from studio import load_manifest, ffmpeg_exe
sys.argv = _argv


def frames(path):
    c = av.open(str(path)); s = c.streams.video[0]; s.thread_count = 2
    out = [f.to_image().convert('RGB') for f in c.decode(s)]; c.close(); return out


def pingpong(seq, i):
    period = 2 * len(seq) - 2; j = i % period
    return seq[j] if j < len(seq) else seq[period - j]


def main():
    ap = argparse.ArgumentParser()
    for n in ('manifest', 'shot', 'job', 'set_clip', 'doll_clip', 'out'):
        ap.add_argument(n)
    ap.add_argument('--protect', action='append', default=[]); ap.add_argument('--doll-height-px', type=int, default=745)
    a = ap.parse_args(); m = load_manifest(a.manifest); m['_job'] = Path(a.job)
    shot = next(s for s in m['shots'] if s['id'] == int(a.shot))
    W, H, FPS = m['frame']['width'], m['frame']['height'], m['frame']['fps']
    tl = json.loads((Path(a.job) / 'r4-timeline.json').read_text())['shots']
    span = next(s for s in tl if s['shot'] == shot['id']); n = span['frames']
    sets, dolls = frames(a.set_clip), frames(a.doll_clip)
    protect = [tuple(int(v) for v in b.split(',')) for b in a.protect]
    lay = m['layouts'][shot['layout']]; doll = next(iter(shot['dolls']))
    slot = lay['slots'][doll] if 'slots' in lay else {}
    slot = {'x': slot} if isinstance(slot, (int, float)) else slot
    height, bottom = slot.get('height', lay.get('height')), slot.get('bottom', lay.get('bottom'))
    cx = slot.get('x', lay.get('x')) * W
    scale = height / a.doll_height_px
    cw, ch = round(dolls[0].width * scale), round(dolls[0].height * scale)
    env = edit.speech_envelope(m, shot)
    p = {'doll': doll, 'sign': 1, 'factor': 1.4, 'phase': 0.0, 'pivot': (cx + edit.PAD, bottom - 80)}
    out = Path(a.out)
    if out.exists():
        raise FileExistsError(out)
    cmd = [ffmpeg_exe(), '-hide_banner', '-nostdin', '-n', '-threads', '2', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
           '-s', f'{W}x{H}', '-r', str(FPS), '-i', 'pipe:0', '-an', '-c:v', 'libx264', '-threads', '2', '-preset', 'fast',
           '-crf', '18', '-pix_fmt', 'yuv420p', str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        for i in range(n):
            t = i / FPS
            bg = pingpong(sets, i).resize((W, H), Image.Resampling.LANCZOS)
            sprite = key(pingpong(dolls, i), 20, 70, protect).resize((cw, ch), Image.Resampling.LANCZOS)
            plate = Image.new('RGBA', (W + 2 * edit.PAD, H))
            top = bottom - ch; visible = sprite.crop((0, 0, cw, max(0, min(ch, H - top))))
            plate.alpha_composite(visible, (round(cx - cw / 2) + edit.PAD, top))
            shadow = Image.new('RGBA', plate.size, (28, 24, 18, 0))
            shadow.putalpha(plate.getchannel('A').filter(ImageFilter.GaussianBlur(22)).point(lambda v: round(v * .16)))
            frame = bg.convert('RGBA')
            dx, dy, angle = edit.motion(m, shot, p, t, env)
            edit.draw(frame, {**p, 'plate': plate, 'shadow': shadow}, dx, dy, angle)
            frame.alpha_composite(edit.foreground_layer(m, bg))
            proc.stdin.write(frame.convert('RGB').tobytes())
        proc.stdin.close(); assert proc.wait(timeout=300) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
    print(json.dumps({'out': str(out), 'frames': n, 'set_frames': len(sets), 'doll_frames': len(dolls)}))


if __name__ == '__main__':
    main()
