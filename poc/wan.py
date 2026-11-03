"""Render one Wan image-to-video clip on the studio's 3090s (E0 PoC, runbook-to-be).

Reuses the sanctioned OP342 path (haynes-ops scripts/wan-video/produce_butter_asmr.py):
inside the Wan API container it imports the installed `api` module and runs its own
`generate()` with a job-local graph, so the job holds the same /workspace/compute.lock as
the HTTP API (a concurrent API job gets 409), uses the API's watchdog, persisted ledger and
telemetry, and refuses unknown or competing engine work. Nothing is deployed or changed.

    python3 poc/wan.py --job DIR --name s1-a --image DIR/keyframes/s1.png \
        --prompt-file p.txt --seed 1 [--width 576 --height 1024 --length 121]

Waits for cool idle first (API accepting, no active job, empty queue, GPUs < 62 C and
<= 5 % busy). Writes DIR/clips/<name>.mp4 create-only, first/last frame PNGs, and appends
DIR/clips/records.jsonl. Stops on any failure: inspect before re-running.
"""
import argparse, hashlib, json, subprocess, time, uuid
from pathlib import Path

REMOTE = ['kubectl', 'exec', '-i', '-n', 'ai', 'deploy/wan-video', '-c', 'api', '--', 'python3', '-c']
# The deployed Wan graph; keep ~/repos/haynes-ops on origin/main.
TEMPLATE = Path.home() / 'repos/haynes-ops/kubernetes/main/apps/ai/wan-video/app/workflow.json'
NEGATIVE = ('changing doll identity, changing faces, new faces, extra people, extra dolls, human hands, text, '
            'subtitles, watermark, camera shake, fast motion, cuts, scene change, blurry, distorted, melting')

PROBE = ('import sys,json,urllib.request;sys.path.insert(0,"/config/video");import api;'
         'h=json.load(urllib.request.urlopen("http://127.0.0.1:8080/health",timeout=10));'
         'print(json.dumps({"health":h,"sample":api.gpu_sample(),"queue":api.engine("/queue")}))')

UPLOAD = '''import pathlib,sys,hashlib
p=pathlib.Path('/workspace/input/studio-e0')/sys.argv[1];p.parent.mkdir(parents=True,exist_ok=True)
b=sys.stdin.buffer.read();assert len(b)<20000000 and hashlib.sha256(b).hexdigest()==sys.argv[2]
if p.exists():
 assert hashlib.sha256(p.read_bytes()).hexdigest()==sys.argv[2],'different file already uploaded'
else:
 with p.open('xb') as f:f.write(b)
print(hashlib.sha256(p.read_bytes()).hexdigest())
'''

# From OP342: admission readback, then the installed generate() with our graph.
RUN = '''import sys,json,urllib.request,time
sys.path.insert(0,'/config/video');import api
p=json.load(sys.stdin);job=p['job'];graph=p['graph']
h=json.load(urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=10))
if h.get('accepting_jobs') is not True or 'active_job' not in h or h['active_job'] is not None:
 raise RuntimeError('Live API busy or hold; no submission')
job['live_admission_readback']={'time':time.time(),'health':h}
original_engine=api.engine
def observed_engine(path,body=None):
 if path.startswith('/history/'):
  q=original_engine('/queue')
  foreign=[e[1] for e in q.get('queue_running',[])+q.get('queue_pending',[]) if e[1]!=job.get('prompt_id')]
  if foreign:job['unexpected_work_seen']=sorted(set(job.get('unexpected_work_seen',[])+foreign))
 return original_engine(path,body)
api.engine=observed_engine
api.make_graph=lambda *args:graph
api.save(job);api.generate(job,p['prompt'])
print(json.dumps(job))
'''


def remote(code, payload=None, timeout=60, args=()):
    r = subprocess.run(REMOTE + [code] + list(args), input=None if payload is None else json.dumps(payload).encode(),
                       capture_output=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError(r.stderr.decode()[-1500:])
    return r.stdout


def wait_cool(max_s=1800):
    t0 = time.monotonic()
    while True:
        s = json.loads(remote(PROBE, timeout=30))
        h, q = s['health'], s['queue']
        if h.get('accepting_jobs') is not True or h.get('active_job') is not None:
            raise RuntimeError(f'Wan API busy or holding submissions: {h}')
        if q.get('queue_running') or q.get('queue_pending'):
            raise RuntimeError('Unknown engine work queued; preserving it and stopping')
        gpus = s['sample']['gpus']
        if all(g['temperature_c'] < 62 and g['utilization_percent'] <= 5 for g in gpus):
            return round(time.monotonic() - t0, 1), [(g['temperature_c'], g['utilization_percent']) for g in gpus]
        if time.monotonic() - t0 > max_s:
            raise RuntimeError('GPUs did not return to cool idle')
        time.sleep(10)


def render(job_dir, name, image, prompt, seed, width, height, length, negative=NEGATIVE, steps=20):
    import av
    job_dir = Path(job_dir); clips = job_dir / 'clips'; clips.mkdir(exist_ok=True)
    clip = clips / f'{name}.mp4'
    if clip.exists():
        raise FileExistsError(clip)
    t0 = time.time()
    cooled_s, temps = wait_cool()
    data = Path(image).read_bytes(); digest = hashlib.sha256(data).hexdigest()
    up_name = f'{digest[:16]}.png'
    r = subprocess.run(REMOTE + [UPLOAD, up_name, digest], input=data, capture_output=True, timeout=30)
    if r.returncode or r.stdout.decode().strip() != digest:
        raise RuntimeError('upload failed: ' + r.stderr.decode()[-500:])
    template = TEMPLATE.read_bytes(); graph = json.loads(template)
    # The template comes from a mutable checkout: refuse it if the edited nodes moved.
    expected = {'4': 'CLIPTextEncode', '5': 'CLIPTextEncode', '8': 'Wan22ImageToVideoLatent', '9': 'KSampler', '12': 'SaveVideo'}
    for node, cls in expected.items():
        assert graph[node]['class_type'] == cls, f'workflow.json node {node} is not {cls}; update wan.py'
    graph['4']['inputs']['text'] = prompt
    graph['5']['inputs']['text'] = negative
    graph['8']['inputs'].update(width=width, height=height, length=length, start_image=['13', 0])
    graph['9']['inputs'].update(seed=seed, steps=steps)
    job = {'id': uuid.uuid4().hex, 'state': 'queued', 'preset': f'studio-e0-i2v-{width}x{height}-{length}f',
           'seed': seed, 'created_at': time.time(), 'telemetry': [], 'kind': 'reference_conditioned_render',
           'reference_image': 'studio-e0/' + up_name, 'reference_sha256': digest,
           'story': 'https://work.haynesnetwork.com/work_packages/387'}
    graph['12']['inputs']['filename_prefix'] = 'video/' + job['id']
    graph['13'] = {'class_type': 'LoadImage', 'inputs': {'image': 'studio-e0/' + up_name}}
    t_submit = time.time()
    result = json.loads(remote(RUN, {'job': job, 'graph': graph, 'prompt': prompt}, timeout=1500))
    t_done = time.time()
    if result['state'] != 'succeeded':
        raise RuntimeError(f"Wan job {job['id']} ended {result['state']}; inspect before any further render")
    fetch = 'import urllib.request,sys;sys.stdout.buffer.write(urllib.request.urlopen("http://127.0.0.1:8080/videos/' + job['id'] + '/file",timeout=60).read())'
    body = remote(fetch, timeout=90)
    with clip.open('xb') as f:
        f.write(body)
    c = av.open(str(clip)); s = c.streams.video[0]; s.thread_count = 2; n = 0; first = last = None
    for fr in c.decode(s):
        if n == 0:
            first = fr.to_image()
        last = fr.to_image(); n += 1
    c.close()
    first.save(clips / f'{name}-first.png'); last.save(clips / f'{name}-last.png')
    rec = {'name': name, 'job_id': job['id'], 'template_sha256': hashlib.sha256(template).hexdigest(), 'seed': seed, 'width': width, 'height': height, 'length': length,
           'frames': n, 'image': Path(image).name, 'image_sha256': digest, 'prompt': prompt, 'negative': negative,
           'clip_sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body), 'cooldown_s': cooled_s,
           'start_temps': temps, 'render_s': round(t_done - t_submit, 1), 'wall_s': round(time.time() - t0, 1),
           'telemetry_tail': result.get('telemetry', [])[-3:], 'unexpected_work_seen': result.get('unexpected_work_seen'),
           'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    with (clips / 'records.jsonl').open('a') as f:
        f.write(json.dumps(rec) + '\n')
    if result.get('unexpected_work_seen'):
        raise RuntimeError('Competing work observed; output kept, stopping further submissions')
    return rec


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--job', required=True); ap.add_argument('--name', required=True); ap.add_argument('--image', required=True)
    ap.add_argument('--prompt'); ap.add_argument('--prompt-file'); ap.add_argument('--seed', type=int, required=True)
    ap.add_argument('--width', type=int, default=576); ap.add_argument('--height', type=int, default=1024)
    ap.add_argument('--length', type=int, default=121)
    a = ap.parse_args()
    prompt = a.prompt or Path(a.prompt_file).read_text().strip()
    rec = render(a.job, a.name, a.image, prompt, a.seed, a.width, a.height, a.length)
    print(json.dumps({k: v for k, v in rec.items() if k not in ('prompt', 'negative', 'telemetry_tail')}))
