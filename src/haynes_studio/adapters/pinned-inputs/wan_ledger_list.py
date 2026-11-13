import json, pathlib, re
# Read-only: lists the edited-production ledgers in /workspace/jobs/. Opens nothing for writing.
out = []
for p in sorted(pathlib.Path('/workspace/jobs').glob('*.json')):
    if not re.fullmatch(r'[0-9a-f]{32}\.json', p.name):
        continue
    try:
        j = json.loads(p.read_text())
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
