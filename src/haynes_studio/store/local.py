"""The ``local`` store adapter: the D39 layout on a local file system, for the CLI and
tests (contract section 8). The installed store (NFS blobs, Postgres ledger, story
434) shares the publication algorithm; this module is not it.

One file is published exactly as section 8 lists it, and the store calls ``on_step``
after each step so a test can inject a failure there:

====  ===================================================================  ==========
Step  Section 8                                                            ``on_step``
====  ===================================================================  ==========
1     open ``.staging/<random>.part`` with ``O_CREAT | O_EXCL``            ``open``
1     stream the bytes while hashing                                       ``write``
2     ``fsync``                                                            ``fsync``
2     check size and hash (and the expected hash, if the caller gave one)  ``check``
3     ``link()`` to the final path; on ``EEXIST`` re-hash the existing     ``link``
      file: equal is success, different is ``store.collision``
4     unlink the staging file                                              ``unlink``
4     ``fsync`` the directories                                            ``fsync_dir``
====  ===================================================================  ==========

``on_step`` receives ``"<what>:<step>"``, where ``what`` is ``blob`` or ``record``.

Never ``rename()`` over a path; never open a final path for writing (every final path
is opened ``O_RDONLY | O_NOFOLLOW``); never delete, truncate or overwrite. The only
``unlink`` is step 4's, of this store's own staging file once the final path holds its
bytes. A failed or interrupted attempt leaves its staging file for :meth:`doctor` to
report (D17).
"""

from __future__ import annotations

import errno
import hashlib
import io
import os
import secrets
import stat
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, BinaryIO

from haynes_studio.store.base import (
    MISMATCH,
    MISSING,
    PRESENT,
    Source,
    StageLedger,
    Store,
    check_source,
)
from haynes_studio.store.errors import (
    BLOB_MISSING,
    COLLISION,
    HASH_MISMATCH,
    LOCATOR_INVALID,
    RECORD_INVALID,
    StoreError,
)
from haynes_studio.store.layout import (
    PART,
    PROBE,
    SHA256_DIR,
    STAGING,
    extension,
    is_locator,
    is_sha256,
    parse_locator,
    parse_record_path,
    record_path,
    scope_prefix,
)
from haynes_studio.store.records import Blob, StageRecord

CHUNK = 1 << 20
# O_NONBLOCK so a FIFO planted at a final path cannot block the open; it does not
# change reads of a regular file.
_READ = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
_ABSENT, _NOT_REGULAR = "absent", "not a regular file"
_CREATE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
# Proposal: published files are read-only (0444), so nothing can reopen one for writing
# by accident. The staging file is created with that mode; its descriptor stays writable.
FILE_MODE = 0o444
DIR_MODE = 0o755

Step = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class _Staged:
    path: str  # absolute path of the staging file
    sha256: str
    size: int


@dataclass(frozen=True)
class DoctorReport:
    """What ``store doctor`` found. It reads only: it removes, moves and repairs
    nothing (D17); removing a leftover is a user action.

    - ``orphans``: blob locators no completed stage record lists and the caller did
      not name as referenced (harmless, section 8).
    - ``staging``: files under ``.staging/`` (an interrupted, refused or in-progress
      publication: check a file's age before removing it).
    - ``unexpected``: paths in the store that are not part of the layout (including
      symbolic links).
    - ``broken_records``: record files that do not read as a stage record, with why.
    - ``dangling``: ``(record path, locator)`` where a record names a missing blob.
      Publication order makes this impossible; it is reported if it ever happens.
    - ``unreadable``: ``(folder, reason)`` for a folder the doctor could not list.

    Only files and links are listed; an empty folder outside the layout is not.
    """

    blobs: int = 0
    records: int = 0
    orphans: tuple[str, ...] = ()
    staging: tuple[str, ...] = ()
    unexpected: tuple[str, ...] = ()
    broken_records: tuple[tuple[str, str], ...] = ()
    dangling: tuple[tuple[str, str], ...] = ()
    unreadable: tuple[tuple[str, str], ...] = ()
    referenced: frozenset[str] = field(default=frozenset(), repr=False)

    @property
    def clean(self) -> bool:
        return not (self.orphans or self.staging or self.unexpected or self.broken_records
                    or self.dangling or self.unreadable)

    def to_document(self) -> dict[str, Any]:
        return {"blobs": self.blobs, "records": self.records, "orphans": list(self.orphans),
                "staging": list(self.staging), "unexpected": list(self.unexpected),
                "broken_records": [list(item) for item in self.broken_records],
                "dangling": [list(item) for item in self.dangling],
                "unreadable": [list(item) for item in self.unreadable]}


class LocalStore(Store, StageLedger):
    """The D39 layout under ``root``, an existing directory the caller names. The store
    creates ``.staging/`` and the layout's folders as it needs them, and nothing
    outside ``root``. ``on_step`` (tests only) is called after each publication step."""

    def __init__(self, root: str | os.PathLike[str], *, on_step: Step | None = None,
                 chunk_size: int = CHUNK):
        root = os.path.abspath(os.fspath(root))
        if not stat.S_ISDIR(os.stat(root).st_mode):
            raise NotADirectoryError(root)
        self.root = root
        self._on_step = on_step
        self._chunk = chunk_size

    def __repr__(self) -> str:
        return f"LocalStore({self.root!r})"

    # Blobs ---------------------------------------------------------------------------

    def publish(self, source: Source, *, scope: str, media_type: str,
                expected_sha256: str | None = None) -> Blob:
        prefix, ext = scope_prefix(scope), extension(media_type)  # refuse before any write
        if expected_sha256 is not None and not is_sha256(expected_sha256):
            raise StoreError(LOCATOR_INVALID, "expected_sha256 must be 64 lower-case hex "
                             f"digits, got {expected_sha256!r}")
        staged = self._publish(_chunks(source, self._chunk), expected_sha256, "blob",
                               lambda sha: f"{prefix}/{SHA256_DIR}/{sha[:2]}/{sha}.{ext}")
        return Blob(sha256=staged.sha256, bytes=staged.size, media_type=media_type,
                    locator=f"{prefix}/{SHA256_DIR}/{staged.sha256[:2]}/{staged.sha256}.{ext}")

    def verify(self, locator: str, sha256: str) -> str:
        parse_locator(locator)
        if not is_sha256(sha256):
            raise StoreError(LOCATOR_INVALID, f"sha256 must be 64 lower-case hex digits, got {sha256!r}")
        found = self._hash_existing(locator)
        if found is None:
            return MISSING
        return PRESENT if found[0] == sha256 else MISMATCH

    def open(self, locator: str) -> BinaryIO:
        parse_locator(locator)
        handle = self._open_read(locator)
        if isinstance(handle, str):
            raise StoreError(BLOB_MISSING, f"no blob at this locator ({handle})", locator=locator)
        return handle

    # Stage records -------------------------------------------------------------------

    def complete_stage(self, record: StageRecord) -> StageRecord:
        """Publish the record create-only, after checking every blob it lists is a
        published regular file of its size (``store.blob_missing`` otherwise, and no
        record is written). Same bytes again succeed; other bytes are
        ``store.collision`` and the finished record is left as it was."""
        for name, blob in record.blobs.items():
            if not self._is_file_of_size(blob.locator, blob.bytes):
                raise StoreError(BLOB_MISSING, f"output {name!r} is not published; the "
                                 "record would name a missing blob", locator=blob.locator)
        path = record_path(record.production_id, record.run_id, record.stage)
        data = record.encode()
        self._publish(_chunks(data, self._chunk), hashlib.sha256(data).hexdigest(), "record",
                      lambda sha: path)
        return record

    def stage_record(self, production_id: str, run_id: str, stage: str) -> StageRecord | None:
        path = record_path(production_id, run_id, stage)
        data = self._read(path)
        if data is None:
            return None
        record = StageRecord.decode(data, source=path)
        if (record.production_id, record.run_id, record.stage) != (production_id, run_id, stage):
            raise StoreError(RECORD_INVALID, "the record names another stage than its path",
                             locator=path)
        return record

    # Doctor --------------------------------------------------------------------------

    def doctor(self, *, referenced: Iterable[str] = ()) -> DoctorReport:
        """A read-only report of orphan blobs, staging leftovers and anything else that
        is not the layout. ``referenced`` names locators known elsewhere (asset
        versions, run snapshots), which are then not orphans. Deletes nothing."""
        blobs: set[str] = set()
        staging, unexpected, broken, dangling, unreadable = [], [], [], [], []
        from_records: set[str] = set()
        records = 0
        for rel, entry in self._walk(unreadable):
            if rel.startswith(STAGING + "/"):
                staging.append(rel)
            elif rel.startswith(PROBE + "/"):
                continue  # the NFS adapter's start-up probe area (story 434)
            elif not entry.is_file(follow_symlinks=False):
                unexpected.append(rel)  # a symbolic link or other special file
            elif is_locator(rel):
                blobs.add(rel)
            elif parse_record_path(rel) is not None:
                records += 1
                try:
                    record = self.stage_record(*parse_record_path(rel))  # type: ignore[misc]
                except StoreError as error:
                    broken.append((rel, error.message))
                    continue
                except OSError as error:
                    broken.append((rel, error.strerror or type(error).__name__))
                    continue
                for blob in (record.blobs.values() if record else ()):
                    from_records.add(blob.locator)
            else:
                unexpected.append(rel)
        for rel in sorted(from_records - blobs):
            dangling.extend((path, rel) for path in self._records_naming(rel))
        known = from_records | set(referenced)
        return DoctorReport(blobs=len(blobs), records=records,
                            orphans=tuple(sorted(blobs - known)), staging=tuple(sorted(staging)),
                            unexpected=tuple(sorted(unexpected)), broken_records=tuple(sorted(broken)),
                            dangling=tuple(sorted(dangling)), unreadable=tuple(sorted(unreadable)),
                            referenced=frozenset(known))

    # The four steps ------------------------------------------------------------------

    def _publish(self, chunks: _Chunks, expected: str | None, what: str,
                 final_for: Callable[[str], str]) -> _Staged:
        try:
            fd, path = self._open_staging(what)  # step 1
        except BaseException:
            _close(chunks)
            raise
        try:
            staged = self._stream(fd, path, chunks, what)  # step 1
            self._sync_and_check(fd, staged, expected, what)  # step 2
        finally:
            os.close(fd)
            _close(chunks)
        final_dir = self._link(staged, final_for(staged.sha256), what)  # step 3
        self._finish(staged, final_dir, what)  # step 4
        return staged

    def _step(self, what: str, step: str) -> None:
        if self._on_step is not None:
            self._on_step(f"{what}:{step}")

    def _open_staging(self, what: str) -> tuple[int, str]:
        """Step 1: open ``.staging/<random>.part`` with ``O_CREAT | O_EXCL``."""
        path = os.path.join(self._ensure_dir(STAGING), secrets.token_hex(16) + PART)
        fd = os.open(path, _CREATE, FILE_MODE)
        try:
            self._step(what, "open")
        except BaseException:
            os.close(fd)
            raise
        return fd, path

    def _stream(self, fd: int, path: str, chunks: _Chunks, what: str) -> _Staged:
        """Step 1: stream the bytes into the staging file while hashing."""
        digest, size = hashlib.sha256(), 0
        for chunk in chunks:
            view = memoryview(chunk)
            while view:
                view = view[os.write(fd, view):]
            digest.update(chunk)
            size += len(chunk)
        self._step(what, "write")
        return _Staged(path=path, sha256=digest.hexdigest(), size=size)

    def _sync_and_check(self, fd: int, staged: _Staged, expected: str | None, what: str) -> None:
        """Step 2: ``fsync``; then re-read the staging file and check its size and hash
        against what was streamed, and against ``expected`` when the caller gave one."""
        os.fsync(fd)
        self._step(what, "fsync")
        found = self._hash_existing(self._rel(staged.path))
        if found != (staged.sha256, staged.size) or os.fstat(fd).st_size != staged.size:
            raise StoreError(HASH_MISMATCH, "the staging file does not read back as the bytes "
                             "written", locator=self._rel(staged.path))
        if expected is not None and staged.sha256 != expected:
            raise StoreError(HASH_MISMATCH, f"the bytes hash to {staged.sha256}, not the "
                             f"expected {expected}", locator=self._rel(staged.path))
        self._step(what, "check")

    def _link(self, staged: _Staged, final_rel: str, what: str) -> str:
        """Step 3: ``link()`` the staging file to the final path; on ``EEXIST`` re-hash
        the existing file. Returns the final directory."""
        final_dir = self._ensure_dir(os.path.dirname(final_rel))
        final = os.path.join(self.root, final_rel)
        try:
            os.link(staged.path, final, follow_symlinks=False)
        except FileExistsError:
            if self._hash_existing(final_rel) != (staged.sha256, staged.size):
                raise StoreError(COLLISION, "other bytes are already published at this path; "
                                 "nothing was overwritten", locator=final_rel) from None
        self._step(what, "link")
        return final_dir

    def _finish(self, staged: _Staged, final_dir: str, what: str) -> None:
        """Step 4: unlink this store's own staging file (the final path holds its
        bytes), then ``fsync`` the final and staging directories."""
        os.unlink(staged.path)
        self._step(what, "unlink")
        _fsync_dir(final_dir)
        _fsync_dir(os.path.dirname(staged.path))
        self._step(what, "fsync_dir")

    # Helpers -------------------------------------------------------------------------

    def _abs(self, rel: str) -> str:
        return os.path.join(self.root, rel)

    def _rel(self, path: str) -> str:
        return os.path.relpath(path, self.root)

    def _ensure_dir(self, rel: str) -> str:
        """Create each missing folder of ``rel`` under the root and ``fsync`` the
        parent of every folder on the way, also one another writer made (its entry
        may not be durable yet). Something else where a folder belongs (a file, a
        symbolic link) is ``store.collision``."""
        current = self.root
        for part in rel.split("/"):
            parent, current = current, os.path.join(current, part)
            try:
                os.mkdir(current, DIR_MODE)
            except FileExistsError:
                if not stat.S_ISDIR(os.lstat(current).st_mode):
                    raise StoreError(COLLISION, "something other than a folder holds a store "
                                     "folder's path", locator=self._rel(current)) from None
            _fsync_dir(parent)
        return current

    def _hash_existing(self, rel: str) -> tuple[str, int] | None:
        """``(sha256, size)`` of the regular file at ``rel``, read-only and without
        following a symbolic link; ``None`` if there is no file; ``("", -1)`` for
        something that is not a regular file."""
        handle = self._open_read(rel)
        if handle == _ABSENT:
            return None
        if isinstance(handle, str):
            return ("", -1)
        digest, size = hashlib.sha256(), 0
        with handle:
            while chunk := handle.read(self._chunk):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size

    def _is_file_of_size(self, rel: str, size: int) -> bool:
        handle = self._open_read(rel)
        if isinstance(handle, str):
            return False
        with handle:
            return os.fstat(handle.fileno()).st_size == size

    def _read(self, rel: str) -> bytes | None:
        handle = self._open_read(rel)
        if handle == _ABSENT:
            return None
        if isinstance(handle, str):
            raise StoreError(RECORD_INVALID, handle, locator=rel)
        with handle:
            return handle.read()

    def _open_read(self, rel: str) -> BinaryIO | str:
        """The regular file at ``rel`` under the root, opened read-only, or
        :data:`_ABSENT` or :data:`_NOT_REGULAR`. Each folder on the way is opened
        relative to the last with ``O_NOFOLLOW``, so no symbolic link anywhere in the
        path is followed out of the store. Never opens anything for writing."""
        parts = rel.split("/")
        folder = os.open(self.root, _DIR)
        try:
            for part in parts[:-1]:
                try:
                    inner = os.open(part, _DIR | os.O_NOFOLLOW, dir_fd=folder)
                except FileNotFoundError:
                    return _ABSENT
                except OSError as error:
                    if error.errno in (errno.ELOOP, errno.ENOTDIR):
                        return _NOT_REGULAR  # a link or a file where a folder belongs
                    raise
                os.close(folder)
                folder = inner
            try:
                fd = os.open(parts[-1], _READ, dir_fd=folder)
            except FileNotFoundError:
                return _ABSENT
            except OSError as error:
                if error.errno in (errno.ELOOP, errno.ENXIO, errno.ENOTDIR):
                    return _NOT_REGULAR  # a link, a socket, or a folder in the way
                raise
        finally:
            os.close(folder)
        try:
            regular = stat.S_ISREG(os.fstat(fd).st_mode)
        except BaseException:
            os.close(fd)
            raise
        if not regular:
            os.close(fd)
            return _NOT_REGULAR
        return os.fdopen(fd, "rb")

    def _walk(self, unreadable: list[tuple[str, str]] | None = None
              ) -> Iterator[tuple[str, os.DirEntry[str]]]:
        """Every entry under the root that is not a directory (symbolic links
        included, never followed), as ``(relative path, entry)``, sorted. A folder
        that cannot be listed goes to ``unreadable`` with the reason."""
        stack = [self.root]
        while stack:
            current = stack.pop()
            try:
                with os.scandir(current) as entries:
                    listed = sorted(entries, key=lambda entry: entry.name)
            except OSError as error:
                if unreadable is not None:
                    unreadable.append((self._rel(current).replace(os.sep, "/"),
                                       error.strerror or type(error).__name__))
                continue
            for entry in listed:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
                else:
                    yield self._rel(entry.path).replace(os.sep, "/"), entry

    def _records_naming(self, locator: str) -> list[str]:
        out = []
        for rel, _entry in self._walk():
            ids = parse_record_path(rel)
            if ids is None:
                continue
            try:
                record = self.stage_record(*ids)
            except (StoreError, OSError):
                continue
            if record and any(blob.locator == locator for blob in record.blobs.values()):
                out.append(rel)
        return out


def _fsync_dir(path: str) -> None:
    fd = os.open(path, _DIR)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class _Chunks:
    """An iterator of byte chunks that closes the file it opened when closed, even
    if iteration never started."""

    def __init__(self, read: Callable[[int], Any], size: int, handle: BinaryIO | None = None):
        self._read, self._size, self._handle = read, size, handle

    def __iter__(self) -> Iterator[bytes]:
        while chunk := self._read(self._size):
            if not isinstance(chunk, bytes | bytearray):
                raise TypeError("a file object to publish must be opened in binary mode")
            yield bytes(chunk)

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()


def _chunks(source: Source, size: int) -> _Chunks:
    """The source's bytes in chunks: bytes-like, a path (``os.PathLike``, opened
    read-only here, before any staging file exists) or a binary file object."""
    check_source(source)
    if isinstance(source, bytes | bytearray | memoryview):
        data = io.BytesIO(memoryview(source).cast("B"))
        return _Chunks(data.read, size)
    if isinstance(source, os.PathLike):
        handle = open(os.fspath(source), "rb")  # noqa: SIM115 (closed by _Chunks.close)
        return _Chunks(handle.read, size, handle)
    return _Chunks(source.read, size)  # type: ignore[union-attr]


def _close(chunks: _Chunks) -> None:
    chunks.close()


__all__ = ["DoctorReport", "LocalStore"]
