"""Manifest-driven doll-short editor (runbook stages 5 and 6).

Generalized from haynes-ops scripts/wan-video/edit_doll_short.py (OP345): same rigid
puppet motion (whole-doll translate/rotate, poses held at 12/s inside 24 fps, no face
animation), but the shots, their lengths, the dolls in each shot, placement and sound
cues come from titles/<slug>/manifest.json instead of code.

    python poc/edit.py titles/<slug>/manifest.json audio|preview|render|validate|transcript [--out edit-2]

Every stage is create-only under <job>/<out>/ (default edit/); a new attempt uses a new --out.
"""
from studio import load_manifest, sha, read_audio, write_audio, levels, ffmpeg, ffmpeg_exe, transcribe, RATE
import argparse, json, math, re, subprocess, sys
import numpy as np
from PIL import Image, ImageFilter, ImageOps

GUARDS = {'audio': ['dialogue-only.wav', 'premaster.wav', 'soundtrack.wav', 'timeline.json'],
          'render': ['picture.mp4', 'encode.log', 'shots.json', 'frame-transforms.json', 'contact-sheet.jpg', 'final.mp4'],
          'validate': ['validation.json'], 'transcript': ['dialogue-transcript.json', 'dialogue-check.wav'], 'preview': []}


def timeline(m):
    """Shot start/end times. A shot with a line lasts start + speech + tail, rounded up to a frame."""
    speech = {}
    if (m['_job'] / 'speech.json').exists():
        speech = {l['shot']: l for l in json.loads((m['_job'] / 'speech.json').read_text())['lines']}
    fps, t, out = m['frame']['fps'], 0.0, []
    for shot in m['shots']:
        if 'duration' in shot:
            d = shot['duration']
        else:
            d = shot['line']['start'] + speech[shot['id']]['duration_s'] + shot['tail']
            assert shot['tail'] >= 0.25, 'lines must end at least 0.25 s before the cut'
        d = math.ceil(d * fps) / fps
        out.append({'shot': shot['id'], 'start_s': round(t, 4), 'end_s': round(t + d, 4), 'frames': round(d * fps)})
        t += d
    return out, speech


def audio(m):
    job, edit = m['_job'], m['_out']
    spans, speech = timeline(m)
    total = spans[-1]['end_s']
    mix = np.zeros((round(total * RATE) + RATE // 10, 2), np.float32)
    placed = []
    for shot, span in zip(m['shots'], spans):
        if shot.get('line'):
            rec = speech[shot['id']]
            assert sha(job / rec['file']) == rec['sha256']
            a = read_audio(job / rec['file'])
            a *= 10 ** (-22 / 20) / max(float(np.sqrt(np.mean(a * a))), 1e-8)
            edge = 240; a[:edge] *= np.linspace(0, 1, edge)[:, None]; a[-edge:] *= np.linspace(1, 0, edge)[:, None]
            start = span['start_s'] + shot['line']['start']
            assert start + len(a) / RATE <= span['end_s'] - 0.25 + 1e-6
            n = round(start * RATE); mix[n:n + len(a)] += a
            placed.append({**rec, 'kind': 'line', 'start_s': round(start, 3), 'end_s': round(start + len(a) / RATE, 3)})
    write_audio(edit / 'dialogue-only.wav', np.clip(mix, -0.99, 0.99))
    for shot, span in zip(m['shots'], spans):
        for cue in shot.get('sfx', []):
            spec = m['sfx'][cue['cue']]
            c = read_audio(job / spec['file'])
            if 'trim' in spec:
                c = c[round(spec['trim'][0] * RATE):round(spec['trim'][1] * RATE)].copy()
            c *= 10 ** (spec['gain_db'] / 20) / max(float(np.sqrt(np.mean(c * c))), 1e-8)
            c[:480] *= np.linspace(0, 1, 480)[:, None]; c[-2400:] *= np.linspace(1, 0, 2400)[:, None]
            start = span['start_s'] + cue['at']; n = round(start * RATE)
            c = c[:len(mix) - n]; mix[n:n + len(c)] += c
            placed.append({'kind': 'sfx', 'cue': cue['cue'], 'file': spec['file'], 'sha256': sha(job / spec['file']),
                           'start_s': round(start, 3), 'end_s': round(start + len(c) / RATE, 3), 'rms_dbfs': spec['gain_db']})
    mix = mix[:round(total * RATE)]
    assert float(np.max(np.abs(mix))) < .95
    write_audio(edit / 'premaster.wav', mix)
    first = levels(edit / 'premaster.wav')
    gain = min(m['master']['lufs'] - float(first['input_i']), m['master']['true_peak'] - float(first['input_tp']))
    ffmpeg(['-i', str(edit / 'premaster.wav'), '-af', f'volume={gain}dB', '-ar', '48000', '-c:a', 'pcm_s24le',
            str(edit / 'soundtrack.wav')])
    with (edit / 'timeline.json').open('x') as f:
        json.dump({'total_s': total, 'shots': spans, 'audio': placed, 'master_gain_db': gain}, f, indent=2)
    print(json.dumps({'total_s': total, 'master_gain_db': round(gain, 2)}))


def trajectory(t, sign, factor, phase=0.0):
    """OP345's held-pose rock: an unseen hand lifts and rocks the toy, 12 poses/s."""
    q = math.floor((t + phase) * 12) / 12 % 5
    knots = [(0, 0, 16, 0), (.25, -12, -12, -1.6), (.5, 2, 0, .5), (1.1, 8, -6, 1.2),
             (1.4, -7, 3, -.8), (2.0, 4, -8, .8), (2.35, -9, 1, -1.2), (2.8, 5, -5, .5),
             (3.3, -3, 2, -.4), (3.8, 0, 0, 0), (5, 0, 0, 0)]
    for lo, hi in zip(knots, knots[1:]):
        if lo[0] <= q <= hi[0]:
            u = (q - lo[0]) / (hi[0] - lo[0]); u = u * u * (3 - 2 * u)
            x = lo[1] + u * (hi[1] - lo[1]); y = lo[2] + u * (hi[2] - lo[2]); a = lo[3] + u * (hi[3] - lo[3])
            return sign * x * factor, y * 1.45, sign * a * factor
    return 0.0, 0.0, 0.0


def edge_y(m, xs):
    """y of the foreground prop's top edge, interpolated from measured [x, y] points."""
    pts = np.array(m['set']['foreground_edge'], dtype=float)
    return np.interp(xs, pts[:, 0], pts[:, 1])


def foreground_layer(m, bg):
    """The set itself, opaque below the measured top edge of the foreground prop
    (a polyline), feathered above it, pasted over the dolls so their cut-off waists
    sit behind the log."""
    feather = m['set'].get('foreground_feather', 0)
    edge = edge_y(m, np.arange(bg.width))[None, :]
    ramp = np.clip((np.arange(bg.height)[:, None] - (edge - feather)) / max(feather, 1), 0, 1)
    alpha = Image.fromarray((ramp * 255).astype(np.uint8))
    layer = bg.convert('RGBA'); layer.putalpha(alpha)
    return layer


def place(m, shot, W, H):
    """One full-frame RGBA plate (and shadow) per doll in the shot, plus its pivot."""
    lay = m['layouts'][shot['layout']]
    plates = []
    for k, (doll, image) in enumerate(shot['dolls'].items()):
        sprite = Image.open(m['_job'] / image).convert('RGBA')
        assert sprite.getextrema()[3][0] == 0, f'{image} has no transparent pixels'
        slot = lay['slots'][doll] if 'slots' in lay else {}
        slot = {'x': slot} if isinstance(slot, (int, float)) else slot
        height, bottom = slot.get('height', lay.get('height')), slot.get('bottom', lay.get('bottom'))
        sprite = sprite.resize((round(sprite.width * height / sprite.height), height), Image.Resampling.LANCZOS)
        cx = slot.get('x', lay.get('x')) * W
        x, y = round(cx - sprite.width / 2), bottom - sprite.height
        span = np.arange(max(x, 0), min(x + sprite.width, W))
        assert bottom > edge_y(m, span).max() + 20, f'{image}: cut-off waist must sit behind the foreground prop'
        plate = Image.new('RGBA', (W, H)); plate.alpha_composite(sprite, (max(x, 0), y) if x >= 0 else (0, y),
                                                                  (0, 0) if x >= 0 else (-x, 0))
        shadow = Image.new('RGBA', (W, H), (28, 24, 18, 0))
        shadow.putalpha(plate.getchannel('A').filter(ImageFilter.GaussianBlur(22)).point(lambda v: round(v * .16)))
        plates.append({'doll': doll, 'image': image, 'plate': plate, 'shadow': shadow, 'pivot': (cx, bottom - 80),
                       'source_rgba_sha256': __import__('hashlib').sha256(sprite.tobytes()).hexdigest(),
                       'file_sha256': sha(m['_job'] / image), 'sign': 1 if k % 2 == 0 else -1,
                       'factor': 1.4 if shot['layout'] == 'single' else 0.8, 'phase': 0.37 * k})
    return plates


def render(m):
    job, edit = m['_job'], m['_out']
    W, H, FPS = m['frame']['width'], m['frame']['height'], m['frame']['fps']
    spans = json.loads((edit / 'timeline.json').read_text())['shots']
    bg = ImageOps.fit(Image.open(job / m['set']['image']).convert('RGB'), (W, H), method=Image.Resampling.LANCZOS)
    foreground = foreground_layer(m, bg)
    cmd = [ffmpeg_exe(), '-hide_banner', '-nostdin', '-n', '-threads', '2', '-filter_threads', '2', '-f', 'rawvideo',
           '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', 'pipe:0', '-an', '-c:v', 'libx264',
           '-threads', '2', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p', str(edit / 'picture.mp4')]
    shots, frames, contact, n_total = [], [], [], 0
    with (edit / 'encode.log').open('xb') as log:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=log, stderr=log)
        try:
            for shot, span in zip(m['shots'], spans):
                plates = place(m, shot, W, H)
                for n in range(span['frames']):
                    t = n / FPS; frame = bg.convert('RGBA'); moves = []
                    for p in plates:
                        dx, dy, angle = trajectory(t, p['sign'], p['factor'], p['phase'])
                        frame.alpha_composite(p['shadow'].rotate(angle, resample=Image.Resampling.BICUBIC,
                                                                 center=p['pivot'], translate=(dx + 12, dy + 6)))
                        frame.alpha_composite(p['plate'].rotate(angle, resample=Image.Resampling.BICUBIC,
                                                                center=p['pivot'], translate=(dx, dy)))
                        moves.append({'doll': p['doll'], 'source_rgba_sha256': p['source_rgba_sha256'],
                                      'dx': round(dx, 2), 'dy': round(dy, 2), 'angle': round(angle, 3)})
                    frame.alpha_composite(foreground)
                    frame = frame.convert('RGB'); proc.stdin.write(frame.tobytes())
                    frames.append({'frame': n_total, 'shot': shot['id'], 'dolls': moves, 'facial_deformation': False})
                    if n in (12, span['frames'] // 2, span['frames'] - 12):
                        contact.append(frame.resize((270, 480)))
                    n_total += 1
                shots.append({**span, 'layout': shot['layout'],
                              'dolls': [{'doll': p['doll'], 'image': p['image'], 'file_sha256': p['file_sha256']} for p in plates]})
                print(f"shot {shot['id']}: {span['frames']} frames", file=sys.stderr)
            proc.stdin.close(); code = proc.wait(timeout=300)
            if code:
                raise RuntimeError('Video encoder failed; see encode.log')
        finally:
            if proc.poll() is None:
                proc.terminate(); proc.wait(timeout=10)
    sheet = Image.new('RGB', (810, 480 * math.ceil(len(contact) / 3)))
    for i, im in enumerate(contact):
        sheet.paste(im, ((i % 3) * 270, (i // 3) * 480))
    sheet.save(edit / 'contact-sheet.jpg', quality=90)
    with (edit / 'shots.json').open('x') as f:
        json.dump(shots, f, indent=2)
    with (edit / 'frame-transforms.json').open('x') as f:
        json.dump(frames, f)
    total = spans[-1]['end_s']
    ffmpeg(['-i', str(edit / 'picture.mp4'), '-i', str(edit / 'soundtrack.wav'), '-map', '0:v:0', '-map', '1:a:0',
            '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-t', f'{total:.4f}', '-movflags', '+faststart',
            str(edit / 'final.mp4')])
    print(json.dumps({'frames': n_total, 'total_s': total}))


def preview(m):
    """One composited frame per shot (mid-shot, no motion), for fast layout iteration."""
    edit = m['_out']; W, H = m['frame']['width'], m['frame']['height']
    bg = ImageOps.fit(Image.open(m['_job'] / m['set']['image']).convert('RGB'), (W, H), method=Image.Resampling.LANCZOS)
    foreground = foreground_layer(m, bg)
    tiles = []
    for shot in m['shots']:
        frame = bg.convert('RGBA')
        for p in place(m, shot, W, H):
            frame.alpha_composite(p['shadow']); frame.alpha_composite(p['plate'])
        frame.alpha_composite(foreground); tiles.append(frame.convert('RGB').resize((360, 640)))
    sheet = Image.new('RGB', (360 * len(tiles), 640))
    for i, t in enumerate(tiles):
        sheet.paste(t, (360 * i, 0))
    n = len(list(edit.glob('preview-*.jpg'))) + 1
    sheet.save(edit / f'preview-{n}.jpg', quality=88); print(edit / f'preview-{n}.jpg')


def validate(m):
    import av
    edit = m['_out']; FPS = m['frame']['fps']
    tl = json.loads((edit / 'timeline.json').read_text()); total = tl['total_s']
    expected_frames = sum(s['frames'] for s in tl['shots'])
    p = edit / 'final.mp4'; c = av.open(str(p)); s = c.streams.video[0]; s.thread_count = 2
    count = sum(1 for _ in c.decode(s)); duration = c.duration / av.time_base
    width, height = s.codec_context.width, s.codec_context.height; c.close()
    frames = json.loads((edit / 'frame-transforms.json').read_text())
    checks = {'frame_count': count == expected_frames, 'duration': abs(duration - total) < .05,
              'size': (width, height) == (m['frame']['width'], m['frame']['height'])}
    # Face art may change only at cuts: within a shot each doll keeps one source image.
    per_shot = {}
    for f in frames:
        for d in f['dolls']:
            per_shot.setdefault((f['shot'], d['doll']), set()).add(d['source_rgba_sha256'])
    checks['face_fixed_within_shot'] = all(len(v) == 1 for v in per_shot.values())
    checks['rigid_motion_present'] = all(len({(d['dx'], d['dy'], d['angle']) for f in frames if f['shot'] == sh['shot']
                                              for d in f['dolls']}) > 10 for sh in tl['shots'])
    a = read_audio(p); lv = levels(p)
    clipped = int(np.count_nonzero(np.abs(a) >= 1))
    checks['true_peak'] = float(lv['input_tp']) <= -2.5
    checks['no_clipping'] = clipped == 0
    report = {'checks': checks, 'passed': all(checks.values()), 'decoded_frames': count, 'expected_frames': expected_frames,
              'duration_s': duration, 'planned_s': total, 'width': width, 'height': height, 'fps': FPS,
              'integrated_lufs': float(lv['input_i']), 'true_peak_dbfs': float(lv['input_tp']), 'clipped_samples': clipped,
              'sha256': sha(p), 'bytes': p.stat().st_size,
              'animation': 'rigid whole-doll transforms of immutable RGBA cutouts; no generative or facial motion',
              'human_review': 'pending (gate 3)'}
    with (edit / 'validation.json').open('x') as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))
    assert report['passed'], 'validation failed'


def transcript(m):
    edit = m['_out']; wav = edit / 'dialogue-check.wav'
    ffmpeg(['-i', str(edit / 'final.mp4'), '-vn', '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(wav)])
    heard = transcribe(wav)
    expected = ' '.join(s['line']['text'] for s in m['shots'] if s.get('line'))
    norm = lambda s: re.sub('[^a-z0-9 ]', ' ', s.lower()).split()
    # Known recognizer spellings (digits for numbers, odd casing) declared in the manifest,
    # applied word by word so they cannot hide a different mismatch.
    tolerated = {k.lower(): v.lower().split() for k, v in m.get('asr_tolerances', {}).items()}
    got = [w for word in norm(heard) for w in tolerated.get(word, [word])]
    exact = norm(expected) == norm(heard)
    report = {'expected': expected, 'heard': heard, 'exact_match': exact,
              'match_with_tolerances': got == norm(expected),
              'tolerances': m.get('asr_tolerances', {}), 'recognizer': 'ai/deploy/whisper (Wyoming ASR)'}
    with (edit / 'dialogue-transcript.json').open('x') as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))
    assert report['match_with_tolerances'], 'transcript differs from the script; inspect before delivering'


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('manifest'); ap.add_argument('stage', choices=list(GUARDS))
    ap.add_argument('--out', default='edit', help='output folder inside the job directory (one per edit attempt)')
    a = ap.parse_args(); m = load_manifest(a.manifest); m['_out'] = m['_job'] / a.out; m['_out'].mkdir(exist_ok=True)
    if any((m['_out'] / n).exists() for n in GUARDS[a.stage]):
        raise FileExistsError(f'{a.stage} outputs already exist in {a.out}; use a new --out')
    {'audio': audio, 'render': render, 'validate': validate, 'transcript': transcript, 'preview': preview}[a.stage](m)
