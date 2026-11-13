"""JSON Schema files (draft 2020-12) shipped with the package, and how their errors
become rule violations.

A schema may annotate a subschema with ``"x-studio": {"<keyword>": {"rule": ...,
"message": ..., "field": ...}}``: when that keyword fails there, the violation takes
that rule code (else the caller's default), that message, and a path extended by
``field``. ``additionalProperties: false`` always reports ``schema.unknown_field``, one
violation per unknown field (contract section 2).

Schema files that declare an ``$id`` (the canonical ``studio.*.v1`` files of story
404) are registered together, so a ``$ref`` to another shipped file (for example
``studio.defs.v1.schema.json#/$defs/brd_id``) resolves offline; nothing is fetched.
"""

from __future__ import annotations

import json
import re
from functools import cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from haynes_studio.errors import Violation, pointer

UNKNOWN_FIELD = "schema.unknown_field"
ANNOTATION = "x-studio"
_MAX_MESSAGE = 160


def schema_text(filename: str) -> str:
    """The text of a shipped schema file, for example ``legacy.manifest.v1.schema.json``."""
    return files(__name__).joinpath(filename).read_text(encoding="utf-8")


def load_schema(filename: str) -> dict[str, Any]:
    """A fresh copy of a shipped schema as a dict."""
    return json.loads(schema_text(filename))


def shipped_schemas() -> list[str]:
    """The file names of every shipped schema, sorted."""
    return sorted(item.name for item in files(__name__).iterdir()
                  if item.name.endswith(".schema.json"))


@cache
def _registry() -> Registry:
    """Every shipped schema with an ``$id``, so cross-file references resolve offline."""
    resources = []
    for filename in shipped_schemas():
        schema = load_schema(filename)
        if "$id" in schema:
            resources.append((schema["$id"], Resource.from_contents(
                schema, default_specification=DRAFT202012)))
    return Registry().with_resources(resources)


@cache
def validator_for(filename: str) -> Draft202012Validator:
    """A checked draft 2020-12 validator for a shipped schema, built once."""
    schema = load_schema(filename)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=_registry())


def schema_violations(filename: str, document: Any, *, default_rule: str) -> list[Violation]:
    """Every schema error in ``document`` as violations, sorted by path then rule."""
    found: dict[tuple[str, str, str], Violation] = {}
    for error in validator_for(filename).iter_errors(document):
        for violation in _from_error(error, default_rule):
            found.setdefault((violation.path, violation.rule, violation.message), violation)
    return sorted(found.values(), key=lambda v: (v.path, v.rule, v.message))


def _from_error(error: ValidationError, default_rule: str) -> list[Violation]:
    path = pointer(*error.absolute_path)
    schema = error.schema if isinstance(error.schema, dict) else {}
    keyword = error.validator
    if keyword == "additionalProperties" and error.validator_value is False:
        known = set(schema.get("properties", {}))
        patterns = list(schema.get("patternProperties", {}))
        unknown = sorted(key for key in error.instance if key not in known
                         and not any(re.search(pattern, key) for pattern in patterns))
        return [Violation(UNKNOWN_FIELD, path + pointer(key), f"unknown field {key!r}")
                for key in unknown]
    note = schema.get(ANNOTATION, {}).get(keyword, {})
    message = note.get("message") or _message(error, schema)
    if "propertyNames" in error.absolute_schema_path:
        message = f"key {_short(error.instance)}: {message}"
        path += pointer(str(error.instance))
    if note.get("field"):
        path += pointer(note["field"])
    return [Violation(note.get("rule", default_rule), path, message)]


def _short(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 40 else text[:37] + "..."


def _message(error: ValidationError, schema: dict[str, Any]) -> str:
    """A short message that names the constraint, never a dump of the instance."""
    keyword, value = error.validator, error.validator_value
    if keyword == "type":
        kinds = value if isinstance(value, list) else [value]
        return f"must be of type {' or '.join(kinds)}"
    if keyword == "minimum":
        return f"must be at least {value}"
    if keyword == "maximum":
        return f"must be at most {value}"
    if keyword == "exclusiveMinimum":
        return f"must be greater than {value}"
    if keyword == "const":
        return f"must be {value!r}"
    if keyword == "enum":
        return f"must be one of {', '.join(repr(item) for item in value)}"
    if keyword == "pattern":
        return f"must match {value}"
    if keyword in ("minLength", "minItems", "minProperties"):
        return "must not be empty" if value == 1 else f"must have at least {value} entries"
    if keyword == "items" and value is False:
        return f"must have exactly {len(schema.get('prefixItems', []))} items"
    if keyword in ("required", "dependentRequired"):
        return error.message
    if keyword in ("not", "anyOf", "oneOf", "allOf"):
        return f"does not satisfy {keyword}"
    message = error.message
    return message if len(message) <= _MAX_MESSAGE else message[: _MAX_MESSAGE - 3] + "..."
