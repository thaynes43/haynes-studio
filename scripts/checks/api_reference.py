"""Generate or check the Studio API and MCP reference without starting a service."""

import argparse
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys

from fastapi.routing import APIRoute, iter_route_contexts
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from haynes_studio.api.app import schema_app
from haynes_studio.api.auth import WorkerRoute
from haynes_studio.jsonio import parse_strict
from haynes_studio.mcp.server import UPLOAD_TOOL, VERSION as MCP_VERSION
from haynes_studio.mcp.tools import OPERATIONS

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "docs/reference"
DATA = REFERENCE / "api-reference-data"
REGENERATE = "uv run --locked python scripts/checks/api_reference.py"
OPENAPI_URI = "urn:haynes-studio:reference:openapi"
WORKER_REASON = (
    "Internal worker protocol excluded from OpenAPI. "
    "[Run queue](run-queue.md#claims-and-reconciliation) and [media workers](media-jobs.md#claims-and-results)."
)
PATH_PARAM = re.compile(r"\{([^{}]+)\}")


@dataclass(frozen=True)
class HttpOperation:
    method: str
    path: str
    name: str
    schema: dict

    @property
    def label(self):
        return f"{self.method.upper()} {self.path}"

    @property
    def family(self):
        return self.schema.get("tags", ["probes"])[0]


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2) + "\n"


def load_data(filename):
    return parse_strict((DATA / filename).read_text(encoding="utf-8"))


def markdown_cell(value):
    return value.replace("|", "&#124;").replace("\n", " ")


def literal(value):
    return f"`{markdown_cell(str(value))}`"


def row(*values):
    return "| " + " | ".join(values) + " |"


def add_unique(index, key, value):
    if key in index:
        raise ValueError(f"Duplicate operation {key}")
    index[key] = value


def read_contracts():
    # This module is the `studio-api` entry point used by the web generator.
    export = subprocess.check_output([sys.executable, "-m", "haynes_studio.api", "openapi"], text=True)
    document = parse_strict(export)
    operations = {}
    for path, methods in sorted(document["paths"].items()):
        for method, schema in sorted(methods.items()):
            name = schema["operationId"]
            add_unique(operations, name, HttpOperation(method, path, name, schema))

    # FastAPI's route contexts flatten included routers, as in its OpenAPI exporter.
    actual = {}
    omitted = []
    for route in iter_route_contexts(schema_app().routes):
        if not isinstance(route.original_route, APIRoute):
            raise ValueError(f"Unclassified application route {route.path}")
        for method in sorted(route.methods):
            operation = HttpOperation(method.lower(), route.path_format, route.operation_id, {})
            if route.include_in_schema:
                add_unique(actual, (operation.method, operation.path), operation.name)
            elif isinstance(route.original_route, WorkerRoute) and route.path.startswith("/internal/v1/work/"):
                omitted.append(operation)
            else:
                raise ValueError(f"Give {operation.label} a reason for exclusion from the reference")
    advertised = {(op.method, op.path): op.name for op in operations.values()}
    if actual != advertised:
        raise ValueError(f"OpenAPI and application routes differ: {sorted(actual.items() ^ advertised.items())}")
    return document, operations, sorted(omitted, key=lambda op: op.path)


def route_key(method, path):
    # MCP names path fields by entity (`board_id`); HTTP often calls them `id`.
    return method.lower(), PATH_PARAM.sub("{}", path)


def read_tools(http):
    by_route = {}
    for operation in http.values():
        add_unique(by_route, route_key(operation.method, operation.path), operation)
    tools, mirrors = {}, {}
    for name, operation in sorted(OPERATIONS.items()):
        schema = operation.schema(name).model_dump(mode="json", by_alias=True, exclude_none=True)
        tools[name] = schema
        mirrors[name] = by_route.get(route_key(operation.method, operation.path))
        fields = schema["inputSchema"]["properties"]
        if not set(PATH_PARAM.findall(operation.path)) <= fields.keys():
            raise ValueError(f"{name}: forwarded HTTP path needs fields missing from inputSchema")
    return tools, mirrors


def agent_scope(operation):
    scope = operation.schema.get("x-studio-scope", [])
    return " and ".join(map(literal, scope if isinstance(scope, list) else [scope]))


def callers(operation):
    auth = {name for alternative in operation.schema.get("security", []) for name in alternative}
    if auth - {"StudioBearer", "StudioSession"}:
        raise ValueError(f"{operation.name}: unknown OpenAPI security scheme {auth}")
    access = []
    if "StudioSession" in auth:
        role = "Person"
        if operation.schema.get("x-studio-scope") == "go_live:approve":
            role += " with " + literal("go_live:approve")
        access.append(role)
    if "StudioBearer" in auth:
        scope = agent_scope(operation) or "any valid key"
        if operation.schema.get("x-studio-key") == "package responder":
            access.append(f"Package responder with {scope}")
        elif operation.name == "get_job":
            access.append(f"Agent with {scope} (board and production-scoped matte jobs)")
        else:
            access.append(f"Agent with {scope}")
    return " or ".join(access) if access else "No Studio credential"


def schema_label(schema):
    if "$ref" in schema:
        return literal(schema["$ref"].rsplit("/", 1)[1])
    for keyword in ("anyOf", "oneOf", "allOf"):
        if keyword in schema:
            separator = " and " if keyword == "allOf" else " or "
            return separator.join(map(schema_label, schema[keyword]))
    if schema.get("format") == "binary":
        return "bytes"
    if schema.get("type") == "object":
        return "inline object"
    if schema.get("type") == "array":
        return f"array of {schema_label(schema['items'])}"
    return literal(schema["type"]) if "type" in schema else "schema unspecified"


def content_label(description):
    parts = defaultdict(list)
    for media, definition in sorted(description.get("content", {}).items()):
        parts[schema_label(definition.get("schema", {}))].append(media)
    labels = []
    for shape, media in parts.items():
        suffix = "" if media == ["application/json"] else f" ({', '.join(map(literal, media))})"
        labels.append(shape + suffix)
    return ", ".join(labels)


def parameters_label(operation):
    parts = defaultdict(list)
    for parameter in operation.schema.get("parameters", []):
        name = literal(parameter["name"]) + ("*" if parameter["required"] else "")
        nested = parameter["schema"].get("contentSchema")
        if nested:
            name += f" ({schema_label(nested)})"
        parts[parameter["in"]].append(name)
    return "<br>".join(f"{place.capitalize()} {', '.join(names)}" for place, names in parts.items()) or "—"


def http_rows(operations):
    groups = defaultdict(list)
    for operation in operations.values():
        groups[operation.family].append(operation)
    for family, items in sorted(groups.items()):
        yield f"### {family.capitalize()}"
        yield ""
        yield row("Method and path", "Operation ID", "Access", "Parameters", "Request body", "Success", "Error status")
        yield row(*(["---"] * 7))
        for operation in items:
            body = operation.schema.get("requestBody")
            request = content_label(body) if body else "—"
            if body and not body.get("required"):
                request += " (optional)"
            success, errors = [], []
            for status, response in sorted(operation.schema["responses"].items()):
                if status.startswith(("2", "3")):
                    shape = content_label(response)
                    success.append(f"{status} {shape}" if shape else status)
                else:
                    errors.append(status)
            yield row(literal(operation.label), literal(operation.name), callers(operation),
                      parameters_label(operation), request, "<br>".join(success), ", ".join(errors) or "—")
        yield ""


def http_example(example, operation, registry):
    part = example["part"]
    if part == "empty response":
        response = operation.schema["responses"][example["status"]]
        if response.get("content") or "value" in example:
            raise ValueError("Expected a response without a documented body and no example value")
        return example["status"] + " response without a body"

    media = example.get("media_type", "application/json")
    if part == "request":
        location = ("requestBody", "content", media, "schema")
    elif part == "response":
        location = ("responses", example["status"], "content", media, "schema")
    elif part == "parameter":
        parameters = operation.schema["parameters"]
        index = next(i for i, p in enumerate(parameters) if (p["in"], p["name"]) ==
                     (example["in"], example["name"]))
        location = ("parameters", index, "schema")
        if "contentSchema" in parameters[index]["schema"]:
            # E.g. the D42 declaration. Validate the decoded JSON carried in the header.
            location += ("contentSchema",)
    else:
        raise ValueError(f"Unknown HTTP example part {part}")

    tokens = ("paths", operation.path, operation.method, *location)
    pointer = "/".join(str(token).replace("~", "~0").replace("/", "~1") for token in tokens)
    validator = Draft202012Validator({"$ref": f"{OPENAPI_URI}#/{pointer}"}, registry=registry,
                                     format_checker=FormatChecker())
    validator.validate(example["value"])
    return example["name"] + " parameter" if part == "parameter" else part


def check_examples(document, operations, tools, mirrors):
    examples = load_data("examples.json")
    required = {operation.family for operation in operations.values()} | {"photo upload"}
    if examples.keys() != required:
        raise ValueError(f"Example families differ: missing {sorted(required - examples.keys())}, "
                         f"extra {sorted(examples.keys() - required)}")
    registry = Registry().with_resource(OPENAPI_URI, DRAFT202012.create_resource(document))
    output = []
    for family, example in sorted(examples.items()):
        try:
            if "tool" in example:
                name = example["tool"]
                operation = mirrors[name]
                if operation is None:
                    raise ValueError(f"{name} has no HTTP family")
                validator = Draft202012Validator(tools[name]["inputSchema"], format_checker=FormatChecker())
                validator.validate(example["value"])
                subject = f"{literal(name)} arguments"
            else:
                name = example["operation"]
                operation = operations[name]
                subject = f"{literal(name)} {http_example(example, operation, registry)}"
            expected = "photo upload" if operation.name == "upload_board_photo" else operation.family
            if family != expected:
                raise ValueError(f"{name} belongs to {expected}")
        except (KeyError, StopIteration) as error:
            raise ValueError(f"Example {family}: unknown operation, parameter or schema ({error})") from error
        except (ValueError, ValidationError) as error:
            raise ValueError(f"Example {family}: {str(error).splitlines()[0]}") from error
        output.append(row(family.capitalize(), subject))
    return output


def error_rows(operations, entries):
    for entry in entries:
        status = str(entry["status"])
        for name in entry["operations"]:
            operation = operations[name]
            if status not in operation.schema["responses"]:
                raise ValueError(f"{name}: HTTP {status} is missing from OpenAPI")
        yield row(", ".join(map(literal, entry["operations"])), status, ", ".join(map(literal, entry["codes"])))


def parity_rows(operations, omitted, tools, mirrors, metadata):
    mirrored = {operation.name for operation in mirrors.values() if operation is not None}
    api_gaps = {name for name in operations if name not in mirrored}
    tool_gaps = {name for name in tools if mirrors[name] is None}
    reasons = metadata["http_gaps"]
    tool_reasons = metadata["mcp_gaps"]
    if reasons.keys() - api_gaps or tool_reasons.keys() - tool_gaps:
        raise ValueError("Parity reasons name an operation or tool that no longer has a gap")

    yield "### API operations with no MCP tool"
    yield ""
    yield row("Method and path", "Operation ID", "Reason")
    yield row("---", "---", "---")
    for operation in [*operations.values(), *omitted]:
        if operation.name not in mirrored:
            reason = reasons.get(operation.name, "unrecorded") if operation.schema else WORKER_REASON
            yield row(literal(operation.label), literal(operation.name), reason)
    yield ""
    yield "### MCP tools with no API operation"
    yield ""
    if not tool_gaps:
        yield "Every registered MCP tool forwards to an HTTP operation."
    else:
        yield row("Tool", "Reason")
        yield row("---", "---")
        for name in sorted(tool_gaps):
            yield row(literal(name), tool_reasons.get(name, "unrecorded"))


def render(document, operations, omitted, tools, mirrors, schemas):
    metadata = load_data("notes.json")
    # Links in the include are also valid when opened from its own directory.
    conventions = (DATA / "conventions.md").read_text(encoding="utf-8").rstrip().replace("](../", "](")
    identity = sha256(json_text({"openapi": document, "tools": tools, "worker_routes": [
        (op.label, op.name) for op in omitted
    ]}).encode("utf-8")).hexdigest()
    lines = [
        "# Studio API and MCP reference",
        "",
        f"API **{document['info']['version']}**, OpenAPI **{document['openapi']}**, studio-mcp **{MCP_VERSION}**.",
        f"Source contract build SHA-256 `{identity}`.",
        "The build digest identifies the offline OpenAPI export, MCP tool descriptors and excluded worker route index.",
        "",
        "Regenerate this page and its schema data when a PR changes an operation, tool or schema.",
        "The source CI job checks the generated files. From the repository root, run",
        "",
        "```sh",
        REGENERATE,
        "```",
        "",
        conventions,
        "",
        f"## HTTP operations ({len(operations)})",
        "",
        f"[Schema data](api-reference-data/{schemas}) holds the named HTTP types under `components.schemas`.",
        "Run `uv run --locked studio-api openapi` for the full document, including parameter constraints and response headers.",
        "A `*` marks a required parameter in OpenAPI. Browser writes also require CSRF.",
        "A success status shown alone has no response body schema in OpenAPI.",
        "Error status shows the statuses declared by OpenAPI, including shared responses.",
        "",
        *http_rows(operations),
        "### Stable errors",
        "",
        "JSON errors use the OpenAPI `ErrorEnvelope`. Common codes and recovery steps appear above.",
        "The table lists stable operation-specific codes recorded in the handlers and guides.",
        "Contract validation can also return rule codes from the [rule index](../contracts/studio-contracts-v1.md#15-rule-index).",
        "HEAD responses carry status and headers without an error body.",
        "",
        row("Operation", "HTTP status", "Stable `error.code` values"),
        row("---", "---", "---"),
        *error_rows(operations, metadata["errors"]),
        "",
        f"## MCP tools ({len(tools)})",
        "",
        f"[Schema data](api-reference-data/{schemas}) holds each full `inputSchema` under `tools.<name>`.",
        "Use the linked operation guides for result projections. Tool parameters are JSON arguments.",
        "Tools use `/mcp` except for the one marked `/mcp/upload`.",
        "",
        row("Tool", "Agent scope", "Input schema", "HTTP operation"),
        row("---", "---", "---", "---"),
    ]
    for name, tool in tools.items():
        mirror = mirrors[name]
        schema = tool["inputSchema"]
        schema_name = literal(schema["title"])
        required = schema.get("required", [])
        if required:
            schema_name += " (requires " + ", ".join(map(literal, required)) + ")"
        endpoint = " (`/mcp/upload`)" if name == UPLOAD_TOOL else ""
        lines.append(row(literal(name) + endpoint, agent_scope(mirror) if mirror else "unrecorded", schema_name,
                         f"{literal(mirror.name)} · {literal(mirror.label)}" if mirror else "—"))
    lines.extend([
        "",
        "## Examples",
        "",
        "[Synthetic examples](api-reference-data/examples.json) show one schema-checked payload per family.",
        "They describe individual request or response parts. Use the HTTP or MCP table for the rest of the call.",
        "",
        row("Family", "Validated part"),
        row("---", "---"),
        *check_examples(document, operations, tools, mirrors),
        "",
        "## Parity gaps",
        "",
        *parity_rows(operations, omitted, tools, mirrors, metadata),
        "",
        "## Not documented",
        "",
        "The following worker-only HTTP contracts are outside the published OpenAPI document.",
        "They require a worker bearer, its lane grant and the current claim fence for claim mutations.",
        "",
        row("Method and path", "Operation ID", "Access", "Reason"),
        row("---", "---", "---", "---"),
        *(row(literal(op.label), literal(op.name), "Worker", WORKER_REASON) for op in omitted),
        "",
    ])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate examples and compare the generated files")
    args = parser.parse_args()
    try:
        document, operations, omitted = read_contracts()
        tools, mirrors = read_tools(operations)
        schema_file = "schemas.json"
        outputs = {
            REFERENCE / "api-reference.md": render(document, operations, omitted, tools, mirrors, schema_file),
            DATA / schema_file: json_text({"components": document["components"], "tools": tools}),
        }
        if args.check:
            stale = [str(path.relative_to(ROOT)) for path, content in outputs.items()
                     if not path.is_file() or path.read_bytes() != content.encode("utf-8")]
            if stale:
                raise ValueError("Stale generated reference files: " + ", ".join(stale))
        else:
            for path, content in outputs.items():
                path.write_bytes(content.encode("utf-8"))
    except (KeyError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"API reference: {error}\nRegenerate with `{REGENERATE}`.", file=sys.stderr)
        return 1
    print(f"API reference: {len(operations)} HTTP operations, {len(tools)} MCP tools, "
          f"{len(omitted)} internal worker exclusions. Examples validated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
