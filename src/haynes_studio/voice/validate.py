"""The ``studio.job/v1`` validator (contract sections 2 and 10), with story 404's
contexts and conventions: it refuses a document nested deeper than 64 levels, reads a
normalized copy, never raises for a malformed document, and returns violations sorted
by path.

The schema file carries the field rules: identifiers (a voice or photo job targets a
board), the status shape (only a succeeded job has a result and says whether it is
current; only a failed job has an error) and the voice block. The code here runs only
on a document the schema accepted and checks what one field cannot: the voice block's
take signatures and the job's ``input_signature`` follow from its lines, lead and gaps
(VOICE-3); every line is spoken in a recorded stock voice of the named model
(``voice.not_stock``, VOICE-1); one gap before each later line; no line twice.

Contexts ``read``, ``write`` and ``queue_run`` check the same rules; a job has no
``derived`` block, so ``derived`` is an unknown field everywhere.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from haynes_studio.canonical.validate import (
    READ,
    SCHEMA_INVALID,
    _blocking,
    _check_context,
    _duplicates,
    _prepare,
    _sorted,
)
from haynes_studio.errors import Violation, pointer
from haynes_studio.library.model import input_signature, is_stock_voice
from haynes_studio.library.validate import NOT_STOCK
from haynes_studio.schemas import schema_violations
from haynes_studio.voice.model import JOB_FILE, JOB_SCHEMA, line_signature


def validate_job(document: Any, *, context: str = READ) -> list[Violation]:
    """Every rule a ``studio.job/v1`` document breaks, sorted by path."""
    _check_context(context)
    document, stop = _prepare(document, JOB_SCHEMA)
    if stop is not None:
        return stop
    found = schema_violations(JOB_FILE, document, default_rule=SCHEMA_INVALID)
    if not _blocking(found) and document.get("voice") is not None:
        found += _voice_rules(document["voice"], document["input_signature"])
    return _sorted(found)


def _voice_rules(voice: Mapping[str, Any], signed: str) -> list[Violation]:
    lines = voice["lines"]
    found = _duplicates(((pointer("voice", "lines", i, "line_id"), line["line_id"])
                         for i, line in enumerate(lines)), "line")
    if len(voice["gaps_ms"]) != len(lines) - 1:
        found.append(Violation(SCHEMA_INVALID, "/voice/gaps_ms",
                               f"{len(lines)} lines need {len(lines) - 1} gaps (one before each "
                               "later line)"))
    for i, line in enumerate(lines):
        at = pointer("voice", "lines", i)
        if not is_stock_voice(voice["model"], line["voice_id"]):
            found.append(Violation(NOT_STOCK, at + "/voice_id",
                                   f"{line['voice_id']!r} is not a recorded stock voice of "
                                   f"{voice['model']!r} (VOICE-1, P-22)"))
        expected = line_signature(voice["engine"], line["voice_id"], line["text"])
        if line["signature"] != expected:
            found.append(Violation(SCHEMA_INVALID, at + "/signature",
                                   "must be the take signature of the engine, voice_id, NFC text "
                                   "and speed (VOICE-3)"))
    if not found:
        expected = input_signature([line["signature"] for line in lines], voice["lead_ms"],
                                   list(voice["gaps_ms"]))
        if signed != expected:
            found.append(Violation(SCHEMA_INVALID, "/input_signature",
                                   "must be the signature of the voice block's takes, lead and "
                                   "gaps (VOICE-3)"))
    return found


__all__ = ["validate_job"]
