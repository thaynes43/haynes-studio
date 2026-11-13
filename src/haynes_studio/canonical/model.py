"""Read-only typed models of the canonical documents (contract sections 2, 5 and 6).

Each model is a frozen dataclass whose field names are the JSON field names, built
with ``from_document`` from a document that has passed its validator, and turned
back into JSON with :func:`to_document`. ``from_document`` reads a normalized copy
(:func:`~haynes_studio.canonical.jsonvalues.normalize`: integral floats are ints). Verbatim legacy JSON (layout presets, the
legacy fire, motion style) stays a read-only mapping. Nothing here reads files,
calls services or knows about the command line.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from haynes_studio.canonical.jsonvalues import integral, normalize
from haynes_studio.jsonio import freeze, thaw

BOARD_SCHEMA = "studio.board/v1"
STORY_SCHEMA = "studio.story/v1"
PRODUCTION_SCHEMA = "studio.production/v1"
STORY_TIMING_SCHEMA = "studio.story-timing/v1"
METHOD_CAPABILITIES_SCHEMA = "studio.method-capabilities/v1"
LEGACY_IMPORT_SCHEMA = "studio.legacy-import/v1"
NARRATOR = "narrator"


def to_document(value: Any) -> Any:
    """Plain JSON (dicts, lists, scalars) for a model, a tuple or a frozen mapping.
    A dataclass may name ``_omit_none`` fields, which are left out when ``None``."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        omit = getattr(value, "_omit_none", ())
        out = {}
        for item in dataclasses.fields(value):
            if item.name.startswith("_"):
                continue
            field_value = getattr(value, item.name)
            if field_value is None and item.name in omit:
                continue
            out[item.name] = to_document(field_value)
        return out
    if isinstance(value, MappingProxyType | dict):
        return {key: to_document(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [to_document(item) for item in value]
    return value


def _verbatim(value: Any) -> Any:
    return None if value is None else freeze(value)


# Principals ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Principal:
    """``{kind: human, iss, sub}``, ``{kind: agent, key_id}``, ``{kind: worker,
    worker_id}`` or ``{kind: cli, command, operator}`` (contract section 2)."""

    kind: str
    iss: str | None = None
    sub: str | None = None
    key_id: str | None = None
    worker_id: str | None = None
    command: str | None = None
    operator: Principal | None = None

    _omit_none = ("iss", "sub", "key_id", "worker_id", "command", "operator")

    @classmethod
    def from_document(cls, doc: Mapping[str, Any]) -> Principal:
        operator = doc.get("operator")
        return cls(kind=doc["kind"], iss=doc.get("iss"), sub=doc.get("sub"),
                   key_id=doc.get("key_id"), worker_id=doc.get("worker_id"),
                   command=doc.get("command"),
                   operator=None if operator is None else cls.from_document(operator))

    @classmethod
    def cli(cls, command: str, iss: str, sub: str) -> Principal:
        return cls(kind="cli", command=command, operator=cls(kind="human", iss=iss, sub=sub))


def _principal(doc: Any) -> Principal | None:
    return None if doc is None else Principal.from_document(doc)


# Board --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Line:
    id: str
    speaker: str  # a cast slot a..z, or "narrator"
    text: str
    gap_before_ms: int | None  # None on the first line (TIME-2)


@dataclass(frozen=True, slots=True)
class Timing:
    lead_ms: int | None
    tail_ms: int | None
    hold_ms: int | None


@dataclass(frozen=True, slots=True)
class Voice:
    style: str | None  # "cast", "narrator", or None on a silent board
    current_version_id: str | None


@dataclass(frozen=True, slots=True)
class Photo:
    current_version_id: str | None
    prompt: str | None
    input_asset_version_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CastEntry:
    slot: str
    asset_version_id: str
    # Story 457 (proposal): an optional pin of the still's motion loop; absent when None.
    motion_asset_version_id: str | None = None

    _omit_none = ("motion_asset_version_id",)


@dataclass(frozen=True, slots=True)
class Layout:
    preset: str
    foreground: bool


@dataclass(frozen=True, slots=True)
class Method:
    layer: str  # "layered" or "whole_frame"
    motion: str  # "s2v" or "i2v"


@dataclass(frozen=True, slots=True)
class Anchor:
    """``{at_ms}`` from board start, or ``{after_line_id, offset_ms}``."""

    at_ms: int | None = None
    after_line_id: str | None = None
    offset_ms: int | None = None

    _omit_none = ("at_ms", "after_line_id", "offset_ms")

    @classmethod
    def from_document(cls, doc: Mapping[str, Any]) -> Anchor:
        return cls(at_ms=doc.get("at_ms"), after_line_id=doc.get("after_line_id"),
                   offset_ms=doc.get("offset_ms"))


@dataclass(frozen=True, slots=True)
class SoundCue:
    id: str
    type: str  # "sound"
    asset_version_id: str
    anchor: Anchor
    trim_ms: tuple[int, int] | None
    level_rms_dbfs: float  # target RMS after trim, not a gain


@dataclass(frozen=True, slots=True)
class MoveCue:
    id: str
    type: str  # "move"
    slot: str
    anchor: Anchor
    duration_ms: int
    dx_px: float
    dy_px: float
    angle_deg: float
    steps: int


@dataclass(frozen=True, slots=True)
class CameraCue:
    id: str
    type: str  # "camera"
    anchor: Anchor
    duration_ms: int
    zoom_from: float
    zoom_to: float
    center_px: tuple[float, float]
    easing: str


@dataclass(frozen=True, slots=True)
class BedCue:
    id: str
    type: str  # "bed"
    asset_version_id: str
    level_rms_dbfs: float
    clock: str  # "film"


BoardCue = SoundCue | MoveCue | CameraCue


def _cue(doc: Mapping[str, Any]) -> BoardCue:
    anchor = Anchor.from_document(doc["anchor"])
    if doc["type"] == "sound":
        trim = doc["trim_ms"]
        return SoundCue(id=doc["id"], type="sound", asset_version_id=doc["asset_version_id"],
                        anchor=anchor, trim_ms=None if trim is None else tuple(trim),
                        level_rms_dbfs=doc["level_rms_dbfs"])
    if doc["type"] == "move":
        return MoveCue(id=doc["id"], type="move", slot=doc["slot"], anchor=anchor,
                       duration_ms=doc["duration_ms"], dx_px=doc["dx_px"], dy_px=doc["dy_px"],
                       angle_deg=doc["angle_deg"], steps=doc["steps"])
    return CameraCue(id=doc["id"], type="camera", anchor=anchor, duration_ms=doc["duration_ms"],
                     zoom_from=doc["zoom_from"], zoom_to=doc["zoom_to"],
                     center_px=tuple(doc["center_px"]), easing=doc["easing"])


@dataclass(frozen=True, slots=True)
class Note:
    id: str
    text: str


@dataclass(frozen=True, slots=True)
class BoardOrigin:
    source_key: str
    legacy_revision: int
    legacy_shot: int
    manifest: str


@dataclass(frozen=True, slots=True)
class BoardDerived:
    timing_state: str  # "timed" or "untimed"
    content_ms: int | None
    frames: int | None
    film_start_frame: int | None
    voice_state: str  # not_needed, absent, generating, current, stale
    photo_state: str  # absent, generating, current, stale


@dataclass(frozen=True, slots=True)
class Board:
    schema: str
    id: str
    story_id: str
    number: int
    revision: int
    title: str
    lines: tuple[Line, ...]
    timing: Timing
    voice: Voice
    photo: Photo
    cast: tuple[CastEntry, ...]
    layout: Layout
    method: Method
    seeds: Mapping[str, int]
    cues: tuple[BoardCue, ...]
    notes: tuple[Note, ...]
    drafted_by: Principal
    origin: BoardOrigin | None
    derived: BoardDerived | None = None
    created_at: str | None = None
    updated_at: str | None = None

    _omit_none = ("derived", "created_at", "updated_at")

    @property
    def spoken(self) -> bool:
        return bool(self.lines)

    @property
    def placed_slots(self) -> tuple[str, ...]:
        return tuple(entry.slot for entry in self.cast)

    @classmethod
    def from_document(cls, doc: Mapping[str, Any]) -> Board:
        """The model of a board document that has passed :func:`validate_board`."""
        doc = normalize(doc)
        origin, derived = doc.get("origin"), doc.get("derived")
        photo = doc["photo"]
        return cls(
            schema=doc["schema"], id=doc["id"], story_id=doc["story_id"], number=doc["number"],
            revision=doc["revision"], title=doc["title"],
            lines=tuple(Line(**line) for line in doc["lines"]),
            timing=Timing(**{key: doc["timing"][key] for key in ("lead_ms", "tail_ms", "hold_ms")}),
            voice=Voice(**doc["voice"]),
            photo=Photo(current_version_id=photo["current_version_id"], prompt=photo["prompt"],
                        input_asset_version_ids=tuple(photo["input_asset_version_ids"])),
            cast=tuple(CastEntry(**entry) for entry in doc["cast"]),
            layout=Layout(**doc["layout"]), method=Method(**doc["method"]),
            seeds=MappingProxyType(dict(doc["seeds"])),
            cues=tuple(_cue(cue) for cue in doc["cues"]),
            notes=tuple(Note(id=note["id"], text=note["text"]) for note in doc["notes"]),
            drafted_by=Principal.from_document(doc["drafted_by"]),
            origin=None if origin is None else BoardOrigin(**origin),
            derived=None if derived is None else BoardDerived(**derived),
            created_at=doc.get("created_at"), updated_at=doc.get("updated_at"),
        )


# Story --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StoryCast:
    slot: str
    name: str
    voice_version_id: str


@dataclass(frozen=True, slots=True)
class StorySet:
    asset_version_id: str | None
    motion_asset_version_id: str | None
    foreground_edge_px: tuple[tuple[float, float], ...] | None
    foreground_feather_px: float | None
    legacy_fire: Mapping[str, Any] | None  # read only by the rigid renderer
    note: str | None = None  # optional in the schema: left out when absent or null

    _omit_none = ("note",)


@dataclass(frozen=True, slots=True)
class Mix:
    line_rms_dbfs: float
    master_lufs: float
    true_peak_dbtp: float


@dataclass(frozen=True, slots=True)
class Checks:
    """Both fields are optional in the schema: left out when absent or null."""

    asr_tolerances: Mapping[str, str] | None = None
    asr_tolerances_note: str | None = None

    _omit_none = ("asr_tolerances", "asr_tolerances_note")


@dataclass(frozen=True, slots=True)
class StoryOrigin:
    source_key: str
    legacy_revision: int
    tracker: str | None
    manifest: str


@dataclass(frozen=True, slots=True)
class DocWarning:
    code: str
    severity: str
    message: str
    build_allowed: bool | None = None
    decision: str | None = None

    _omit_none = ("build_allowed", "decision")


@dataclass(frozen=True, slots=True)
class StoryDerived:
    board_count: int
    next_board_number: int
    timed_boards: int
    untimed_boards: int
    frames: int  # timed boards only: a lower bound while untimed_boards > 0 (TIME-6)
    fps: int
    duration_ms: int  # floor(frames * 1000 / fps)
    warnings: tuple[DocWarning, ...]


@dataclass(frozen=True, slots=True)
class Story:
    schema: str
    id: str
    production_id: str
    media_kind: str
    title: str
    revision: int
    format_version_id: str | None
    cast: tuple[StoryCast, ...]
    narrator_voice_version_id: str | None
    set: StorySet | None
    layouts: Mapping[str, Any]
    motion_style: Mapping[str, Any] | None
    mix: Mix
    checks: Checks
    beds: tuple[BedCue, ...]
    board_order: tuple[str, ...]
    boards: tuple[Board, ...] | None  # exchange and snapshot form only
    origin: StoryOrigin | None
    derived: StoryDerived | None = None
    created_at: str | None = None
    updated_at: str | None = None
    created_by: Principal | None = None

    _omit_none = ("boards", "derived", "created_at", "updated_at", "created_by")

    @property
    def slots(self) -> tuple[str, ...]:
        return tuple(member.slot for member in self.cast)

    def ordered_boards(self) -> tuple[Board, ...]:
        """The embedded boards in ``board_order``."""
        by_id = {board.id: board for board in self.boards or ()}
        return tuple(by_id[board_id] for board_id in self.board_order)

    @classmethod
    def from_document(cls, doc: Mapping[str, Any]) -> Story:
        """The model of a story document that has passed :func:`validate_story`."""
        doc = normalize(doc)
        story_set, origin, derived = doc["set"], doc["origin"], doc.get("derived")
        boards = doc.get("boards")
        return cls(
            schema=doc["schema"], id=doc["id"], production_id=doc["production_id"],
            media_kind=doc["media_kind"], title=doc["title"], revision=doc["revision"],
            format_version_id=doc["format_version_id"],
            cast=tuple(StoryCast(**member) for member in doc["cast"]),
            narrator_voice_version_id=doc["narrator_voice_version_id"],
            set=None if story_set is None else StorySet(
                asset_version_id=story_set["asset_version_id"],
                motion_asset_version_id=story_set["motion_asset_version_id"],
                foreground_edge_px=(None if story_set["foreground_edge_px"] is None else
                                    tuple(tuple(point) for point in story_set["foreground_edge_px"])),
                foreground_feather_px=story_set["foreground_feather_px"],
                legacy_fire=_verbatim(story_set["legacy_fire"]), note=story_set.get("note")),
            layouts=freeze(doc["layouts"]), motion_style=_verbatim(doc["motion_style"]),
            mix=Mix(**doc["mix"]), checks=Checks(**doc["checks"]),
            beds=tuple(BedCue(**bed) for bed in doc["beds"]),
            board_order=tuple(doc["board_order"]),
            boards=None if boards is None else tuple(Board.from_document(b) for b in boards),
            origin=None if origin is None else StoryOrigin(**origin),
            derived=None if derived is None else StoryDerived(
                **{**derived, "warnings": tuple(DocWarning(**w) for w in derived["warnings"])}),
            created_at=doc.get("created_at"), updated_at=doc.get("updated_at"),
            created_by=_principal(doc.get("created_by")),
        )


# Production -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MediaType:
    kind: str  # "short" (9:16, 1080x1920) or "video" (16:9, 1920x1080, P-20)
    aspect: str
    width: int
    height: int
    fps: int
    enabled_at: str


@dataclass(frozen=True, slots=True)
class Production:
    schema: str
    id: str
    name: str
    revision: int
    media_types: tuple[MediaType, ...]
    labels: tuple[str, ...]
    created_at: str | None = None
    updated_at: str | None = None
    created_by: Principal | None = None

    _omit_none = ("created_at", "updated_at", "created_by")

    @property
    def enabled_kinds(self) -> frozenset[str]:
        return frozenset(media.kind for media in self.media_types)

    @classmethod
    def from_document(cls, doc: Mapping[str, Any]) -> Production:
        doc = normalize(doc)
        return cls(schema=doc["schema"], id=doc["id"], name=doc["name"],
                   revision=doc["revision"],
                   media_types=tuple(MediaType(**media) for media in doc["media_types"]),
                   labels=tuple(doc["labels"]), created_at=doc.get("created_at"),
                   updated_at=doc.get("updated_at"),
                   created_by=_principal(doc.get("created_by")))


# Story timing ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BoardTimingRow:
    board_id: str
    state: str
    frames: int | None
    film_start_frame: int | None
    reason: str | None = None  # voice.absent or voice.stale on an untimed board

    _omit_none = ("reason",)


@dataclass(frozen=True, slots=True)
class FormatLength:
    """A format's length range (D45). Formats arrive with story 447; until then the
    caller supplies it."""

    format_version_id: str
    min_ms: int
    max_ms: int
    source: str | None = None

    _omit_none = ("source",)

    def __post_init__(self) -> None:
        for name in ("min_ms", "max_ms"):  # integral floats are integers
            object.__setattr__(self, name, integral(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class BuildBlocker:
    code: str
    board_id: str | None = None
    path: str | None = None

    _omit_none = ("board_id", "path")


@dataclass(frozen=True, slots=True)
class StoryTiming:
    schema: str
    story_id: str
    story_revision: int
    fps: int
    boards: tuple[BoardTimingRow, ...]
    frames_known: int
    complete: bool
    format_length: FormatLength | None
    warnings: tuple[DocWarning, ...]
    build_allowed: bool
    build_blockers: tuple[BuildBlocker, ...]

    @classmethod
    def from_document(cls, doc: Mapping[str, Any]) -> StoryTiming:
        doc = normalize(doc)
        length = doc["format_length"]
        return cls(schema=doc["schema"], story_id=doc["story_id"],
                   story_revision=doc["story_revision"], fps=doc["fps"],
                   boards=tuple(BoardTimingRow(**row) for row in doc["boards"]),
                   frames_known=doc["frames_known"], complete=doc["complete"],
                   format_length=None if length is None else FormatLength(**length),
                   warnings=tuple(DocWarning(**w) for w in doc["warnings"]),
                   build_allowed=doc["build_allowed"],
                   build_blockers=tuple(BuildBlocker(**b) for b in doc["build_blockers"]))


# Method capabilities --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MethodCell:
    layer: str
    motion: str
    status: str  # "buildable" or "unavailable"
    adapter_story: int | None
    evidence: tuple[str, ...]
    profile: Mapping[str, Any] | None = None
    reason: str | None = None

    _omit_none = ("profile", "reason")


@dataclass(frozen=True, slots=True)
class MethodCapabilities:
    schema: str
    contract: str
    cells: tuple[MethodCell, ...]
    rules: tuple[str, ...]

    def status(self, layer: str, motion: str) -> str | None:
        for cell in self.cells:
            if (cell.layer, cell.motion) == (layer, motion):
                return cell.status
        return None

    @classmethod
    def from_document(cls, doc: Mapping[str, Any]) -> MethodCapabilities:
        doc = normalize(doc)
        return cls(schema=doc["schema"], contract=doc["contract"],
                   cells=tuple(MethodCell(**{**cell, "evidence": tuple(cell["evidence"]),
                                             "profile": _verbatim(cell.get("profile"))})
                               for cell in doc["cells"]),
                   rules=tuple(doc["rules"]))


# Legacy import map ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LegacyImport:
    """The import map (``studio.legacy-import/v1``), kept as read-only JSON with typed
    lookups: the importer reads IDs from it and returns an updated copy."""

    document: Mapping[str, Any]

    @property
    def boards_field(self) -> str:
        return f"boards_from_r{self.document['draft_from_revision']}"

    @classmethod
    def from_document(cls, doc: Mapping[str, Any]) -> LegacyImport:
        return cls(document=freeze(normalize(doc)))

    def to_json(self) -> dict[str, Any]:
        return thaw(self.document)
