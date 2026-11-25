"""Link the shipped canonical JSON Schemas into the generated OpenAPI document."""

from copy import deepcopy

from fastapi import FastAPI

from haynes_studio.db.drafts import BOARD_FIELDS, STORY_FIELDS
from haynes_studio.drafting.declaration import (
    DraftDeclaration, PersonEditAcknowledgment, RedraftDeclaration,
)
from haynes_studio.schemas import load_schema

from .models import ExternalPhotoDeclaration
from .transport import REQUEST_ID_HEADER

_CANONICAL = {
    "studio.defs.v1.schema.json": "StudioDefs",
    "studio.production.v1.schema.json": "Production",
    "studio.story.v1.schema.json": "Story",
    "studio.board.v1.schema.json": "Board",
    "studio.story-timing.v1.schema.json": "Timing",
    "studio.asset.v1.schema.json": "Asset",
    "studio.asset-version.v1.schema.json": "AssetVersion",
    "studio.delivery.v1.schema.json": "Delivery",
    "studio.run.v1.schema.json": "RunView",
    "studio.format-recipe.v1.schema.json": "FormatRecipe",
    "studio.job.v1.schema.json": "JobView",
    "studio.escalation.v1.schema.json": "EscalationPackage",
}


def _rewrite(value, current: str, components: dict, sources: dict):
    if isinstance(value, list):
        return [_rewrite(item, current, components, sources) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in ("$id", "$schema", "$defs"):
            continue
        if key == "$ref":
            file, _, anchor = item.partition("#")
            target = _CANONICAL[file] if file else current
            name = target
            if anchor:
                parts = anchor.removeprefix("/").split("/")
                name = "_".join([target, *parts[1:]])
                if name not in components:
                    schema = sources[target]
                    for part in parts:
                        schema = schema[part.replace("~1", "/").replace("~0", "~")]
                    components[name] = {}
                    components[name] = _rewrite(schema, target, components, sources)
            result[key] = f"#/components/schemas/{name}"
        else:
            result[key] = _rewrite(item, current, components, sources)
    return result


def _write(title: str, source: dict, fields: frozenset[str], required=()) -> dict:
    properties = {key: deepcopy(value) for key, value in source["properties"].items() if key in fields}
    output = {"title": title, "type": "object", "properties": properties, "additionalProperties": False}
    if required:
        output["required"] = list(required)
    return output


def _child_input(schemas, source: str, child: str):
    document = deepcopy(schemas[f"StudioDefs_{source}"])
    document["required"].remove("id")
    document["properties"]["id"]["description"] = "Omit for a new item. Preserve an existing item's ID."
    schemas[child] = document
    return {"$ref": f"#/components/schemas/{child}"}


def _write_schemas(schemas):
    schemas["StoryCreate"] = _write("StoryCreate", schemas["Story"], STORY_FIELDS, ("title",))
    schemas["StoryPatch"] = _write("StoryPatch", schemas["Story"], STORY_FIELDS)
    for shape in ("StoryCreate", "StoryPatch"):
        ref = _child_input(schemas, "bed_cue", "BedInput")
        schemas[shape]["properties"]["beds"]["items"] = ref
    board = _write("BoardCreate", schemas["Board"], BOARD_FIELDS)
    fields = board["properties"]
    line = fields["lines"]["items"]
    line["required"].remove("id")
    line["properties"]["id"]["description"] = (
        "Omit for a new line or preserve an existing line ID. An agent draft declaration "
        "also allows a fresh line ID to anchor a cue in the same write."
    )
    note = _child_input(schemas, "note", "NoteInput")
    fields["notes"]["items"] = note
    cue = deepcopy(schemas["StudioDefs_board_cue"])
    for branch, kind in zip(cue["allOf"], ("sound", "move", "camera"), strict=True):
        branch["then"] = _child_input(schemas, f"{kind}_cue", f"{kind.title()}CueInput")
    schemas["BoardCueInput"] = cue
    fields["cues"]["items"] = {"$ref": "#/components/schemas/BoardCueInput"}
    fields["draft_application"] = {"description": "Agent only.", **DraftDeclaration.model_json_schema()}
    schemas["BoardCreate"] = board
    schemas["PersonEditAcknowledgment"] = PersonEditAcknowledgment.model_json_schema()
    schemas["BoardPatch"] = {
        **board, "title": "BoardPatch", "properties": {
            **fields,
            "draft_application": {"description": "Agent only.", **RedraftDeclaration.model_json_schema()},
            "acknowledge_person_edit": {"$ref": "#/components/schemas/PersonEditAcknowledgment"},
        },
    }


_HUMAN_OPERATIONS = {"get_selections", "put_selections", "create_production", "enable_media_type",
                     "logout", "get_queue_lanes", "set_queue_lane",
                     "authorize_escalation", "decline_escalation", "cancel_escalation"}
_PREVIEW = {"get_job_result", "get_version_media", "head_version_media", "get_job_media", "head_job_media"}
_ASSET_OPERATIONS = {"generate_board_voice": "assets:generate", "generate_board_photo": "assets:generate",
                     "generate_asset_candidate": "assets:generate", "upload_board_photo": "assets:upload"}
_RUN_QUEUE_OPERATIONS = {"queue_run", "cancel_run", "record_check_override"}
_GO_LIVE_OPERATIONS = {"approve_go_live", "withdraw_go_live"}
_FORMAT_WRITE_OPERATIONS = {"create_format", "add_format_version"}
_DRAFT_OPERATIONS = {"create_story", "update_story", "create_board", "update_board",
                     "reorder_boards", "remove_board"}


def _document_access(document: dict) -> None:
    for methods in document["paths"].values():
        for method, operation in methods.items():
            if not operation.get("security"):
                continue
            name = operation["operationId"]
            if name in _HUMAN_OPERATIONS | _PREVIEW | {"promote_asset_version"}:
                operation["security"] = [{"StudioSession": []}]
                operation["x-studio-scope"] = "human"
            elif name in _ASSET_OPERATIONS:
                operation["x-studio-scope"] = _ASSET_OPERATIONS[name]
                if name == "generate_asset_candidate":
                    operation["security"] = [{"StudioSession": []}]
                elif name == "upload_board_photo":
                    operation["security"] = [{"StudioBearer": []}]
                    operation["parameters"] = [
                        parameter for parameter in operation["parameters"] if parameter["name"] != "X-Studio-CSRF"
                    ]
                    for parameter in operation["parameters"]:
                        if parameter["name"] == "X-Studio-Photo-Provenance":
                            parameter["required"] = True
                            parameter["schema"] = {"type": "string", "contentMediaType": "application/json",
                                                   "contentSchema": {"$ref": "#/components/schemas/ExternalPhotoDeclaration"}}
            elif name in _GO_LIVE_OPERATIONS:
                operation["security"] = [{"StudioSession": []}]
                operation["x-studio-scope"] = "go_live:approve"
            elif name in _RUN_QUEUE_OPERATIONS:
                if name == "record_check_override":
                    operation["security"] = [{"StudioSession": []}]
                operation["x-studio-scope"] = "runs:queue"
            elif name in _DRAFT_OPERATIONS:
                operation["x-studio-scope"] = "draft:write"
            elif name in _FORMAT_WRITE_OPERATIONS:
                operation["x-studio-scope"] = "formats:write"
            elif name == "report_escalation":
                operation["security"] = [{"StudioBearer": []}]
                operation["x-studio-scope"] = "read"
                operation["x-studio-key"] = "package responder"
            elif name != "get_me":
                operation["x-studio-scope"] = "read"
            if (method in ("get", "head") or name == "report_escalation") and "parameters" in operation:
                operation["parameters"] = [
                    value for value in operation["parameters"] if value["name"] != "X-Studio-CSRF"
                ]


def _document_request_ids(document: dict) -> None:
    for methods in document["paths"].values():
        for method, operation in methods.items():
            for response in operation["responses"].values():
                response.setdefault("headers", {})[REQUEST_ID_HEADER] = {
                    "description": "Server-generated request ID, also used in errors and access logs",
                    "schema": {"type": "string"},
                }
                if method == "head":
                    response.pop("content", None)


def install_openapi(app: FastAPI):
    generate = app.openapi

    def openapi():
        document = generate()
        schemas = document["components"]["schemas"]
        if "ExternalPhotoDeclaration" in schemas:
            return document
        sources = {name: load_schema(file) for file, name in _CANONICAL.items()}
        for name, schema in sources.items():
            if name != "StudioDefs":
                schemas[name] = _rewrite(schema, name, schemas, sources)
        # The API returns a story summary and separate boards. The exchange/snapshot
        # representation remains in the canonical schema file.
        schemas["Story"]["properties"].pop("boards")
        approval_id = {"type": ["string", "null"]}
        schemas["Story"]["required"].extend(["approved", "published", "latest_finished_run"])
        schemas["Story"]["properties"].update({
            "approved": {"type": "boolean"},
            "published": {"type": "boolean"},
            "latest_finished_run": {"type": ["object", "null"],
                                    "required": ["id", "status", "finished_at", "active_approval_id"],
                                    "properties": {
                                        "id": {"type": "string"},
                                        "status": {"enum": ["succeeded", "failed", "cancelled"]},
                                        "finished_at": {"type": "string", "format": "date-time"},
                                        "active_approval_id": approval_id,
                                    }},
        })
        schemas["AssetDetail"]["properties"]["asset"] = {"$ref": "#/components/schemas/Asset"}
        schemas["EscalationView"]["properties"]["package"] = {"$ref": "#/components/schemas/EscalationPackage"}
        run = schemas["RunView"]
        run["required"].extend(["revision", "cancel_requested", "estimate_methods", "queue_wait",
                                "active_approval_id"])
        run["properties"].update({
            "revision": {"type": "integer", "minimum": 1},
            "active_approval_id": approval_id,
            "cancel_requested": {"type": "boolean"},
            "estimate_methods": {"type": "array", "items": {"$ref": "#/components/schemas/MethodEstimate"}},
            "queue_wait": {"anyOf": [{"$ref": "#/components/schemas/QueueWait"}, {"type": "null"}]},
            "wan_attempts": {"type": "array", "items": {
                "type": "object", "required": ["job_id", "kind", "attempt", "state"],
                "properties": {
                    "job_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
                    "kind": {"enum": ["i2v", "s2v"]},
                    "attempt": {"type": "integer", "minimum": 1},
                    "state": {"enum": ["reserved", "sent", "succeeded", "failed", "restart_failed", "busy"]},
                },
            }},
            "check_overrides": {"type": "array", "items": {"$ref": "#/components/schemas/CheckOverrideView"}},
        })
        _write_schemas(schemas)
        _document_access(document)
        _document_request_ids(document)
        schemas["ExternalPhotoDeclaration"] = ExternalPhotoDeclaration.model_json_schema()
        return document

    app.openapi = openapi
