"""The resolver: every asset version a story or board names resolves to its record,
its pin (content hash, or definition or takes signature) and its locator, or to a
named problem (contract sections 5, 8 and 9).

Whether bytes exist is asked of an injected ``exists(locator, sha256)`` function
(story 379's store, or a synthetic one in tests); nothing here touches a file.
Definition-only versions (``voice``, and a ``board_voice`` whose track was never
assembled) have no locator and ask nothing.

Problems (codes beyond the rule index are proposals of story 382):

- ``ref.unknown``: the library has no version with that ID (story 404's proposal).
- ``asset.kind_mismatch``: the field needs another kind: a cast voice is a ``voice``,
  a board's voice a ``board_voice``, a sound cue or bed a ``sound``, a board cast entry
  a ``cast``, the set a ``set``, its motion a ``motion``, a board photo a ``photo``
  (proposal).
- ``asset.capability_mismatch``: a layered board's cast entry has neither
  ``rgba_cutout`` nor ``keyed_layer`` (section 5, review M6).
- ``asset.bytes_missing``: the store does not hold the version's bytes (proposal).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from haynes_studio.canonical.jsonvalues import normalize
from haynes_studio.errors import Violation, pointer
from haynes_studio.library.library import REF_UNKNOWN, Exists, Library
from haynes_studio.library.model import LAYER_CAPABILITIES
from haynes_studio.library.validate import CAPABILITY_MISMATCH

KIND_MISMATCH = "asset.kind_mismatch"
BYTES_MISSING = "asset.bytes_missing"
STORY_SCHEMA, BOARD_SCHEMA = "studio.story/v1", "studio.board/v1"


@dataclass(frozen=True, slots=True)
class Reference:
    """One asset version ID in a document: where, and what the field needs."""

    path: str  # JSON Pointer into the story or board document
    version_id: str
    kinds: frozenset[str] | None  # None: any kind (a photo's composer inputs)
    layered: bool = False  # a layered board's cast entry needs a layer capability


@dataclass(frozen=True, slots=True)
class Resolved:
    path: str
    version_id: str
    asset_id: str
    kind: str
    number: int
    pin: str  # model.pin: what a snapshot pins
    sha256: str | None  # the content hash; None for definition-only versions
    locator: str | None


@dataclass(frozen=True)
class Resolution:
    references: tuple[Reference, ...]
    resolved: tuple[Resolved, ...]  # every reference whose version the library holds
    problems: tuple[Violation, ...]

    @property
    def complete(self) -> bool:
        """Every reference resolved to a version of the right kind and capability whose
        bytes the store holds."""
        return not self.problems

    def version_ids(self) -> frozenset[str]:
        return frozenset(item.version_id for item in self.resolved)


def _id(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _get(document: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(document, Mapping):
            return None
        document = document.get(key)
    return document


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def board_references(board: Mapping[str, Any], prefix: str = "") -> list[Reference]:
    """The asset version IDs a board names, in document order."""
    refs = []

    def add(path: str, value: Any, kinds: set[str] | None, layered: bool = False) -> None:
        if _id(value) is not None:
            refs.append(Reference(prefix + path, value, None if kinds is None else frozenset(kinds),
                                  layered))

    add("/voice/current_version_id", _get(board, "voice", "current_version_id"), {"board_voice"})
    add("/photo/current_version_id", _get(board, "photo", "current_version_id"), {"photo"})
    for i, value in enumerate(_list(_get(board, "photo", "input_asset_version_ids"))):
        add(pointer("photo", "input_asset_version_ids", i), value, None)
    layered = _get(board, "method", "layer") == "layered"
    for i, entry in enumerate(_list(_get(board, "cast"))):
        add(pointer("cast", i, "asset_version_id"), _get(entry, "asset_version_id"), {"cast"},
            layered)
    for i, cue in enumerate(_list(_get(board, "cues"))):
        if _get(cue, "type") == "sound":
            add(pointer("cues", i, "asset_version_id"), _get(cue, "asset_version_id"), {"sound"})
    return refs


def story_references(story: Mapping[str, Any]) -> list[Reference]:
    """The asset version IDs a story names, its embedded boards included."""
    refs = []
    for i, member in enumerate(_list(_get(story, "cast"))):
        value = _get(member, "voice_version_id")
        if _id(value):
            refs.append(Reference(pointer("cast", i, "voice_version_id"), value,
                                  frozenset({"voice"})))
    for path, value, kind in (
            ("/narrator_voice_version_id", _get(story, "narrator_voice_version_id"), "voice"),
            ("/set/asset_version_id", _get(story, "set", "asset_version_id"), "set"),
            ("/set/motion_asset_version_id", _get(story, "set", "motion_asset_version_id"),
             "motion")):
        if _id(value):
            refs.append(Reference(path, value, frozenset({kind})))
    for i, bed in enumerate(_list(_get(story, "beds"))):
        value = _get(bed, "asset_version_id")
        if _id(value):
            refs.append(Reference(pointer("beds", i, "asset_version_id"), value,
                                  frozenset({"sound"})))
    for i, board in enumerate(_list(_get(story, "boards"))):
        if isinstance(board, Mapping):
            refs += board_references(board, pointer("boards", i))
    return refs


def references(document: Mapping[str, Any]) -> list[Reference]:
    """A story's or a board's references, by its ``schema``."""
    document = normalize(document)
    if _get(document, "schema") == BOARD_SCHEMA:
        return board_references(document)
    return story_references(document)


def resolve(document: Mapping[str, Any], library: Library, exists: Exists) -> Resolution:
    """Resolve every asset version a ``studio.story/v1`` (boards embedded) or
    ``studio.board/v1`` document names, by ID only: the library is never asked for
    "latest". ``exists(locator, sha256)`` is called once per distinct pair."""
    refs = references(document)
    resolved, problems = [], []
    asked: dict[tuple[str, str], bool] = {}

    def held(locator: str, sha256: str) -> bool:
        if (locator, sha256) not in asked:
            asked[(locator, sha256)] = bool(exists(locator, sha256))
        return asked[(locator, sha256)]

    for ref in refs:
        version = library.get(ref.version_id)
        if version is None:
            problems.append(Violation(REF_UNKNOWN, ref.path,
                                      f"the library has no asset version {ref.version_id}"))
            continue
        content = version.content
        resolved.append(Resolved(
            path=ref.path, version_id=version.id, asset_id=version.asset_id, kind=version.kind,
            number=version.number, pin=library.pin(version.id),
            sha256=None if content is None else content.sha256,
            locator=None if content is None else content.locator))
        if ref.kinds is not None and version.kind not in ref.kinds:
            problems.append(Violation(KIND_MISMATCH, ref.path,
                                      f"{version.id} is a {version.kind}; this field needs a "
                                      f"{' or '.join(sorted(ref.kinds))}"))
        if ref.layered and not set(version.capabilities) & LAYER_CAPABILITIES:
            problems.append(Violation(CAPABILITY_MISMATCH, ref.path,
                                      f"{version.id} has {', '.join(version.capabilities)}; a "
                                      "layered cast still needs rgba_cutout or keyed_layer "
                                      "(review M6)"))
        stored = [content] if content is not None else []
        if version.voice is not None and version.voice.track is not None:
            stored.append(version.voice.track)
        for item in stored:
            if not held(item.locator, item.sha256):
                problems.append(Violation(BYTES_MISSING, ref.path,
                                          f"the store does not hold {item.locator}"))
    return Resolution(references=tuple(refs), resolved=tuple(resolved),
                      problems=tuple(sorted(problems, key=lambda v: (v.path, v.rule))))


__all__ = ["BYTES_MISSING", "KIND_MISMATCH", "Reference", "Resolution", "Resolved",
           "board_references", "references", "resolve", "story_references"]
