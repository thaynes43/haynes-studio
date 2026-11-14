import errno, hashlib, json, os, re, stat, sys
# Read-only (story 846): prints the bytes of one Wan job's output. The job's ledger,
# /workspace/jobs/<job_id>.json, must be a regular file of a succeeded job with that id; its output is
# a relative .mp4 path below /workspace/output, each part a plain name (no '.', '..' or empty part).
# Every folder below /workspace is opened with O_NOFOLLOW | O_DIRECTORY relative to the one above,
# after an lstat; each file is lstat'ed, then opened with O_NOFOLLOW | O_NONBLOCK and checked on that
# descriptor: a regular file (the clip also with one link, at most LIMIT bytes and the size its ledger
# records), the same inode the lstat saw, read to the end from the descriptor; the clip is hashed. No
# link is followed below /workspace. Nothing is opened for writing.
# A refusal is one line, REFUSED <reason>, on stderr and exit status 3, with nothing on stdout. Any
# other error (a permission, an I/O error) is a traceback and exit status 1.
ROOT = '/workspace'
LIMIT = 67108864
LEDGER_LIMIT = 16777216
CHUNK = 1048576
held = []
def refuse(reason):
    sys.stderr.write('REFUSED ' + reason + '\n')
    raise SystemExit(3)
def step(folder_fd, name, folder, fixed=False):
    # A fixed folder of the volume (not one a record names) that is not a plain folder means the
    # wrong container or a volume not as recorded: REFUSED volume, which stops the whole import.
    def bad(reason):
        refuse('volume' if fixed else reason)
    try:
        seen = os.stat(name, dir_fd=folder_fd, follow_symlinks=False)
    except FileNotFoundError:
        bad('missing')
    if stat.S_ISLNK(seen.st_mode):
        bad('link')
    if not (stat.S_ISDIR(seen.st_mode) if folder else stat.S_ISREG(seen.st_mode)):
        bad('not_regular')
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | (os.O_DIRECTORY if folder else os.O_NONBLOCK),
                     dir_fd=folder_fd)
    except OSError as error:
        if error.errno in (errno.ENOENT, errno.ELOOP, errno.ENOTDIR, errno.ENXIO):
            bad('changed')  # swapped between the lstat and the open
        raise  # anything else (a permission, an I/O error) is a traceback: the import stops
    held.append(fd)
    st = os.fstat(fd)
    if (st.st_dev, st.st_ino) != (seen.st_dev, seen.st_ino):
        bad('changed')
    return fd, st
def read(fd, st, limit):
    if st.st_size > limit:
        refuse('too_large')
    data = bytearray()
    while chunk := os.read(fd, CHUNK):
        if len(data) + len(chunk) > limit:
            refuse('too_large')  # a growing file: refused before the chunk is kept
        data += chunk
    if len(data) != st.st_size or os.fstat(fd).st_size != st.st_size:
        refuse('changed')
    return data
def main():
    job_id, digest = sys.argv[1], sys.argv[2]
    if not re.fullmatch('[0-9a-f]{32}', job_id) or not re.fullmatch('[0-9a-f]{64}', digest):
        refuse('request')
    root = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY)
    held.append(root)
    jobs, _ = step(root, 'jobs', True, fixed=True)
    fd, st = step(jobs, job_id + '.json', False)
    try:
        job = json.loads(bytes(read(fd, st, LEDGER_LIMIT)))
    except ValueError:
        refuse('record')
    if not isinstance(job, dict) or job.get('id') != job_id or job.get('state') != 'succeeded' \
            or not isinstance(job.get('output'), str):
        refuse('record')
    parts = job['output'].split('/')
    if parts[0] == '':
        parts = parts[1:]  # the API records '/<file>' when the engine's subfolder is empty
    if not 0 < len(parts) <= 8 or not parts[-1].endswith('.mp4') \
            or not all(re.fullmatch('[A-Za-z0-9_][A-Za-z0-9._-]{0,254}', part) for part in parts):
        refuse('outside')
    size = job.get('bytes')
    fd, _ = step(root, 'output', True, fixed=True)
    for part in parts[:-1]:
        fd, _ = step(fd, part, True)
    fd, st = step(fd, parts[-1], False)
    if st.st_nlink != 1:
        refuse('hard_link')
    if isinstance(size, int) and not isinstance(size, bool) and size != st.st_size:
        refuse('size_mismatch')
    data = read(fd, st, LIMIT)
    if os.fstat(fd).st_nlink != 1:
        refuse('changed')
    if hashlib.sha256(data).hexdigest() != digest:
        refuse('hash_mismatch')
    sys.stdout.buffer.write(bytes(data))
try:
    main()
finally:
    for fd in held:
        os.close(fd)
