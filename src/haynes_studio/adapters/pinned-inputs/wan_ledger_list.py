import json, os, pathlib, re, stat
# Read-only: lists the edited-production ledgers in /workspace/jobs/. Opens nothing for writing.
# A ledger must resolve under /workspace/jobs and be a regular file, opened with O_NOFOLLOW and
# read from that descriptor; any other is listed as unreadable, by file name only.
jobs = pathlib.Path('/workspace/jobs').resolve()
def read(p):
    if not p.resolve().is_relative_to(jobs):
        raise ValueError('outside /workspace/jobs')
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('not a regular file')
        data = bytearray()
        while chunk := os.read(fd, 1048576):
            data += chunk
        return data
    finally:
        os.close(fd)
out = []
for p in sorted(jobs.glob('*.json')):
    if not re.fullmatch(r'[0-9a-f]{32}\.json', p.name):
        continue
    try:
        j = json.loads(read(p))
    except Exception:
        out.append({'file': p.name, 'error': 'unreadable'})
        continue
    if not isinstance(j, dict) or j.get('kind') != 'edited_production':
        continue
    assets = j.get('assets') if isinstance(j.get('assets'), list) else []
    out.append({'id': j.get('id'), 'title': j.get('title'), 'state': j.get('state'), 'output': j.get('output'),
                'bytes': j.get('bytes'), 'sha256': j.get('sha256'), 'created_at': j.get('created_at'),
                'asset_sha256': sorted({a['sha256'] for a in assets if isinstance(a, dict) and isinstance(a.get('sha256'), str)})})
print(json.dumps(out))
