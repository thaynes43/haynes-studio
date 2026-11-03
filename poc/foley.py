"""One ControlFoley take for a Wan clip (E0.5): POST /foley on the Foley service (its own
compute lease, cool-idle wait and guards), poll, fetch, verify the checksum. 0.7 to 8 s windows.

    python3 poc/foley.py OUT.wav SOURCE_JOB_ID START DURATION SEED "prompt" ["negative"]
"""
import hashlib, json, subprocess, sys, time
from pathlib import Path
REMOTE = ['kubectl', 'exec', '-i', '-n', 'ai', 'deploy/wan-video', '-c', 'api', '--', 'python3', '-c']
CODE = '''import json,sys,urllib.request
p=json.load(sys.stdin);b=None if p['body'] is None else json.dumps(p['body']).encode()
r=urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8189'+p['path'],data=b,headers={'Content-Type':'application/json'}),timeout=30)
sys.stdout.buffer.write(r.read())
'''
def call(path, body=None, binary=False):
    out = subprocess.run(REMOTE + [CODE], input=json.dumps({'path': path, 'body': body}).encode(), capture_output=True, check=True, timeout=60).stdout
    return out if binary else json.loads(out)
out = Path(sys.argv[1]); src, start, dur, seed, prompt = sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), int(sys.argv[5]), sys.argv[6]
neg = sys.argv[7] if len(sys.argv) > 7 else 'music, speech, voices, singing, wind noise, hum'
if out.exists(): raise FileExistsError(out)
t0 = time.time(); acc = call('/foley', {'source_job_id': src, 'start_seconds': start, 'duration': dur, 'seed': seed, 'prompt': prompt, 'negative_prompt': neg})
jid = acc['id']
while True:
    j = call('/foley/' + jid)
    if j['state'] in ('succeeded', 'failed'): break
    if time.time() - t0 > 1500: raise RuntimeError('Foley job still running after 25 min: ' + jid)
    time.sleep(10)
if j['state'] != 'succeeded': raise RuntimeError(json.dumps(j)[-600:])
b = call('/foley/' + jid + '/file', binary=True); assert hashlib.sha256(b).hexdigest() == j['provenance']['output_sha256']
with out.open('xb') as f: f.write(b)
print(json.dumps({'id': jid, 'wall_s': round(time.time() - t0, 1), 'bytes': len(b), 'sha256': j['provenance']['output_sha256']}))
