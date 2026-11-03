"""Save a finished short to private storage behind the Wan API (runbook stage 7).

Generalized from haynes-ops scripts/wan-video/preserve_doll_short.py (OP345).

    python3 poc/deliver.py titles/<slug>/manifest.json [--out edit-2]

1. Refuses unless validation and the transcript check passed.
2. Copies every asset create-only to /workspace/output/productions/<job>/ on PVC
   ai/wan-video (through `kubectl exec` into the API container), verifying SHA256. A
   file already there with the same hash is skipped, so a partial delivery can be
   rerun; a different file at the same path stops it.
3. Builds the ledger, validates it locally (the API reads every ledger at startup with
   no error handling, so a bad one would crash the shared service), and hard-links it
   into /workspace/jobs/<id>.json.
4. Reads it back through the API inside the pod and writes <job>/production.json.
"""
import json, re, subprocess, sys, time, uuid
from studio import load_manifest, sha

REMOTE = ['kubectl', 'exec', '-i', '-n', 'ai', 'deploy/wan-video', '-c', 'api', '--', 'python3', '-c']
WRITE = '''import pathlib,sys,hashlib,json
p=pathlib.Path(sys.argv[1]);p.parent.mkdir(parents=True,exist_ok=True);h=hashlib.sha256()
if p.exists():
 # Resume after a partial delivery: identical bytes are fine, anything else is refused.
 if hashlib.sha256(p.read_bytes()).hexdigest()!=sys.argv[2]:raise FileExistsError('Different file already at '+str(p))
 sys.stdin.buffer.read();print(json.dumps({'path':str(p),'bytes':p.stat().st_size,'sha256':sys.argv[2],'existing':True}));sys.exit(0)
with p.open('xb') as f:
 while True:
  b=sys.stdin.buffer.read(1048576)
  if not b:break
  f.write(b);h.update(b)
if h.hexdigest()!=sys.argv[2]:p.unlink();raise RuntimeError('Checksum mismatch')
print(json.dumps({'path':str(p),'bytes':p.stat().st_size,'sha256':h.hexdigest()}))
'''
PUBLISH = '''import pathlib,sys,json,uuid,os
j=json.load(sys.stdin);root=pathlib.Path('/workspace/jobs');temp=root/('editorial-'+uuid.uuid4().hex+'.tmp')
temp.write_text(json.dumps(j,indent=2)+'\\n')
try:os.link(temp,root/(j['id']+'.json'))
finally:temp.unlink()
'''
READ = '''import sys,urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8080/videos/'+sys.argv[1]).read().decode())'''
SPACE = '''import shutil;u=shutil.disk_usage('/workspace');print(u.free)'''


def provenance(m):
    """Built from the manifest's `provenance` section plus its cast voices and cues."""
    title_dir = m['_path'].parent.name
    cues = [f"{name}: {c['source']['service']} job {c['source']['job']} seed {c['source']['seed']}"
            for name, c in m.get('sfx', {}).items()]
    return {**m.get('provenance', {}),
            'records': f'haynes-studio titles/{title_dir}/ (manifest.json, prompts.json, evidence/)',
            'voices': 'Kokoro-82M v1.0 stock voices ' + ', '.join(sorted({c['voice'] for c in m['cast'].values()}))
                      + '; no cloning, no lip sync.',
            'sfx': '; '.join(cues) or 'none',
            'human_approval': 'Pending: gate 3 (Tom).'}


def check_ledger(j):
    """The fields the Wan API relies on (api.py recover(), job_path(), output_file())."""
    assert re.fullmatch(r'[0-9a-f]{32}', j['id'])
    assert j['state'] == 'succeeded' and j['kind'] == 'edited_production'
    assert j['output'].endswith('.mp4') and not j['output'].startswith('/') and '..' not in j['output']
    for k in ('title', 'story', 'assets', 'bytes', 'sha256', 'created_at', 'finished_at', 'telemetry', 'preset', 'provenance'):
        assert k in j, k
    json.loads(json.dumps(j))


def main(path, out):
    m = load_manifest(path); job = m['_job']; edit = job / out
    if (job / 'production.json').exists():
        raise FileExistsError('already delivered; a new attempt is a new revision')
    v = json.loads((edit / 'validation.json').read_text()); t = json.loads((edit / 'dialogue-transcript.json').read_text())
    assert v['passed'] and t['match_with_tolerances'], 'checks did not pass'
    speech = json.loads((job / 'speech.json').read_text())
    names = ([f'{out}/{n}' for n in ('final.mp4', 'soundtrack.wav', 'dialogue-only.wav', 'timeline.json', 'shots.json',
                                      'frame-transforms.json', 'validation.json', 'dialogue-transcript.json', 'contact-sheet.jpg')]
             + ['speech.json'] + [l['file'] for l in speech['lines']]
             + sorted({img for s in m['shots'] for img in s['dolls'].values()} | {m['set']['image']})
             + [c['file'] for c in m['sfx'].values()])
    digests = {n: sha(job / n) for n in names}
    assert digests[f'{out}/final.mp4'] == v['sha256']
    for l in speech['lines']:
        assert digests[l['file']] == l['sha256']
    need = sum((job / n).stat().st_size for n in names)
    free = int(subprocess.run(REMOTE + [SPACE], capture_output=True, check=True, timeout=30).stdout)
    assert free > need * 10, f'only {free} bytes free on the Wan PVC'
    base = f"/workspace/output/productions/{m['job']}/"
    assets = []
    for n in names:
        with (job / n).open('rb') as f:
            r = subprocess.run(REMOTE + [WRITE, base + n, digests[n]], stdin=f, capture_output=True, check=True, timeout=180)
        assets.append(json.loads(r.stdout))
    now = time.time()
    ledger = {'id': uuid.uuid4().hex, 'kind': 'edited_production', 'story': m['story'], 'title': m['title'],
              'state': 'succeeded', 'created_at': now, 'finished_at': now, 'telemetry': [],
              'output': f"productions/{m['job']}/{out}/final.mp4", 'bytes': v['bytes'], 'sha256': v['sha256'],
              'assets': assets, 'preset': 'rigid-doll-dialogue-manifest',
              'provenance': provenance(m)}
    check_ledger(ledger)
    subprocess.run(REMOTE + [PUBLISH], input=json.dumps(ledger).encode(), capture_output=True, check=True, timeout=30)
    served = json.loads(subprocess.run(REMOTE + [READ, ledger['id']], capture_output=True, check=True, timeout=30).stdout)
    assert served['id'] == ledger['id'] and served['state'] == 'succeeded'
    with (job / 'production.json').open('x') as f:
        json.dump(ledger, f, indent=2)
    print('https://video.haynesops.com/videos/' + ledger['id'] + '/file')


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument('manifest'); ap.add_argument('--out', default='edit')
    a = ap.parse_args(); main(a.manifest, a.out)
