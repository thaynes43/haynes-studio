"""The allowlist of Studio tools and their projections of API records."""

import binascii
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import get_args

from mcp.types import Tool as MCPTool, ToolAnnotations

from haynes_studio.api.archive_routes import MAX_TEXT_BYTES
from haynes_studio.photo_limits import MAX_UPLOAD_BYTES

from . import arguments as args
from .upstream import Problem, Reply, StudioAPI

Projection = Callable[[Reply, args.Arguments], dict]
BOARD_FIELDS = get_args(args.BOARD_EDIT_FIELDS)


def pick(record: dict, *fields: str) -> dict:
    return {key: record[key] for key in fields if key in record}


def production(record: dict) -> dict:
    return {
        "schema": record["schema"], "id": record["id"], "revision": record["revision"],
        "name": record["name"],
        "media_types": [pick(item, "kind", "width", "height", "fps", "aspect")
                        for item in record["media_types"]],
    }


def story(record: dict) -> dict:
    return {
        **pick(record, "schema", "production_id", "media_kind", "title", "format_version_id"),
        "id": record["id"], "revision": record["revision"],
        "board_count": len(record["board_order"]),
        "derived": pick(record.get("derived", {}), "frames", "fps", "duration_ms",
                        "timed_boards", "untimed_boards", "next_board_number"),
    }


def board(record: dict) -> dict:
    provenance = pick(record, "drafted_by", "draft_application") if "draft_application" in record else {}
    return {
        **pick(record, "schema", "number", "title"), **provenance,
        **pick(record, "person_edit", "person_edit_revision", "person_edit_acknowledgments"),
        "id": record["id"], "story_id": record["story_id"], "revision": record["revision"],
    }


def version(record: dict) -> dict:
    return {
        **pick(record, "schema", "asset_id", "kind", "name", "capabilities", "state", "scope"),
        "id": record["id"], "number": record["number"],
    }


def page(project: Callable[[dict], dict]) -> Projection:
    def projection(reply: Reply, arguments: args.Arguments) -> dict:
        return {"items": [project(item) for item in reply.document["items"]],
                "next_cursor": reply.document["next_cursor"]}
    return projection


def production_detail(reply: Reply, _) -> dict:
    return {**production(reply.document), "labels": reply.document["labels"]}


def story_write(reply: Reply, _) -> dict:
    return story(reply.document)


def ordered_page(items: list, ids: list[str], revision: int, request_id: str | None,
                 cursor: str | None, limit: int) -> tuple[list, str | None]:
    start = 0
    if cursor:
        cursor_revision, anchor = cursor.split(":")
        if int(cursor_revision) != revision:
            raise Problem(409, "conflict.revision", "The story changed. Restart from the first page",
                          path="/cursor", request_id=request_id, current_revision=revision)
        try:
            start = ids.index(anchor) + 1
        except ValueError:
            raise Problem(422, "cursor.invalid", "The cursor does not belong to this story",
                          path="/cursor", request_id=request_id) from None
    end = start + limit
    return items[start:end], f"{revision}:{ids[end - 1]}" if end < len(ids) else None


def story_detail(reply: Reply, arguments: args.StorySummary) -> dict:
    record = reply.document
    order = record["board_order"]
    ids, cursor = ordered_page(order, order, record["revision"], reply.request_id,
                               arguments.cursor, arguments.limit)
    return {
        **story(record), **pick(record, *(arguments.fields or [])),
        "board_order": ids, "next_cursor": cursor,
    }


def timing_detail(reply: Reply, arguments: args.StoryPage) -> dict:
    record = reply.document
    rows = record["boards"]
    boards, cursor = ordered_page(rows, [item["board_id"] for item in rows],
                                  record["story_revision"], reply.request_id,
                                  arguments.cursor, arguments.limit)
    return {
        **pick(record, "schema", "story_id", "story_revision", "fps", "frames_known",
               "complete", "format_length", "build_allowed", "warnings"),
        "boards": boards, "next_cursor": cursor,
        "build_blocker_count": len(record["build_blockers"]),
    }


def board_detail(reply: Reply, arguments: args.GetBoard) -> dict:
    record = reply.document
    fields = BOARD_FIELDS if arguments.fields is None else arguments.fields
    read_token = {"read_token": reply.board_read_token} if reply.board_read_token else {}
    return {**board(record), **pick(record, *fields), **read_token,
            "derived": pick(record.get("derived", {}), "frames", "voice_state", "photo_state",
                            "timing_state", "content_ms", "film_start_frame")}


def board_write(reply: Reply, _) -> dict:
    return board(reply.document)


def added_board(reply: Reply, arguments: args.AddBoard) -> dict:
    # This API's accepted POST appends one board in the same revision transaction.
    return {**board(reply.document), "story_revision": arguments.revision + 1}


def removed_board(_: Reply, arguments: args.BoardWrite) -> dict:
    # A successful API 204 has no representation. The tombstone increments once.
    return {"id": arguments.board_id, "revision": arguments.revision + 1, "tombstone": True}


def asset_detail(reply: Reply, _) -> dict:
    record = reply.document
    item = record["asset"]
    return {
        "asset": {**pick(item, "schema", "kind", "name", "scope", "labels"),
                  "id": item["id"], "revision": item["revision"]},
        "versions": [version(item) for item in record["versions"]],
        "next_cursor": record["next_cursor"],
    }


def delivery_detail(reply: Reply, _) -> dict:
    record = reply.document
    return {
        **pick(record, "schema", "id", "run_id"),
        "master": pick(record["master"], "sha256", "bytes", "frames", "media_type"),
        "proxy": pick(record["proxy"], "sha256", "bytes", "frames", "media_type")
        if record["proxy"] is not None else None,
    }


@dataclass(frozen=True)
class Operation:
    description: str
    arguments: type[args.Arguments]
    method: str
    path: str
    project: Projection
    query: tuple[str, ...] = ()
    body: str | tuple[str, ...] | None = None
    expect: int | tuple[int, ...] = 200
    job_input: tuple[str, ...] | None = None
    argument_limit: int | None = None
    result_limit: int | None = None
    idempotent: bool = False

    def schema(self, name: str) -> MCPTool:
        return MCPTool(
            name=name, description=self.description, inputSchema=self.arguments.model_json_schema(),
            annotations=ToolAnnotations(
                readOnlyHint=self.method == "GET", destructiveHint=self.method in {"PATCH", "PUT", "DELETE"},
                idempotentHint=True if (self.idempotent or self.job_input is not None
                                        or self.arguments is args.QueueRun) else None,
                openWorldHint=False,
            ),
        )

    async def call(self, api: StudioAPI, authorization: str, arguments: args.Arguments) -> Reply:
        values = arguments.model_dump(exclude_unset=True)
        query = {field: getattr(arguments, field) for field in self.query
                 if getattr(arguments, field) is not None}
        body = values[self.body] if isinstance(self.body, str) else pick(values, *(self.body or ())) or None
        if self.job_input is not None:
            body = pick(values, *self.job_input)
        transport = {}
        if isinstance(arguments, args.UploadPhoto):
            try:
                binary = binascii.a2b_base64(arguments.data_base64, strict_mode=True)
            except ValueError:
                raise Problem(422, "photo.image_invalid", "Expected base64 encoded image bytes") from None
            if len(binary) > MAX_UPLOAD_BYTES:
                raise Problem(413, "photo.too_large", "An upload can be at most 20 MiB")
            transport = {"binary": binary, "media_type": arguments.media_type,
                         "provenance": json.dumps(values["provenance"], ensure_ascii=True, separators=(",", ":"))}
        return await api.request(authorization, self.method, self.path.format_map(values),
                                 query=query or None, body=body, idempotency_key=values.get("idempotency_key"),
                                 revision=values.get("revision"), expect=self.expect, **transport)


def job_detail(reply, _):
    return pick(reply.document, "schema", "id", "kind", "target_id", "status", "input_signature",
                "result_version_id", "result_is_current", "error", "created_by", "created_at", "updated_at")


def raw_detail(reply, _):
    return reply.document


def run_detail(reply, _):
    return run_status(reply.document)


def run_status(doc):
    return pick(doc, "schema", "id", "story_id", "revision", "number", "status", "snapshot",
                "progress", "wait_reason", "queue_wait", "stages", "checks", "error",
                "delivery_id", "cancel_requested", "answers")


def candidate_page(reply, _):
    record = reply.document
    return {
        **pick(record, "next_cursor", "revision", "iteration"),
        "items": [{
            **pick(item, "id", "run_id", "target_id", "presented_by", "presented_at", "answering_runs"),
            "notes": [pick(note, "id", "text", "board_ids", "replaces_id", "written_by", "written_at")
                      for note in item["notes"]],
        } for item in record["items"]],
    }


def upload_detail(reply, _):
    return {**reply.document, "version": version(reply.document["version"])}


_PAGE = ("cursor", "limit")
_ARCHIVE_TEXT_BODY = ("text", "format_version_id", "provenance")
# JSON may escape text bytes. Reserve space for the worst escape expansion and metadata.
ARCHIVE_TOOL_BYTES = 6 * MAX_TEXT_BYTES + 64 * 1024
OPERATIONS = {
    "studio_list_productions": Operation(
        "List productions visible to this key, with a cursor for the next page.",
        args.ListProductions, "GET", "/v1/productions", page(production), _PAGE),
    "studio_get_production": Operation(
        "Read a production's metadata and revision.", args.Production,
        "GET", "/v1/productions/{production_id}", production_detail),
    "studio_list_stories": Operation(
        "List story summaries for one production and media kind. Pass the same filters with next_cursor.",
        args.ListStories, "GET", "/v1/productions/{production_id}/media-types/{kind}/stories",
        page(story), (*_PAGE, "publication", "approved")),
    "studio_create_story": Operation(
        "Create a draft story under an enabled media kind. Supply a title and optional story fields.",
        args.CreateStory, "POST", "/v1/productions/{production_id}/media-types/{kind}/stories",
        story_write, body="fields", expect=201),
    "studio_get_story_summary": Operation(
        "Read a story summary and page through its ordered board IDs. Optionally select editable story fields.",
        args.StorySummary, "GET", "/v1/stories/{story_id}", story_detail),
    "studio_patch_story": Operation(
        "Replace supplied story fields at the given story revision. Omitted fields stay as stored.",
        args.PatchStory, "PATCH", "/v1/stories/{story_id}", story_write, body="patch"),
    "studio_get_story_timing": Operation(
        "Read timing and page through board frame counts and starts for one story revision.",
        args.StoryPage, "GET", "/v1/stories/{story_id}/timing", timing_detail),
    "studio_list_candidates": Operation(
        "Read a story's candidates and feedback notes. Use answers.candidate_id and batches of up to "
        "ten answers.note_ids to read selected notes. Page candidates with next_cursor.",
        args.Candidates, "GET", "/v1/stories/{story_id}/candidates", candidate_page,
        (*_PAGE, "run_id", "candidate_id", "note_ids")),
    "studio_add_board": Operation(
        "Append a draft board at the given story revision. Supply an empty fields object for defaults.",
        args.AddBoard, "POST", "/v1/stories/{story_id}/boards", added_board, body="fields", expect=201),
    "studio_get_board": Operation(
        "Read a board, its revision and a read token. Use fields to select editable fields, "
        "or omit it for all of them.",
        args.GetBoard, "GET", "/v1/boards/{board_id}", board_detail),
    "studio_patch_board": Operation(
        "Replace supplied board fields at the given board revision. Preserve IDs to edit lines, cues or "
        "notes, omit IDs to add them, and omit entries from the array to remove them. Re-read for child IDs. "
        "Use acknowledge_person_edit only when a person asked for this board by ID.",
        args.PatchBoard, "PATCH", "/v1/boards/{board_id}", board_write, body="patch"),
    "studio_reorder_boards": Operation(
        "Set the order at the given story revision. Include each active board ID exactly once. "
        "Acknowledge each protected board that moves only when a person asked for it by ID.",
        args.ReorderBoards, "PUT", "/v1/stories/{story_id}/board-order", story_write,
        body=("board_order", "acknowledge_person_edit")),
    "studio_remove_board": Operation(
        "Tombstone a draft board at the given board revision. "
        "Use acknowledge_person_edit only when a person asked for this board by ID.",
        args.RemoveBoard, "DELETE", "/v1/boards/{board_id}", removed_board,
        body=("acknowledge_person_edit",), expect=204),
    "studio_search_assets": Operation(
        "Search visible asset version metadata for a version ID to pin in a draft.",
        args.SearchAssets, "GET", "/v1/assets", page(version), (*_PAGE, "kind", "label", "production", "board")),
    "studio_get_asset": Operation(
        "Read an asset's metadata and revision and page through its version summaries.",
        args.Asset, "GET", "/v1/assets/{asset_id}", asset_detail, _PAGE),
    "studio_get_delivery": Operation(
        "Read the master and proxy metadata of a delivery by run ID.", args.Delivery,
        "GET", "/v1/runs/{run_id}/delivery", delivery_detail),
    "studio_list_formats": Operation(
        "List shared Studio format recipes by name and slug.", args.ListFormats,
        "GET", "/v1/formats", page(lambda item: pick(item, "id", "name")), _PAGE),
    "studio_list_format_versions": Operation(
        "List immutable version IDs, numbers and recipe hashes for a format.", args.ListFormatVersions,
        "GET", "/v1/formats/{format_id}/versions",
        page(lambda item: pick(item, "id", "format_id", "number", "sha256")), _PAGE),
    "studio_get_format_version": Operation(
        "Read a recipe by version ID. To pin it, use studio_patch_story with format_version_id.",
        args.FormatVersion, "GET", "/v1/format-versions/{version_id}",
        lambda reply, _: pick(reply.document, "id", "format_id", "number", "sha256", "recipe")),
    "studio_create_archive_record": Operation(
        "Stage the first immutable text version in a production. Reuse the idempotency key on a retry.",
        args.CreateArchiveRecord, "POST", "/v1/productions/{production_id}/archive-records", raw_detail,
        body=("kind", "title", *_ARCHIVE_TEXT_BODY), expect=(200, 201),
        argument_limit=ARCHIVE_TOOL_BYTES, idempotent=True),
    "studio_add_archive_version": Operation(
        "Append immutable text to a record at its current version ID. Reuse the idempotency key on a retry.",
        args.AddArchiveVersion, "POST", "/v1/archive-records/{record_id}/versions", raw_detail,
        body=("revises_version_id", *_ARCHIVE_TEXT_BODY), expect=(200, 201),
        argument_limit=ARCHIVE_TOOL_BYTES, idempotent=True),
    "studio_list_archive_records": Operation(
        "List archive records and their newest version IDs for one production.",
        args.ListArchiveRecords, "GET", "/v1/productions/{production_id}/archive-records", raw_detail, _PAGE),
    "studio_get_archive_record": Operation(
        "Read an archive record and a page of version metadata, newest first.",
        args.ArchiveRecord, "GET", "/v1/archive-records/{record_id}", raw_detail, _PAGE),
    "studio_get_archive_version": Operation(
        "Read the exact immutable text and provenance of an archive version by ID.",
        args.ArchiveVersion, "GET", "/v1/archive-versions/{version_id}", raw_detail,
        result_limit=ARCHIVE_TOOL_BYTES),
    "studio_apply_archive_storyboard": Operation(
        "Apply a pinned storyboard at the current story revision and report protected boards.",
        args.ApplyArchiveStoryboard, "POST", "/v1/archive-versions/{version_id}/apply", raw_detail,
        body=("story_id",), result_limit=ARCHIVE_TOOL_BYTES),
    "studio_generate_voice": Operation(
        "Queue voice for the saved board and return job status. Reuse the idempotency key on a retry.",
        args.GenerateVoice, "POST", "/v1/boards/{board_id}/voice-jobs", job_detail,
        expect=(200, 202), job_input=()),
    "studio_generate_photo": Operation(
        "Queue a reference photo for the saved board. Reuse the idempotency key on a retry.",
        args.GeneratePhoto, "POST", "/v1/boards/{board_id}/photo-jobs", job_detail,
        expect=(200, 202), job_input=("seed",)),
    "studio_upload_photo": Operation(
        "Upload base64 encoded still bytes and D42 provenance at the current board revision.",
        args.UploadPhoto, "POST", "/v1/boards/{board_id}/photo-versions", upload_detail, expect=201),
    "studio_get_job": Operation(
        "Read compact status and the result version ID for a scoped voice or photo job.",
        args.GetJob, "GET", "/v1/jobs/{job_id}", job_detail),
    "studio_estimate_run": Operation(
        "Read build estimates and preflight problems for a story.",
        args.Story, "GET", "/v1/stories/{story_id}/estimate", raw_detail),
    "studio_queue_run": Operation(
        "Queue a build from the saved story revision. Reuse the idempotency key on a retry.",
        args.QueueRun, "POST", "/v1/stories/{story_id}/runs", run_detail, expect=(200, 201)),
    "studio_list_runs": Operation(
        "Read a page of runs for a story.",
        args.Runs, "GET", "/v1/stories/{story_id}/runs", page(run_status), _PAGE),
    "studio_get_run": Operation(
        "Read a run's status, progress, stages and checks.",
        args.Delivery, "GET", "/v1/runs/{run_id}", run_detail),
    "studio_cancel_run": Operation(
        "Cancel a queued run or ask a running worker to cancel it at the current revision.",
        args.CancelRun, "POST", "/v1/runs/{run_id}/cancel", run_detail),
}
