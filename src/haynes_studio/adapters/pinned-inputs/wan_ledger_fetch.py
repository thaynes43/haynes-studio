import hashlib, json, os, pathlib, re, stat, sys
# Read-only: prints the bytes of one asset a ledger lists, after checking its path and sha256.
# The ledger and the asset are each opened once with O_NOFOLLOW, checked on that descriptor
# (a regular file; the asset also one link and at most 64 MiB) and read from it, so a symlink
# or hard link swapped in after the path checks is refused.
ledger_id, digest = sys.argv[1], sys.argv[2]
if not re.fullmatch('[0-9a-f]{32}', ledger_id) or not re.fullmatch('[0-9a-f]{64}', digest):
    raise SystemExit('invalid ledger id or sha256')
LIMIT = 67108864
def read(path, asset):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise SystemExit(('asset' if asset else 'ledger') + ' is not a regular file')
        if asset and st.st_nlink != 1:
            raise SystemExit('asset has more than one hard link')
        if asset and st.st_size > LIMIT:
            raise SystemExit('asset is over 64 MiB')
        data = bytearray()
        while chunk := os.read(fd, 1048576):
            data += chunk
            if asset and len(data) > LIMIT:
                raise SystemExit('asset is over 64 MiB')
        return data
    finally:
        os.close(fd)
jobs = pathlib.Path('/workspace/jobs').resolve()
ledger = jobs / (ledger_id + '.json')
if not ledger.resolve().is_relative_to(jobs):
    raise SystemExit('ledger path is outside /workspace/jobs')
job = json.loads(read(ledger, False))
if job.get('kind') != 'edited_production':
    raise SystemExit('not an edited_production ledger')
match = [a for a in job.get('assets', []) if isinstance(a, dict) and a.get('sha256') == digest]
if not match:
    raise SystemExit('no asset with that sha256 in the ledger')
base = pathlib.Path('/workspace/output/productions').resolve()
path = pathlib.Path(match[0]['path']).resolve()
if not path.is_relative_to(base):
    raise SystemExit('asset path is outside /workspace/output/productions')
data = read(path, True)
if hashlib.sha256(data).hexdigest() != digest:
    raise SystemExit('asset bytes do not match the ledger sha256')
sys.stdout.buffer.write(data)
