"""Plan the entire draft, then make serial, conditional writes through MCP."""

import re
from dataclasses import asdict, dataclass, field
from typing import Protocol

from mcp import types

from haynes_studio.canonical.facts import Facts
from haynes_studio.canonical.ids import Minter, is_id
from haynes_studio.errors import ContractError, Violation
from haynes_studio.jsonio import thaw
from haynes_studio.library.resolve import board_references
from haynes_studio.mcp.server import MAX_ARGUMENT_BYTES
from haynes_studio.mcp.upstream import json_text

from .document import Draft, Proposal

RECEIPT_SCHEMA = "studio.agent-draft-receipt/v1"
_STORY_FIELDS = ["cast", "layouts", "narrator_voice_version_id", "set"]
_CODE = re.compile(r"[a-z][a-z0-9_.-]{0,95}")


class ToolSession(Protocol):
    async def call_tool(self, name: str, arguments: dict) -> types.CallToolResult: ...


@dataclass(frozen=True)
class BoardState:
    board_id: str
    revision: int
    draft_sha256: str


def read_baseline(document: object, draft: Draft) -> dict[str, BoardState]:
    """Load the last confirmed state and keep removed IDs for future conflicts."""
    if (not isinstance(document, dict) or document.get("schema") != RECEIPT_SCHEMA
            or document.get("story_id") != draft.story_id
            or document.get("production_id") != draft.production_id
            or not isinstance(entries := document.get("baseline"), dict)):
        raise ValueError("The previous receipt must match this production and story")
    baseline = {}
    ids = set()
    for key, entry in entries.items():
        if (not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", key)
                or not isinstance(entry, dict)
                or set(entry) != {"board_id", "revision", "draft_sha256"}
                or not is_id(board_id := entry["board_id"], "brd") or board_id in ids
                or type(entry["revision"]) is not int or not 1 <= entry["revision"] < 2**63 - 1
                or not isinstance(entry["draft_sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", entry["draft_sha256"])):
            raise ValueError("The previous receipt contains an invalid board baseline")
        ids.add(board_id)
        baseline[key] = BoardState(**entry)
    return baseline


@dataclass
class Result:
    draft: Draft
    baseline: dict[str, BoardState]
    boards: list[dict] = field(default_factory=list)
    error: dict | None = None

    def record(self, outcome: str, reason: str, *, key: str | None = None,
               board_id: str | None = None, **details) -> None:
        self.boards.append({"outcome": outcome, "reason": reason, "key": key,
                            "board_id": board_id, **details})

    @property
    def ok(self) -> bool:
        return self.error is None and all(row["outcome"] in ("applied", "skipped") for row in self.boards)

    def document(self) -> dict:
        draft = self.draft
        return {"schema": RECEIPT_SCHEMA, "production_id": draft.production_id, "story_id": draft.story_id,
                "draft_sha256": draft.sha256, "usage": {"model": draft.model, "session": draft.session,
                                                       **draft.usage},
                "error": self.error, "boards": self.boards,
                "baseline": {key: asdict(board) for key, board in self.baseline.items()}}

    def abort(self, error: dict) -> None:
        self.error = error
        reported = {row["key"] for row in self.boards}
        for board in self.draft.boards:
            if board.key not in reported:
                state = self.baseline.get(board.key)
                self.record("skipped", error["code"], key=board.key,
                            board_id=state.board_id if state else None)


class ToolFailure(Exception):
    def __init__(self, code: str, http_status: int | None = None, *,
                 current_revision: int | None = None, path: str | None = None):
        super().__init__(code)
        self.code = code
        self.http_status = http_status
        self.current_revision = current_revision
        self.path = path

    @property
    def detail(self) -> dict:
        detail = {"code": self.code, "http_status": self.http_status}
        if self.current_revision is not None:
            detail["current_revision"] = self.current_revision
        if self.path:
            detail["path"] = self.path
        return detail


async def _call(session: ToolSession, name: str, **arguments) -> dict:
    try:
        result = await session.call_tool(name, arguments)
    except Exception:
        # The SDK may also fail while receiving or validating a committed reply.
        # Only a structured tool refusal proves the write did not take effect.
        raise ToolFailure("draft.transport_failed") from None
    document = result.structuredContent
    if isinstance(document, dict):
        if not result.isError:
            return document
        problem = document.get("error")
        if isinstance(problem, dict):
            code, status = problem.get("code"), problem.get("http_status")
            if isinstance(code, str) and _CODE.fullmatch(code) and type(status) is int:
                revision, path = problem.get("current_revision"), problem.get("path")
                raise ToolFailure(code, status,
                                  current_revision=revision if type(revision) is int else None,
                                  path=path if isinstance(path, str) else None)
    raise ToolFailure("draft.response_invalid")


async def _story(session: ToolSession, draft: Draft) -> dict:
    params = {"story_id": draft.story_id, "limit": 20}
    story = await _call(session, "studio_get_story_summary", **params, fields=_STORY_FIELDS)
    if story["production_id"] != draft.production_id:
        raise ToolFailure("draft.production_mismatch")
    order = story["board_order"]
    cursor = story["next_cursor"]
    while cursor is not None:
        page = await _call(session, "studio_get_story_summary", **params, cursor=cursor)
        order += page["board_order"]
        cursor = page["next_cursor"]
    return story


async def _assets(session: ToolSession, production: str, ids: set[str]) -> dict:
    matched = {}
    cursor = None
    while ids - matched.keys():
        page = await _call(session, "studio_search_assets", production=production, limit=20, cursor=cursor)
        matched.update((item["id"], item) for item in page["items"] if item["id"] in ids)
        cursor = page["next_cursor"]
        if cursor is None:
            break
    return matched


async def _validate_context(session: ToolSession, draft: Draft, story: dict,
                            baseline: dict[str, BoardState]) -> None:
    set_fields = ("asset_version_id", "motion_asset_version_id")
    story_set = story["set"]
    expected = draft.set_pins
    if [None if story_set is None else story_set.get(key) for key in set_fields] != [
            None if expected is None else expected.get(key) for key in set_fields]:
        raise ContractError("<agent draft>", [Violation("draft.set_changed", "/set",
                                                       "The story's pinned set differs from the draft")])
    refs = [(board, ref) for board in draft.boards for ref in board_references(thaw(board.document))]
    assets = await _assets(session, draft.production_id, {ref.version_id for _, ref in refs})
    facts = Facts.build(capabilities={id_: item["capabilities"] for id_, item in assets.items()})
    problems = []
    for board in draft.boards:
        problems.extend(board.problems(story_cast={item["slot"] for item in story["cast"]},
                                       story_layouts=story["layouts"], facts=facts))
        if board.fields["voice"]["style"] == "narrator" and story["narrator_voice_version_id"] is None:
            problems.append(Violation("voice.narrator_missing", board.path + "/voice",
                                      "The story has no pinned narrator voice"))
    for board, ref in refs:
        version = assets.get(ref.version_id)
        if version is None:
            problems.append(Violation("ref.unknown", board.path + ref.path, "Version is not visible"))
            continue
        scope = version.get("scope") or {}
        state = baseline.get(board.key)
        if (scope.get("story_id") not in (None, draft.story_id)
                or scope.get("board_id") not in (None, state.board_id if state else None)):
            problems.append(Violation("asset.scope_mismatch", board.path + ref.path,
                                      "Version is outside this story or board"))
        if ref.kinds is not None and version["kind"] not in ref.kinds:
            problems.append(Violation("asset.kind_mismatch", board.path + ref.path,
                                      "Version has the wrong asset kind"))
    if problems:
        raise ContractError("<agent draft>", problems)


async def _eligible(session: ToolSession, result: Result, order: list[str]) -> set[str]:
    live_ids = set(order)
    proposed = {board.key for board in result.draft.boards}
    eligible = set()
    for key, state in result.baseline.items():
        id_ = state.board_id
        reason = "removed"
        if id_ in live_ids:
            try:
                board = await _call(session, "studio_get_board", board_id=id_, fields=[])
            except ToolFailure as error:
                if error.http_status != 404:
                    raise
            else:
                reason = _baseline_conflict(board, key, state)
        if reason:
            result.record("conflict", reason, key=key, board_id=id_)
        elif key not in proposed:
            result.record("skipped", "not_targeted", key=key, board_id=id_)
        elif state.draft_sha256 == result.draft.sha256:
            result.record("skipped", "already_applied", key=key, board_id=id_)
        else:
            eligible.add(key)
    tracked = {state.board_id for state in result.baseline.values()}
    for id_ in order:
        if id_ not in tracked:
            result.record("conflict", "untracked_board", board_id=id_)
    for board in result.draft.boards:
        if board.key not in result.baseline:
            result.record("conflict", "unbound_board_key", key=board.key)
    return eligible


def _baseline_conflict(board: dict, key: str, state: BoardState) -> str | None:
    stamp = board.get("draft_application", {})
    if "person_edit" in stamp:
        return {"content": "edited_by_person", "reordered": "reordered", "removed": "removed"}[
            stamp["person_edit"]]
    if stamp.get("board_key") != key or stamp.get("draft_sha256") != state.draft_sha256:
        return "draft_hash_or_key_changed"
    if board["revision"] != state.revision or stamp.get("board_revision") != state.revision:
        return "revision_changed"
    return None


def _operation(draft: Draft, board: Proposal, revision: int,
               state: BoardState | None) -> tuple[str, dict]:
    stamp = {"board_key": board.key, "draft_sha256": draft.sha256,
             "model": draft.model, "session": draft.session}
    # Use new IDs for each attempt, even when a library caller reuses a parsed
    # draft after another draft has replaced and retired its original lines.
    minter = Minter()
    fields = thaw(board.fields)
    ids = {}
    for line in fields["lines"]:
        line_id = minter.mint("lin")
        ids[line["id"]] = line_id
        line["id"] = line_id
    for cue in fields["cues"]:
        anchor = cue["anchor"]
        if "after_line_id" in anchor:
            anchor["after_line_id"] = ids[anchor["after_line_id"]]
    fields["draft_application"] = stamp
    if state is None:
        return "studio_add_board", {"story_id": draft.story_id, "revision": revision, "fields": fields}
    stamp.update(previous_draft_sha256=state.draft_sha256, story_revision=revision)
    return "studio_patch_board", {"board_id": state.board_id, "revision": state.revision, "patch": fields}


async def apply_draft(session: ToolSession, draft: Draft,
                      previous: dict[str, BoardState] | None = None) -> Result:
    """Apply through an initialized MCP session. Return a receipt even after partial writes."""
    result = Result(draft, dict(previous or {}))
    await apply_into(session, result, first_apply=previous is None)
    return result


async def apply_into(session: ToolSession, result: Result, *, first_apply: bool) -> None:
    """Keep confirmed writes in a caller-owned receipt across transport cancellation."""
    draft = result.draft
    try:
        violations = [v for board in draft.boards for v in board.problems()]
        if violations:
            raise ContractError("<agent draft>", violations)
        story = await _story(session, draft)
        if first_apply and story["derived"]["next_board_number"] != 1:
            for id_ in story["board_order"]:
                result.record("conflict", "baseline_required", board_id=id_)
            raise ToolFailure("draft.baseline_required")
        await _validate_context(session, draft, story, result.baseline)
        eligible = ({b.key for b in draft.boards} if first_apply
                    else await _eligible(session, result, story["board_order"]))
        plan = [(board, *_operation(draft, board, story["revision"] + index, result.baseline.get(board.key)))
                for index, board in enumerate(b for b in draft.boards if b.key in eligible)]
        if any(len(json_text(arguments).encode("utf-8")) > MAX_ARGUMENT_BYTES for _, _, arguments in plan):
            raise ToolFailure("draft.arguments_too_large")
    except ContractError as error:
        result.abort({"code": "draft.invalid", "violations": [
            {"code": violation.rule, "path": violation.path} for violation in error.violations
        ]})
        return
    except ToolFailure as error:
        result.abort(error.detail)
        return

    stopped = False
    for board, tool, arguments in plan:
        state = result.baseline.get(board.key)
        id_ = state.board_id if state else None
        if stopped:
            result.record("skipped", "stopped_after_write_failure", key=board.key, board_id=id_)
            continue
        try:
            written = await _call(session, tool, **arguments)
            id_, revision, key_id, applied_at = _confirmed_write(written, draft, board, state)
        except ToolFailure as error:
            status = error.http_status
            outcome = ("conflict" if status in (404, 409) else
                       "failed" if status is not None and status < 500 else "uncertain")
            result.record(outcome, error.code, key=board.key, board_id=id_, error=error.detail)
            stopped = True
        except BaseException:
            # A transport task group or Ctrl-C can interrupt an awaited write.
            # Preserve its unknown outcome and pass the interruption to the caller.
            result.record("uncertain", "draft.write_interrupted", key=board.key, board_id=id_)
            raise
        else:
            result.baseline[board.key] = BoardState(id_, revision, draft.sha256)
            result.record("applied", "created" if state is None else "updated", key=board.key,
                          board_id=id_, revision=revision, key_id=key_id, applied_at=applied_at)


def _confirmed_write(written: dict, draft: Draft, board: Proposal,
                     state: BoardState | None) -> tuple[str, int, str, str]:
    stamp = written.get("draft_application") or {}
    principal = written.get("drafted_by") or {}
    id_, revision = written.get("id"), written.get("revision")
    expected = state.revision + 1 if state else 1
    if (not isinstance(stamp, dict) or not isinstance(principal, dict)
            or written.get("story_id") != draft.story_id or not is_id(id_, "brd")
            or (state is not None and id_ != state.board_id)
            or type(revision) is not int or revision != expected
            or stamp.get("board_revision") != revision or stamp.get("draft_sha256") != draft.sha256
            or stamp.get("board_key") != board.key or stamp.get("model") != draft.model
            or stamp.get("session") != draft.session or "person_edit" in stamp
            or not isinstance(applied_at := stamp.get("applied_at"), str)
            or principal.get("kind") != "agent" or not is_id(key_id := principal.get("key_id"), "key")):
        raise ToolFailure("draft.response_invalid")
    return id_, revision, key_id, applied_at
