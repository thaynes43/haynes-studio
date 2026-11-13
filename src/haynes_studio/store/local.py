"""The ``local`` store adapter: the D39 layout on a local file system, for the CLI and
tests (contract section 8). The installed store (NFS blobs, Postgres ledger, story
434) shares the publication algorithm; this module is not it. Linux only: it walks
folders with ``openat`` and links through ``/proc/self/fd``.

Every write works on descriptors, as every read does. The root is opened once per
operation and each folder below it is reached one component at a time with
``O_DIRECTORY | O_NOFOLLOW`` (a missing one is made with ``mkdir`` relative to its
parent), so a symbolic link anywhere under the root is refused, never followed. One
file is published exactly as section 8 lists it, and the store calls ``on_step`` after
each step so a test can inject a failure there:

====  ======================================================================  ==========
Step  Section 8, as implemented                                               ``on_step``
====  ======================================================================  ==========
1     create ``<random>.part`` with ``O_CREAT | O_EXCL | O_NOFOLLOW``         ``open``
      relative to the ``.staging`` descriptor; both stay open to the end
1     stream the bytes while hashing; before each write the file's only name  ``write``
      must still be its ``.part`` in the held ``.staging`` (not linked or
      renamed elsewhere) and it must have no write bit
2     ``fsync``                                                               ``fsync``
2     re-read the file through its descriptor (``pread``): size and hash,     ``check``
      and the expected hash when the caller gave one
3     the same name and mode check, re-read the hash, then ``link``           ``link``
      ``/proc/self/fd/<fd>`` (the checked inode, not a name) into the final
      folder's descriptor. On ``EEXIST`` the existing entry is success only
      if it is a regular file of the staged bytes, with no write bit and no
      name outside ``.staging``; else ``store.collision``. Then the final
      path, walked again from the root, must name that inode
4     unlink the staging name through the ``.staging`` descriptor, only if    ``unlink``
      that folder and that name still hold the staging inode; otherwise
      leave it and warn (:class:`StagingLeftoverWarning`)
4     ``fsync`` the final and staging folders                                 ``fsync_dir``
====  ======================================================================  ==========

``on_step`` receives ``"<what>:<step>"``, where ``what`` is ``blob`` or ``record``.

Never ``rename()``; never open a final path for writing (only the staging file is
opened with a write flag; every final path is opened ``O_RDONLY | O_NOFOLLOW``); never
delete, truncate, ``chmod`` or overwrite. The only ``unlink`` is step 4's, of this
publication's own staging name, once the final path holds its inode. A failed or
interrupted attempt leaves its staging file for :meth:`LocalStore.doctor` to report
(D17); nothing tidies it.
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import io
import os
import secrets
import stat
import warnings
from collections import Counter
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
_SUBDIR = _DIR | os.O_NOFOLLOW
_ABSENT, _NOT_REGULAR = "absent", "not a regular file"
# The staging file, and nothing else: created here and read back through the same
# descriptor (pread), so read-write. No O_TRUNC, no O_APPEND.
_CREATE = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
# Proposal: published files are read-only (0444), so nothing can reopen one for writing
# by accident. The staging file is created with that mode; its descriptor stays writable.
FILE_MODE = 0o444
DIR_MODE = 0o755
_WRITE_BITS = 0o222
_PROC_FD = "/proc/self/fd"  # step 3 links the checked inode through this (Linux)

Step = Callable[[str], None]
_Inode = tuple[int, int]  # (st_dev, st_ino)


class StagingLeftoverWarning(UserWarning):
    """A publication succeeded but its staging name was left in place: by step 4 the
    ``.staging`` folder or that name no longer held the publication's own file (another
    writer swapped it). Nothing removes it; ``store doctor`` lists it."""


@dataclass(frozen=True, slots=True)
class _Staged:
    name: str  # the staging file's name inside .staging
    sha256: str
    size: int

    @property
    def rel(self) -> str:
        return f"{STAGING}/{self.name}"


@dataclass(frozen=True)
class DoctorReport:
    """What ``store doctor`` found. It reads only: it removes, moves and repairs
    nothing (D17); removing a leftover is a user action. It re-hashes every blob.

    - ``orphans``: blob locators no completed stage record lists and the caller did
      not name as referenced (harmless, section 8).
    - ``staging``: files under ``.staging/`` (an interrupted, refused or in-progress
      publication: check a file's age before removing it).
    - ``unexpected``: paths in the store that are not part of the layout (including
      symbolic links).
    - ``broken_records``: record files that do not read as a stage record, with why.
    - ``dangling``: ``(record path, locator)`` where a record names a missing blob.
      Publication order makes this impossible; it is reported if it ever happens.
    - ``damaged``: blob locators whose bytes do not hash to the name.
    - ``mismatched``: ``(record path, locator)`` where a record names a blob that is
      there but is not the recorded hash and size.
    - ``foreign``: blob locators and record paths whose file has a write bit, or a
      name outside the store's ``.staging`` (a hard link from a backup or a dedupe
      tool, say). Publishing the same bytes there again is ``store.collision``.
    - ``unreadable``: ``(path, reason)`` for a folder the doctor could not list or a
      blob it could not read.

    Only files and links are listed; an empty folder outside the layout is not.
    """

    blobs: int = 0
    records: int = 0
    orphans: tuple[str, ...] = ()
    staging: tuple[str, ...] = ()
    unexpected: tuple[str, ...] = ()
    broken_records: tuple[tuple[str, str], ...] = ()
    dangling: tuple[tuple[str, str], ...] = ()
    damaged: tuple[str, ...] = ()
    mismatched: tuple[tuple[str, str], ...] = ()
    foreign: tuple[str, ...] = ()
    unreadable: tuple[tuple[str, str], ...] = ()
    referenced: frozenset[str] = field(default=frozenset(), repr=False)

    @property
    def clean(self) -> bool:
        return not (self.orphans or self.staging or self.unexpected or self.broken_records
                    or self.dangling or self.damaged or self.mismatched or self.foreign
                    or self.unreadable)

    def to_document(self) -> dict[str, Any]:
        return {"blobs": self.blobs, "records": self.records, "orphans": list(self.orphans),
                "staging": list(self.staging), "unexpected": list(self.unexpected),
                "broken_records": [list(item) for item in self.broken_records],
                "dangling": [list(item) for item in self.dangling],
                "damaged": list(self.damaged),
                "mismatched": [list(item) for item in self.mismatched],
                "foreign": list(self.foreign),
                "unreadable": [list(item) for item in self.unreadable]}


class LocalStore(Store, StageLedger):
    """The D39 layout under ``root``, an existing directory the caller names. The store
    creates ``.staging/`` and the layout's folders as it needs them, and nothing
    outside ``root``. ``on_step`` (tests only) is called after each publication step."""

    def __init__(self, root: str | os.PathLike[str], *, on_step: Step | None = None,
                 chunk_size: int = CHUNK):
        if type(chunk_size) is not int or chunk_size < 1:  # 0 would read nothing at all
            raise ValueError(f"chunk_size must be a positive integer, got {chunk_size!r}")
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
        """Publish the record create-only, after re-hashing every blob it lists: each
        must be a regular file of its recorded hash and size (``store.blob_missing``
        if absent, ``store.hash_mismatch`` otherwise; no record is written).
        Immediately before the record's ``link`` each blob must still be that file:
        regular, same size, same device and inode. Same record bytes again succeed;
        other bytes are ``store.collision`` and the finished record is left as it was. The
        checks and the record's publication share one root descriptor."""
        path = record_path(record.production_id, record.run_id, record.stage)
        data = record.encode()
        root = os.open(self.root, _DIR)
        try:
            checked = {name: self._check_blob(name, blob, digest=True, root=root)
                       for name, blob in record.blobs.items()}

            def blobs_unchanged() -> None:
                for name, blob in record.blobs.items():
                    try:
                        info = self._lstat(blob.locator, root=root)
                    except OSError as error:
                        raise StoreError(BLOB_MISSING, f"output {name!r} cannot be read after "
                                         f"its check ({_reason(error)}); the store linked no "
                                         "record", locator=blob.locator) from None
                    if info == _ABSENT:
                        raise StoreError(BLOB_MISSING, f"output {name!r} was removed after its "
                                         "check; the store linked no record", locator=blob.locator)
                    if (isinstance(info, str) or not stat.S_ISREG(info.st_mode)
                            or info.st_size != blob.bytes or _inode(info) != checked[name]):
                        raise StoreError(HASH_MISMATCH, f"output {name!r} was replaced after its "
                                         "check; the store linked no record", locator=blob.locator)

            self._publish(_chunks(data, self._chunk), hashlib.sha256(data).hexdigest(), "record",
                          lambda sha: path, before_link=blobs_unchanged, root=root)
        finally:
            os.close(root)
        return record

    def stage_record(self, production_id: str, run_id: str, stage: str, *,
                     verify: bool = True) -> StageRecord | None:
        """The completed stage's record, or ``None`` if it has not completed. Every blob
        it lists must be a regular file of the recorded size (``store.blob_missing`` if
        absent, ``store.hash_mismatch`` otherwise). With ``verify`` (the default) each
        blob is also re-hashed, which reads every listed blob in full; ``verify=False``
        costs one ``fstat`` per blob and does not prove the bytes."""
        record = self._load_record(production_id, run_id, stage)
        if record is not None:
            for name, blob in record.blobs.items():
                self._check_blob(name, blob, digest=verify)
        return record

    # Doctor --------------------------------------------------------------------------

    def doctor(self, *, referenced: Iterable[str] = ()) -> DoctorReport:
        """A read-only report of orphan blobs, staging leftovers, damaged blobs and
        anything else that is not the layout. ``referenced`` names locators known
        elsewhere (asset versions, run snapshots), which are then not orphans. Reads
        every blob in full. Deletes nothing."""
        blobs: set[str] = set()
        staging: list[str] = []
        unexpected: list[str] = []
        broken: list[tuple[str, str]] = []
        unreadable: list[tuple[str, str]] = []
        records: dict[str, StageRecord] = {}
        record_files: list[str] = []
        for rel, regular in self._walk(unreadable):
            if rel.startswith(STAGING + "/"):
                staging.append(rel)
            elif rel.startswith(PROBE + "/"):
                continue  # the NFS adapter's start-up probe area (story 434)
            elif not regular:
                unexpected.append(rel)  # a symbolic link or other special file
            elif is_locator(rel):
                blobs.add(rel)
            elif (ids := parse_record_path(rel)) is not None:
                record_files.append(rel)
                try:
                    record = self._load_record(*ids)
                except StoreError as error:
                    broken.append((rel, error.message))
                    continue
                except OSError as error:
                    broken.append((rel, _reason(error)))
                    continue
                if record is not None:
                    records[rel] = record
            else:
                unexpected.append(rel)
        hashes: dict[str, tuple[str, int]] = {}
        for rel in sorted(blobs):
            try:
                found = self._hash_existing(rel)
            except OSError as error:
                unreadable.append((rel, _reason(error)))
                continue
            if found is not None and found[1] >= 0:
                hashes[rel] = found
        damaged = [rel for rel, (digest, _size) in hashes.items()
                   if digest != parse_locator(rel).sha256]
        dangling: list[tuple[str, str]] = []
        mismatched: list[tuple[str, str]] = []
        from_records: set[str] = set()
        for path, record in records.items():
            for blob in record.blobs.values():
                from_records.add(blob.locator)
                if blob.locator not in blobs:
                    dangling.append((path, blob.locator))
                elif blob.locator in hashes and hashes[blob.locator] != (blob.sha256, blob.bytes):
                    mismatched.append((path, blob.locator))
        known = from_records | set(referenced)
        return DoctorReport(blobs=len(blobs), records=len(record_files),
                            orphans=tuple(sorted(blobs - known)), staging=tuple(sorted(staging)),
                            unexpected=tuple(sorted(unexpected)), broken_records=tuple(sorted(broken)),
                            dangling=tuple(sorted(dangling)), damaged=tuple(sorted(damaged)),
                            mismatched=tuple(sorted(mismatched)),
                            foreign=self._foreign(sorted(blobs) + record_files, staging),
                            unreadable=tuple(sorted(unreadable)), referenced=frozenset(known))

    def _foreign(self, finals: list[str], staging: list[str]) -> tuple[str, ...]:
        """The final files a publication of the same bytes would refuse (see
        :meth:`_adopt`): a write bit, or a name that is not a ``.part`` in ``.staging``."""
        parts: Counter[_Inode] = Counter()
        for rel in staging:
            if rel.endswith(PART) and rel.count("/") == 1:
                with contextlib.suppress(OSError):
                    info = self._lstat(rel)
                    if not isinstance(info, str) and stat.S_ISREG(info.st_mode):
                        parts[_inode(info)] += 1
        foreign = []
        for rel in finals:
            try:
                info = self._lstat(rel)
            except OSError:
                continue
            if isinstance(info, str) or not stat.S_ISREG(info.st_mode):
                continue
            if info.st_mode & _WRITE_BITS or info.st_nlink - 1 > parts[_inode(info)]:
                foreign.append(rel)
        return tuple(sorted(foreign))

    # The four steps ------------------------------------------------------------------

    def _publish(self, chunks: _Chunks, expected: str | None, what: str,
                 final_for: Callable[[str], str], *,
                 before_link: Callable[[], None] | None = None,
                 root: int | None = None) -> _Staged:
        """The four steps, all relative to one root descriptor (``root``, when the
        caller already holds one, else the root opened once here)."""
        with contextlib.ExitStack() as held:
            held.callback(_close, chunks)
            root = _hold(held, os.open(self.root, _DIR) if root is None else os.dup(root))
            staging = _hold(held, self._descend(root, STAGING, create=True))
            fd, name = self._open_staging(held, staging, what)  # step 1
            staged = self._stream(fd, staging, name, chunks, what)  # step 1
            self._sync_and_check(fd, staged, expected, what)  # step 2
            final_rel = final_for(staged.sha256)
            final_dir = _hold(held, self._descend(root, final_rel.rpartition("/")[0], create=True))
            self._link(root, staging, final_dir, fd, staged, final_rel, what, before_link)  # step 3
            self._finish(root, staging, final_dir, fd, staged, what)  # step 4
            return staged

    def _step(self, what: str, step: str) -> None:
        if self._on_step is not None:
            self._on_step(f"{what}:{step}")

    def _open_staging(self, held: contextlib.ExitStack, staging: int, what: str) -> tuple[int, str]:
        """Step 1: create ``<random>.part`` with ``O_CREAT | O_EXCL | O_NOFOLLOW``
        relative to the ``.staging`` descriptor."""
        name = secrets.token_hex(16) + PART
        fd = _hold(held, os.open(name, _CREATE, FILE_MODE, dir_fd=staging))
        self._step(what, "open")
        return fd, name

    def _stream(self, fd: int, staging: int, name: str, chunks: _Chunks, what: str) -> _Staged:
        """Step 1: stream the bytes into the staging file while hashing. Before each
        write the file must still have only its ``.part`` name, so a final name another
        writer gives it (a hard link, a rename) stops the stream at the next write."""
        digest, size = hashlib.sha256(), 0
        for chunk in chunks:
            _require_untouched(fd, staging, name)
            view = memoryview(chunk)
            while view:
                view = view[os.write(fd, view):]
            digest.update(chunk)
            size += len(chunk)
        self._step(what, "write")
        return _Staged(name=name, sha256=digest.hexdigest(), size=size)

    def _sync_and_check(self, fd: int, staged: _Staged, expected: str | None, what: str) -> None:
        """Step 2: ``fsync``; then re-read the staging file through its descriptor and
        check its size and hash against what was streamed, and against ``expected``
        when the caller gave one."""
        os.fsync(fd)
        self._step(what, "fsync")
        if (_read_back(fd, self._chunk) != (staged.sha256, staged.size)
                or os.fstat(fd).st_size != staged.size):
            raise StoreError(HASH_MISMATCH, "the staging file does not read back as the bytes "
                             "written", locator=staged.rel)
        if expected is not None and staged.sha256 != expected:
            raise StoreError(HASH_MISMATCH, f"the bytes hash to {staged.sha256}, not the "
                             f"expected {expected}", locator=staged.rel)
        self._step(what, "check")

    def _link(self, root: int, staging: int, final_dir: int, fd: int, staged: _Staged,
              final_rel: str, what: str, before_link: Callable[[], None] | None) -> None:
        """Step 3: link the checked inode itself (``/proc/self/fd/<fd>``) to the final
        name in the final folder's descriptor; on ``EEXIST``, adopt the existing file
        only if this store could have published it. Then the final path, walked again
        from the root, must name the inode that was checked."""
        folder, _, name = final_rel.rpartition("/")
        _require_untouched(fd, staging, staged.name)
        if _read_back(fd, self._chunk) != (staged.sha256, staged.size):
            raise StoreError(HASH_MISMATCH, "the staging file changed after its check; "
                             "nothing was published", locator=staged.rel)
        source = _proc_path(fd)
        if not self._still_holds(root, folder, final_dir):
            raise StoreError(COLLISION, "the final folder was moved or replaced during the "
                             "publication; nothing was linked", locator=final_rel)
        if before_link is not None:
            before_link()
        try:
            os.link(source, name, dst_dir_fd=final_dir, follow_symlinks=True)
            inode = _inode(os.fstat(fd))
        except FileExistsError:
            inode = self._adopt(root, final_dir, name, final_rel, staged)
        except FileNotFoundError:  # the staging file lost its name, or the folder went
            raise StoreError(COLLISION, "another writer removed the staging file or the final "
                             "folder just before the link; nothing was linked",
                             locator=final_rel) from None
        info = _lstat_at(final_dir, name)
        if (info is None or not stat.S_ISREG(info.st_mode) or _inode(info) != inode
                or not self._still_holds(root, folder, final_dir)):
            raise StoreError(COLLISION, "after the link the final path does not name the "
                             "checked file (another writer replaced it or its folder); "
                             "nothing further was changed", locator=final_rel)
        self._step(what, "link")

    def _adopt(self, root: int, final_dir: int, name: str, final_rel: str,
               staged: _Staged) -> _Inode:
        """``EEXIST``: the existing entry is success only if it is a regular file (not a
        link) holding the staged bytes, with no write bit, and every other name it has
        is a ``.part`` in the store's ``.staging`` folder (this store's own publication
        between its link and its unlink, or one interrupted there). Anything else is
        ``store.collision``; the file is never changed, never ``chmod``-ed."""
        fd = _open_at(final_dir, name)
        if isinstance(fd, str):
            raise _collision(final_rel, "it was removed while being checked" if fd == _ABSENT
                             else "it is not a regular file")
        try:
            found = _read_back(fd, self._chunk)
            staging_names = self._staging_names(root, _inode(os.fstat(fd)))
            info = os.fstat(fd)  # after the count: a .part only ever loses its name
        finally:
            os.close(fd)
        if found != (staged.sha256, staged.size):
            raise _collision(final_rel, "it holds other bytes")
        if info.st_mode & _WRITE_BITS:
            raise _collision(final_rel, f"it is writable (mode {stat.S_IMODE(info.st_mode):o})")
        if info.st_nlink - 1 > staging_names:
            raise _collision(final_rel, "it has a name outside the store's .staging folder")
        return _inode(info)

    def _finish(self, root: int, staging: int, final_dir: int, fd: int, staged: _Staged,
                what: str) -> None:
        """Step 4: unlink the staging name through the ``.staging`` descriptor, only if
        that folder is still the root's ``.staging`` and the name still names this
        publication's inode; then ``fsync`` the final and staging folders."""
        left = None
        if not self._still_holds(root, STAGING, staging):
            left = "the .staging folder was moved or replaced"
        else:
            info = _lstat_at(staging, staged.name)
            if info is not None and _inode(info) != _inode(os.fstat(fd)):
                left = "the name no longer names this publication's staging file"
            elif info is not None:
                try:
                    os.unlink(staged.name, dir_fd=staging)  # the only unlink: its own name
                except FileNotFoundError:
                    pass  # another writer removed the name: nothing is left
                except OSError as error:  # the folder made read-only, say: the link stands
                    left = f"it could not be removed ({_reason(error)})"
        self._step(what, "unlink")
        os.fsync(final_dir)
        os.fsync(staging)
        self._step(what, "fsync_dir")
        if left is not None:
            warnings.warn(StagingLeftoverWarning(
                f"{staged.rel} was left in place: {left}. The publication succeeded; "
                "store doctor lists the leftover."), stacklevel=4)

    # Helpers -------------------------------------------------------------------------

    def _descend(self, root: int, rel: str, *, create: bool) -> int:
        """A new descriptor for the folder ``rel`` below the root descriptor, reached one
        component at a time with ``O_DIRECTORY | O_NOFOLLOW``: a symbolic link is never
        followed. With ``create``, a missing folder is made with ``mkdir`` relative to
        its parent, the parent is ``fsync``ed (also when another writer made the folder:
        its entry may not be durable yet), and a link or a file where a folder belongs
        is ``store.collision``. Without it, the ``OSError`` is raised as it is."""
        parts = rel.split("/") if rel else []
        current = os.dup(root)
        try:
            for index, part in enumerate(parts):
                if create:
                    with contextlib.suppress(FileExistsError):
                        os.mkdir(part, DIR_MODE, dir_fd=current)
                try:
                    inner = os.open(part, _SUBDIR, dir_fd=current)
                except OSError as error:
                    if create and error.errno in (errno.ELOOP, errno.ENOTDIR):
                        raise StoreError(COLLISION, "something other than a folder holds a "
                                         "store folder's path",
                                         locator="/".join(parts[:index + 1])) from None
                    raise
                parent, current = current, inner
                try:
                    if create:
                        os.fsync(parent)
                finally:
                    os.close(parent)
        except BaseException:
            os.close(current)
            raise
        return current

    def _still_holds(self, root: int, rel: str, held: int) -> bool:
        """Whether the folder ``rel``, walked again from the root without following a
        link, is the folder ``held`` refers to (same device and inode)."""
        try:
            folder = self._descend(root, rel, create=False)
        except OSError:
            return False
        try:
            return _inode(os.fstat(folder)) == _inode(os.fstat(held))
        finally:
            os.close(folder)

    def _staging_names(self, root: int, inode: _Inode) -> int:
        """How many ``.part`` entries of the root's ``.staging`` folder name ``inode``."""
        try:
            folder = self._descend(root, STAGING, create=False)
        except OSError:
            return 0
        try:
            with os.scandir(folder) as entries:
                names = [entry.name for entry in entries if entry.name.endswith(PART)]
            count = 0
            for name in names:
                info = _lstat_at(folder, name)
                if info is not None and stat.S_ISREG(info.st_mode) and _inode(info) == inode:
                    count += 1
            return count
        finally:
            os.close(folder)

    def _folder_of(self, rel: str, root: int | None = None) -> tuple[int, str] | str:
        """``(descriptor of the folder holding rel, rel's last component)``, or
        :data:`_ABSENT` / :data:`_NOT_REGULAR` when a folder on the way is missing, or
        is a link or a file. Never follows a link. ``root`` is a root descriptor the
        caller holds; without one the root is opened here."""
        folder_rel, _, name = rel.rpartition("/")
        opened = os.open(self.root, _DIR) if root is None else None
        try:
            return self._descend(root if opened is None else opened, folder_rel,
                                 create=False), name
        except FileNotFoundError:
            return _ABSENT
        except OSError as error:
            if error.errno in (errno.ELOOP, errno.ENOTDIR):
                return _NOT_REGULAR  # a link or a file where a folder belongs
            raise
        finally:
            if opened is not None:
                os.close(opened)

    def _open_fd(self, rel: str, root: int | None = None) -> int | str:
        """A read-only descriptor for the regular file at ``rel`` under the root, or
        :data:`_ABSENT` or :data:`_NOT_REGULAR`. Never opens anything for writing."""
        found = self._folder_of(rel, root)
        if isinstance(found, str):
            return found
        folder, name = found
        try:
            return _open_at(folder, name)
        finally:
            os.close(folder)

    def _open_read(self, rel: str) -> BinaryIO | str:
        fd = self._open_fd(rel)
        return fd if isinstance(fd, str) else os.fdopen(fd, "rb")

    def _lstat(self, rel: str, root: int | None = None) -> os.stat_result | str:
        """The entry at ``rel`` without following a link, or :data:`_ABSENT` or
        :data:`_NOT_REGULAR` (a folder on the way is a link or a file)."""
        found = self._folder_of(rel, root)
        if isinstance(found, str):
            return found
        folder, name = found
        try:
            info = _lstat_at(folder, name)
        finally:
            os.close(folder)
        return _ABSENT if info is None else info

    def _examine(self, rel: str, *, digest: bool,
                 root: int | None = None) -> tuple[str, int, _Inode] | str:
        """``(sha256, size, inode)`` of the regular file at ``rel`` (``sha256`` is
        empty without ``digest``), or :data:`_ABSENT` or :data:`_NOT_REGULAR`."""
        fd = self._open_fd(rel, root)
        if isinstance(fd, str):
            return fd
        try:
            info = os.fstat(fd)
            if not digest:
                return "", info.st_size, _inode(info)
            found, size = _read_back(fd, self._chunk)
            return found, size, _inode(info)
        finally:
            os.close(fd)

    def _hash_existing(self, rel: str) -> tuple[str, int] | None:
        """``(sha256, size)`` of the regular file at ``rel``, read-only and without
        following a symbolic link; ``None`` if there is no file; ``("", -1)`` for
        something that is not a regular file."""
        found = self._examine(rel, digest=True)
        if found == _ABSENT:
            return None
        if isinstance(found, str):
            return ("", -1)
        return found[0], found[1]

    def _check_blob(self, name: str, blob: Blob, *, digest: bool,
                    root: int | None = None) -> _Inode:
        """The inode of a record's blob, after checking it is a regular file of the
        recorded size (and hash, with ``digest``). A blob that cannot be read is
        ``store.blob_missing``, never a bare ``OSError``."""
        try:
            found = self._examine(blob.locator, digest=digest, root=root)
        except OSError as error:
            raise StoreError(BLOB_MISSING, f"output {name!r}: the blob cannot be read "
                             f"({_reason(error)})", locator=blob.locator) from None
        if found == _ABSENT:
            raise StoreError(BLOB_MISSING, f"output {name!r}: no blob at its locator",
                             locator=blob.locator)
        if isinstance(found, str):
            raise StoreError(HASH_MISMATCH, f"output {name!r}: {found} at its locator",
                             locator=blob.locator)
        sha, size, inode = found
        if size != blob.bytes or (digest and sha != blob.sha256):
            raise StoreError(HASH_MISMATCH, f"output {name!r}: the file is not the recorded "
                             f"{blob.bytes} bytes hashing to {blob.sha256}", locator=blob.locator)
        return inode

    def _load_record(self, production_id: str, run_id: str, stage: str) -> StageRecord | None:
        """The record file decoded, or ``None``; its blobs are not looked at."""
        path = record_path(production_id, run_id, stage)
        data = self._read(path)
        if data is None:
            return None
        record = StageRecord.decode(data, source=path)
        if (record.production_id, record.run_id, record.stage) != (production_id, run_id, stage):
            raise StoreError(RECORD_INVALID, "the record names another stage than its path",
                             locator=path)
        return record

    def _read(self, rel: str) -> bytes | None:
        handle = self._open_read(rel)
        if handle == _ABSENT:
            return None
        if isinstance(handle, str):
            raise StoreError(RECORD_INVALID, handle, locator=rel)
        with handle:
            return handle.read()

    def _walk(self, unreadable: list[tuple[str, str]] | None = None
              ) -> Iterator[tuple[str, bool]]:
        """Every entry under the root that is not a folder (symbolic links included,
        never followed), as ``(relative path, is a regular file)``, sorted within each
        folder. Each folder is reached from the root one component at a time with
        ``O_NOFOLLOW`` and listed through its descriptor. A folder that cannot be
        listed goes to ``unreadable`` with the reason."""
        root = os.open(self.root, _DIR)
        try:
            stack = [""]
            while stack:
                rel = stack.pop()
                try:
                    folder = self._descend(root, rel, create=False)
                    try:
                        with os.scandir(folder) as entries:
                            listed = sorted((entry.name, entry.is_dir(follow_symlinks=False),
                                             entry.is_file(follow_symlinks=False))
                                            for entry in entries)
                    finally:
                        os.close(folder)
                except OSError as error:
                    if unreadable is not None:
                        unreadable.append((rel or ".", _reason(error)))
                    continue
                for name, is_dir, is_file in listed:
                    child = f"{rel}/{name}" if rel else name
                    if is_dir:
                        stack.append(child)
                    else:
                        yield child, is_file
        finally:
            os.close(root)


def _hold(held: contextlib.ExitStack, fd: int) -> int:
    held.callback(os.close, fd)
    return fd


def _inode(info: os.stat_result) -> _Inode:
    return info.st_dev, info.st_ino


def _reason(error: OSError) -> str:
    return error.strerror or type(error).__name__


def _collision(final_rel: str, why: str) -> StoreError:
    return StoreError(COLLISION, f"the final path holds a file this store did not publish "
                      f"({why}); nothing was overwritten or changed", locator=final_rel)


def _require_untouched(fd: int, staging: int, name: str) -> None:
    """The staging file must still be as step 1 made it: one name, and that name is
    ``name`` in the staging folder (a ``.part`` name, never a final or record path), with
    no write bit. Another writer has not linked, renamed or removed it, or made it
    writable."""
    info = os.fstat(fd)
    named = _lstat_at(staging, name)
    if (info.st_nlink != 1 or info.st_mode & _WRITE_BITS or named is None
            or _inode(named) != _inode(info)):
        raise StoreError(COLLISION, "another writer linked, renamed, removed or made writable "
                         f"this publication's staging file ({info.st_nlink} names, mode "
                         f"{stat.S_IMODE(info.st_mode):o}); the store links nothing from it",
                         locator=f"{STAGING}/{name}")


def _read_back(fd: int, chunk: int) -> tuple[str, int]:
    """``(sha256, size)`` of the file behind ``fd``, read from offset 0 with ``pread``."""
    digest, offset = hashlib.sha256(), 0
    while data := os.pread(fd, chunk, offset):
        digest.update(data)
        offset += len(data)
    return digest.hexdigest(), offset


def _open_at(folder: int, name: str) -> int | str:
    """A read-only, non-following descriptor for the regular file ``name`` in
    ``folder``, or :data:`_ABSENT` or :data:`_NOT_REGULAR`."""
    try:
        fd = os.open(name, _READ, dir_fd=folder)
    except FileNotFoundError:
        return _ABSENT
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENXIO, errno.ENOTDIR):
            return _NOT_REGULAR  # a link, a socket, or a folder in the way
        raise
    try:
        regular = stat.S_ISREG(os.fstat(fd).st_mode)
    except BaseException:
        os.close(fd)
        raise
    if not regular:
        os.close(fd)
        return _NOT_REGULAR
    return fd


def _lstat_at(folder: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=folder, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _proc_path(fd: int) -> str:
    """``/proc/self/fd/<fd>``, after checking that it reaches the descriptor's own
    inode. Without it publication fails closed: there is no fallback to linking a
    name, which another writer could swap."""
    path = f"{_PROC_FD}/{fd}"
    try:
        same = _inode(os.stat(path)) == _inode(os.fstat(fd))
    except OSError:
        same = False
    if not same:
        raise OSError(errno.ENOTSUP, f"publication links the checked file through {_PROC_FD} "
                      "(Linux), which is not available here; nothing was linked")
    return path


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


__all__ = ["DoctorReport", "LocalStore", "StagingLeftoverWarning"]
