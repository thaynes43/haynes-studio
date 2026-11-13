"""Fail-fast checks before any renderer call (contract sections 4, 6 and 8).

:func:`preflight` takes a story (story 404's model, boards embedded), its facts and
the asset versions the library resolved for it (ID to hash and locator, passed in
explicitly), and reports every problem it finds:

1. the story's ``queue_run`` validation (:func:`haynes_studio.canonical.validate_story`
   in context ``queue_run``: voices, photos, methods, cue anchors and ranges, and the
   rest of the write rules), called, never copied;
2. every asset version the story references is resolved, and every blob the build
   reads is in the store at a valid locator with its hash (re-hashed).

Each problem names the board (ID and display code), the legacy shot when the board
has one, and the field, so a person can fix the story. :func:`ensure_buildable` raises
:class:`PreflightError` on any blocking problem; a build calls it before its first
renderer call.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from haynes_studio.canonical import Facts, Story, to_document, validate_story
from haynes_studio.canonical.validate import QUEUE_RUN, SCHEMA_INVALID
from haynes_studio.errors import INVALID, ROOT, WARNING, ContractError, pointer
from haynes_studio.store import (
    BLOB_MISSING,
    HASH_MISMATCH,
    LIBRARY,
    LOCATOR_INVALID,
    MISSING,
    PRESENT,
    Store,
    StoreError,
    is_sha256,
    parse_locator,
)
from haynes_studio.store.errors import FAILED

# Proposal (story 379): a version the story names that the library did not resolve.
ASSET_UNRESOLVED = "asset.unresolved"

_BOARD_PATH = re.compile(r"/boards/(\d+)((?:/.*)?)", re.DOTALL)


@dataclass(frozen=True, slots=True)
class BlobRef:
    """One blob of a resolved asset version: its hash and locator."""

    sha256: str
    locator: str


@dataclass(frozen=True, slots=True)
class ResolvedVersion:
    """What the library resolved one asset version to: the blobs a build reads. A
    definition-only version (a stock ``voice``) has none; a ``board_voice`` version
    may list its takes and track."""

    blobs: tuple[BlobRef, ...] = ()

    @classmethod
    def of(cls, sha256: str, locator: str) -> ResolvedVersion:
        """A version whose content is one blob."""
        return cls((BlobRef(sha256, locator),))


DEFINITION_ONLY = ResolvedVersion()


@dataclass(frozen=True, slots=True)
class Problem:
    """One reason the story cannot be built yet. ``path`` is a JSON Pointer into the
    story document; ``field`` is the same pointer inside the board (or the story's,
    when ``board_id`` is ``None``)."""

    rule: str
    status: str
    path: str
    message: str
    board_id: str | None = None
    board_number: int | None = None
    legacy_shot: int | None = None
    field: str = ""
    asset_version_id: str | None = None
    locator: str | None = None

    @property
    def where(self) -> str:
        if self.board_id is None:
            return "story"
        shot = f", legacy shot {self.legacy_shot}" if self.legacy_shot is not None else ""
        return f"board B{self.board_number:02d} ({self.board_id}{shot})"

    def __str__(self) -> str:
        return f"{self.where} field {self.field or ROOT}: {self.rule} ({self.status}): {self.message}"


@dataclass(frozen=True)
class PreflightReport:
    problems: tuple[Problem, ...]

    @property
    def blocking(self) -> tuple[Problem, ...]:
        return tuple(problem for problem in self.problems if problem.status != WARNING)

    @property
    def ok(self) -> bool:
        return not self.blocking


class PreflightError(ContractError):
    """The story is not buildable; ``report`` holds every problem."""

    def __init__(self, source: str, report: PreflightReport):
        self.report = report
        super().__init__(source, report.blocking)


def ensure_buildable(story: Story, *, facts: Facts, resolved: Mapping[str, ResolvedVersion],
                     store: Store, source: str = "<story>") -> PreflightReport:
    """:func:`preflight`, raising :class:`PreflightError` if anything blocks."""
    report = preflight(story, facts=facts, resolved=resolved, store=store)
    if not report.ok:
        raise PreflightError(source, report)
    return report


def preflight(story: Story, *, facts: Facts, resolved: Mapping[str, ResolvedVersion],
              store: Store) -> PreflightReport:
    """Every problem that would stop a build of ``story``: story-level problems first,
    then by the board's place in ``board_order``, then field. Reads the store, never
    writes it."""
    boards = story.boards or ()
    raw: list[tuple[str, str, str, str | None, str | None]] = []  # rule, status, path, message, avid, locator
    if story.boards is None:
        raw.append((SCHEMA_INVALID, INVALID, "/boards",
                    "the story's boards must be embedded to check a build", None, None))
    for violation in validate_story(_draft_document(story), context=QUEUE_RUN, facts=facts):
        raw.append((violation.rule, violation.status, violation.path, violation.message, None, None))
    raw += _blob_problems(story, resolved, store)
    problems = [_locate(rule, status, path, message, avid, locator, boards)
                for rule, status, path, message, avid, locator in raw]
    order = {board_id: index for index, board_id in enumerate(story.board_order)}
    problems.sort(key=lambda p: (-1 if p.board_id is None else order.get(p.board_id, len(order)),
                                 p.board_number or 0, p.field, p.rule, p.message))
    return PreflightReport(tuple(problems))


def _draft_document(story: Story) -> dict[str, Any]:
    """The story as a client writes it: ``derived`` blocks are the server's, and the
    ``queue_run`` context refuses them."""
    boards = None if story.boards is None else tuple(
        dataclasses.replace(board, derived=None) for board in story.boards)
    return to_document(dataclasses.replace(story, derived=None, boards=boards))


def _locate(rule: str, status: str, path: str, message: str, avid: str | None,
            locator: str | None, boards: tuple) -> Problem:
    match = _BOARD_PATH.fullmatch(path)
    if match is None or int(match[1]) >= len(boards):
        return Problem(rule, status, path, message, field=path, asset_version_id=avid,
                       locator=locator)
    board = boards[int(match[1])]
    return Problem(rule, status, path, message, board_id=board.id, board_number=board.number,
                   legacy_shot=board.origin.legacy_shot if board.origin else None,
                   field=match[2], asset_version_id=avid, locator=locator)


def references(story: Story) -> Iterable[tuple[str, str, bool]]:
    """``(path, asset_version_id, needs_bytes)`` for every asset version the story
    names. Only the story's cast voices and narrator voice (definition-only ``voice``
    versions) may resolve without bytes."""
    for i, member in enumerate(story.cast):
        yield pointer("cast", i, "voice_version_id"), member.voice_version_id, False
    if story.narrator_voice_version_id is not None:
        yield "/narrator_voice_version_id", story.narrator_voice_version_id, False
    if story.set is not None:
        for name in ("asset_version_id", "motion_asset_version_id"):
            if getattr(story.set, name) is not None:
                yield pointer("set", name), getattr(story.set, name), True
    for i, bed in enumerate(story.beds):
        yield pointer("beds", i, "asset_version_id"), bed.asset_version_id, True
    for b, board in enumerate(story.boards or ()):
        if board.voice.current_version_id is not None:
            yield pointer("boards", b, "voice", "current_version_id"), board.voice.current_version_id, True
        if board.photo.current_version_id is not None:
            yield pointer("boards", b, "photo", "current_version_id"), board.photo.current_version_id, True
        for i, version_id in enumerate(board.photo.input_asset_version_ids):
            yield pointer("boards", b, "photo", "input_asset_version_ids", i), version_id, True
        for i, entry in enumerate(board.cast):
            yield pointer("boards", b, "cast", i, "asset_version_id"), entry.asset_version_id, True
        for i, cue in enumerate(board.cues):
            if cue.type == "sound":
                yield pointer("boards", b, "cues", i, "asset_version_id"), cue.asset_version_id, True


def _blob_problems(story: Story, resolved: Mapping[str, ResolvedVersion],
                   store: Store) -> list[tuple[str, str, str, str, str | None, str | None]]:
    found = []
    checked: dict[tuple[str, str], tuple[str, str] | None] = {}  # (locator, sha256) -> problem
    allowed = {LIBRARY, story.production_id}
    for path, version_id, needs_bytes in references(story):
        version = resolved.get(version_id)
        if version is None:
            found.append((ASSET_UNRESOLVED, INVALID, path,
                          f"asset version {version_id} was not resolved by the library",
                          version_id, None))
            continue
        if needs_bytes and not version.blobs:
            found.append((BLOB_MISSING, FAILED, path,
                          f"asset version {version_id} resolved without bytes, and the build "
                          "reads them", version_id, None))
        for ref in version.blobs:
            key = (ref.locator, ref.sha256)
            if key not in checked:
                checked[key] = _check_blob(ref, allowed, store)
            if checked[key] is not None:
                rule, message = checked[key]
                status = INVALID if rule in (LOCATOR_INVALID, SCHEMA_INVALID) else FAILED
                found.append((rule, status, path, f"asset version {version_id}: {message}",
                              version_id, ref.locator if isinstance(ref.locator, str) else None))
    return found


def _check_blob(ref: BlobRef, allowed: set[str], store: Store) -> tuple[str, str] | None:
    """``(rule, message)`` for a blob that is not usable, else ``None``."""
    if not is_sha256(ref.sha256):
        return SCHEMA_INVALID, f"the resolved hash {ref.sha256!r} is not 64 lower-case hex digits"
    try:
        locator = parse_locator(ref.locator)
    except StoreError as error:
        return LOCATOR_INVALID, f"locator {ref.locator!r}: {error.message}"
    if locator.sha256 != ref.sha256:
        return LOCATOR_INVALID, f"locator {ref.locator} names another hash than {ref.sha256}"
    if locator.scope not in allowed:
        return LOCATOR_INVALID, (f"locator {ref.locator} is in another production's folder; "
                                 "a story reads the library and its own production")
    try:
        state = store.verify(ref.locator, ref.sha256)
    except OSError as error:  # unreadable (a mode, a folder's mode, an I/O error): report it
        return BLOB_MISSING, (f"the blob at {ref.locator} cannot be read: "
                              f"{error.strerror or type(error).__name__}")
    if state == PRESENT:
        return None
    if state == MISSING:
        return BLOB_MISSING, f"no blob at {ref.locator}"
    return HASH_MISMATCH, f"the bytes at {ref.locator} do not hash to {ref.sha256}"
