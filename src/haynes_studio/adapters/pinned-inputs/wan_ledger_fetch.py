import hashlib, json, pathlib, re, sys
# Read-only: prints the bytes of one asset a ledger lists, after checking its path and sha256.
ledger_id, digest = sys.argv[1], sys.argv[2]
if not re.fullmatch('[0-9a-f]{32}', ledger_id) or not re.fullmatch('[0-9a-f]{64}', digest):
    raise SystemExit('invalid ledger id or sha256')
job = json.loads(pathlib.Path('/workspace/jobs/' + ledger_id + '.json').read_text())
if job.get('kind') != 'edited_production':
    raise SystemExit('not an edited_production ledger')
match = [a for a in job.get('assets', []) if isinstance(a, dict) and a.get('sha256') == digest]
if not match:
    raise SystemExit('no asset with that sha256 in the ledger')
base = pathlib.Path('/workspace/output/productions').resolve()
path = pathlib.Path(match[0]['path']).resolve()
if not path.is_relative_to(base):
    raise SystemExit('asset path is outside /workspace/output/productions')
if path.stat().st_size > 67108864:
    raise SystemExit('asset is over 64 MiB')
data = path.read_bytes()
if hashlib.sha256(data).hexdigest() != digest:
    raise SystemExit('asset bytes do not match the ledger sha256')
sys.stdout.buffer.write(data)
