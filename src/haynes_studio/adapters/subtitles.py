"""Read one scene from a configured Linux filesystem subtitle source."""

from __future__ import annotations

import errno
import hashlib
import hmac
import os
import re
import stat
import sys
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from functools import wraps
from typing import Literal, ParamSpec, Protocol, TypeVar

from haynes_studio.store import canonical_json

from ._subtitle_text import MAX_FILE_CUES, Cue, parse_cues, refusal
from .errors import (
    SOURCE_CHANGED,
    SOURCE_HARD_LINK,
    SOURCE_LINK,
    SOURCE_MISSING,
    SOURCE_NOT_REGULAR,
    SOURCE_OUTSIDE,
    SOURCE_TOO_LARGE,
    RequestInvalid,
)

MAX_FILE_BYTES = 1_048_576
MAX_DIRECTORY_ENTRIES = 512
MAX_SCENE_CUES = 80
MAX_SCENE_CHARACTERS = 8_192
MAX_SCENE_MS = 120_000
_MAX_TIME_MS = 3_600_000_000  # Cue grammar supports up to 999 hours.
_SUFFIXES = (".srt", ".vtt")
_SOURCE_ID = re.compile(r"[A-Za-z][A-Za-z0-9]{0,29}")
_PRINCIPAL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_P = ParamSpec("_P")
_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class CueRange:
    """One-based half-open range in file order, independent of cue identifiers."""

    start: int
    end: int


@dataclass(frozen=True, slots=True)
class TimeRange:
    """Millisecond window. Only cues wholly contained in the window are returned."""

    start_ms: int
    end_ms: int


@dataclass(frozen=True, slots=True)
class _ReadRange:
    unit: Literal["cue", "ms"]
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class ReadProvenance:
    source_id: str
    title_id: str
    episode_id: str
    range: _ReadRange
    passage_sha256: str
    principal: str
    read_at: str

    def as_record(self) -> dict:
        """Metadata-only receipt for optional private recordkeeping."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SceneRead:
    cues: tuple[Cue, ...] = field(repr=False)
    provenance: ReadProvenance
    _scene_number: int = field(repr=False)


class SubtitleSource(Protocol):
    def list_titles(self) -> tuple[str, ...]: ...

    def list_episodes(self, title: str) -> tuple[str, ...]: ...

    def read_scene(
        self, title: str, episode: str, selection: CueRange | TimeRange, *,
        scene_number: int, principal: str,
    ) -> SceneRead: ...


def _plain_name(name: str) -> bool:
    return (
        isinstance(name, str) and 0 < len(name) <= 255 and name.isprintable()
        and name not in {".", ".."} and "/" not in name and "\\" not in name
        and len(os.fsencode(name)) <= 255
    )


def _suffix(name: str) -> str:
    return os.path.splitext(name)[1].lower()


def _range(selection: CueRange | TimeRange) -> _ReadRange:
    if isinstance(selection, CueRange):
        result = _ReadRange("cue", selection.start, selection.end)
        lower, upper, span = 1, MAX_FILE_CUES + 1, MAX_SCENE_CUES
    elif isinstance(selection, TimeRange):
        result = _ReadRange("ms", selection.start_ms, selection.end_ms)
        lower, upper, span = 0, _MAX_TIME_MS, MAX_SCENE_MS
    else:
        raise RequestInvalid("subtitles", "Supply one cue or time range")
    if not (
        type(result.start) is int and type(result.end) is int
        and lower <= result.start < result.end <= upper and result.end - result.start <= span
    ):
        raise refusal("subtitle.range", "Scene range is invalid or exceeds the limit")
    return result


def _select(cues: tuple[Cue, ...], selection: _ReadRange) -> tuple[Cue, ...]:
    if selection.unit == "cue":
        if selection.end > len(cues) + 1:
            raise refusal("subtitle.range", "Cue range exceeds the end of the file")
        selected = cues[selection.start - 1:selection.end - 1]
    else:
        selected = tuple(
            cue for cue in cues if selection.start <= cue.start_ms and cue.end_ms <= selection.end
        )
    if not selected:
        raise refusal("subtitle.range", "Scene range contains no complete cues")
    if (len(selected) > MAX_SCENE_CUES
            or sum(len(cue.text) for cue in selected) > MAX_SCENE_CHARACTERS
            or max(cue.end_ms for cue in selected) - min(cue.start_ms for cue in selected) > MAX_SCENE_MS):
        raise refusal("subtitle.limit", "Scene exceeds the cue, character or duration limit")
    return tuple(sorted(selected, key=lambda cue: (cue.start_ms, cue.number)))


def _sanitize_io(call: Callable[_P, _T]) -> Callable[_P, _T]:
    @wraps(call)
    def read(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        try:
            return call(*args, **kwargs)
        except OSError as error:
            code, message = {
                errno.EACCES: ("subtitle.access_denied", "Subtitle source access was denied"),
                errno.EPERM: ("subtitle.access_denied", "Subtitle source access was denied"),
                errno.ENOENT: (SOURCE_MISSING, "Subtitle source entry is missing"),
                errno.ENOTDIR: (SOURCE_NOT_REGULAR, "Subtitle source entry has the wrong file type"),
                errno.ELOOP: (SOURCE_LINK, "Subtitle source entry is a symbolic link"),
            }.get(error.errno, ("subtitle.io", "Subtitle source I/O failed"))
        raise refusal(code, message) from None
    return read


@contextmanager
def _descriptor(path: str, flags: int, parent: int | None = None) -> Iterator[int]:
    fd = os.open(path, flags, dir_fd=parent)
    try:
        yield fd
    finally:
        os.close(fd)


@contextmanager
def _entry(parent: int, name: str, *, directory: bool) -> Iterator[tuple[int, os.stat_result]]:
    # O_PATH gets a reference to the inode without opening a FIFO or device for I/O.
    with _descriptor(name, os.O_PATH | os.O_NOFOLLOW, parent) as fd:
        info = os.fstat(fd)
        if stat.S_ISLNK(info.st_mode):
            raise refusal(SOURCE_LINK, "Subtitle source entry is a symbolic link")
        expected = stat.S_ISDIR if directory else stat.S_ISREG
        if not expected(info.st_mode):
            raise refusal(SOURCE_NOT_REGULAR, "Subtitle source entry has the wrong file type")
        yield fd, info


def _mount_id(fd: int) -> bytes:
    with open(f"/proc/self/fdinfo/{fd}", "rb") as descriptor_info:
        match = re.search(rb"^mnt_id:\s+([0-9]+)$", descriptor_info.read(4096), re.MULTILINE)
    if match is None:
        raise refusal("subtitle.io", "Subtitle source mount could not be verified")
    return match[1]


def _same_mount(fd: int, mount: bytes) -> None:
    if _mount_id(fd) != mount:
        raise refusal(SOURCE_OUTSIDE, "Subtitle source entry crosses the configured root mount")


@contextmanager
def _read_descriptor(fd: int) -> Iterator[int]:
    # Reopen only the checked inode. The link here is the kernel's own fd reference,
    # never a link or pathname supplied by the source.
    reference = f"/proc/self/fd/{fd}"
    try:
        reader = os.open(reference, os.O_RDONLY | os.O_NOATIME)
    except PermissionError as error:
        if error.errno != errno.EPERM:
            raise
        flags = os.fstatvfs(fd).f_flag
        if not flags & (os.ST_RDONLY | os.ST_NOATIME):
            raise
        reader = os.open(reference, os.O_RDONLY)
    try:
        yield reader
    finally:
        os.close(reader)


def _listing(fd: int, *, directories: bool) -> tuple[str, ...]:
    names = []
    with _read_descriptor(fd) as directory, os.scandir(directory) as entries:
        for count, entry in enumerate(entries, start=1):
            if count > MAX_DIRECTORY_ENTRIES:
                raise refusal("subtitle.limit", "Subtitle discovery exceeds the directory entry limit")
            if not _plain_name(entry.name):
                continue
            if directories:
                if entry.is_dir(follow_symlinks=False):
                    names.append(entry.name)
            elif _suffix(entry.name) in _SUFFIXES:
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= MAX_FILE_BYTES:
                    names.append(entry.name)
    return tuple(sorted(names))


def _read_file(fd: int, info: os.stat_result) -> bytes:
    if info.st_nlink != 1:
        raise refusal(SOURCE_HARD_LINK, "Subtitle file must have one hard link")
    if info.st_size > MAX_FILE_BYTES:
        raise refusal(SOURCE_TOO_LARGE, "Subtitle file exceeds the byte limit")
    data = bytearray()
    with _read_descriptor(fd) as reader:
        while remaining := MAX_FILE_BYTES + 1 - len(data):
            chunk = os.read(reader, remaining)
            if not chunk:
                break
            data.extend(chunk)
        after = os.fstat(reader)
    if len(data) > MAX_FILE_BYTES:
        raise refusal(SOURCE_TOO_LARGE, "Subtitle file exceeds the byte limit")
    if len(data) != info.st_size or (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_nlink) != (
        info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink
    ):
        raise refusal(SOURCE_CHANGED, "Subtitle file changed during the read")
    return bytes(data)


def _opaque_id(key: bytes, *parts: str) -> str:
    return hmac.digest(key, canonical_json(parts), "sha256").hex()


class FilesystemSubtitleSource:
    """Two levels under an explicit root: title directories containing episode files."""

    def __init__(
        self, root: str | os.PathLike[str], *, source_id: str, receipt_key: bytes,
        allow_windows_1252: bool = False,
    ):
        if sys.platform != "linux":
            raise refusal("subtitle.platform", "Filesystem subtitle sources require Linux")
        path = os.fspath(root)
        parts = path[1:].split("/") if isinstance(path, str) and path.startswith("/") else []
        if not (0 < len(parts) <= 32 and all(_plain_name(part) for part in parts)):
            raise refusal(SOURCE_OUTSIDE, "Source root must be an absolute directory path with plain components")
        if not isinstance(source_id, str) or not _SOURCE_ID.fullmatch(source_id):
            raise RequestInvalid("subtitles", "Supply an opaque source ID for the archive locator")
        if not isinstance(receipt_key, bytes) or len(receipt_key) != 32:
            raise RequestInvalid("subtitles", "Supply a 32-byte secret receipt key for this source")
        self._root = tuple(parts)
        self._source_id = source_id
        self._receipt_key = receipt_key
        self._allow_windows_1252 = allow_windows_1252

    @contextmanager
    def _open_root(self) -> Iterator[int]:
        with ExitStack() as stack:
            fd = stack.enter_context(_descriptor("/", os.O_PATH | os.O_DIRECTORY))
            for part in self._root:
                fd, _ = stack.enter_context(_entry(fd, part, directory=True))
            yield fd

    @_sanitize_io
    def list_titles(self) -> tuple[str, ...]:
        with self._open_root() as root:
            return _listing(root, directories=True)

    @_sanitize_io
    def list_episodes(self, title: str) -> tuple[str, ...]:
        if not _plain_name(title):
            raise refusal(SOURCE_OUTSIDE, "Title selector must be a single name")
        with self._open_root() as root, _entry(root, title, directory=True) as (directory, _):
            _same_mount(directory, _mount_id(root))
            return _listing(directory, directories=False)

    @_sanitize_io
    def read_scene(
        self, title: str, episode: str, selection: CueRange | TimeRange, *,
        scene_number: int, principal: str,
    ) -> SceneRead:
        if not _plain_name(title) or not _plain_name(episode):
            raise refusal(SOURCE_OUTSIDE, "Title and episode selectors must be single names")
        if _suffix(episode) not in _SUFFIXES:
            raise refusal("subtitle.format", "Episode must be a SubRip or WebVTT file")
        if not isinstance(principal, str) or not _PRINCIPAL.fullmatch(principal):
            raise RequestInvalid("subtitles", "Supply an opaque principal ID")
        if type(scene_number) is not int or not 1 <= scene_number <= 999_999_999:
            raise RequestInvalid("subtitles", "Scene number must be from 1 to 999999999")
        requested_range = _range(selection)
        with self._open_root() as root:
            mount = _mount_id(root)
            with _entry(root, title, directory=True) as (directory, _):
                _same_mount(directory, mount)
                with _entry(directory, episode, directory=False) as (fd, info):
                    _same_mount(fd, mount)
                    data = _read_file(fd, info)
        cues = _select(
            parse_cues(data, vtt=_suffix(episode) == ".vtt", allow_windows_1252=self._allow_windows_1252),
            requested_range,
        )
        passage = canonical_json([[cue.start_ms, cue.end_ms, cue.text] for cue in cues])
        provenance = ReadProvenance(
            source_id=self._source_id,
            title_id=_opaque_id(self._receipt_key, self._source_id, title),
            episode_id=_opaque_id(self._receipt_key, self._source_id, title, episode),
            range=requested_range,
            passage_sha256=hashlib.sha256(passage).hexdigest(),
            principal=principal,
            read_at=datetime.now(UTC).isoformat(),
        )
        return SceneRead(cues, provenance, scene_number)
