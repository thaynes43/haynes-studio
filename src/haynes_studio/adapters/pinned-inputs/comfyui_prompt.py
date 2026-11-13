
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
sys.stderr.write('PROMPT_ID %s\n' % pid); sys.stderr.flush()  # the caller logs it even if we fail later
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
