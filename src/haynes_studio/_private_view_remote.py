"""Fixed, standard-library-only programs for private viewing, run with separate argv.

This file is also sent verbatim to the Wan API container; it imports no studio code.
No cleanup deletes a name. Media use anonymous temporary inodes; the staged ledger
remains as recovery evidence. Linux O_TMPFILE/linkat/renameat2 are required.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import stat
import sys
import urllib.request
import uuid
from contextlib import ExitStack

JOB = re.compile(r"[a-z0-9][a-z0-9-]{2,63}")
LEDGER = re.compile(r"[0-9a-f]{32}")
NAMES = ("final.mp4", "proxy.mp4", "run.json", "delivery.json")
DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


def check_ledger(document):
    """poc/deliver.py's route check, with explicit exceptions (also under -O)."""
    if not LEDGER.fullmatch(document["id"]):
        raise ValueError("invalid ledger id")
    if document["state"] != "succeeded" or document["kind"] != "edited_production":
        raise ValueError("invalid ledger state or kind")
    output = document["output"]
    if not output.endswith(".mp4") or output.startswith("/") or ".." in output:
        raise ValueError("invalid ledger output")
    for key in ("title", "story", "assets", "bytes", "sha256", "created_at", "finished_at",
                "telemetry", "preset", "provenance"):
        if key not in document:
            raise ValueError("missing ledger field: " + key)
    json.dumps(document, allow_nan=False)


def identity(fd):
    info = os.fstat(fd)
    return [info.st_dev, info.st_ino]


def check_new_folder(fd):
    if os.fstat(fd).st_uid != os.geteuid() or os.listdir(fd):
        raise ValueError("new directory must be empty and owned by the effective uid")


def digest_file(fd):
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("not a regular file")
    digest, size = hashlib.sha256(), 0
    while chunk := os.read(fd, 1 << 20):
        digest.update(chunk)
        size += len(chunk)
    after = os.fstat(fd)
    if any(getattr(before, k) != getattr(after, k) for k in
           ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")):
        raise ValueError("file changed while hashing")
    return {"bytes": size, "sha256": digest.hexdigest()}


def absent(parent, name):
    try:
        os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise FileExistsError("name already exists: " + name)


def open_dirs(stack, root, request, *, job=False, rollback=False):
    def take(path, parent=None):
        fd = os.open(path, DIR, dir_fd=parent)
        stack.callback(os.close, fd)
        return fd
    # Traverse root itself by descriptor too: no symlink in /workspace's parents.
    root_fd = take("/")
    for component in root.strip("/").split("/"):
        root_fd = take(component, root_fd)
    fds = {"root": root_fd, "jobs": take("jobs", root_fd)}
    if not rollback:
        fds["output"] = take("output", root_fd)
        fds["productions"] = take("productions", fds["output"])
        if job:
            fds["job"] = take(request["job"], fds["productions"])
    expected = request.get("identities", {})
    for key, fd in fds.items():
        if key in expected and identity(fd) != expected[key]:
            raise ValueError("directory identity changed: " + key)
    return fds


def check_namespace(root, request, *, job=True):
    with ExitStack() as stack:
        open_dirs(stack, root, request, job=job)


def verify_files(folder, files):
    if set(files) != set(NAMES):
        raise ValueError("expected exactly four delivery files")
    for name in NAMES:
        fd = os.open(name, FILE, dir_fd=folder)
        try:
            if digest_file(fd) != files[name]:
                raise ValueError("final file does not match: " + name)
        finally:
            os.close(fd)


def check_ledger_files(ledger, job, files):
    outputs = {"productions/" + job + "/" + name: files[name] for name in NAMES[:2]}
    if outputs.get(ledger["output"]) != {k: ledger[k] for k in ("bytes", "sha256")}:
        raise ValueError("ledger output does not match this job's verified media")
    assets = {"/workspace/output/productions/" + job + "/" + name: files[name]
              for name in NAMES}
    for asset in ledger["assets"]:
        if assets.get(asset["path"]) != {k: asset[k] for k in ("bytes", "sha256")}:
            raise ValueError("ledger asset does not match this job's verified files")


def fill_temp(fd, source, expected):
    with os.fdopen(os.dup(fd), "wb") as target:
        while chunk := source.read(1 << 20):
            target.write(chunk)
        target.flush()
        os.fsync(target.fileno())
    os.lseek(fd, 0, os.SEEK_SET)
    if digest_file(fd) != expected:
        raise ValueError("temporary file hash/size mismatch")


def write_temp(folder, source, expected):
    name = ".private-view-" + uuid.uuid4().hex + ".tmp"
    fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600,
                 dir_fd=folder)
    try:
        fill_temp(fd, source, expected)
        named = os.stat(name, dir_fd=folder, follow_symlinks=False)
        if [named.st_dev, named.st_ino] != identity(fd):
            raise ValueError("temporary file identity changed")
        return name, identity(fd)
    finally:
        os.close(fd)


def link_fd(source_fd, target_dir, name):
    """Exclusive link from a held descriptor, without CAP_DAC_READ_SEARCH.

    /proc/self/fd is the kernel's own descriptor reference, not a path in the
    production namespace. No user-controlled symlink or source name is followed.
    """
    libc = ctypes.CDLL(None, use_errno=True)
    link = libc.linkat
    link.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    link.restype = ctypes.c_int
    source = os.fsencode("/proc/self/fd/" + str(source_fd))
    if link(-100, source, target_dir, os.fsencode(name), 0x400) != 0:  # AT_SYMLINK_FOLLOW
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def rename_only(source_dir, source, target_dir, target):
    """Linux same-volume rename with RENAME_NOREPLACE; never overwrite a name."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
                       ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(source_dir, os.fsencode(source), target_dir, os.fsencode(target), 1) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def perform(action, root, request):
    if not JOB.fullmatch(request["job"]) or not LEDGER.fullmatch(request["id"]):
        raise ValueError("invalid job or ledger id")
    with ExitStack() as stack:
        fds = open_dirs(stack, root, request, job=action in ("copy", "prepare", "link", "verify"),
                        rollback=action == "withdraw")
        jobs = fds["jobs"]
        served = request["id"] + ".json"
        recovery = ".private-view-" + request["id"]
        if action in ("preflight", "reserve"):
            usage = os.fstatvfs(fds["root"])
            free = usage.f_bavail * usage.f_frsize
            if free <= request["need"] * 10:
                raise ValueError("less than ten times the delivery size free")
            absent(fds["productions"], request["job"])
            absent(jobs, served)
            absent(jobs, recovery)
            if action == "reserve":
                os.mkdir(request["job"], 0o755, dir_fd=fds["productions"])
                fds["job"] = os.open(request["job"], DIR, dir_fd=fds["productions"])
                stack.callback(os.close, fds["job"])
                check_new_folder(fds["job"])
            return {"free": free, "identities": {k: identity(v) for k, v in fds.items()}}
        if action == "copy":
            name = request["name"]
            if name not in NAMES:
                raise ValueError("invalid delivery filename")
            absent(fds["job"], name)
            fd = os.open(".", os.O_TMPFILE | os.O_RDWR | os.O_NOFOLLOW, 0o600,
                         dir_fd=fds["job"])
            try:
                os.fchmod(fd, 0o644)
                fill_temp(fd, sys.stdin.buffer, request["files"][name])
                check_namespace(root, request)
                link_fd(fd, fds["job"], name)
            finally:
                os.close(fd)
            check_namespace(root, request)
            return {"copied": name}
        if action == "verify":
            verify_files(fds["job"], request["files"])
            check_namespace(root, request)
            return {"verified": True}
        if action == "prepare":
            # Own a separate unserved folder, usable even if the production moves.
            os.mkdir(recovery, 0o700, dir_fd=jobs)
            folder = os.open(recovery, DIR, dir_fd=jobs)
            stack.callback(os.close, folder)
            check_new_folder(folder)
            os.fchmod(folder, 0o700)
            expected = request["ledger_file"]
            temp, inode = write_temp(folder, sys.stdin.buffer, expected)
            return {"folder": identity(folder), "temp": temp, "inode": inode, **expected}
        receipt = request["receipt"]
        folder = os.open(recovery, DIR, dir_fd=jobs)
        stack.callback(os.close, folder)
        if identity(folder) != receipt["folder"]:
            raise ValueError("recovery directory identity changed")
        if action == "link":
            fd = os.open(receipt["temp"], FILE, dir_fd=folder)
            try:
                if identity(fd) != receipt["inode"] or digest_file(fd) != request["ledger_file"]:
                    raise ValueError("staged ledger changed")
                os.lseek(fd, 0, os.SEEK_SET)
                with os.fdopen(os.dup(fd), "rb") as source:
                    ledger = json.load(source)
                check_ledger(ledger)
                if ledger != request["ledger"]:
                    raise ValueError("staged ledger is another document")
                verify_files(fds["job"], request["files"])
                check_ledger_files(ledger, request["job"], request["files"])
                os.fchmod(fd, 0o644)
                check_namespace(root, request)
                link_fd(fd, jobs, served)
            finally:
                os.close(fd)
            check_namespace(root, request)
            return {"linked": served}
        if action == "withdraw":
            try:
                fd = os.open(served, FILE, dir_fd=jobs)
            except FileNotFoundError:
                return {"withdrawn": False, "reason": "no served ledger"}
            try:
                # Content corruption is itself a reason to withdraw our inode.
                # A hash mismatch must not leave that ledger under a served name.
                if identity(fd) != receipt["inode"]:
                    raise ValueError("served name is not this attempt's ledger; left untouched")
            finally:
                os.close(fd)
            # Identity checked immediately before the same-volume rename.
            named = os.stat(served, dir_fd=jobs, follow_symlinks=False)
            if [named.st_dev, named.st_ino] != receipt["inode"]:
                raise ValueError("served ledger identity changed; left untouched")
            rename_only(jobs, served, folder, "withdrawn")
            moved = os.stat("withdrawn", dir_fd=folder, follow_symlinks=False)
            if [moved.st_dev, moved.st_ino] != receipt["inode"]:
                try:
                    rename_only(folder, "withdrawn", jobs, served)
                except OSError as error:
                    raise ValueError("withdrawal moved a replacement ledger; could not restore "
                                     "served name; retained at " + recovery + "/withdrawn: "
                                     + str(error)) from error
                raise ValueError("withdrawal moved a replacement ledger; restored to served name")
            return {"withdrawn": True, "path": "/workspace/jobs/" + recovery + "/withdrawn"}
        raise ValueError("unknown action")


def fetch(ledger_id):
    if not LEDGER.fullmatch(ledger_id):
        raise ValueError("invalid ledger id")
    with urllib.request.urlopen("http://127.0.0.1:8080/videos/" + ledger_id + "/file",
                                timeout=240) as response:
        digest, size = hashlib.sha256(), 0
        while chunk := response.read(1 << 20):
            digest.update(chunk)
            size += len(chunk)
        return {"status": response.status, "content_type": response.headers.get("Content-Type"),
                "bytes": size, "sha256": digest.hexdigest()}


if __name__ == "__main__":
    action, root, raw = sys.argv[1:]
    request = json.loads(raw)
    result = fetch(request["id"]) if action == "fetch" else perform(action, root, request)
    print(json.dumps(result, allow_nan=False))
