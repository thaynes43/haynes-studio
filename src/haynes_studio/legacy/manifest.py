"""The legacy manifest, ``legacy.manifest/v1`` (contract sections 1 and 2).

Detects a PoC title manifest by shape, validates it against the shipped JSON Schema
plus the rules the schema cannot express, and loads it, read-only, into one typed
model for The Winter Menu r1 to r4. Nothing here writes or rewrites a legacy file.

Only two defaults are applied, both named by the contract: a later line without
``gap`` gets 300 ms (``edit.resolve_lines``), and a manifest without ``revision`` is
revision 1. Every other absent field stays ``None`` (or an empty tuple for a list).
Times become integer milliseconds, exactly; a seconds value that is not a whole
millisecond is refused (``time.not_integer_ms``), never rounded.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from haynes_studio.errors import ContractError, Violation, blocking, pointer
from haynes_studio.jsonio import freeze, read_json
from haynes_studio.schemas import schema_violations
from haynes_studio.timebase import SECONDS_LIMIT, ms_from_seconds

SCHEMA_NAME = "legacy.manifest/v1"
SCHEMA_FILE = "legacy.manifest.v1.schema.json"
SHAPE_FIELDS = ("shots", "frame", "job")
DEFAULT_GAP_MS = 300
DEFAULT_REVISION = 1
CONTEXTS = ("read", "write", "queue_run")

# Rule codes. The first five are in the contract's rule index; the last two are this
# package's proposals (docs/reference/studio-cli.md, "Rules").
UNSUPPORTED = "schema.unsupported"
DURATION_WITH_LINES = "legacy.duration_with_lines"
NOT_INTEGER_MS = "time.not_integer_ms"
TAIL_TOO_SHORT = "time.tail_too_short"
FIRST_LINE_GAP = "time.first_line_gap"
INVALID = "legacy.invalid"
REFERENCE = "legacy.reference"


# Detection and validation ---------------------------------------------------------


def detect(document: Any) -> str | None:
    """``legacy.manifest/v1`` for an object with ``shots``, ``frame`` and ``job`` and no
    ``schema`` field (contract section 2); otherwise ``None``."""
    if isinstance(document, dict) and "schema" not in document \
            and all(name in document for name in SHAPE_FIELDS):
        return SCHEMA_NAME
    return None


def validate(document: Any, *, context: str = "read") -> list[Violation]:
    """Every rule ``document`` breaks as a legacy manifest; empty means valid.

    The checks are the same in every context: a legacy manifest is only ever read.
    """
    if context not in CONTEXTS:
        raise ValueError(f"unknown context {context!r}")
    if detect(document) is None:
        return [Violation(UNSUPPORTED, "", "not a legacy manifest: needs an object with "
                                           "shots, frame and job, and no schema field")]
    found = schema_violations(SCHEMA_FILE, document, default_rule=INVALID)
    found += _non_finite(document)
    found += _whole_milliseconds(document)
    found += _trim_order(document)
    found += _references(document)
    return sorted(found, key=lambda v: (v.path, v.rule))


def _shots(document: Mapping) -> Iterator[tuple[int, Mapping]]:
    shots = document.get("shots")
    if isinstance(shots, list):
        for i, shot in enumerate(shots):
            if isinstance(shot, dict):
                yield i, shot


def _raw_lines(shot: Mapping) -> list[tuple[str, Any]]:
    """(pointer suffix, line) for the shot's lines, as the legacy ``lines_of`` reads them."""
    if isinstance(shot.get("lines"), list):
        return [(pointer("lines", k), line) for k, line in enumerate(shot["lines"])]
    if "line" in shot:
        return [(pointer("line"), shot["line"])]
    return []


def _dicts(value: Any) -> Iterator[tuple[int, Mapping]]:
    if isinstance(value, list):
        for i, item in enumerate(value):
            if isinstance(item, dict):
                yield i, item


def _seconds_fields(document: Mapping) -> Iterator[tuple[str, Any]]:
    """(pointer, value) for every field the legacy code reads as seconds."""
    for i, shot in _shots(document):
        base = pointer("shots", i)
        for name in ("tail", "duration"):
            if name in shot:
                yield base + pointer(name), shot[name]
        for suffix, line in _raw_lines(shot):
            if isinstance(line, dict):
                for name in ("start", "gap"):
                    if name in line:
                        yield base + suffix + pointer(name), line[name]
        for list_name, names in (("sfx", ("at", "offset")), ("moves", ("at", "offset", "dur"))):
            for j, item in _dicts(shot.get(list_name)):
                for name in names:
                    if name in item:
                        yield base + pointer(list_name, j, name), item[name]
        camera = shot.get("camera")
        if isinstance(camera, dict) and "over" in camera:
            yield base + pointer("camera", "over"), camera["over"]
    sounds = document.get("sfx")
    if isinstance(sounds, dict):
        for name, sound in sounds.items():
            if isinstance(sound, dict) and isinstance(sound.get("trim"), list):
                for j, value in enumerate(sound["trim"]):
                    yield pointer("sfx", name, "trim", j), value


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _integer(value: Any) -> int | None:
    """``value`` as an int if it is a JSON integer (draft 2020-12 counts ``4.0`` as one),
    else ``None``."""
    if isinstance(value, bool) or not _is_number(value):
        return None
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    return value


def _non_finite(value: Any, path: str = "") -> list[Violation]:
    """NaN and infinities, which a document built in memory may hold (strict JSON
    cannot)."""
    if isinstance(value, float) and not math.isfinite(value):
        return [Violation(INVALID, path, "must be a finite number")]
    if isinstance(value, dict):
        return [v for key, item in value.items() for v in _non_finite(item, path + pointer(key))]
    if isinstance(value, list):
        return [v for i, item in enumerate(value) for v in _non_finite(item, path + pointer(i))]
    return []


def _whole_milliseconds(document: Mapping) -> list[Violation]:
    found = []
    for path, value in _seconds_fields(document):
        if not _is_number(value) or not math.isfinite(value):
            continue  # the schema or _non_finite reports it
        if abs(value) >= SECONDS_LIMIT:
            found.append(Violation(INVALID, path, f"{value!r} s is out of range"))
            continue
        try:
            ms_from_seconds(value)
        except ValueError:
            found.append(Violation(NOT_INTEGER_MS, path,
                                   f"{value!r} s is not a whole number of milliseconds"))
    return found


def _trim_order(document: Mapping) -> list[Violation]:
    found = []
    sounds = document.get("sfx")
    for name, sound in (sounds.items() if isinstance(sounds, dict) else ()):
        trim = sound.get("trim") if isinstance(sound, dict) else None
        if isinstance(trim, list) and len(trim) == 2 and all(map(_is_number, trim)) \
                and not trim[0] < trim[1]:
            found.append(Violation(INVALID, pointer("sfx", name, "trim"),
                                   "trim must be [from, to] with from before to"))
    return found


def _references(document: Mapping) -> list[Violation]:
    """References the timeline depends on: unique shot ids (speech records are keyed by
    shot id), cue names in the ``sfx`` table, and ``after_line`` within the shot."""
    found = []
    sounds = document.get("sfx") if isinstance(document.get("sfx"), dict) else {}
    seen: set[int] = set()
    for i, shot in _shots(document):
        base = pointer("shots", i)
        shot_id = _integer(shot.get("id"))
        if shot_id is not None:
            if shot_id in seen:
                found.append(Violation(REFERENCE, base + pointer("id"),
                                       f"shot id {shot_id} is not unique"))
            seen.add(shot_id)
        count = len(_raw_lines(shot))
        for list_name in ("sfx", "moves"):
            for j, item in _dicts(shot.get(list_name)):
                after = _integer(item.get("after_line"))
                if after is not None and after >= count:
                    found.append(Violation(
                        REFERENCE, base + pointer(list_name, j, "after_line"),
                        f"after_line {after} but the shot has {count} line(s)"))
        for j, item in _dicts(shot.get("sfx")):
            cue = item.get("cue")
            if isinstance(cue, str) and cue not in sounds:
                found.append(Violation(REFERENCE, base + pointer("sfx", j, "cue"),
                                       f"sound {cue!r} is not in the manifest's sfx table"))
    return found


# Model ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Frame:
    width: int
    height: int
    fps: int


@dataclass(frozen=True, slots=True)
class CastMember:
    slot: str
    name: str
    voice: str  # a Kokoro stock voice name


@dataclass(frozen=True, slots=True)
class Line:
    """One spoken line. ``k`` is its position in the shot, the ``k`` of speech.json."""

    k: int
    doll: str
    text: str
    gap_ms: int | None  # None on the first line, which starts at the shot's lead_ms
    gap_defaulted: bool  # True when a later line had no gap and took DEFAULT_GAP_MS


@dataclass(frozen=True, slots=True)
class Anchor:
    """Where a cue or move starts: ``at_ms`` from shot start, or ``offset_ms`` after the
    end of line ``after_line``."""

    at_ms: int | None
    after_line: int | None
    offset_ms: int | None


@dataclass(frozen=True, slots=True)
class ShotSound:
    index: int  # position in the shot's sfx list
    cue: str  # a name in the manifest's sfx table
    anchor: Anchor


@dataclass(frozen=True, slots=True)
class Move:
    index: int
    doll: str
    anchor: Anchor
    dur_ms: int | None  # None: absent (the legacy editor read it as 0, instant)
    dx: float | None
    dy: float | None
    angle: float | None


@dataclass(frozen=True, slots=True)
class Camera:
    zoom: tuple[float, float]
    over_ms: int | None  # None: absent (the legacy editor used 400 ms)
    center: tuple[float, float]


@dataclass(frozen=True, slots=True)
class Shot:
    index: int  # position in shots[], from 0
    id: int
    layout: str
    dolls: tuple[tuple[str, str], ...]  # (slot, still path) in draw order
    lead_ms: int | None  # the first line's start; None on a silent shot
    lines: tuple[Line, ...]
    tail_ms: int | None  # spoken shots only
    duration_ms: int | None  # silent shots only (the canonical hold)
    sfx: tuple[ShotSound, ...]
    moves: tuple[Move, ...]
    camera: Camera | None
    foreground: bool | None  # None: absent (the legacy renderer drew the foreground)
    note: str | None
    lines_field: str | None  # "line" or "lines": which legacy field held the lines

    @property
    def spoken(self) -> bool:
        return bool(self.lines)


@dataclass(frozen=True, slots=True)
class Sound:
    """A manifest ``sfx`` entry. ``level_rms_dbfs`` is the legacy ``gain_db``: a target
    RMS level after trimming, not a gain."""

    name: str
    file: str
    trim_ms: tuple[int, int] | None
    level_rms_dbfs: float
    source: Mapping[str, Any] | None
    rejected: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class Bed:
    name: str
    file: str
    level_rms_dbfs: float  # the legacy gain_db, a target RMS level
    source: Mapping[str, Any] | None


@dataclass(frozen=True, slots=True)
class LegacyManifest:
    """One legacy manifest, normalized and read-only. Render presets, the set, motion
    style, master, tolerances and provenance are kept verbatim as read-only JSON."""

    source: str  # the file it was read from, or "<document>"
    sha256: str | None  # of the file's bytes; None when built from a document
    title: str
    story: str | None  # a tracker URL, not a domain story
    job: str
    job_dir: str | None
    revision: int
    revision_field_present: bool
    revision_note: str | None
    frame: Frame
    cast: tuple[CastMember, ...]
    shots: tuple[Shot, ...]
    sfx: tuple[Sound, ...]
    beds: tuple[Bed, ...]
    layouts: Mapping[str, Any] | None
    set: Mapping[str, Any] | None
    motion: Mapping[str, Any] | None
    master: Mapping[str, Any] | None
    asr_tolerances: Mapping[str, str] | None
    asr_tolerances_note: str | None
    provenance: Mapping[str, str] | None

    schema = SCHEMA_NAME

    def sound(self, name: str) -> Sound:
        for sound in self.sfx:
            if sound.name == name:
                return sound
        raise KeyError(name)

    def shot(self, shot_id: int) -> Shot:
        for shot in self.shots:
            if shot.id == shot_id:
                return shot
        raise KeyError(shot_id)


def _ms(value: Any) -> int | None:
    return None if value is None else ms_from_seconds(value)


def _anchor(item: Mapping) -> Anchor:
    return Anchor(at_ms=_ms(item.get("at")), after_line=_integer(item.get("after_line")),
                  offset_ms=_ms(item.get("offset")))


def _shot(index: int, raw: Mapping) -> Shot:
    if "lines" in raw:
        field, raw_lines = "lines", raw["lines"]
    elif "line" in raw:
        field, raw_lines = "line", [raw["line"]]
    else:
        field, raw_lines = None, []
    lines = []
    for k, line in enumerate(raw_lines):
        if k == 0:
            gap, defaulted = None, False
        elif "gap" in line:
            gap, defaulted = ms_from_seconds(line["gap"]), False
        else:
            gap, defaulted = DEFAULT_GAP_MS, True
        lines.append(Line(k=k, doll=line["doll"], text=line["text"], gap_ms=gap,
                          gap_defaulted=defaulted))
    camera = raw.get("camera")
    return Shot(
        index=index,
        id=_integer(raw["id"]),
        layout=raw["layout"],
        dolls=tuple(raw["dolls"].items()),
        lead_ms=ms_from_seconds(raw_lines[0]["start"]) if raw_lines else None,
        lines=tuple(lines),
        tail_ms=_ms(raw.get("tail")),
        duration_ms=_ms(raw.get("duration")),
        sfx=tuple(ShotSound(index=j, cue=item["cue"], anchor=_anchor(item))
                  for j, item in enumerate(raw.get("sfx", []))),
        moves=tuple(Move(index=j, doll=item["doll"], anchor=_anchor(item),
                         dur_ms=_ms(item.get("dur")), dx=item.get("dx"), dy=item.get("dy"),
                         angle=item.get("angle"))
                    for j, item in enumerate(raw.get("moves", []))),
        camera=None if camera is None else Camera(
            zoom=tuple(camera["zoom"]), over_ms=_ms(camera.get("over")),
            center=tuple(camera["center"])),
        foreground=raw.get("foreground"),
        note=raw.get("note"),
        lines_field=field,
    )


def _optional(document: Mapping, name: str) -> Any:
    return freeze(document[name]) if name in document else None


def from_document(document: Any, *, source: str = "<document>",
                  sha256: str | None = None) -> LegacyManifest:
    """The typed model of a legacy manifest document. Raises :class:`ContractError`
    listing every violation if it is not a valid ``legacy.manifest/v1``."""
    problems = blocking(validate(document))
    if problems:
        raise ContractError(source, problems)
    sounds = document.get("sfx", {})
    beds = document.get("beds", {})
    return LegacyManifest(
        source=source,
        sha256=sha256,
        title=document["title"],
        story=document.get("story"),
        job=document["job"],
        job_dir=document.get("job_dir"),
        revision=_integer(document.get("revision", DEFAULT_REVISION)),
        revision_field_present="revision" in document,
        revision_note=document.get("revision_note"),
        frame=Frame(**{name: _integer(value) for name, value in document["frame"].items()}),
        cast=tuple(CastMember(slot=slot, name=member["name"], voice=member["voice"])
                   for slot, member in document.get("cast", {}).items()),
        shots=tuple(_shot(i, shot) for i, shot in enumerate(document["shots"])),
        sfx=tuple(Sound(name=name, file=spec["file"],
                        trim_ms=(tuple(ms_from_seconds(v) for v in spec["trim"])
                                 if "trim" in spec else None),
                        level_rms_dbfs=spec["gain_db"], source=_optional(spec, "source"),
                        rejected=freeze(spec.get("rejected", [])))
                  for name, spec in sounds.items()),
        beds=tuple(Bed(name=name, file=spec["file"], level_rms_dbfs=spec["gain_db"],
                       source=_optional(spec, "source"))
                   for name, spec in beds.items()),
        layouts=_optional(document, "layouts"),
        set=_optional(document, "set"),
        motion=_optional(document, "motion"),
        master=_optional(document, "master"),
        asr_tolerances=_optional(document, "asr_tolerances"),
        asr_tolerances_note=document.get("asr_tolerances_note"),
        provenance=_optional(document, "provenance"),
    )


def load(path: str | Path) -> LegacyManifest:
    """Read a legacy manifest file (never written). ``OSError`` if unreadable;
    :class:`ContractError` naming the file, rule and path if it is not valid."""
    try:
        parsed = read_json(path)
    except ValueError as error:
        raise ContractError(str(path), [Violation(INVALID, "", str(error).split(": ", 1)[-1])]) \
            from None
    return from_document(parsed.document, source=parsed.label, sha256=parsed.sha256)
