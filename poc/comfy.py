"""Submit one Qwen image job to the shared in-cluster ComfyUI and save the result.

PoC helper (runbook stage 2). Talks to ComfyUI's HTTP API from inside its own pod
(`kubectl exec -i -n ai comfyui-0 -c app`), one prompt in flight, and waits while
anyone else's job is queued or running. It never cancels or interrupts other work.

    python poc/comfy.py t2i  --job DIR --name a-base-1 --prompt-file p.txt --seed 1 --size 1104x1472
    python poc/comfy.py edit --job DIR --name a-proud --image DIR/a-base-1.png --prompt "..." --seed 1

Both modes use Qwen-Image 2.1 (int8), the model Home Assistant's renders keep warm, so
we do not evict each other's weights. Text-to-image uses poc/graphs/qwen_image_2_1_t2i_API.json
(hand-converted from haynes-ops' UI template image_qwen_image_2_1_t2i.json); edits use
haynes-ops' stored qwen_image_2_1_edit_API.json. Each output is written create-only as DIR/<name>.png and one
JSON line per job is appended to DIR/records.jsonl (graph, prompt, seed, timings, sha256).
"""
import argparse, base64, hashlib, json, subprocess, time, uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
T2I = HERE / 'graphs/qwen_image_2_1_t2i_API.json'
EDIT = Path.home() / 'repos/haynes-ops/kubernetes/main/apps/ai/stable-diffusion/comfyui/resources/api-workflows/qwen_image_2_1_edit_API.json'
EXEC = ['kubectl', 'exec', '-i', '-n', 'ai', 'comfyui-0', '-c', 'app', '--', 'python3', '-c']

# Runs inside the ComfyUI pod. Reads {"graph", "client_id", "upload"?} on stdin, waits for
# an idle queue, submits, polls history, and prints {"prompt_id", "images": [...b64]}.
REMOTE = r'''
import base64, json, sys, time, urllib.request, uuid
B = 'http://127.0.0.1:8188'
def get(path): return json.loads(urllib.request.urlopen(B + path, timeout=30).read())
def post(path, body, ctype='application/json'):
    req = urllib.request.Request(B + path, data=body, headers={'Content-Type': ctype})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())
job = json.load(sys.stdin)
if job.get('upload'):
    name, data = job['upload']['name'], base64.b64decode(job['upload']['b64'])
    boundary = uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\n'
            f'Content-Type: image/png\r\n\r\n').encode() + data + (
            f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\ntrue'
            f'\r\n--{boundary}--\r\n').encode()
    up = post('/upload/image', body, f'multipart/form-data; boundary={boundary}')
    sys.stderr.write('uploaded %s\n' % up)
waited = 0
while True:  # share politely: never queue behind or alongside someone else's work
    q = get('/queue')
    if not q['queue_running'] and not q['queue_pending']: break
    if waited > 1800: raise SystemExit('ComfyUI stayed busy for 30 min; not submitting')
    time.sleep(10); waited += 10
start = time.time()
pid = post('/prompt', json.dumps({'prompt': job['graph'], 'client_id': job['client_id']}).encode())['prompt_id']
while True:
    h = get('/history/' + pid)
    if pid in h and h[pid].get('status', {}).get('completed'): break
    if pid in h and h[pid].get('status', {}).get('status_str') == 'error':
        raise SystemExit('ComfyUI error: ' + json.dumps(h[pid]['status'])[:2000])
    if time.time() - start > 1200: raise SystemExit('Timed out waiting for ' + pid)
    time.sleep(3)
images = []
for node in h[pid]['outputs'].values():
    for im in node.get('images', []):
        q = 'filename=%s&subfolder=%s&type=%s' % (urllib.request.quote(im['filename']), urllib.request.quote(im['subfolder']), im['type'])
        images.append({**im, 'b64': base64.b64encode(urllib.request.urlopen(B + '/view?' + q, timeout=60).read()).decode()})
print(json.dumps({'prompt_id': pid, 'waited_s': waited, 'render_s': round(time.time() - start, 1), 'images': images}))
'''


def t2i_graph(prompt, seed, width, height, prefix):
    g = json.loads(T2I.read_text())
    g['4']['inputs']['prompt'] = prompt
    g['5']['inputs'].update(width=width, height=height)
    g['6']['inputs']['seed'] = seed
    g['8']['inputs']['filename_prefix'] = prefix
    return g


def edit_graph(prompt, seed, image_name, prefix):
    g = json.loads(EDIT.read_text())
    assert g['6']['class_type'] == 'TextEncodeQwenImage21' and g['1']['class_type'] == 'LoadImage'
    g['6']['inputs']['prompt'] = prompt
    g['7']['inputs']['seed'] = seed
    g['1']['inputs']['image'] = image_name
    g['9']['inputs']['filename_prefix'] = prefix
    return g


def run(job_dir, name, graph, meta, upload=None):
    job_dir = Path(job_dir)
    target = job_dir / f'{name}.png'
    if target.exists():
        raise FileExistsError(target)
    payload = {'graph': graph, 'client_id': f'studio-{job_dir.name}'}
    if upload:
        payload['upload'] = upload
    t0 = time.time()
    r = subprocess.run(EXEC + [REMOTE], input=json.dumps(payload).encode(), capture_output=True, timeout=3300)
    if r.returncode:
        raise RuntimeError(r.stderr.decode()[-2000:])
    out = json.loads(r.stdout)
    data = base64.b64decode(out['images'][0]['b64'])
    with target.open('xb') as f:
        f.write(data)
    record = {**meta, 'name': name, 'file': target.name, 'sha256': hashlib.sha256(data).hexdigest(),
              'bytes': len(data), 'prompt_id': out['prompt_id'], 'comfy_file': out['images'][0]['filename'],
              'comfy_subfolder': out['images'][0]['subfolder'], 'waited_s': out['waited_s'],
              'render_s': out['render_s'], 'wall_s': round(time.time() - t0, 1),
              'graph_sha256': hashlib.sha256(json.dumps(graph, sort_keys=True).encode()).hexdigest(),
              'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    with (job_dir / 'records.jsonl').open('a') as f:
        f.write(json.dumps(record) + '\n')
    print(json.dumps({k: v for k, v in record.items() if k != 'prompt'}))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    for cmd in ('t2i', 'edit'):
        p = sub.add_parser(cmd)
        p.add_argument('--job', required=True)
        p.add_argument('--name', required=True)
        p.add_argument('--seed', type=int, required=True)
        p.add_argument('--prompt')
        p.add_argument('--prompt-file')
    sub.choices['t2i'].add_argument('--size', default='1104x1472')
    sub.choices['edit'].add_argument('--image', required=True)
    a = ap.parse_args()
    prompt = a.prompt or Path(a.prompt_file).read_text().strip()
    prefix = f'studio/{Path(a.job).name}/{a.name}'
    if a.cmd == 't2i':
        w, h = map(int, a.size.split('x'))
        graph = t2i_graph(prompt, a.seed, w, h, prefix)
        meta = {'mode': 't2i', 'graph': T2I.name, 'width': w, 'height': h, 'seed': a.seed, 'prompt': prompt}
        run(a.job, a.name, graph, meta)
    else:
        src = Path(a.image).read_bytes()
        upload_name = f'studio-{uuid.uuid4().hex[:12]}.png'
        graph = edit_graph(prompt, a.seed, upload_name, prefix)
        meta = {'mode': 'edit', 'graph': EDIT.name, 'seed': a.seed, 'prompt': prompt, 'source': Path(a.image).name,
                'source_sha256': hashlib.sha256(src).hexdigest()}
        run(a.job, a.name, graph, meta, upload={'name': upload_name, 'b64': base64.b64encode(src).decode()})


if __name__ == '__main__':
    main()
