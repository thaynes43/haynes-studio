"""Shared helpers for the store and stage tests: IDs, a tree snapshot and a fault
injector. Every store root is under pytest's ``tmp_path``."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable
from pathlib import Path

PRD = "prd_01M79V9FC00000000000000001"
PRD_OTHER = "prd_01M79V9FC00000000000000002"
RUN = "run_01M79V9FC00000000000000001"
STEPS = ("open", "write", "fsync", "check", "link", "unlink", "fsync_dir")


class InjectedFault(Exception):
    """Raised from ``on_step`` to stand for a crash at that point."""


class FailAt:
    """``on_step`` that raises :class:`InjectedFault` at the ``index``-th call (or the
    first call named ``step``), and records every call."""

    def __init__(self, index: int | None = None, step: str | None = None):
        self.index, self.step, self.calls = index, step, []

    def __call__(self, name: str) -> None:
        self.calls.append(name)
        if (self.index is not None and len(self.calls) - 1 == self.index) or name == self.step:
            raise InjectedFault(name)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree(root: Path) -> dict[str, tuple]:
    """Every path under ``root`` with its type, inode, mode, size, mtime and (for a
    regular file) content hash: any change to the store shows up here."""
    out = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        content = sha(path.read_bytes()) if path.is_file() and not path.is_symlink() else None
        out[path.relative_to(root).as_posix()] = (
            "link" if path.is_symlink() else "dir" if path.is_dir() else "file",
            info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, content)
    return out


def files(root: Path, prefix: str) -> list[str]:
    base = root / prefix
    if not base.exists():
        return []
    return sorted(p.relative_to(root).as_posix() for p in base.rglob("*") if p.is_file())


def plant(root: Path, rel: str, data: bytes) -> Path:
    """Write a file directly into a store, as a foreign writer or disk damage would."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def blob_files(root: Path) -> Iterable[Path]:
    for base in ("library", "productions"):
        if (root / base).exists():
            yield from (p for p in (root / base).rglob("*")
                        if p.is_file() and "/sha256/" in p.as_posix())


def assert_every_blob_is_its_hash(root: Path) -> None:
    """No final blob file holds bytes other than its name says."""
    for path in blob_files(root):
        assert sha(path.read_bytes()) == path.stem, f"{path} does not hold its hash"
        assert not os.access(path, os.W_OK) or os.geteuid() == 0, f"{path} is writable"
