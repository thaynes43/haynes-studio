"""Compose each shot's first frame as a Wan keyframe (E0): the doll layout, foreground and
close-up framing from a title manifest, without motion or fire, at the Wan render size.

    python poc/keyframes.py titles/<slug>/manifest-<rev>.json OUT_DIR [--size 576x1024]
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')
import argparse, hashlib, json, sys
from pathlib import Path
from PIL import Image, ImageOps
sys.argv, _argv = sys.argv[:1], sys.argv
import edit
from studio import load_manifest
sys.argv = _argv


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('manifest'); ap.add_argument('out'); ap.add_argument('--size', default='576x1024')
    ap.add_argument('--job-dir', help='override the manifest job_dir (where cutouts live)')
    a = ap.parse_args(); m = load_manifest(a.manifest)
    if a.job_dir:
        m['_job'] = Path(os.path.expanduser(a.job_dir))
    W, H = m['frame']['width'], m['frame']['height']; w, h = map(int, a.size.split('x'))
    bg = ImageOps.fit(Image.open(m['_job'] / m['set']['image']).convert('RGB'), (W, H), method=Image.Resampling.LANCZOS)
    fg = edit.foreground_layer(m, bg); out = Path(a.out); out.mkdir(parents=True, exist_ok=True); recs = []
    for shot in m['shots']:
        frame = bg.convert('RGBA')
        for p in edit.place(m, shot, W, H):
            edit.draw(frame, p, 0, 0, 0)
        if shot.get('foreground', True):
            frame.alpha_composite(fg)
        cam = shot.get('camera')
        frame = edit.camera({'camera': {**cam, 'over': 1e-6}} if cam else {}, frame.convert('RGB'), 1.0)
        target = out / f"s{shot['id']}.png"
        frame.resize((w, h), Image.Resampling.LANCZOS).save(target)
        recs.append({'shot': shot['id'], 'file': target.name, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                     'dolls': shot['dolls'], 'layout': shot['layout']})
    (out / 'keyframes.json').write_text(json.dumps(recs, indent=2) + '\n'); print(len(recs), 'keyframes ->', out)


if __name__ == '__main__':
    main()
