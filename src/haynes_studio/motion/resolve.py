"""Which clip, which frames, which keying inputs: a board's motion loops, pinned
(story 457, contract sections 3, 5 and 9).

:func:`resolve_board` gives each cast entry that needs a loop, and the set, one
:class:`PinnedClip` or a problem, the same answer every time for the same board and
library:

- **A cast still.** The entry's ``motion_asset_version_id`` when it has one; without
  a pin, the one promoted doll loop whose ``still_sha256`` is the entry's still, in the
  production (the story's, or ``production_id``) and the global library. A layered I2V board
  needs a loop for every entry; a layered S2V board for every entry that speaks no
  line on it (speakers get their timed clip); a whole-frame board for none. A pin is
  checked wherever it stands.
- **The set** (a layered board, given the story): the story's
  ``set.motion_asset_version_id``; without a pin, the one promoted set loop of the set
  still, or none (a static plate, as ``cache.plan`` builds it; proposal).

:func:`resolve_timed` gives a speaking cast still its timed clip for one drive track.

Problems, each with its own code (codes beyond the contract are **proposals**):

| Code | Status | When |
|---|---|---|
| ``ref.unknown`` | invalid | the pinned version, or the entry's still, is not in the library |
| ``asset.kind_mismatch`` | invalid | the pin is not a ``motion`` version |
| ``asset.scope_mismatch`` | invalid | the pin belongs to another production |
| ``motion.record_missing`` | invalid | a motion version without a motion block |
| ``motion.clip_absent`` | invalid | no pin, and no promoted loop (or timed clip) of that still |
| ``motion.clip_ambiguous`` | invalid | no pin, and several promoted loops of that still |
| ``motion.timed_not_loop`` | invalid | a timed clip pinned where a loop plays (TIME-8, TIME-8a) |
| ``asset.capability_mismatch`` | invalid | a set loop pinned for a doll, or a doll clip for the set |
| ``motion.still_mismatch`` | invalid | the pinned clip stands in for another still |
| ``motion.keying_missing`` | invalid | a doll clip with no keying inputs recorded |
| ``motion.identity_mismatch`` | invalid | a recorded key is not what the record's inputs give (a corrupt record) |
| ``motion.drive_track_mismatch`` | invalid | a timed clip made for another board length |
| ``asset.bytes_missing`` | invalid | the store does not hold the clip |
| ``store.hash_mismatch`` | failed | the store holds other bytes at the clip's locator (corrupt) |

A clip is returned only without a blocking problem, so a ``PinnedClip`` is always
playable. ``verify(locator, sha256)`` is the store's ``Store.verify`` (``present``,
``missing`` or ``mismatch``) or a synthetic one; one call asks it once per distinct
clip. Nothing here touches a file.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from haynes_studio.cache.errors import CacheError
from haynes_studio.canonical.jsonvalues import normalize
from haynes_studio.errors import Violation, blocking, pointer
from haynes_studio.library.library import REF_UNKNOWN, Library
from haynes_studio.library.model import PROMOTED, AssetVersion
from haynes_studio.library.resolve import BYTES_MISSING, KIND_MISMATCH, SCOPE_MISMATCH
from haynes_studio.motion.check import CAPABILITY_MISMATCH, IDENTITY_MISMATCH, identity_problems
from haynes_studio.motion.identity import MotionIdentity, motion_identity
from haynes_studio.motion.record import DOLL, LOOP, SET, SUBJECT_CAPABILITY, TIMED, MotionRecord
from haynes_studio.render.clock import SET_SLOT, loop_phase
from haynes_studio.store.base import MISSING, PRESENT
from haynes_studio.store.errors import HASH_MISMATCH

RECORD_MISSING = "motion.record_missing"
CLIP_ABSENT = "motion.clip_absent"
CLIP_AMBIGUOUS = "motion.clip_ambiguous"
TIMED_NOT_LOOP = "motion.timed_not_loop"
STILL_MISMATCH = "motion.still_mismatch"
KEYING_MISSING = "motion.keying_missing"
DRIVE_TRACK_MISMATCH = "motion.drive_track_mismatch"
FAILED = "failed"

CODES = (REF_UNKNOWN, KIND_MISMATCH, SCOPE_MISMATCH, RECORD_MISSING, CLIP_ABSENT, CLIP_AMBIGUOUS, TIMED_NOT_LOOP,
         CAPABILITY_MISMATCH, STILL_MISMATCH, KEYING_MISSING, IDENTITY_MISMATCH,
         DRIVE_TRACK_MISMATCH, BYTES_MISSING, HASH_MISMATCH)

Verify = Callable[[str, str], str]
"""``verify(locator, sha256)``: ``present``, ``missing`` or ``mismatch`` (story 379)."""


@dataclass(frozen=True)
class PinnedClip:
    """One resolved clip: what it is, where the board names it, and how board frame
    ``n`` maps to a frame of the file (:meth:`source_frame`)."""

    path: str  # JSON Pointer of the pin (or where a pin would go) in the board or story
    slot: str  # the cast slot, or "set"
    version_id: str
    asset_id: str
    number: int
    pinned: bool  # True: named by the board or story; False: the one promoted loop
    record: MotionRecord
    identity: MotionIdentity
    sha256: str
    locator: str
    phase: int | None  # a loop's phase on this board (P-06); None for a timed clip

    @property
    def keyed_key(self) -> str | None:
        """The keyed frames' cache key (story 426 keys or reuses those frames)."""
        return None if self.identity.keyed is None else self.identity.keyed.value

    def source_frame(self, n: int) -> int:
        """The file frame board frame ``n`` shows: TIME-8a for a loop (with this board's
        phase), TIME-8 for a timed clip."""
        return self.record.board_frame(n, phase=self.phase or 0)


@dataclass(frozen=True)
class BoardMotion:
    board_id: str | None
    cast: tuple[PinnedClip, ...]
    set: PinnedClip | None
    problems: tuple[Violation, ...]

    @property
    def complete(self) -> bool:
        return not blocking(self.problems)

    def clip_for(self, slot: str) -> PinnedClip | None:
        if slot == SET_SLOT:
            return self.set
        return next((clip for clip in self.cast if clip.slot == slot), None)


def _get(document: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(document, Mapping):
            return None
        document = document.get(key)
    return document


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _v(rule: str, path: str, message: str, status: str = "invalid") -> Violation:
    return Violation(rule, path, message, status)


def _record(version: AssetVersion) -> MotionRecord | None:
    try:
        return MotionRecord.from_block(version.motion) if version.motion is not None else None
    except (KeyError, TypeError, ValueError):
        return None


def _in_scope(library: Library, version: AssetVersion, production_id: str | None) -> bool:
    scope = library.asset(version.asset_id).scope
    return production_id is None or scope.production_id in (None, production_id)


def candidates(library: Library, *, use: str, subject: str, still_sha256: str,
               production_id: str | None = None, drive_track_sha256: str | None = None,
               ) -> tuple[AssetVersion, ...]:
    """The promoted motion versions of ``use`` and ``subject`` that stand in for
    ``still_sha256`` (and were made from ``drive_track_sha256``, for a timed clip), in
    the production's scope, by ID. A candidate version, a motion version without a
    block, or one with no recorded still is never found this way."""
    out = []
    for version in library.versions.values():
        if version.kind != "motion" or version.state != PROMOTED:
            continue
        record = _record(version)
        if record is None or record.use != use or record.subject != subject \
                or record.still_sha256 != still_sha256:
            continue
        if drive_track_sha256 is not None and (record.drive_track is None or
                                               record.drive_track.sha256 != drive_track_sha256):
            continue
        if _in_scope(library, version, production_id):
            out.append(version)
    return tuple(sorted(out, key=lambda v: v.id))


def _check(library: Library, version: AssetVersion, *, path: str, slot: str, use: str,
           subject: str, still_sha256: str | None, pinned: bool, verify: Verify,
           board_id: str | None, production_id: str | None = None,
           board_frames: int | None = None) -> tuple[PinnedClip | None, list[Violation]]:
    """Every problem of using ``version`` as ``use`` of ``subject`` for this still, and
    the clip when there is no blocking one."""
    clip, found = _clip(library, version, path=path, slot=slot, use=use, subject=subject,
                        still_sha256=still_sha256, pinned=pinned, verify=verify,
                        board_id=board_id, production_id=production_id,
                        board_frames=board_frames)
    return (None if blocking(found) else clip), found


def _clip(library: Library, version: AssetVersion, *, path: str, slot: str, use: str,
          subject: str, still_sha256: str | None, pinned: bool, verify: Verify,
          board_id: str | None, production_id: str | None,
          board_frames: int | None) -> tuple[PinnedClip | None, list[Violation]]:
    if version.kind != "motion":
        return None, [_v(KIND_MISMATCH, path, f"{version.id} is a {version.kind}; this field "
                                               "needs a motion")]
    record = _record(version)
    if record is None:
        return None, [_v(RECORD_MISSING, path, f"{version.id} has no motion block: nothing says "
                                               "how it plays or is keyed")]
    found: list[Violation] = []
    if not _in_scope(library, version, production_id):
        found.append(_v(SCOPE_MISMATCH, path, f"{version.id} belongs to another production"))
    if use == LOOP and record.use == TIMED:
        return None, [_v(TIMED_NOT_LOOP, path,
                         f"{version.id} is a timed clip made for one board's speech; it is never "
                         "played as a ping-pong loop (TIME-8, TIME-8a)")]
    if record.subject != subject or SUBJECT_CAPABILITY[subject] not in version.capabilities:
        found.append(_v(CAPABILITY_MISMATCH, path,
                        f"{version.id} is a {record.subject} clip; this needs a "
                        f"{SUBJECT_CAPABILITY[subject]}"))
    if still_sha256 is not None and record.still_sha256 not in (None, still_sha256):
        found.append(_v(STILL_MISMATCH, path,
                        f"{version.id} stands in for another still than this one"))
    if record.subject == DOLL and record.keying is None:
        found.append(_v(KEYING_MISSING, path,
                        f"{version.id} records no keying inputs, so its frames cannot be keyed"))
    if board_frames is not None and record.drive_track is not None \
            and record.drive_track.board_frames != board_frames:
        found.append(_v(DRIVE_TRACK_MISMATCH, path,
                        f"{version.id} was made for a {record.drive_track.board_frames}-frame "
                        f"board, not {board_frames}"))
    content = version.content
    if content is None:
        return None, found + [_v(RECORD_MISSING, path, f"{version.id} has no content")]
    found += [_v(v.rule, path, v.message, v.status)
              for v in identity_problems(record, content.sha256)]
    state = verify(content.locator, content.sha256)
    if state == MISSING:
        found.append(_v(BYTES_MISSING, path, f"the store does not hold {content.locator}"))
    elif state != PRESENT:  # MISMATCH: a file is there, but not these bytes
        found.append(_v(HASH_MISMATCH, path,
                        f"the store's bytes at {content.locator} are not the recorded hash",
                        FAILED))
    try:
        identity = motion_identity(record, content.sha256)
    except (CacheError, ValueError):  # identity_problems reported it
        return None, found
    phase = None
    if record.use == LOOP and board_id is not None and record.period is not None:
        phase = loop_phase(board_id, slot, record.period)
    clip = PinnedClip(path=path, slot=slot, version_id=version.id, asset_id=version.asset_id,
                      number=version.number, pinned=pinned, record=record, identity=identity,
                      sha256=content.sha256, locator=content.locator, phase=phase)
    return clip, found


def _choose(library: Library, *, path: str, slot: str, use: str, subject: str,
            still_sha256: str, production_id: str | None, verify: Verify,
            board_id: str | None, absent_ok: bool = False, drive_track_sha256: str | None = None,
            board_frames: int | None = None) -> tuple[PinnedClip | None, list[Violation]]:
    found = candidates(library, use=use, subject=subject, still_sha256=still_sha256,
                       production_id=production_id, drive_track_sha256=drive_track_sha256)
    if not found:
        if absent_ok:
            return None, []
        what = "timed clip for this drive track" if use == TIMED else f"{subject} loop"
        return None, [_v(CLIP_ABSENT, path, f"no promoted {what} of this still; pin one or "
                                            "promote one")]
    if len(found) > 1:
        return None, [_v(CLIP_AMBIGUOUS, path,
                         f"{len(found)} promoted {subject} clips of this still "
                         f"({', '.join(v.id for v in found)}); pin one")]
    return _check(library, found[0], path=path, slot=slot, use=use, subject=subject,
                  still_sha256=still_sha256, pinned=False, verify=verify, board_id=board_id,
                  production_id=production_id, board_frames=board_frames)


def _pinned(library: Library, version_id: str, *, production_id: str | None,
            **kwargs: Any) -> tuple[PinnedClip | None, list[Violation]]:
    version = library.get(version_id)
    if version is None:
        return None, [_v(REF_UNKNOWN, kwargs["path"], f"the library has no asset version "
                                                      f"{version_id}")]
    return _check(library, version, pinned=True, production_id=production_id, **kwargs)


def _content_sha(library: Library, version_id: Any) -> str | None:
    version = library.get(version_id) if isinstance(version_id, str) else None
    return None if version is None or version.content is None else version.content.sha256


def needs_loop(board: Mapping[str, Any], slot: str) -> bool:
    """Does this cast slot play a loop on this board (section 5)? Layered I2V: every
    slot; layered S2V: every slot that speaks no line here; whole-frame: none."""
    if _get(board, "method", "layer") != "layered":
        return False
    if _get(board, "method", "motion") == "s2v":
        return slot not in {_text(_get(line, "speaker")) for line in _list(_get(board, "lines"))}
    return True


def remembered(verify: Verify) -> Verify:
    """``verify`` asked once per distinct ``(locator, sha256)``."""
    answers: dict[tuple[str, str], str] = {}

    def ask(locator: str, sha256: str) -> str:
        if (locator, sha256) not in answers:
            answers[(locator, sha256)] = verify(locator, sha256)
        return answers[(locator, sha256)]

    ask.remembers = True  # type: ignore[attr-defined]
    return ask


def resolve_board(board: Mapping[str, Any], library: Library, verify: Verify, *,
                  story: Mapping[str, Any] | None = None, production_id: str | None = None,
                  prefix: str = "") -> BoardMotion:
    """Every loop a ``studio.board/v1`` document plays, and its set loop when ``story``
    (a ``studio.story/v1`` document) is given. ``production_id`` (else the story's)
    scopes the search and the pins; without either, every production's loops count.
    Paths are JSON Pointers into the board (``prefix`` +
    ``/cast/<i>/motion_asset_version_id``) and, for the set, into the story
    (``/set/motion_asset_version_id``). Never raises for a malformed document."""
    board = normalize(board)
    story = None if story is None else normalize(story)
    board_id = _text(_get(board, "id"))
    production = production_id or _text(_get(story, "production_id"))
    if not getattr(verify, "remembers", False):
        verify = remembered(verify)
    clips: list[PinnedClip] = []
    problems: list[Violation] = []
    for i, entry in enumerate(_list(_get(board, "cast"))):
        slot = _text(_get(entry, "slot"))
        pin = _text(_get(entry, "motion_asset_version_id"))
        if slot is None or (pin is None and not needs_loop(board, slot)):
            continue
        path = prefix + pointer("cast", i, "motion_asset_version_id")
        still = _content_sha(library, _get(entry, "asset_version_id"))
        if still is None:
            problems.append(_v(REF_UNKNOWN, prefix + pointer("cast", i, "asset_version_id"),
                               "the cast entry's still is not a library version with bytes"))
            if pin is None:
                continue
        common = dict(path=path, slot=slot, use=LOOP, subject=DOLL, still_sha256=still,
                      verify=verify, board_id=board_id)
        if pin is not None:
            clip, found = _pinned(library, pin, production_id=production, **common)
        else:
            assert still is not None
            clip, found = _choose(library, production_id=production, **common)
        problems += found
        if clip is not None:
            clips.append(clip)
    set_clip = None
    if story is not None and _get(board, "method", "layer") == "layered":
        pin = _text(_get(story, "set", "motion_asset_version_id"))
        still = _content_sha(library, _get(story, "set", "asset_version_id"))
        common = dict(path="/set/motion_asset_version_id", slot=SET_SLOT, use=LOOP, subject=SET,
                      still_sha256=still, verify=verify, board_id=board_id)
        if pin is not None:
            set_clip, found = _pinned(library, pin, production_id=production, **common)
            problems += found
        elif still is not None:
            set_clip, found = _choose(library, production_id=production, absent_ok=True,
                                      **common)
            problems += found
    return BoardMotion(board_id=board_id, cast=tuple(clips), set=set_clip,
                       problems=tuple(sorted(problems, key=lambda v: (v.path, v.rule))))


def resolve_story(story: Mapping[str, Any], library: Library,
                  verify: Verify) -> tuple[BoardMotion, ...]:
    """:func:`resolve_board` for each embedded board of a story, in document order. Each
    layered board reports a problem of the story's set loop itself."""
    story = normalize(story)
    verify = remembered(verify)
    return tuple(resolve_board(board, library, verify, story=story, prefix=pointer("boards", i))
                 for i, board in enumerate(_list(_get(story, "boards")))
                 if isinstance(board, Mapping))


def resolve_timed(library: Library, verify: Verify, *, still_sha256: str,
                  drive_track_sha256: str, board_frames: int, slot: str,
                  production_id: str | None = None, path: str = "",
                  ) -> tuple[PinnedClip | None, tuple[Violation, ...]]:
    """The one promoted timed clip of a cast still made from this drive track (TIME-8,
    TIME-9), checked against the board's frames; a loop is never returned."""
    clip, found = _choose(library, path=path, slot=slot, use=TIMED, subject=DOLL,
                          still_sha256=still_sha256, production_id=production_id,
                          verify=remembered(verify),
                          board_id=None, drive_track_sha256=drive_track_sha256,
                          board_frames=board_frames)
    return clip, tuple(sorted(found, key=lambda v: (v.path, v.rule)))


__all__ = [
    "CLIP_ABSENT", "CLIP_AMBIGUOUS", "CODES", "DRIVE_TRACK_MISMATCH", "KEYING_MISSING",
    "RECORD_MISSING", "STILL_MISMATCH", "TIMED_NOT_LOOP", "BoardMotion", "PinnedClip", "Verify",
    "candidates", "needs_loop", "remembered", "resolve_board", "resolve_story", "resolve_timed",
]
