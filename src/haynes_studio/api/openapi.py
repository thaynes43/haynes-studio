"""Link the shipped canonical JSON Schemas into the generated OpenAPI document."""

from copy import deepcopy

from fastapi import FastAPI

from haynes_studio.db.drafts import BOARD_FIELDS, STORY_FIELDS
from haynes_studio.drafting.declaration import DraftDeclaration, RedraftDeclaration
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
    schemas["BoardWrite"] = _write("BoardWrite", schemas["Board"], BOARD_FIELDS)
    for shape in ("StoryCreate", "StoryPatch"):
        ref = _child_input(schemas, "bed_cue", "BedInput")
        schemas[shape]["properties"]["beds"]["items"] = ref
    line = schemas["BoardWrite"]["properties"]["lines"]["items"]
    line["required"].remove("id")
    line["properties"]["id"]["description"] = (
        "Omit for a new line or preserve an existing line ID. An agent draft declaration "
        "also allows a fresh line ID to anchor a cue in the same write."
    )
    schemas["BoardWrite"]["properties"]["draft_application"] = {
        "description": "Agent only. Use DraftDeclaration to create and RedraftDeclaration to patch.",
        "oneOf": [DraftDeclaration.model_json_schema(), RedraftDeclaration.model_json_schema()],
    }
    note = _child_input(schemas, "note", "NoteInput")
    schemas["BoardWrite"]["properties"]["notes"]["items"] = note
    cue = deepcopy(schemas["StudioDefs_board_cue"])
    for branch, kind in zip(cue["allOf"], ("sound", "move", "camera"), strict=True):
        branch["then"] = _child_input(schemas, f"{kind}_cue", f"{kind.title()}CueInput")
    schemas["BoardCueInput"] = cue
    schemas["BoardWrite"]["properties"]["cues"]["items"] = {"$ref": "#/components/schemas/BoardCueInput"}


_HUMAN_OPERATIONS = {"get_selections", "put_selections", "create_production", "enable_media_type", "logout"}
_DRAFT_OPERATIONS = {"create_story", "update_story", "create_board", "update_board",
                     "reorder_boards", "remove_board"}


def _document_access(document: dict) -> None:
    for methods in document["paths"].values():
        for method, operation in methods.items():
            if not operation.get("security"):
                continue
            name = operation["operationId"]
            if name in _HUMAN_OPERATIONS:
                operation["security"] = [{"StudioSession": []}]
                operation["x-studio-scope"] = "human"
            elif name in _DRAFT_OPERATIONS:
                operation["x-studio-scope"] = "draft:write"
            elif name != "get_me":
                operation["x-studio-scope"] = "read"
            if method in ("get", "head") and "parameters" in operation:
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
        schemas["AssetDetail"]["properties"]["asset"] = {"$ref": "#/components/schemas/Asset"}
        _write_schemas(schemas)
        _document_access(document)
        _document_request_ids(document)
        schemas["ExternalPhotoDeclaration"] = ExternalPhotoDeclaration.model_json_schema()
        return document

    app.openapi = openapi
