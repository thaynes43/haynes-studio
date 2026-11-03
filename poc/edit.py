"""Manifest-driven doll-short editor (runbook stages 5 and 6).

Generalized from haynes-ops scripts/wan-video/edit_doll_short.py (OP345): rigid
puppet motion (whole-doll translate/rotate, poses held at 12/s inside 24 fps, no face
animation). Shots, lengths, dolls per shot, placement, sound cues, talk bounce, scripted
moves and an animated campfire come from titles/<slug>/manifest.json instead of code.

    python poc/edit.py titles/<slug>/manifest.json audio|preview|render|validate|transcript [--out edit-2]

Every stage is create-only under <job>/<out>/ (default edit/); a new attempt uses a new --out.
"""
from studio import load_manifest, sha, read_audio, write_audio, levels, ffmpeg, ffmpeg_exe, transcribe, lines_of, RATE
import argparse, json, math, re, subprocess, sys
import numpy as np
from PIL import Image, ImageFilter, ImageOps

GUARDS = {'audio': ['dialogue-only.wav', 'premaster.wav', 'soundtrack.wav', 'timeline.json'],
          'render': ['picture.mp4', 'encode.log', 'shots.json', 'frame-transforms.json', 'contact-sheet.jpg', 'final.mp4',
                     'picture-inputs.sha256'],
          'validate': ['validation.json'], 'transcript': ['dialogue-transcript.json', 'dialogue-check.wav'], 'preview': []}


def speech_records(m):
    """speech.json keyed by (shot, k); older files without `k` are single-line shots."""
    if not (m['_job'] / 'speech.json').exists():
        return {}
    return {(l['shot'], l.get('k', 0)): l for l in json.loads((m['_job'] / 'speech.json').read_text())['lines']}


def resolve_lines(shot, speech):
    """Each line of the shot with its start time (s into the shot) and its speech record."""
    out, t = [], None
    for k, line in lines_of(shot):
        rec = speech[(shot['id'], k)]
        start = line['start'] if t is None else t + line.get('gap', 0.3)
        out.append({**line, 'k': k, 'start': start, 'rec': rec, 'end': start + rec['duration_s']})
        t = out[-1]['end']
    return out


def anchored(shot, item, speech):
    """Time (s into the shot) of a cue or move: `at`, or `offset` after the end of line
    `after_line` (its index in the shot), so a gavel lands right as a line finishes."""
    if 'after_line' in item:
        return resolve_lines(shot, speech)[item['after_line']]['end'] + item.get('offset', 0.0)
    return item['at']


def timeline(m):
    """Shot start/end times. A shot with lines lasts until its last line ends plus `tail`,
    rounded up to a frame."""
    speech = speech_records(m)
    fps, t, out = m['frame']['fps'], 0.0, []
    for shot in m['shots']:
        if 'duration' in shot:
            d = shot['duration']
        else:
            d = resolve_lines(shot, speech)[-1]['end'] + shot['tail']
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
        for line in resolve_lines(shot, speech):
            rec = line['rec']
            assert sha(job / rec['file']) == rec['sha256']
            a = read_audio(job / rec['file'])
            a *= 10 ** (-22 / 20) / max(float(np.sqrt(np.mean(a * a))), 1e-8)
            edge = 240; a[:edge] *= np.linspace(0, 1, edge)[:, None]; a[-edge:] *= np.linspace(1, 0, edge)[:, None]
            start = span['start_s'] + line['start']
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
            start = span['start_s'] + anchored(shot, cue, speech); n = round(start * RATE)
            c = c[:len(mix) - n]; mix[n:n + len(c)] += c
            placed.append({'kind': 'sfx', 'cue': cue['cue'], 'file': spec['file'], 'sha256': sha(job / spec['file']),
                           'start_s': round(start, 3), 'end_s': round(start + len(c) / RATE, 3), 'rms_dbfs': spec['gain_db']})
    for name, spec in m.get('beds', {}).items():
        # An ambience bed (fire crackle) looped with 1 s crossfades under the whole film.
        b = read_audio(job / spec['file'])
        b *= 10 ** (spec['gain_db'] / 20) / max(float(np.sqrt(np.mean(b * b))), 1e-8)
        fade = RATE; loop = b.copy()
        assert len(b) > 2 * fade, f'{name}: a bed must be longer than 2 s to loop with 1 s crossfades'
        while len(loop) < len(mix):
            ramp = np.linspace(0, 1, fade)[:, None]
            loop = np.concatenate([loop[:-fade], loop[-fade:] * (1 - ramp) + b[:fade] * ramp, b[fade:]])
        loop = loop[:len(mix)]; loop[:RATE // 2] *= np.linspace(0, 1, RATE // 2)[:, None]
        mix += loop
        placed.append({'kind': 'bed', 'cue': name, 'file': spec['file'], 'sha256': sha(job / spec['file']),
                       'start_s': 0, 'end_s': round(total, 3), 'rms_dbfs': spec['gain_db']})
    mix = mix[:round(total * RATE)]
    # Gain staging: transient cues (a crunch) can peak hot. Leave headroom here; the
    # master stage then sets the final loudness and true peak.
    peak = float(np.max(np.abs(mix))); headroom_db = 0.0
    if peak > 0.5:
        mix *= 0.5 / peak; headroom_db = 20 * math.log10(0.5 / peak)
    write_audio(edit / 'premaster.wav', mix)
    first = levels(edit / 'premaster.wav')
    # Gain to the loudness target, then a peak limiter catches transients (a crunch)
    # instead of letting one peak hold the whole film down. 1 dB below the true-peak
    # target leaves room for inter-sample peaks after encoding.
    gain = m['master']['lufs'] - float(first['input_i'])
    limit = 10 ** ((m['master']['true_peak'] - 1) / 20)
    ffmpeg(['-i', str(edit / 'premaster.wav'), '-af',
            f'volume={gain}dB,alimiter=limit={limit:.4f}:attack=2:release=60:level=0', '-ar', '48000',
            '-c:a', 'pcm_s24le', str(edit / 'soundtrack.wav')])
    with (edit / 'timeline.json').open('x') as f:
        json.dump({'total_s': total, 'shots': spans, 'audio': placed, 'premaster_headroom_db': headroom_db, 'master_gain_db': gain}, f, indent=2)
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


PAD = 240  # off-frame margin on each side of a doll plate


def draw(frame, p, dx, dy, angle):
    """Composite one doll (shadow, then body) moved by (dx, dy, angle) onto frame."""
    W, H = frame.size
    for layer, off in ((p['shadow'], (dx + 12, dy + 6)), (p['plate'], (dx, dy))):
        moved = layer.rotate(angle, resample=Image.Resampling.BICUBIC, center=p['pivot'], translate=off)
        frame.alpha_composite(moved.crop((PAD, 0, PAD + W, H)))


def camera(shot, frame, t):
    """Optional push-in: crop toward `center` from zoom[0] to zoom[1] over `over` seconds
    (ease-out, like a snap zoom), scaled back to the frame size."""
    cam = shot.get('camera')
    if not cam:
        return frame
    W, H = frame.size; z0, z1 = cam['zoom']
    u = min(1.0, t / cam.get('over', 0.4)); u = 1 - (1 - u) ** 3
    z = z0 + (z1 - z0) * u
    if abs(z - 1) < 1e-3:
        return frame
    cx, cy = cam['center']; w, h = W / z, H / z
    x0 = min(max(cx - w / 2, 0), W - w); y0 = min(max(cy - h / 2, 0), H - h)
    return frame.crop((round(x0), round(y0), round(x0 + w), round(y0 + h))).resize((W, H), Image.Resampling.BICUBIC)


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
        if 'crop' in slot:  # close-ups: keep a fraction of the cutout [x0, y0, x1, y1]
            fx0, fy0, fx1, fy1 = slot['crop']
            sprite = sprite.crop((round(fx0 * sprite.width), round(fy0 * sprite.height),
                                  round(fx1 * sprite.width), round(fy1 * sprite.height)))
        sprite = sprite.resize((round(sprite.width * height / sprite.height), height), Image.Resampling.LANCZOS)
        cx = slot.get('x', lay.get('x')) * W
        x, y = round(cx - sprite.width / 2), bottom - sprite.height
        span = np.arange(max(x, 0), min(x + sprite.width, W))
        if shot.get('foreground', True):
            assert bottom > edge_y(m, span).max() + 20, f'{image}: cut-off waist must sit behind the foreground prop'
        else:
            assert bottom >= H + 60, f'{image}: with no foreground the cut edge must be below the frame'
        # The plate is wider than the frame so a doll hanging off an edge keeps her full
        # width when a move slides her back into view; draw() crops to the frame.
        assert x + PAD >= 0 and x + sprite.width <= W + PAD, f'{image}: more than {PAD}px off the frame'
        plate = Image.new('RGBA', (W + 2 * PAD, H)); plate.alpha_composite(sprite.crop((0, 0, sprite.width, max(0, min(sprite.height, H - y)))), (x + PAD, y))
        shadow = Image.new('RGBA', (W + 2 * PAD, H), (28, 24, 18, 0))
        shadow.putalpha(plate.getchannel('A').filter(ImageFilter.GaussianBlur(22)).point(lambda v: round(v * .16)))
        plates.append({'doll': doll, 'image': image, 'plate': plate, 'shadow': shadow, 'pivot': (cx + PAD, bottom - 80),
                       'source_rgba_sha256': __import__('hashlib').sha256(sprite.tobytes()).hexdigest(),
                       'file_sha256': sha(m['_job'] / image), 'sign': 1 if k % 2 == 0 else -1,
                       'factor': 1.4 if shot['layout'] == 'single' else 0.8, 'phase': 0.37 * k})
    return plates


POSE_HZ = 12  # stop-motion: every movement is held for two 24 fps frames


def speech_envelope(m, shot):
    """For each line in the shot: (doll, start, loudness at 12 poses/s scaled 0..1), so the
    speaker bounces on her syllables."""
    talks = []
    for line in resolve_lines(shot, speech_records(m)):
        a = read_audio(m['_job'] / line['rec']['file']).mean(1); hop = RATE // POSE_HZ
        env = np.array([np.sqrt(np.mean(a[i:i + hop] ** 2)) for i in range(0, len(a), hop)])
        talks.append((line['doll'], line['start'], env / max(env.max(), 1e-8)))
    return talks


def motion(m, shot, p, t, env):
    """Whole-doll offset at time t: a small idle wobble, a hop-and-tilt on each syllable
    while this doll speaks (a hand shaking the toy as it 'talks'), and scripted moves
    such as lunging toward someone. Quantized to 12 poses/s."""
    q = math.floor(t * POSE_HZ) / POSE_HZ
    style = m.get('motion', {})
    idle = style.get('idle_scale', 0.3) * (1.0 if shot['layout'] == 'single' else 0.6)
    dx, dy, angle = trajectory(q, p['sign'], p['factor'] * idle, p['phase'])
    dy *= idle
    for doll, start, curve in env or []:
        if doll != p['doll']:
            continue
        k = int(round((q - start) * POSE_HZ))
        if 0 <= k < len(curve):
            e = float(curve[k]); hop = style.get('talk_hop', 34) * (1.0 if shot['layout'] == 'single' else 0.7)
            # Each syllable lifts the doll and tips her alternately left and right.
            dy -= hop * e
            angle += style.get('talk_tilt', 3.2) * e * (1 if (k // 2) % 2 == 0 else -1)
            dx += style.get('talk_shuffle', 7) * e * (1 if (k // 3) % 2 == 0 else -1)
    for mv in shot.get('moves', []):
        at = anchored(shot, mv, speech_records(m)) if 'after_line' in mv else mv['at']
        if mv['doll'] != p['doll'] or q < at:
            continue
        u = 1.0 if mv.get('dur', 0) == 0 else min(1.0, (q - at) / mv['dur'])
        u = math.ceil(u * 3) / 3  # a hand jerks the toy over in three held steps
        dx += mv.get('dx', 0) * u; dy += mv.get('dy', 0) * u; angle += mv.get('angle', 0) * u
    return dx, dy, angle


class Fire:
    """Stop-motion flicker for a flame in the set: at each held pose the flame region is
    re-drawn as a randomly stretched, swayed and brightened copy of itself. Render then
    lets the warm firelight on the whole frame (set, dolls, log) breathe with it."""

    def __init__(self, m, bg):
        spec = m['set']['fire']; self.spec = spec
        x0, y0, x1, y1 = spec['box']; self.box = (x0, y0, x1, y1)
        a = np.asarray(bg).astype(np.float32); self.patch = a[y0:y1, x0:x1].copy()
        r, g, b = (self.patch[..., i] for i in range(3))
        hot = ((r > 170) & (g > 90) & (r - b > 70)).astype(np.float32)
        mask = Image.fromarray((hot * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(6))
        self.mask = np.asarray(mask).astype(np.float32)[..., None] / 255
        self.rng = np.random.default_rng(spec.get('seed', 7)); self.cache = {}
        H, W = a.shape[:2]; cx, cy = spec['glow_center']
        yy, xx = np.mgrid[0:H, 0:W]
        self.falloff = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * spec.get('glow_radius', 650) ** 2)))[..., None].astype(np.float32)

    def pose(self, k):
        if k not in self.cache:
            r = self.rng
            self.cache[k] = {'stretch': float(r.uniform(0.9, 1.18)), 'sway': float(r.uniform(-9, 9)),
                             'gain': float(r.uniform(0.75, 1.3)), 'glow': float(r.uniform(-1, 1)), 'phase': float(r.uniform(0, 6.3))}
        return self.cache[k]

    def apply(self, frame, t):
        """Draw the flame for time t onto an RGB PIL frame (render adds the firelight)."""
        k = int(math.floor(t * POSE_HZ)); p = self.pose(k)
        x0, y0, x1, y1 = self.box; h, w = self.patch.shape[:2]
        # Stretch upward from the flame's base, and sway rows more the higher they are.
        rows = np.arange(h); base = h - 1
        src_rows = np.clip(base - (base - rows) / p['stretch'], 0, base).astype(int)
        height = (base - rows) / base
        shift = (p['sway'] * height ** 1.5 * np.sin(rows / 11 + p['phase'])).astype(int)
        cols = (np.arange(w)[None, :] - shift[:, None]).clip(0, w - 1)
        warped = self.patch[src_rows[:, None], cols]; wmask = self.mask[src_rows[:, None], cols]
        a = np.asarray(frame).astype(np.float32)
        region = a[y0:y1, x0:x1]
        flame = np.clip(warped * p['gain'], 0, 255)
        # Screen-blend the moving flame over the static one so it flares and licks without ghosts.
        region[:] = region + (255 - region) * (flame / 255) * wmask * self.spec.get('strength', 0.85) * (0.5 + 0.5 * p['gain'])
        return Image.fromarray(a.clip(0, 255).astype(np.uint8))


def mux(m, edit, total):
    ffmpeg(['-i', str(edit / 'picture.mp4'), '-i', str(edit / 'soundtrack.wav'), '-map', '0:v:0', '-map', '1:a:0',
            '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-t', f'{total:.4f}', '-movflags', '+faststart',
            str(edit / 'final.mp4')])


def picture_inputs(m):
    """Hash of everything the picture depends on: frame, set, layouts, motion, each shot's
    dolls, layout, moves and line timing, the cutout and set files, and the voice files
    (their envelopes drive the talk bounce). Sound-only settings are left out."""
    import hashlib
    shots = [{k: s.get(k) for k in ('id', 'layout', 'dolls', 'moves', 'line', 'lines', 'tail', 'duration', 'camera', 'foreground')}
             for s in m['shots']]
    files = sorted({img for s in m['shots'] for img in s['dolls'].values()} | {m['set']['image']})
    speech = json.loads((m['_job'] / 'speech.json').read_text())['lines'] if (m['_job'] / 'speech.json').exists() else []
    blob = {'frame': m['frame'], 'set': m['set'], 'layouts': m['layouts'], 'motion': m.get('motion'), 'shots': shots,
            'files': {f: sha(m['_job'] / f) for f in files}, 'voices': [l['sha256'] for l in speech]}
    return hashlib.sha256(json.dumps(blob, sort_keys=True).encode()).hexdigest()


def reuse_picture(m, source):
    """Audio-only change: reuse another attempt's picture (same shot timing) and re-mux."""
    import shutil
    edit = m['_out']; src = m['_job'] / source
    ours = json.loads((edit / 'timeline.json').read_text())['shots']
    theirs = json.loads((src / 'timeline.json').read_text())['shots']
    assert ours == theirs, 'shot timing differs; a full render is needed'
    recorded = src / 'picture-inputs.sha256'
    assert recorded.exists(), f'{source} has no picture-inputs record; render it again'
    assert recorded.read_text().strip() == picture_inputs(m), 'picture inputs changed (layout, motion, set, cutouts or voices); a full render is needed'
    for n in ('picture.mp4', 'shots.json', 'frame-transforms.json', 'contact-sheet.jpg', 'picture-inputs.sha256'):
        with (src / n).open('rb') as a, (edit / n).open('xb') as b:
            shutil.copyfileobj(a, b)
    (edit / 'encode.log').open('x').write(f'picture reused from {source}\n')
    mux(m, edit, ours[-1]['end_s']); print(json.dumps({'picture_from': source, 'total_s': ours[-1]['end_s']}))


def render(m):
    job, edit = m['_job'], m['_out']
    if m.get('_picture_from'):
        return reuse_picture(m, m['_picture_from'])
    W, H, FPS = m['frame']['width'], m['frame']['height'], m['frame']['fps']
    spans = json.loads((edit / 'timeline.json').read_text())['shots']
    bg = ImageOps.fit(Image.open(job / m['set']['image']).convert('RGB'), (W, H), method=Image.Resampling.LANCZOS)
    foreground = foreground_layer(m, bg)
    fire = Fire(m, bg) if 'fire' in m['set'] else None
    for shot in m['shots']:  # fail fast: check every placement before encoding anything
        place(m, shot, W, H)
    cmd = [ffmpeg_exe(), '-hide_banner', '-nostdin', '-n', '-threads', '2', '-filter_threads', '2', '-f', 'rawvideo',
           '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', 'pipe:0', '-an', '-c:v', 'libx264',
           '-threads', '2', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p', str(edit / 'picture.mp4')]
    shots, frames, contact, n_total = [], [], [], 0
    with (edit / 'encode.log').open('xb') as log:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=log, stderr=log)
        try:
            for shot, span in zip(m['shots'], spans):
                plates = place(m, shot, W, H); env = speech_envelope(m, shot)
                for n in range(span['frames']):
                    t = n / FPS
                    base = fire.apply(bg, span['start_s'] + t) if fire else bg  # film time: no reset at cuts
                    frame = base.convert('RGBA'); moves = []
                    for p in plates:
                        dx, dy, angle = motion(m, shot, p, t, env)
                        draw(frame, p, dx, dy, angle)
                        moves.append({'doll': p['doll'], 'source_rgba_sha256': p['source_rgba_sha256'],
                                      'dx': round(dx, 2), 'dy': round(dy, 2), 'angle': round(angle, 3)})
                    if shot.get('foreground', True):
                        frame.alpha_composite(foreground)
                    frame = camera(shot, frame.convert('RGB'), t)
                    if fire:  # firelight also falls on the dolls and the log, not just the set
                        k = int(math.floor((span['start_s'] + t) * POSE_HZ)); g = fire.pose(k)['glow']
                        a = np.asarray(frame).astype(np.float32)
                        warm = 1 + fire.spec.get('doll_glow', 0.035) * g * fire.falloff
                        a *= np.concatenate([warm, 1 + (warm - 1) * 0.55, 1 + (warm - 1) * 0.1], axis=2)
                        frame = Image.fromarray(a.clip(0, 255).astype(np.uint8))
                    proc.stdin.write(frame.tobytes())
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
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait(timeout=10)
    sheet = Image.new('RGB', (810, 480 * math.ceil(len(contact) / 3)))
    for i, im in enumerate(contact):
        sheet.paste(im, ((i % 3) * 270, (i // 3) * 480))
    sheet.save(edit / 'contact-sheet.jpg', quality=90)
    with (edit / 'shots.json').open('x') as f:
        json.dump(shots, f, indent=2)
    (edit / 'picture-inputs.sha256').open('x').write(picture_inputs(m) + '\n')
    with (edit / 'frame-transforms.json').open('x') as f:
        json.dump(frames, f)
    total = spans[-1]['end_s']
    mux(m, edit, total)
    print(json.dumps({'frames': n_total, 'total_s': total}))


def preview(m):
    """One composited still per shot at mid-shot (motion and fire applied), for fast layout iteration."""
    edit = m['_out']; W, H = m['frame']['width'], m['frame']['height']
    bg = ImageOps.fit(Image.open(m['_job'] / m['set']['image']).convert('RGB'), (W, H), method=Image.Resampling.LANCZOS)
    foreground = foreground_layer(m, bg); fire = Fire(m, bg) if 'fire' in m['set'] else None
    spans = json.loads((edit / 'timeline.json').read_text())['shots'] if (edit / 'timeline.json').exists() else None
    tiles = []
    for i, shot in enumerate(m['shots']):
        t = (spans[i]['end_s'] - spans[i]['start_s']) / 2 if spans else 1.0
        start = spans[i]['start_s'] if spans else 0.0
        env = speech_envelope(m, shot) if spans else None
        frame = (fire.apply(bg, start + t) if fire else bg).convert('RGBA')
        for p in place(m, shot, W, H):
            dx, dy, angle = motion(m, shot, p, t, env)
            draw(frame, p, dx, dy, angle)
        if shot.get('foreground', True):
            frame.alpha_composite(foreground)
        tiles.append(camera(shot, frame.convert('RGB'), t).resize((360, 640)))
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
    checks['loudness'] = abs(float(lv['input_i']) - m['master']['lufs']) <= 1.5
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
    expected = ' '.join(line['text'] for s in m['shots'] for _, line in lines_of(s))
    norm = lambda s: re.sub('[^a-z0-9 ]', ' ', s.lower()).split()
    # Known recognizer spellings (digits for numbers, odd casing) declared in the manifest,
    # applied word by word so they cannot hide a different mismatch.
    tolerated = {k.lower(): v.lower().split() for k, v in m.get('asr_tolerances', {}).items()}
    got = [w for word in norm(heard) for w in tolerated.get(word, [word])]
    # Phrase tolerances replace an exact multi-word sequence only (e.g. "i i nay" for
    # "aye aye nay"), so a common word elsewhere is never rewritten.
    for wrong, right in m.get('asr_phrase_tolerances', []):
        wrong, right = norm(wrong), norm(right)
        for i in range(len(got) - len(wrong) + 1):
            if got[i:i + len(wrong)] == wrong:
                got = got[:i] + right + got[i + len(wrong):]
                break
    exact = norm(expected) == norm(heard)
    report = {'expected': expected, 'heard': heard, 'exact_match': exact,
              'match_with_tolerances': got == norm(expected),
              'tolerances': m.get('asr_tolerances', {}), 'phrase_tolerances': m.get('asr_phrase_tolerances', []), 'recognizer': 'ai/deploy/whisper (Wyoming ASR)'}
    with (edit / 'dialogue-transcript.json').open('x') as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))
    assert report['match_with_tolerances'], 'transcript differs from the script; inspect before delivering'


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('manifest'); ap.add_argument('stage', choices=list(GUARDS))
    ap.add_argument('--out', default='edit', help='output folder inside the job directory (one per edit attempt)')
    ap.add_argument('--picture-from', help='render: reuse the picture from another --out (audio-only change)')
    a = ap.parse_args(); m = load_manifest(a.manifest); m['_out'] = m['_job'] / a.out; m['_out'].mkdir(exist_ok=True)
    m['_picture_from'] = a.picture_from
    if any((m['_out'] / n).exists() for n in GUARDS[a.stage]):
        raise FileExistsError(f'{a.stage} outputs already exist in {a.out}; use a new --out')
    {'audio': audio, 'render': render, 'validate': validate, 'transcript': transcript, 'preview': preview}[a.stage](m)
