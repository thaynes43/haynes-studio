import hashlib, os, re, stat, sys
# Read-only (story 846): prints the bytes of one E0 upload, /workspace/input/studio-e0/<name>, whose
# name is the first 16 hex digits of its sha256 and .png or .wav (poc/wan.py, poc/s2v.py). Every folder
# below /workspace is opened with O_NOFOLLOW | O_DIRECTORY relative to the one above, after an lstat;
# the file is lstat'ed, then opened with O_NOFOLLOW | O_NONBLOCK and checked on that descriptor: a
# regular file with one link and at most LIMIT bytes, the same inode the lstat saw, read to the end
# from the descriptor and hashed. No link is followed below /workspace. Nothing is opened for writing.
# A refusal is one line, REFUSED <reason>, on stderr and exit status 3, with nothing on stdout.
ROOT = '/workspace'
LIMIT = 20000000
CHUNK = 1048576
held = []
def refuse(reason):
    sys.stderr.write('REFUSED ' + reason + '\n')
    raise SystemExit(3)
def step(folder_fd, name, folder):
    try:
        seen = os.stat(name, dir_fd=folder_fd, follow_symlinks=False)
    except FileNotFoundError:
        refuse('missing')
    if stat.S_ISLNK(seen.st_mode):
        refuse('link')
    if not (stat.S_ISDIR(seen.st_mode) if folder else stat.S_ISREG(seen.st_mode)):
        refuse('not_regular')
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | (os.O_DIRECTORY if folder else os.O_NONBLOCK),
                     dir_fd=folder_fd)
    except OSError:
        refuse('changed')
    held.append(fd)
    st = os.fstat(fd)
    if (st.st_dev, st.st_ino) != (seen.st_dev, seen.st_ino):
        refuse('changed')
    return fd, st
def main():
    name, digest = sys.argv[1], sys.argv[2]
    if not re.fullmatch('[0-9a-f]{64}', digest) or not re.fullmatch('[0-9a-f]{16}[.](png|wav)', name) \
            or name[:16] != digest[:16]:
        refuse('request')
    fd = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY)
    held.append(fd)
    for part in ('input', 'studio-e0'):
        fd, _ = step(fd, part, True)
    fd, st = step(fd, name, False)
    if st.st_nlink != 1:
        refuse('hard_link')
    if st.st_size > LIMIT:
        refuse('too_large')
    data = bytearray()
    while chunk := os.read(fd, CHUNK):
        data += chunk
        if len(data) > LIMIT:
            refuse('too_large')
    after = os.fstat(fd)
    if len(data) != st.st_size or after.st_size != st.st_size or after.st_nlink != 1:
        refuse('changed')
    if hashlib.sha256(data).hexdigest() != digest:
        refuse('hash_mismatch')
    sys.stdout.buffer.write(bytes(data))
try:
    main()
finally:
    for fd in held:
        os.close(fd)
