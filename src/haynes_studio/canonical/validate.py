"""One validator per canonical type, called with a context: ``read`` (a document as
the server returns it, ``derived`` allowed), ``write`` (as a client sends it) or
``queue_run`` (the draft is about to be built).

Each validator first refuses a document that nests deeper than
:data:`~haynes_studio.canonical.jsonvalues.MAX_DEPTH` levels and then reads a
normalized copy (integral floats such as ``1900.0`` are ints), so the schema, the code
rules, the models and the derived values see the same numbers.

Each rule is checked in exactly one place. The JSON Schema file reports field rules
through its ``x-studio`` annotations (identifiers, integer and bounded times, a board's
spoken or silent shape, ``method.unknown``, ``cue.type_unknown``,
``time.duration_is_derived``); anything else it rejects is ``schema.unknown_field`` or
the generic ``schema.invalid``. The code here checks what needs more than one field or
facts JSON Schema cannot hold, and runs only on the parts of a document the schema
accepted, so a malformed document never raises. Rules that need the asset library take
:class:`~haynes_studio.canonical.facts.Facts`.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Collection, Iterable, Mapping
from typing import Any

from haynes_studio.canonical import methods
from haynes_studio.canonical.derive import (
    ABSENT,
    GENERATING,
    METHOD_UNAVAILABLE,
    STALE,
    TIMED,
    board_clock,
    length_warning,
    photo_state,
    resolve_anchor,
    voice_state,
)
from haynes_studio.canonical.facts import NO_FACTS, Facts
from haynes_studio.canonical.jsonvalues import MAX_DEPTH, normalize, too_deep
from haynes_studio.canonical.model import (
    BOARD_SCHEMA,
    LEGACY_IMPORT_SCHEMA,
    METHOD_CAPABILITIES_SCHEMA,
    NARRATOR,
    PRODUCTION_SCHEMA,
    STORY_SCHEMA,
    STORY_TIMING_SCHEMA,
    Board,
    FormatLength,
)
from haynes_studio.errors import INVALID, WARNING, Violation, pointer
from haynes_studio.schemas import UNKNOWN_FIELD, schema_violations

READ, WRITE, QUEUE_RUN = "read", "write", "queue_run"
CONTEXTS = (READ, WRITE, QUEUE_RUN)
UNAVAILABLE = "unavailable"

SCHEMA_INVALID = "schema.invalid"
SCHEMA_UNSUPPORTED = "schema.unsupported"
# Proposals of story 404 (not yet in the rule index): references inside a document.
REF_UNKNOWN = "ref.unknown"
REF_DUPLICATE = "ref.duplicate"
BOARD_ORDER = "story.board_order"

LAYERED, WHOLE_FRAME, S2V, I2V = "layered", "whole_frame", "s2v", "i2v"
LAYER_CAPABILITIES = frozenset({"rgba_cutout", "keyed_layer"})
NOTE_FIELDS = frozenset({"id", "text"})

SCHEMA_FILES = {
    BOARD_SCHEMA: "studio.board.v1.schema.json",
    STORY_SCHEMA: "studio.story.v1.schema.json",
    PRODUCTION_SCHEMA: "studio.production.v1.schema.json",
    STORY_TIMING_SCHEMA: "studio.story-timing.v1.schema.json",
    METHOD_CAPABILITIES_SCHEMA: "studio.method-capabilities.v1.schema.json",
    LEGACY_IMPORT_SCHEMA: "studio.legacy-import.v1.schema.json",
}


def _v(rule: str, path: str, message: str, status: str = INVALID) -> Violation:
    return Violation(rule, path, message, status)


def _sorted(found: Iterable[Violation]) -> list[Violation]:
    unique = {(v.path, v.rule, v.message, v.status): v for v in found}
    return [unique[key] for key in sorted(unique)]


def _check_context(context: str) -> None:
    if context not in CONTEXTS:
        raise ValueError(f"context must be one of {', '.join(CONTEXTS)}, got {context!r}")


def _prepare(document: Any, name: str) -> tuple[Any, list[Violation] | None]:
    """The normalized document, and the violations that stop validation early: it
    nests too deeply, or it is not an object of this schema and major."""
    if too_deep(document):
        return document, [_v(SCHEMA_INVALID, "", f"nests deeper than {MAX_DEPTH} levels")]
    document = normalize(document)
    if not isinstance(document, dict):
        return document, [_v(SCHEMA_INVALID, "", "must be a JSON object")]
    schema = document.get("schema")
    if schema is None:
        return document, [_v(SCHEMA_INVALID, "/schema", f"required: {name!r}")]
    if schema != name:
        return document, [_v(SCHEMA_UNSUPPORTED, "/schema",
                             f"{schema!r} is not supported here; this reader implements {name!r}")]
    return document, None


def _no_derived(document: Mapping, context: str, prefix: str = "") -> list[Violation]:
    """``derived`` is computed by the server: returned on reads, rejected on writes."""
    if context != READ and "derived" in document:
        return [_v(UNKNOWN_FIELD, prefix + "/derived",
                   "derived values are computed by the server and not accepted on write")]
    return []


def _schema(name: str, document: Mapping) -> list[Violation]:
    return schema_violations(SCHEMA_FILES[name], document, default_rule=SCHEMA_INVALID)


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def _blocking(found: Iterable[Violation]) -> list[Violation]:
    return [v for v in found if v.status != WARNING]


def _duplicates(items: Iterable[tuple[str, Any]], what: str) -> list[Violation]:
    """``ref.duplicate`` for every value seen before; ``items`` are (path, value)."""
    seen: dict[Any, str] = {}
    found = []
    for path, value in items:
        if value in seen:
            found.append(_v(REF_DUPLICATE, path, f"{what} {value!r} is already used at {seen[value]}"))
        else:
            seen[value] = path
    return found


# Board ---------------------------------------------------------------------------------


def validate_board(document: Any, *, context: str = READ, facts: Facts | None = None,
                   story_cast: Collection[str] | None = None,
                   story_layouts: Collection[str] | None = None) -> list[Violation]:
    """Every rule a ``studio.board/v1`` document breaks, sorted by path.

    ``story_cast`` (the story's cast slots) and ``story_layouts`` (its preset names)
    enable the speaker rule (VOICE-1) and the slot and layout references; ``facts``
    supplies measured takes, voice and photo states and capabilities. Without them
    those checks do not run, except at ``queue_run``, where a voice the facts do not
    know is ``voice.absent``."""
    _check_context(context)
    document, stop = _prepare(document, BOARD_SCHEMA)
    if stop is not None:
        return stop
    found = _no_derived(document, context) + _schema(BOARD_SCHEMA, document)
    if not _blocking(found):
        found += board_rules(document, "", context=context, facts=facts or NO_FACTS,
                             story_cast=story_cast, story_layouts=story_layouts)
    return _sorted(found)


def board_rules(document: Mapping, prefix: str, *, context: str, facts: Facts,
                story_cast: Collection[str] | None, story_layouts: Collection[str] | None,
                check_ids: bool = True) -> list[Violation]:
    """The code rules of one normalized, schema-valid board, paths under ``prefix``.
    The schema has already checked the board's spoken or silent shape (lead, tail,
    hold, gaps and voice; TIME-2 to TIME-5), so its clock can be computed."""
    board = Board.from_document(document)
    at = lambda *parts: prefix + pointer(*parts)  # noqa: E731
    found: list[Violation] = []

    # Speakers: VOICE-1.
    for i, line in enumerate(board.lines):
        if line.speaker == NARRATOR:
            if board.voice.style != NARRATOR:
                found.append(_v("voice.speaker_not_in_cast", at("lines", i, "speaker"),
                                "narrator lines need a board whose voice style is narrator (VOICE-1)"))
        elif story_cast is not None and line.speaker not in story_cast:
            found.append(_v("voice.speaker_not_in_cast", at("lines", i, "speaker"),
                            f"speaker {line.speaker!r} is not a story cast slot (VOICE-1)"))

    # Slots the board places or seeds must be the story's.
    if story_cast is not None:
        for i, entry in enumerate(board.cast):
            if entry.slot not in story_cast:
                found.append(_v(REF_UNKNOWN, at("cast", i, "slot"),
                                f"slot {entry.slot!r} is not a story cast slot"))
        for key in board.seeds:
            kind, _, slot = key.partition(":")
            if kind == S2V and slot not in story_cast:
                found.append(_v(REF_UNKNOWN, at("seeds", key),
                                f"seed {key!r} names slot {slot!r}, which is not a story cast slot"))

    # Method matrix: section 5.
    method = board.method
    if method.motion == S2V:
        if not board.spoken:
            found.append(_v("method.s2v_needs_line", at("method", "motion"),
                            "speech-to-video needs at least one line (D38)"))
        elif not any(line.speaker in board.placed_slots for line in board.lines):
            found.append(_v("method.s2v_needs_onscreen_speaker", at("method", "motion"),
                            "speech-to-video needs a line spoken by a cast slot on the board (P-08)"))
    if method.layer == LAYERED:
        if not board.cast:
            found.append(_v("method.layered_needs_cast", at("cast"),
                            "a layered board needs cast; use whole-frame I2V for an empty set (P-08)"))
        for i, entry in enumerate(board.cast):
            capabilities = facts.capabilities.get(entry.asset_version_id)
            if capabilities is not None and not capabilities & LAYER_CAPABILITIES:
                found.append(_v("asset.capability_mismatch", at("cast", i, "asset_version_id"),
                                "a layered cast still needs rgba_cutout or keyed_layer (review M6)"))
            # Story 457 (proposal): a pinned motion loop is a doll clip.
            motion = (None if entry.motion_asset_version_id is None
                      else facts.capabilities.get(entry.motion_asset_version_id))
            if motion is not None and "motion_clip" not in motion:
                found.append(_v("asset.capability_mismatch",
                                at("cast", i, "motion_asset_version_id"),
                                "a cast still's motion pin is a doll clip (motion_clip)"))
    if methods.status(method.layer, method.motion) == methods.UNAVAILABLE:
        found.append(_v(METHOD_UNAVAILABLE, at("method"),
                        "whole-frame speech-to-video has no adapter yet; it saves and Build refuses it",
                        UNAVAILABLE if context == QUEUE_RUN else WARNING))

    # References inside the board.
    if story_layouts is not None and board.layout.preset not in story_layouts:
        found.append(_v(REF_UNKNOWN, at("layout", "preset"),
                        f"layout preset {board.layout.preset!r} is not in the story's layouts"))
    found += _duplicates(((at("cast", i, "slot"), e.slot) for i, e in enumerate(board.cast)),
                         "cast slot")
    if check_ids:
        found += _duplicates(_board_ids(board, prefix), "ID")

    # Cues: section 6 and TIME-10. An untimed board's cue range waits for queue_run.
    line_ids = {line.id for line in board.lines}
    clock = board_clock(board, facts)
    for i, cue in enumerate(board.cues):
        anchor = cue.anchor
        if anchor.after_line_id is not None and anchor.after_line_id not in line_ids:
            found.append(_v("cue.anchor_line_missing", at("cues", i, "anchor", "after_line_id"),
                            "the anchor line is not on this board"))
            continue
        if cue.type == "move" and cue.slot not in board.placed_slots:
            found.append(_v("cue.slot_not_on_board", at("cues", i, "slot"),
                            f"slot {cue.slot!r} is not placed on this board"))
        if cue.type == "sound" and cue.trim_ms is not None and cue.trim_ms[0] >= cue.trim_ms[1]:
            found.append(_v(SCHEMA_INVALID, at("cues", i, "trim_ms"),
                            "trim_ms must be [from, to] with from before to"))
        if clock is not None:
            start = resolve_anchor(anchor, clock)
            if not clock.contains(start):
                field = "at_ms" if anchor.at_ms is not None else "offset_ms"
                found.append(_v("cue.out_of_range", at("cues", i, "anchor", field),
                                f"starts at {start} ms, outside the board's {clock.frames} "
                                "frames (TIME-10)"))

    # Notes: free text only (control characters are the schema's).
    for i, raw in enumerate(document["notes"]):
        extra = sorted(set(raw) - NOTE_FIELDS)
        if extra:
            found.append(_v("note.text_only", at("notes", i),
                            f"a note is text only; cue fields {', '.join(extra)} belong in cues"))
        elif not unicodedata.is_normalized("NFC", raw["text"]):
            found.append(_v(SCHEMA_INVALID, at("notes", i, "text"), "note text must be NFC"))

    if context == QUEUE_RUN:
        found += _queue_board(board, at, facts)
    return found


def _board_ids(board: Board, prefix: str) -> Iterable[tuple[str, str]]:
    yield prefix + "/id", board.id
    for i, line in enumerate(board.lines):
        yield prefix + pointer("lines", i, "id"), line.id
    for i, cue in enumerate(board.cues):
        yield prefix + pointer("cues", i, "id"), cue.id
    for i, note in enumerate(board.notes):
        yield prefix + pointer("notes", i, "id"), note.id


def _queue_board(board: Board, at, facts: Facts) -> list[Violation]:
    """What Build needs that a draft may lack (TIME-6, VOICE-6, section 5)."""
    found = []
    voice = voice_state(board, facts)
    if voice == ABSENT:
        found.append(_v("voice.absent", at("voice", "current_version_id"),
                        "a spoken board needs a current voice before Build (VOICE-6)"))
    elif voice == STALE:
        found.append(_v("voice.stale", at("voice", "current_version_id"),
                        "the board's voice no longer matches its lines (VOICE-4)"))
    elif voice == GENERATING:
        found.append(_v("asset.generating", at("voice"), "a voice job is still running"))
    photo = photo_state(board, facts)
    if photo == GENERATING:
        found.append(_v("asset.generating", at("photo"), "a photo job is still running"))
    elif (board.method.layer, board.method.motion) == (WHOLE_FRAME, I2V) and photo == ABSENT:
        found.append(_v("photo.absent", at("photo", "current_version_id"),
                        "whole-frame I2V starts from the board's photo (section 5)"))
    return found


# Story ---------------------------------------------------------------------------------


def validate_story(document: Any, *, context: str = READ, facts: Facts | None = None,
                   enabled_media_kinds: Collection[str] | None = None,
                   format_length: FormatLength | None = None) -> list[Violation]:
    """Every rule a ``studio.story/v1`` document breaks, its embedded ``boards[]``
    included (each against the story's cast and layouts). ``enabled_media_kinds``
    (the production's) and ``format_length`` (D45, a warning) are optional facts."""
    _check_context(context)
    document, stop = _prepare(document, STORY_SCHEMA)
    if stop is not None:
        return stop
    facts = facts or NO_FACTS
    found = _no_derived(document, context)
    boards = document.get("boards")
    if isinstance(boards, list):
        for i, board in enumerate(boards):
            if isinstance(board, dict):
                found += _no_derived(board, context, pointer("boards", i))
    found += _schema(STORY_SCHEMA, document)
    blocking = _blocking(found)
    if any(not _under(v.path, "/boards") for v in blocking):
        return _sorted(found)

    slots = [member["slot"] for member in document["cast"]]
    found += _duplicates(((pointer("cast", i, "slot"), slot) for i, slot in enumerate(slots)),
                         "cast slot")
    found += _duplicates(((pointer("board_order", i), board_id)
                          for i, board_id in enumerate(document["board_order"])), "board")
    if enabled_media_kinds is not None and document["media_kind"] not in enabled_media_kinds:
        found.append(_v(REF_UNKNOWN, "/media_kind",
                        f"media kind {document['media_kind']!r} is not enabled on the production"))
    ids: list[tuple[str, str]] = [("/id", document["id"])]
    ids += [(pointer("beds", i, "id"), bed["id"]) for i, bed in enumerate(document["beds"])]
    if isinstance(boards, list):
        found += _story_boards(document, boards, blocking, context, facts, slots, ids)
    found += _duplicates(ids, "ID")
    if context == QUEUE_RUN and document["narrator_voice_version_id"] is None and any(
            isinstance(b, dict) and isinstance(b.get("voice"), dict)
            and b["voice"].get("style") == NARRATOR for b in boards or ()):
        found.append(_v("voice.absent", "/narrator_voice_version_id",
                        "a narrator board needs the story's narrator voice"))
    # D45 needs every board's clock, so only a story whose boards all passed the
    # schema (which checks each board's shape) gets the warning.
    if format_length is not None and isinstance(boards, list) and not blocking:
        found += _length(document, boards, facts, format_length)
    return _sorted(found)


def _story_boards(document: Mapping, boards: list, blocking: list[Violation], context: str,
                  facts: Facts, slots: list[str], ids: list[tuple[str, str]]) -> list[Violation]:
    """Code rules of the embedded boards that passed the schema; references between
    them and the story. A board with a schema violation is skipped, never read."""
    found: list[Violation] = []
    layouts = set(document["layouts"])
    listed = set(document["board_order"])
    clean = [(i, board) for i, board in enumerate(boards)
             if isinstance(board, dict)
             and not any(_under(v.path, pointer("boards", i)) for v in blocking)]
    present = set()
    for i, board in clean:
        prefix = pointer("boards", i)
        present.add(board["id"])
        if board["id"] not in listed:
            found.append(_v(BOARD_ORDER, prefix + "/id", "the board is not in board_order"))
        if board["story_id"] != document["id"]:
            found.append(_v(REF_UNKNOWN, prefix + "/story_id", "the board belongs to another story"))
        found += board_rules(board, prefix, context=context, facts=facts, story_cast=slots,
                             story_layouts=layouts, check_ids=False)
        ids += list(_board_ids(Board.from_document(board), prefix))
    found += _duplicates(((pointer("boards", i, "number"), board["number"]) for i, board in clean),
                         "board number")
    if len(clean) == len(boards):
        for i, board_id in enumerate(document["board_order"]):
            if board_id not in present:
                found.append(_v(BOARD_ORDER, pointer("board_order", i),
                                "board_order names a board the story does not have"))
    return found


def _length(document: Mapping, boards: list, facts: Facts,
            format_length: FormatLength) -> list[Violation]:
    by_id = {b["id"]: Board.from_document(b) for b in boards}
    clocks = [board_clock(by_id[board_id], facts) for board_id in document["board_order"]
              if board_id in by_id]
    frames = sum(clock.frames for clock in clocks if clock)
    warning = length_warning(frames, all(clocks), format_length)
    return [] if warning is None else [_v(warning.code, "/board_order", warning.message, WARNING)]


# The other four types -------------------------------------------------------------------


def _simple(document: Any, name: str, context: str) -> tuple[Any, list[Violation], bool]:
    _check_context(context)
    document, stop = _prepare(document, name)
    if stop is not None:
        return document, stop, False
    found = _schema(name, document)
    return document, found, not found


def validate_production(document: Any, *, context: str = READ) -> list[Violation]:
    """``studio.production/v1``: schema, identifiers, one entry per media kind."""
    document, found, ok = _simple(document, PRODUCTION_SCHEMA, context)
    if ok:
        found += _duplicates(((pointer("media_types", i, "kind"), media["kind"])
                              for i, media in enumerate(document["media_types"])), "media kind")
    return _sorted(found)


def validate_story_timing(document: Any, *, context: str = READ) -> list[Violation]:
    """``studio.story-timing/v1`` (read-only output): schema, identifiers, one row per
    board, and totals that agree with the rows: ``complete`` when every row is timed,
    ``frames_known`` the sum of the timed rows' frames, ``build_allowed`` when there is
    no build blocker."""
    document, found, ok = _simple(document, STORY_TIMING_SCHEMA, context)
    if not ok:
        return _sorted(found)
    rows = document["boards"]
    found += _duplicates(((pointer("boards", i, "board_id"), row["board_id"])
                          for i, row in enumerate(rows)), "board")
    complete = all(row["state"] == TIMED for row in rows)
    if document["complete"] != complete:
        found.append(_v(SCHEMA_INVALID, "/complete",
                        f"must be {str(complete).lower()}: "
                        + ("every board row is timed" if complete else "a board row is untimed")))
    frames = sum(row["frames"] for row in rows if row["state"] == TIMED)
    if document["frames_known"] != frames:
        found.append(_v(SCHEMA_INVALID, "/frames_known",
                        f"must be {frames}, the sum of the timed rows' frames"))
    allowed = not document["build_blockers"]
    if document["build_allowed"] != allowed:
        found.append(_v(SCHEMA_INVALID, "/build_allowed",
                        f"must be {str(allowed).lower()}: "
                        + ("there is no build blocker" if allowed else "build_blockers is not empty")))
    return _sorted(found)


def validate_method_capabilities(document: Any, *, context: str = READ) -> list[Violation]:
    """``studio.method-capabilities/v1``: schema, each layer and motion pair once, and
    each cell's status as contract v1's matrix has it (:data:`methods.MATRIX`)."""
    document, found, ok = _simple(document, METHOD_CAPABILITIES_SCHEMA, context)
    if not ok:
        return _sorted(found)
    cells = document["cells"]
    found += _duplicates(((pointer("cells", i), (cell["layer"], cell["motion"]))
                          for i, cell in enumerate(cells)), "method")
    for i, cell in enumerate(cells):
        expected = methods.status(cell["layer"], cell["motion"])
        if cell["status"] != expected:
            found.append(_v(SCHEMA_INVALID, pointer("cells", i, "status"),
                            f"{cell['layer']} + {cell['motion']} is {expected} in contract v1 "
                            "(section 5)"))
    return _sorted(found)


def validate_legacy_import(document: Any, *, context: str = READ) -> list[Violation]:
    """``studio.legacy-import/v1``: schema, identifiers, the draft's board map named
    ``boards_from_r<draft_from_revision>``, and unique revisions, legacy shots, legacy
    lines within a shot, IDs and source keys."""
    document, found, ok = _simple(document, LEGACY_IMPORT_SCHEMA, context)
    if not ok:
        return _sorted(found)
    expected = f"boards_from_r{document['draft_from_revision']}"
    maps = sorted(key for key in document if key.startswith("boards_from_r"))
    for key in maps:
        if key != expected:
            found.append(_v(SCHEMA_INVALID, pointer(key),
                            f"the draft is from revision {document['draft_from_revision']}; "
                            f"its board map is {expected}"))
    found += _duplicates(((pointer("revisions", i, "legacy_revision"), r["legacy_revision"])
                          for i, r in enumerate(document["revisions"])), "revision")
    ids: list[tuple[str, str]] = []
    keys: list[tuple[str, tuple[str, str]]] = []
    shots: list[tuple[str, int]] = []
    for i, board in enumerate(document.get(expected, [])):
        base = pointer(expected, i)
        shots.append((base + "/legacy_shot", board["legacy_shot"]))
        found += _duplicates(((base + pointer("lines", j, "legacy_k"), line["legacy_k"])
                              for j, line in enumerate(board["lines"])), "legacy line")
        ids.append((base + "/board_id", board["board_id"]))
        ids += [(base + pointer("lines", j, "line_id"), line["line_id"])
                for j, line in enumerate(board["lines"])]
        for kind, field in (("cues", "cue_id"), ("notes", "note_id")):
            for j, item in enumerate(board.get(kind, [])):
                ids.append((base + pointer(kind, j, field), item[field]))
                keys.append((base + pointer(kind, j, "source_key"), (kind, item["source_key"])))
        if "source_key" in board:
            keys.append((base + "/source_key", ("board", board["source_key"])))
    found += _duplicates(shots, "legacy shot")
    for j, record in enumerate(document.get("story_records", [])):
        ids.append((pointer("story_records", j, "id"), record["id"]))
        keys.append((pointer("story_records", j, "source_key"),
                     (record["kind"], record["source_key"])))
    found += _duplicates(ids, "ID") + _duplicates(keys, "source key")
    return _sorted(found)
