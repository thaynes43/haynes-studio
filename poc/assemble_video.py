"""Assemble Wan clips into a delivery video (E0): per cut, join its clips (a chained clip's
first frame repeats the previous clip's last frame, so it is dropped), trim to the cut's
length from a reference timeline, scale to the delivery size, then mux a soundtrack.

    python poc/assemble_video.py JOB_DIR TIMELINE.json SOUNDTRACK.wav OUT.mp4 --method wf
        [--size 1080x1920] [--stretch] [--clip-fps 24]

--stretch slows a cut's footage to fill its length instead of chaining extra clips (the
other lengthening option E0 compares). Create-only output.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')
import argparse, json, subprocess, sys
from pathlib import Path
import av
from PIL import Image
sys.argv, _argv = sys.argv[:1], sys.argv
from studio import ffmpeg, ffmpeg_exe
sys.argv = _argv


def frames(path):
    c = av.open(str(path)); s = c.streams.video[0]; s.thread_count = 2
    out = [f.to_image() for f in c.decode(s)]; c.close(); return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('job'); ap.add_argument('timeline'); ap.add_argument('soundtrack'); ap.add_argument('out')
    ap.add_argument('--method', default='wf'); ap.add_argument('--size', default='1080x1920')
    ap.add_argument('--stretch', action='store_true'); ap.add_argument('--fps', type=int, default=24)
    a = ap.parse_args(); job = Path(a.job); W, H = map(int, a.size.split('x')); out = Path(a.out)
    if out.exists():
        raise FileExistsError(out)
    shots = json.loads(Path(a.timeline).read_text())['shots']
    picture = out.with_suffix('.picture.mp4')
    cmd = [ffmpeg_exe(), '-hide_banner', '-nostdin', '-n', '-threads', '2', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
           '-s', f'{W}x{H}', '-r', str(a.fps), '-i', 'pipe:0', '-an', '-c:v', 'libx264', '-threads', '2',
           '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p', str(picture)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL); report = []
    try:
        for sh in shots:
            n = sh['frames']; name = f"s{sh['shot']}-{a.method}"
            clips = [job / 'clips' / f'{name}-a.mp4']
            if not a.stretch:
                k = 1
                while (job / 'clips' / f'{name}-x{k}.mp4').exists():
                    clips.append(job / 'clips' / f'{name}-x{k}.mp4'); k += 1
            seq = []
            for i, c in enumerate(clips):
                fr = frames(c); seq += fr if i == 0 else fr[1:]
            if len(seq) >= n or not a.stretch:
                picks = [seq[min(i, len(seq) - 1)] for i in range(n)]   # trim; hold last frame if short
                mode = 'chained' if len(clips) > 1 else ('trim' if len(seq) >= n else 'hold-last')
            else:
                picks = [seq[int(i * len(seq) / n)] for i in range(n)]   # slow down to fit
                mode = f'stretch x{n / len(seq):.2f}'
            for im in picks:
                proc.stdin.write(im.resize((W, H), Image.Resampling.LANCZOS).tobytes())
            report.append({'shot': sh['shot'], 'frames': n, 'source_frames': len(seq), 'clips': [c.name for c in clips], 'mode': mode})
            print(report[-1], file=sys.stderr)
        proc.stdin.close(); assert proc.wait(timeout=600) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
    total = shots[-1]['end_s']
    ffmpeg(['-i', str(picture), '-i', a.soundtrack, '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac',
            '-b:a', '192k', '-t', f'{total:.4f}', '-movflags', '+faststart', str(out)])
    (out.with_suffix('.json')).write_text(json.dumps({'method': a.method, 'stretch': a.stretch, 'size': [W, H], 'shots': report}, indent=2) + '\n')
    print(out)


if __name__ == '__main__':
    main()
