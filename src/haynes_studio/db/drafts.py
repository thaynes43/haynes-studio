"""Storage for production metadata and the editable story aggregate.

Every draft mutation locks its story before reading any boards. A successful board
edit advances its own revision and the story revision in the same transaction.
Board numbers and nested IDs survive removal in the database.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Literal

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import insert

from haynes_studio.canonical import (
    BuildBlocker, Story, boards_derived, story_derived, timing_summary, to_document, validate_production,
    validate_story,
)
from haynes_studio.canonical.ids import Minter, is_id
from haynes_studio.canonical.jsonvalues import normalize
from haynes_studio.drafting.declaration import DraftDeclaration, RedraftDeclaration
from haynes_studio.errors import ContractError, Violation, pointer
from haynes_studio.formats import records as format_records
from haynes_studio.formats.recipe import PIN_PATH, allowed_methods, format_length, method_violation
from haynes_studio.golive import records as go_live
from haynes_studio.library.library import require_media
from haynes_studio.library.resolve import resolve, story_references

from haynes_studio.photo.plan import photo_facts
from haynes_studio.voice import Engine, voice_facts

from .jobs import active_for_story
from .catalog import ProductionScope, load_library, record_asset_version
from .problems import DraftProtected, NotFound, require_revision, require_valid
from .schema import boards, draft_ids, media_types, productions, stories, story_asset_refs

MEDIA_KINDS = {"short": ("9:16", 1080, 1920), "video": ("16:9", 1920, 1080)}
STORY_FIELDS = frozenset({
    "title", "format_version_id", "cast", "narrator_voice_version_id", "set", "layouts",
    "motion_style", "mix", "checks", "beds",
})
BOARD_FIELDS = frozenset({"title", "lines", "timing", "voice", "photo", "cast", "layout",
                          "method", "seeds", "cues", "notes", "draft_application"})
BOARD_CHILDREN = {"lines": "lin", "cues": "cue", "notes": "nte"}
_PERSON_EDIT_FIELDS = ("person_edit", "person_edit_revision", "person_edit_acknowledgments")


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def invalid(code: str, path: str, message: str) -> ContractError:
    return ContractError("<draft>", [Violation(code, path, message)])


def _record(conn, table, id_: str, *, lock: bool = False):
    stmt = sa.select(table.c.document).where(table.c.id == id_)
    document = conn.scalar(stmt.with_for_update() if lock else stmt)
    if document is None:
        raise NotFound
    return document


def production(conn: sa.Connection, id_: str) -> dict:
    row = _record(conn, productions, id_)
    row["media_types"] = list(conn.scalars(sa.select(media_types.c.document).where(
        media_types.c.production_id == id_,
    ).order_by(media_types.c.kind)))
    return row


def list_productions(conn: sa.Connection, allowed: ProductionScope,
                     after: str | None, limit: int) -> list[dict]:
    stmt = sa.select(productions.c.id)
    if allowed is not None:
        stmt = stmt.where(productions.c.id.in_(allowed))
    if after is not None:
        stmt = stmt.where(productions.c.id > after)
    ids = conn.scalars(stmt.order_by(productions.c.id).limit(limit))
    return [production(conn, id_) for id_ in ids]


def _insert_production(conn: sa.Connection, document: dict) -> None:
    require_valid(validate_production(document, context="write"))
    profile = document["media_types"]
    conn.execute(productions.insert().values(
        id=document["id"], document={**document, "media_types": []},
    ))
    if profile:
        conn.execute(media_types.insert(), [
            {"production_id": document["id"], "kind": item["kind"], "document": item}
            for item in profile
        ])


def create_production(conn: sa.Connection, name: str, labels: list[str], by: dict) -> dict:
    now = timestamp()
    document = {"schema": "studio.production/v1", "id": Minter().mint("prd"), "revision": 1,
                "name": name, "media_types": [], "labels": labels, "created_by": by,
                "created_at": now, "updated_at": now}
    _insert_production(conn, document)
    return document


def enable_media_type(conn: sa.Connection, id_: str, kind: str, revision: int) -> dict:
    held = _record(conn, productions, id_, lock=True)
    require_revision(held["revision"], revision)
    doc = production(conn, id_)
    if any(item["kind"] == kind for item in doc["media_types"]):
        return doc
    profile = _profile(kind)
    conn.execute(media_types.insert().values(production_id=id_, kind=kind, document=profile))
    updated = {**held, "revision": revision + 1, "updated_at": profile["enabled_at"]}
    conn.execute(productions.update().where(productions.c.id == id_).values(document=updated))
    return production(conn, id_)


def _profile(kind: str) -> dict:
    aspect, width, height = MEDIA_KINDS[kind]
    return {"kind": kind, "aspect": aspect, "width": width, "height": height, "fps": 24,
            "enabled_at": timestamp()}


def check_media_type(conn: sa.Connection, production_id: str, kind: str) -> None:
    if conn.scalar(sa.select(media_types.c.kind).where(
        media_types.c.production_id == production_id, media_types.c.kind == kind,
    )) is None:
        raise NotFound


def story_production(conn: sa.Connection, id_: str) -> str:
    result = conn.scalar(sa.select(stories.c.production_id).where(stories.c.id == id_))
    if result is None:
        raise NotFound
    return result


def board_story(conn: sa.Connection, id_: str, *, include_tombstone=False) -> str:
    stmt = sa.select(boards.c.story_id).where(boards.c.id == id_)
    if not include_tombstone:
        stmt = stmt.where(boards.c.tombstone.is_(False))
    result = conn.scalar(stmt)
    if result is None:
        raise NotFound
    return result


def list_stories(conn: sa.Connection, production_id: str, kind: str,
                 after: str | None, limit: int, *, published: bool | None = None,
                 approved: bool | None = None) -> list[dict]:
    check_media_type(conn, production_id, kind)
    stmt = go_live.story_status_query().where(
        stories.c.production_id == production_id, stories.c.media_kind == kind,
    )
    if after is not None:
        stmt = stmt.where(stories.c.id > after)
    if published is not None:
        stmt = stmt.where(stories.c.published.is_(published))
    if approved is not None:
        stmt = stmt.where(go_live.story_approved().is_(approved))
    return [get_draft(conn, row["id"]).summary(conn, row)
            for row in conn.execute(stmt.order_by(stories.c.id).limit(limit)).mappings()]


@dataclass
class Draft:
    story: dict
    boards: dict[str, dict]
    highest_board: int

    def exchange(self) -> dict:
        ordered = [self.boards[id_] for id_ in self.story["board_order"]]
        return {**self.story, "boards": ordered}

    def format_version(self, conn: sa.Connection) -> dict | None:
        return format_records.version(conn, self.story.get("format_version_id"))

    def _library(self, conn: sa.Connection, document: dict):
        refs = story_references(document)
        library = load_library(conn, {ref.version_id for ref in refs}, self.story["production_id"])
        return refs, library

    def facts(self, conn, document, library):
        return voice_facts(library, document, active_for_story(conn, self.story["id"]),
                           current_engine=Engine().signing_name).merged(
            photo_facts(Story.from_document(document), library),
        )

    def summary(self, conn: sa.Connection, status=None) -> dict:
        doc = self.exchange()
        _, library = self._library(conn, doc)
        story = Story.from_document(doc)
        derived = story_derived(story, story.ordered_boards(), self.facts(conn, doc, library),
                                format_length=format_length(self.format_version(conn)),
                                highest_number_issued=self.highest_board)
        if status is None:
            stmt = go_live.story_status_query().where(stories.c.id == self.story["id"])
            status = conn.execute(stmt).mappings().one()
        return {**self.story, "derived": to_document(derived),
                "published": status["published"], "approved": status["approved"],
                "latest_finished_run": status["latest_finished_run"]}

    def board(self, conn: sa.Connection, id_: str) -> dict:
        if id_ not in self.boards:
            raise NotFound
        doc = self.exchange()
        _, library = self._library(conn, doc)
        derived = boards_derived(Story.from_document(doc).ordered_boards(), self.facts(conn, doc, library))
        index = self.story["board_order"].index(id_)
        return {**self.boards[id_], "derived": to_document(derived[index])}

    def timing(self, conn: sa.Connection) -> dict:
        doc = self.exchange()
        _, library = self._library(conn, doc)
        pinned = self.format_version(conn)
        timing = timing_summary(doc, facts=self.facts(conn, doc, library), format_length=format_length(pinned))
        blockers = list(timing.build_blockers)
        if pinned is not None:
            for board in doc["boards"]:
                issue = method_violation(pinned["recipe"], board)
                if issue is not None:
                    blockers.append(BuildBlocker(code=issue.rule, board_id=board["id"], path=None))
        elif doc.get("format_version_id") is not None:
            blockers.append(BuildBlocker(code="ref.unknown", board_id=None, path=PIN_PATH))
        return to_document(replace(timing, build_allowed=not blockers, build_blockers=tuple(blockers)))

    def validate(self, conn: sa.Connection, *, board: dict | None = None,
                 previous: dict | None = None) -> set[str]:
        doc = self.exchange()
        require_valid(validate_story(doc, context="write"))
        refs, library = self._library(conn, doc)
        # Resolve metadata on edit. The build's own preflight verifies bytes.
        result = resolve(doc, library, lambda locator, sha: True)
        ordered = [self.boards[id_] for id_ in self.story["board_order"]]
        problems = list(result.problems)
        for ref in refs:
            version = library.get(ref.version_id)
            if version is None:
                continue
            scope = library.asset(version.asset_id).scope
            board_id = None
            if ref.path.startswith("/boards/"):
                board_id = ordered[int(ref.path.split("/", 3)[2])]["id"]
            if scope.story_id not in (None, self.story["id"]) or scope.board_id not in (None, board_id):
                problems.append(Violation("asset.scope_mismatch", ref.path,
                                          "That version is outside this draft or board"))
        require_valid(problems)
        if board is not None:
            for kind in ("photo", "voice"):
                version_id = (board.get(kind) or {}).get("current_version_id")
                previous_id = ((previous or {}).get(kind) or {}).get("current_version_id")
                if version_id is not None and version_id != previous_id:
                    require_media(library.get(version_id), f"/{kind}/current_version_id")
        require_valid(validate_story(doc, context="write", facts=library.facts(doc)))
        return {ref.version_id for ref in refs}


def get_draft(conn: sa.Connection, id_: str, *, lock: bool = False) -> Draft:
    doc = _record(conn, stories, id_, lock=lock)
    rows = conn.execute(sa.select(boards.c.document, boards.c.number, boards.c.tombstone).where(
        boards.c.story_id == id_,
    )).all()
    return Draft(doc, {row.document["id"]: row.document for row in rows if not row.tombstone},
                 max((row.number for row in rows), default=0))


def _exact_fields(fields: dict, allowed: frozenset[str]) -> None:
    extras = fields.keys() - allowed
    if extras:
        raise invalid("schema.unknown_field", pointer(min(extras)), "The field is not writable")


def _with_child_ids(fields: dict, previous: dict, children: dict[str, str], minter: Minter,
                    *, allow_new_line_ids: bool = False) -> dict:
    out = normalize(fields)
    for field, prefix in children.items():
        items = out.get(field)
        if not isinstance(items, list):
            continue  # The canonical validator reports shape errors.
        existing = {item["id"] for item in previous.get(field, [])}
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            if "id" not in item:
                item["id"] = minter.mint(prefix)
            elif allow_new_line_ids and field == "lines" and is_id(item["id"], prefix):
                # A cue may anchor to a new line in the same write. _reserve_ids
                # still checks each new ID against the global registry.
                continue
            elif not isinstance(item["id"], str) or item["id"] not in existing:
                raise invalid("ref.unknown", pointer(field, index, "id"),
                              "Omit the ID to create an item, or use an existing item ID")
    return out


def _reserve_ids(conn: sa.Connection, ids: set[str]) -> None:
    if not ids:
        return
    saved = conn.execute(insert(draft_ids).values([{"id": id_} for id_ in sorted(ids)])
                         .on_conflict_do_nothing().returning(draft_ids.c.id)).scalars().all()
    if len(saved) != len(ids):
        raise invalid("ref.duplicate", "", "A child ID is already in use")


def _child_ids(doc: dict, fields) -> set[str]:
    return {item["id"] for field in fields for item in doc[field]}


def _references(conn: sa.Connection, story_id: str, refs: set[str]) -> None:
    old = set(conn.scalars(sa.select(story_asset_refs.c.version_id).where(
        story_asset_refs.c.story_id == story_id,
    )))
    if old - refs:
        conn.execute(story_asset_refs.delete().where(
            story_asset_refs.c.story_id == story_id, story_asset_refs.c.version_id.in_(old - refs),
        ))
    if refs - old:
        conn.execute(story_asset_refs.insert(), [
            {"story_id": story_id, "version_id": version} for version in sorted(refs - old)
        ])


def _insert_story(conn, doc):
    pin = doc.get("format_version_id")
    format_records.require_pin(conn, pin, doc["media_kind"])
    conn.execute(stories.insert().values(
        id=doc["id"], production_id=doc["production_id"], media_kind=doc["media_kind"],
        source_key=(doc.get("origin") or {}).get("source_key"), document=doc,
        format_version_id=pin,
    ))


def _insert_board(conn, doc):
    conn.execute(boards.insert().values(
        id=doc["id"], story_id=doc["story_id"], number=doc["number"],
        source_key=(doc.get("origin") or {}).get("source_key"), document=doc,
    ))


def create_story(conn: sa.Connection, production_id: str, kind: str, fields: dict, by: dict) -> Draft:
    check_media_type(conn, production_id, kind)
    _exact_fields(fields, STORY_FIELDS)
    now = timestamp()
    minter = Minter()
    doc = {
        "title": "", "format_version_id": None, "cast": [], "narrator_voice_version_id": None,
        "set": None, "layouts": {"default": {}}, "motion_style": None,
        "mix": {"line_rms_dbfs": -22, "master_lufs": -20, "true_peak_dbtp": -3.5},
        "checks": {}, "beds": [],
        **_with_child_ids(fields, {}, {"beds": "cue"}, minter),
        "schema": "studio.story/v1", "id": minter.mint("sty"), "production_id": production_id,
        "media_kind": kind, "revision": 1, "board_order": [], "origin": None,
        "created_at": now, "updated_at": now, "created_by": by,
    }
    draft = Draft(doc, {}, 0)
    refs = draft.validate(conn)
    _insert_story(conn, doc)
    _reserve_ids(conn, _child_ids(doc, ("beds",)))
    _references(conn, doc["id"], refs)
    return draft


def _save_story(conn: sa.Connection, draft: Draft, refs: set[str], *, pin_changed=False) -> None:
    values = {"document": draft.story}
    if pin_changed:
        pin = draft.story["format_version_id"]
        format_records.require_pin(conn, pin, draft.story["media_kind"])
        values["format_version_id"] = pin
    conn.execute(stories.update().where(stories.c.id == draft.story["id"]).values(**values))
    _references(conn, draft.story["id"], refs)


def _advance(draft: Draft, changes: dict, now: str) -> Draft:
    return replace(draft, story={**draft.story, **changes, "revision": draft.story["revision"] + 1,
                                 "updated_at": now})


def _draft_declaration(fields: dict, by: dict, model: type[DraftDeclaration]):
    if "draft_application" not in fields:
        return fields, None
    if by["kind"] != "agent":
        raise invalid("draft.agent_required", "/draft_application",
                      "Draft provenance requires an authenticated agent")
    fields = dict(fields)
    try:
        declaration = model.model_validate(fields.pop("draft_application"))
    except ValidationError as error:
        first = error.errors(include_input=False)[0]
        raise invalid("schema.invalid", pointer("draft_application", *first["loc"]),
                      "Invalid agent draft declaration") from None
    return fields, declaration


def _draft_stamp(declaration: DraftDeclaration, revision: int, now: str) -> dict:
    return {**declaration.model_dump(include=set(DraftDeclaration.model_fields)),
            "board_revision": revision, "applied_board_revision": revision, "applied_at": now}


def _check_board_write(held: dict, by: dict, acknowledgment: int | None) -> None:
    if by["kind"] != "agent":
        return
    protection = held.get("draft_application", held)
    if acknowledgment is not None:
        require_revision(held["revision"], acknowledgment, "/acknowledge_person_edit/board_revision")
        if "draft_application" not in held and "person_edit" not in protection:
            raise invalid("draft.no_protection", "/acknowledge_person_edit",
                          "Acknowledge a board with a person edit or a draft stamp")
    elif "person_edit" in protection:
        raise DraftProtected(held)


def _board_changed(held: dict, by: dict, reason: str, now: str,
                   acknowledgment: int | None = None) -> dict:
    updated = {**held, "revision": held["revision"] + 1, "updated_at": now}
    stamp = held.get("draft_application")
    protection = dict(stamp) if stamp is not None else {
        key: held[key] for key in _PERSON_EDIT_FIELDS if key in held
    }
    if by["kind"] == "human":
        if reason != "media" or "person_edit" not in protection:
            protection.update(person_edit="content" if reason == "media" else reason,
                              person_edit_revision=updated["revision"])
    elif by["kind"] == "agent":
        if (stamp is not None and reason in ("reordered", "media") and held["drafted_by"] == by
                and stamp["board_revision"] == held["revision"]):
            protection.setdefault("applied_board_revision", held["revision"])
            protection["board_revision"] = updated["revision"]
        if acknowledgment is not None:
            protection["person_edit_acknowledgments"] = [
                *protection.get("person_edit_acknowledgments", []),
                {"key_id": by["key_id"], "acknowledged_at": now, "board_revision": acknowledgment},
            ]
    if stamp is None:
        updated.update(protection)
    else:
        updated["draft_application"] = protection
    return updated


def edit_story(conn: sa.Connection, id_: str, revision: int, fields: dict) -> Draft:
    draft = get_draft(conn, id_, lock=True)
    require_revision(draft.story["revision"], revision)
    _exact_fields(fields, STORY_FIELDS)
    fields = _with_child_ids(fields, draft.story, {"beds": "cue"}, Minter())
    updated = _advance(draft, fields, timestamp())
    refs = updated.validate(conn)
    _reserve_ids(conn, _child_ids(updated.story, ("beds",)) - _child_ids(draft.story, ("beds",)))
    _save_story(conn, updated, refs, pin_changed="format_version_id" in fields)
    return updated


def add_board(conn: sa.Connection, id_: str, revision: int, fields: dict, by: dict) -> tuple[Draft, str]:
    draft = get_draft(conn, id_, lock=True)
    require_revision(draft.story["revision"], revision)
    _exact_fields(fields, BOARD_FIELDS)
    fields, declaration = _draft_declaration(fields, by, DraftDeclaration)
    minter = Minter()
    id_board, now = minter.mint("brd"), timestamp()
    number = draft.highest_board + 1
    doc = {
        "title": f"Board {number}", "lines": [],
        "photo": {"current_version_id": None, "prompt": None, "input_asset_version_ids": []},
        "cast": [], "layout": {"preset": next(iter(sorted(draft.story["layouts"])), "default"),
                               "foreground": True},
        "seeds": {}, "cues": [], "notes": [],
        **_with_child_ids(fields, {}, BOARD_CHILDREN, minter,
                          allow_new_line_ids=declaration is not None),
        "schema": "studio.board/v1", "id": id_board, "story_id": id_, "number": number,
        "revision": 1, "drafted_by": by, "origin": None, "created_at": now, "updated_at": now,
    }
    if declaration is not None:
        doc["draft_application"] = _draft_stamp(declaration, 1, now)
    elif by["kind"] == "human":
        doc.update(person_edit="content", person_edit_revision=1)
    spoken = bool(doc["lines"])
    doc.setdefault("timing", {"lead_ms": 0 if spoken else None, "tail_ms": 0 if spoken else None,
                              "hold_ms": None if spoken else 1000})
    # P-08 requires cast for a layered board and an on-screen speaker for S2V.
    # Infer a valid method when neither is available on a new draft.
    cast = doc["cast"] if isinstance(doc["cast"], list) else []
    lines = doc["lines"] if isinstance(doc["lines"], list) else []
    cast_slots = [entry.get("slot") for entry in cast if isinstance(entry, dict)]
    speakers = [entry.get("speaker") for entry in lines if isinstance(entry, dict)]
    voice_style = None
    if spoken:
        voice_style = "narrator" if speakers and all(s == "narrator" for s in speakers) else "cast"
    doc.setdefault("voice", {"style": voice_style, "current_version_id": None})
    if "method" not in doc:
        method = {"layer": "layered" if cast else "whole_frame",
                  "motion": "s2v" if any(s in cast_slots for s in speakers) else "i2v"}
        pinned = draft.format_version(conn)
        if pinned is not None:
            methods = allowed_methods(pinned["recipe"], {"cast": cast, "lines": lines})
            if methods:
                method = methods[0]
        doc["method"] = method
    updated = _advance(draft, {"board_order": [*draft.story["board_order"], id_board]}, now)
    updated.boards = {**draft.boards, id_board: doc}
    updated.highest_board = number
    refs = updated.validate(conn, board=doc)
    _reserve_ids(conn, _child_ids(doc, BOARD_CHILDREN))
    _insert_board(conn, doc)
    _save_story(conn, updated, refs)
    return updated, id_board


def edit_board(conn: sa.Connection, story_id: str, id_: str, revision: int,
               fields: dict, by: dict, *, acknowledgment: int | None = None) -> Draft:
    draft = get_draft(conn, story_id, lock=True)
    held = draft.boards.get(id_)
    if held is None:
        raise NotFound
    require_revision(held["revision"], revision)
    _exact_fields(fields, BOARD_FIELDS)
    fields, declaration = _draft_declaration(fields, by, RedraftDeclaration)
    _check_board_write(held, by, acknowledgment)
    if declaration is not None:
        require_revision(draft.story["revision"], declaration.story_revision,
                         "/draft_application/story_revision")
        previous = held.get("draft_application", {})
        if (previous.get("board_key") != declaration.board_key
                or previous.get("draft_sha256") != declaration.previous_draft_sha256
                or (acknowledgment is None and (
                    previous.get("board_revision") != revision or held["drafted_by"] != by))):
            raise DraftProtected(held)
    fields = _with_child_ids(fields, held, BOARD_CHILDREN, Minter(),
                             allow_new_line_ids=declaration is not None)
    now = timestamp()
    doc = {**_board_changed(held, by, "content", now, acknowledgment), **fields}
    if declaration is not None:
        doc["drafted_by"] = by
        history = doc["draft_application"]
        doc["draft_application"] = {
            **_draft_stamp(declaration, doc["revision"], now),
            **{key: history[key] for key in _PERSON_EDIT_FIELDS if key in history},
        }
    return _replace_board(conn, draft, held, doc, now)


def select_board_media(conn: sa.Connection, draft: Draft, board_id: str, kind: Literal["photo", "voice"],
                       version_id: str, by: dict) -> int | None:
    """Attach a current result to the locked board under its person-edit protection."""
    held = draft.boards[board_id]
    try:
        _check_board_write(held, by, acknowledgment=None)
    except DraftProtected:
        return None
    media = held[kind]
    protection = held.get("draft_application", held)
    person_adopting = by["kind"] == "human" and "person_edit" not in protection
    if media["current_version_id"] == version_id and not person_adopting:
        return held["revision"]
    now = timestamp()
    doc = {**_board_changed(held, by, "media", now),
           kind: {**media, "current_version_id": version_id}}
    _replace_board(conn, draft, held, doc, now)
    return doc["revision"]


def _replace_board(conn, draft, held, doc, now):
    id_ = held["id"]
    updated = _advance(draft, {}, now)
    updated.boards = {**draft.boards, id_: doc}
    refs = updated.validate(conn, board=doc, previous=held)
    _reserve_ids(conn, _child_ids(doc, BOARD_CHILDREN) - _child_ids(held, BOARD_CHILDREN))
    conn.execute(boards.update().where(boards.c.id == id_).values(document=doc))
    _save_story(conn, updated, refs)
    return updated


def reorder(conn: sa.Connection, id_: str, revision: int, order: list[str], by: dict,
            *, acknowledgments: dict[str, int] | None = None) -> Draft:
    draft = get_draft(conn, id_, lock=True)
    require_revision(draft.story["revision"], revision)
    if len(order) != len(draft.boards) or set(order) != draft.boards.keys():
        raise invalid("story.board_order", "/board_order", "List every active board exactly once")
    moved = [new for old, new in zip(draft.story["board_order"], order, strict=True) if old != new]
    acknowledgments = acknowledgments or {}
    if acknowledgments.keys() - set(moved):
        raise invalid("draft.not_moved", "/acknowledge_person_edit",
                      "Acknowledge only boards that move in this reorder")
    now = timestamp()
    updated = _advance(draft, {"board_order": order}, now)
    updated.boards = dict(draft.boards)
    changed = []
    for id_board in moved:
        held = draft.boards[id_board]
        acknowledgment = acknowledgments.get(id_board)
        _check_board_write(held, by, acknowledgment)
        if by["kind"] == "human" or "draft_application" in held or "person_edit" in held:
            updated.boards[id_board] = _board_changed(held, by, "reordered", now, acknowledgment)
            changed.append(id_board)
    refs = updated.validate(conn)
    for id_board in changed:
        conn.execute(boards.update().where(boards.c.id == id_board).values(
            document=updated.boards[id_board],
        ))
    _save_story(conn, updated, refs)
    return updated


def remove_board(conn: sa.Connection, story_id: str, id_: str, revision: int, by: dict,
                 *, acknowledgment: int | None = None) -> None:
    draft = get_draft(conn, story_id, lock=True)
    held = draft.boards.get(id_)
    if held is None:
        raise NotFound
    require_revision(held["revision"], revision)
    _check_board_write(held, by, acknowledgment)
    now = timestamp()
    order = [board_id for board_id in draft.story["board_order"] if board_id != id_]
    updated = _advance(draft, {"board_order": order}, now)
    updated.boards = {board_id: doc for board_id, doc in draft.boards.items() if board_id != id_}
    refs = updated.validate(conn)
    conn.execute(boards.update().where(boards.c.id == id_).values(
        tombstone=True, document=_board_changed(held, by, "removed", now, acknowledgment),
    ))
    _save_story(conn, updated, refs)


def _import_child_ids(exchange: dict) -> set[str]:
    return _child_ids(exchange, ("beds",)).union(
        *(_child_ids(board, BOARD_CHILDREN) for board in exchange["boards"]),
    )


def check_new_import(conn: sa.Connection, exchange: dict) -> None:
    """Check the draft identities before a create-only import publishes its files."""
    board_docs = exchange["boards"]
    story_match = stories.c.id == exchange["id"]
    story_key = (exchange.get("origin") or {}).get("source_key")
    if story_key is not None:
        story_match = sa.or_(story_match, stories.c.source_key == story_key)
    board_keys = [(board.get("origin") or {}).get("source_key") for board in board_docs]
    checks = (
        sa.exists().where(productions.c.id == exchange["production_id"]),
        sa.exists().where(story_match),
        sa.exists().where(sa.or_(boards.c.id.in_(board["id"] for board in board_docs),
                                 boards.c.source_key.in_(key for key in board_keys if key is not None))),
        sa.exists().where(draft_ids.c.id.in_(_import_child_ids(exchange))),
    )
    if conn.scalar(sa.select(sa.or_(*checks))):
        raise invalid("ref.duplicate", "", "An archive draft identity is already in use")


def import_draft(conn: sa.Connection, production_doc: dict, exchange: dict,
                 versions: list[dict], *, create_only: bool = False) -> Draft:
    """Import the canonical CLI exchange and library into Postgres in one transaction.

    Existing imported drafts are returned intact unless create_only is set. An
    archive import uses create_only to require a fresh production and draft.
    """
    production_doc = normalize(production_doc)
    doc = normalize(exchange)
    require_valid(validate_production(production_doc))
    require_valid(validate_story(doc, enabled_media_kinds=[p["kind"]
                                                           for p in production_doc["media_types"]]))
    if "boards" not in doc or doc["production_id"] != production_doc["id"]:
        raise invalid("ref.unknown", "/production_id", "The exchange must include its boards and production")
    if create_only:
        # Plain inserts also refuse conflicts committed after the identity check.
        _insert_production(conn, production_doc)
        return _insert_imported_draft(conn, doc, versions)
    by_source = (doc.get("origin") or {}).get("source_key")
    # Serialize duplicate imports, including the same source claimed by another production.
    for identity, namespace in ((by_source or doc["id"], 410), (production_doc["id"], 409)):
        conn.execute(sa.select(sa.func.pg_advisory_xact_lock(sa.func.hashtextextended(
            identity, namespace,
        ))))
    exists = conn.scalar(sa.select(productions.c.id).where(productions.c.id == production_doc["id"]))
    if exists is None:
        _insert_production(conn, production_doc)
    check_media_type(conn, doc["production_id"], doc["media_kind"])
    match = stories.c.id == doc["id"]
    if by_source is not None:
        match = sa.or_(match, stories.c.source_key == by_source)
    matches = conn.scalars(sa.select(stories.c.id).where(match)).all()
    if matches:
        held = get_draft(conn, matches[0], lock=True)
        held_source = (held.story.get("origin") or {}).get("source_key")
        expected = (doc["production_id"], doc["media_kind"], by_source)
        actual = (held.story["production_id"], held.story["media_kind"], held_source)
        if len(matches) != 1 or actual != expected:
            raise invalid("legacy.import_map_mismatch", "/origin",
                          "The import identity already belongs to another draft")
        return held
    return _insert_imported_draft(conn, doc, versions)


def _insert_imported_draft(conn: sa.Connection, doc: dict, versions: list[dict]) -> Draft:
    ids = _import_child_ids(doc)
    board_docs = doc.pop("boards")
    doc.pop("derived", None)
    _insert_story(conn, doc)
    for board in board_docs:
        board.pop("derived", None)
        _insert_board(conn, board)
    _reserve_ids(conn, ids)
    for version in sorted(versions, key=lambda item: (item["asset_id"], item["number"])):
        record_asset_version(conn, version)
    draft = get_draft(conn, doc["id"])
    _references(conn, doc["id"], draft.validate(conn))
    return draft


def board_snapshot(conn, draft, board_id, additional=()):
    board = draft.boards.get(board_id)
    if board is None:
        raise NotFound
    story = {**draft.story, "boards": [board], "board_order": [board_id]}
    refs = {ref.version_id for ref in story_references(story)}
    return story, load_library(conn, refs.union(additional), story["production_id"])
