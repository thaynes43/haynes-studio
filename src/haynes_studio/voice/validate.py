"""The ``studio.job/v1`` validator (contract sections 2 and 10), with story 404's
contexts and conventions: it refuses a document nested deeper than 64 levels, reads a
normalized copy, never raises for a malformed document, and returns violations sorted
by path.

The schema file carries the field rules: identifiers (a voice or photo job targets a
board), the status shape (only a succeeded job has a result and says whether it is
current; only a failed job has an error) and the voice block, whose lead and gaps are
at most 120000 ms each. The code here runs only on a document the schema accepted and
checks what one field cannot: the voice block's take signatures and the job's
``input_signature`` follow from its lines, lead and gaps (VOICE-3); every line is
spoken in a recorded stock voice of the named model (``voice.not_stock``, VOICE-1); one
gap before each later line; no line twice; the lead and gaps together leave room in a
track of at most 600000 ms.

:func:`voice_input_violations` applies the same voice rules to a
:class:`~haynes_studio.voice.model.VoiceInput` that did not come from a validated job
(``make_voice``'s own argument), so no input reaches the speech client unchecked.

Contexts ``read``, ``write`` and ``queue_run`` check the same rules; a job has no
``derived`` block, so ``derived`` is an unknown field everywhere.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from haynes_studio.canonical.model import to_document
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
from haynes_studio.voice.model import (
    GAP_MAX_MS,
    JOB_FILE,
    JOB_SCHEMA,
    LEAD_MAX_MS,
    LINES_MAX,
    TRACK_MAX_MS,
    VoiceInput,
    line_signature,
)


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


def voice_input_violations(voice: VoiceInput) -> list[Violation]:
    """The voice block's rules for an input that did not come from a validated job:
    stock voices (VOICE-1), take signatures (VOICE-3), one gap per later line, no line
    twice, and the time bounds. Paths are under ``/voice``, as in a job."""
    return _sorted(_voice_rules(to_document(voice), None))


def _whole_ms(value: Any, limit: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= limit


def time_violations(lead_ms: Any, gaps: Iterable[tuple[str, Any]], *, lead_at: str,
                    total_at: str) -> list[Violation]:
    """The time bounds of a voice input (proposal, story 405), as ``schema.invalid``: a
    lead and each gap (``(path, ms)`` pairs) are integer milliseconds from 0 to 120000,
    the contract's longest silent hold (TIME-4), and together they leave room in a
    track of at most 600000 ms."""
    gaps = list(gaps)
    found = []
    for at, value, limit in [(lead_at, lead_ms, LEAD_MAX_MS),
                             *((at, value, GAP_MAX_MS) for at, value in gaps)]:
        if not _whole_ms(value, limit):
            found.append(Violation(SCHEMA_INVALID, at, f"must be integer milliseconds from 0 to "
                                                       f"{limit} (the longest silent hold, TIME-4)"))
    if not found and lead_ms + sum(value for _, value in gaps) > TRACK_MAX_MS:
        found.append(Violation(SCHEMA_INVALID, total_at,
                               f"the lead and gaps alone are over a track's {TRACK_MAX_MS} ms"))
    return found


def _voice_rules(voice: Mapping[str, Any], signed: str | None) -> list[Violation]:
    lines = voice["lines"]
    if len(lines) > LINES_MAX:  # before any per-line work: each line costs a call or a read
        return [Violation(SCHEMA_INVALID, "/voice/lines",
                          f"a board voice has at most {LINES_MAX} lines, not {len(lines)}")]
    found = _duplicates(((pointer("voice", "lines", i, "line_id"), line["line_id"])
                         for i, line in enumerate(lines)), "line")
    if len(voice["gaps_ms"]) != len(lines) - 1:
        found.append(Violation(SCHEMA_INVALID, "/voice/gaps_ms",
                               f"{len(lines)} lines need {len(lines) - 1} gaps (one before each "
                               "later line)"))
    found += time_violations(voice["lead_ms"], ((pointer("voice", "gaps_ms", i), gap)
                                                for i, gap in enumerate(voice["gaps_ms"])),
                             lead_at="/voice/lead_ms", total_at="/voice")
    for i, line in enumerate(lines):
        at = pointer("voice", "lines", i)
        voice_id = line["voice_id"]
        if not isinstance(voice_id, str) or not is_stock_voice(voice["model"], voice_id):
            found.append(Violation(NOT_STOCK, at + "/voice_id",
                                   f"{voice_id!r} is not a recorded stock voice of "
                                   f"{voice['model']!r} (VOICE-1, P-22)"))
            if not isinstance(voice_id, str):
                continue
        expected = line_signature(voice["engine"], voice_id, line["text"])
        if line["signature"] != expected:
            found.append(Violation(SCHEMA_INVALID, at + "/signature",
                                   "must be the take signature of the engine, voice_id, NFC text "
                                   "and speed (VOICE-3)"))
    if not found and signed is not None:
        expected = input_signature([line["signature"] for line in lines], voice["lead_ms"],
                                   list(voice["gaps_ms"]))
        if signed != expected:
            found.append(Violation(SCHEMA_INVALID, "/input_signature",
                                   "must be the signature of the voice block's takes, lead and "
                                   "gaps (VOICE-3)"))
    return found


__all__ = ["time_violations", "validate_job", "voice_input_violations"]
