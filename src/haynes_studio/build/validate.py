"""Validators of ``studio.run/v1`` and ``studio.run-snapshot/v1`` (story 406), with
story 404's conventions: a document nested deeper than 64 levels is refused, a
normalized copy is read, a malformed document never raises, and violations come back
sorted by path. Contexts ``read``, ``write`` and ``queue_run`` check the same rules.

The schema files hold the field rules (``run.snapshot_missing`` for a run without its
snapshot's hash or revision, ``prov.licence_missing`` for an engine or engine file
without a licence object). The code checks what one field cannot:

- a public credit names an engine of the run with role ``video``, ``voice`` or
  ``sound`` (``credit.outside_video_sound``, D44); a credit naming no engine of the
  run is ``ref.unknown`` (proposal);
- a snapshot lists every asset version its story names exactly once
  (``asset.unresolved``, ``ref.duplicate``; proposals), and its story is a valid
  ``studio.story/v1`` read as the server returns it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from haynes_studio.canonical import validate_story
from haynes_studio.canonical.validate import (
    READ,
    REF_DUPLICATE,
    REF_UNKNOWN,
    SCHEMA_INVALID,
    _blocking,
    _check_context,
    _prepare,
    _sorted,
)
from haynes_studio.errors import Violation, pointer
from haynes_studio.library.resolve import references
from haynes_studio.schemas import schema_violations
from haynes_studio.stages.preflight import ASSET_UNRESOLVED

RUN_SCHEMA = "studio.run/v1"
RUN_FILE = "studio.run.v1.schema.json"
SNAPSHOT_SCHEMA = "studio.run-snapshot/v1"
SNAPSHOT_FILE = "studio.run-snapshot.v1.schema.json"
CREDIT_OUTSIDE = "credit.outside_video_sound"
CREDIT_ROLES = ("video", "voice", "sound")


def validate_run(document: Any, *, context: str = READ) -> list[Violation]:
    """Every rule a ``studio.run/v1`` document breaks, sorted by path."""
    _check_context(context)
    document, stop = _prepare(document, RUN_SCHEMA)
    if stop is not None:
        return stop
    found = schema_violations(RUN_FILE, document, default_rule=SCHEMA_INVALID)
    if not _blocking(found):
        found += _credits(document)
    return _sorted(found)


def _credits(document: Mapping[str, Any]) -> list[Violation]:
    provenance = document.get("provenance")
    if not isinstance(provenance, Mapping):
        return []
    roles = {engine["key"]: engine["role"] for engine in provenance["engines"]}
    out = []
    for index, credit in enumerate(provenance["public"]["credits"]):
        path = pointer("provenance", "public", "credits", index)
        role = roles.get(credit["engine_key"])
        if role is None:
            out.append(Violation(REF_UNKNOWN, path, f"credit names engine {credit['engine_key']!r}, "
                                 "which is not an engine of this run"))
        elif role not in CREDIT_ROLES:
            out.append(Violation(CREDIT_OUTSIDE, path, f"a public credit names a video, voice or "
                                 f"sound engine (D44); {credit['engine_key']!r} is {role}"))
    return out


def validate_run_snapshot(document: Any, *, context: str = READ) -> list[Violation]:
    """Every rule a ``studio.run-snapshot/v1`` document breaks, sorted by path."""
    _check_context(context)
    document, stop = _prepare(document, SNAPSHOT_SCHEMA)
    if stop is not None:
        return stop
    found = schema_violations(SNAPSHOT_FILE, document, default_rule=SCHEMA_INVALID)
    if not _blocking(found):
        found += [Violation(v.rule, "/story" + v.path, v.message, v.status)
                  for v in validate_story(document["story"], context=READ)]
    if not _blocking(found):
        found += _resolved(document)
    return _sorted(found)


def _resolved(document: Mapping[str, Any]) -> list[Violation]:
    out = []
    listed: dict[str, int] = {}
    for index, entry in enumerate(document["resolved_asset_versions"]):
        if entry["id"] in listed:
            out.append(Violation(REF_DUPLICATE, pointer("resolved_asset_versions", index, "id"),
                                 f"{entry['id']} is listed twice"))
        listed.setdefault(entry["id"], index)
    for reference in references(document["story"]):
        if reference.version_id not in listed:
            out.append(Violation(ASSET_UNRESOLVED, "/story" + reference.path,
                                 f"{reference.version_id} is not pinned in the snapshot"))
    return out


__all__ = ["CREDIT_OUTSIDE", "RUN_FILE", "RUN_SCHEMA", "SNAPSHOT_FILE", "SNAPSHOT_SCHEMA",
           "validate_run", "validate_run_snapshot"]
