"""The canonical storyboard model of contract v1 (story 404): productions, stories,
boards, the story timing summary, the method matrix and the legacy import map.

- :mod:`.model`: read-only typed models (``from_document``, :func:`to_document`).
- :mod:`.validate`: one validator per type, in context ``read``, ``write`` or
  ``queue_run``, returning violations with the contract's rule codes.
- :mod:`.derive`: derived values from the documents and measured takes.
- :mod:`.facts`: what the asset library must supply (takes, states, capabilities).
- :mod:`.legacy_import`: a legacy manifest and its speech.json to one story.
- :mod:`.ids`: prefixed ULIDs.

Nothing here reads or writes files except :mod:`.legacy_import`'s explicit loaders,
and nothing calls a service. A malformed document never raises anything but
:class:`~haynes_studio.errors.ContractError` from :func:`load_story`,
:func:`timing_summary` or :func:`with_derived`, and validators only return violations.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from haynes_studio.canonical.derive import boards_derived, story_derived, story_timing
from haynes_studio.canonical.facts import NO_FACTS, Facts, PhotoVersionFacts, VoiceVersionFacts
from haynes_studio.canonical.model import (
    Board,
    BuildBlocker,
    FormatLength,
    LegacyImport,
    MethodCapabilities,
    Production,
    Story,
    StoryTiming,
    to_document,
)
from haynes_studio.canonical.validate import (
    CONTEXTS,
    QUEUE_RUN,
    SCHEMA_INVALID,
    validate_board,
    validate_legacy_import,
    validate_method_capabilities,
    validate_production,
    validate_story,
    validate_story_timing,
)
from haynes_studio.errors import ContractError, Violation, blocking

__all__ = [
    "CONTEXTS", "Board", "BuildBlocker", "Facts", "FormatLength", "LegacyImport",
    "MethodCapabilities", "NO_FACTS", "PhotoVersionFacts", "Production", "Story",
    "StoryTiming", "VoiceVersionFacts", "boards_derived", "load_story", "story_derived",
    "story_timing", "timing_summary", "to_document", "validate_board", "validate_legacy_import",
    "validate_method_capabilities", "validate_production", "validate_story",
    "validate_story_timing", "with_derived",
]


def _draft(document: Any) -> Any:
    """The story without its ``derived`` blocks (the server recomputes them); anything
    that is not an object is returned as is, for the validator to refuse."""
    if not isinstance(document, Mapping):
        return document
    out = {key: value for key, value in document.items() if key != "derived"}
    if isinstance(out.get("boards"), list):
        out["boards"] = [{k: v for k, v in board.items() if k != "derived"}
                         if isinstance(board, dict) else board for board in out["boards"]]
    return out


def load_story(document: Any, *, facts: Facts | None = None, context: str = "read",
               source: str = "<document>") -> Story:
    """A validated story model; :class:`ContractError` lists every violation."""
    problems = blocking(validate_story(document, context=context, facts=facts))
    if problems:
        raise ContractError(source, problems)
    return Story.from_document(document)


def _with_boards(document: Any, *, facts: Facts, source: str) -> Story:
    """A validated story whose boards are embedded (the exchange and snapshot form)."""
    story = load_story(document, facts=facts, source=source)
    if story.boards is None:
        raise ContractError(source, [Violation(
            SCHEMA_INVALID, "/boards",
            "the story's boards must be embedded to derive its timing (exchange form)")])
    return story


def timing_summary(document: Any, *, facts: Facts | None = None,
                   format_length: FormatLength | None = None,
                   source: str = "<document>") -> StoryTiming:
    """``studio.story-timing/v1`` for a story with embedded boards. Its build blockers
    are the story's ``queue_run`` violations, so Build and the summary agree. Raises
    :class:`ContractError` if the story breaks a rule or has no embedded boards."""
    facts = facts or NO_FACTS
    document = _draft(document)
    story = _with_boards(document, facts=facts, source=source)
    by_path = {f"/boards/{i}": board.id for i, board in enumerate(story.boards or ())}
    blockers = []
    for violation in blocking(validate_story(document, context=QUEUE_RUN, facts=facts)):
        board_id = next((bid for path, bid in by_path.items()
                         if violation.path == path or violation.path.startswith(path + "/")), None)
        blockers.append(BuildBlocker(code=violation.rule, board_id=board_id,
                                     path=None if board_id else violation.path))
    return story_timing(story, story.ordered_boards(), facts, blockers=blockers,
                        format_length=format_length)


def with_derived(document: Any, *, facts: Facts | None = None,
                 format_length: FormatLength | None = None,
                 source: str = "<document>") -> dict[str, Any]:
    """A copy of a story document (boards embedded) with every ``derived`` block
    computed from the document and ``facts``, as a read returns it; the story's
    ``derived.warnings`` carry each board's ``method.unavailable`` and the D45 length
    warning. Raises :class:`ContractError` if the story breaks a rule or has no
    embedded boards."""
    facts = facts or NO_FACTS
    story = _with_boards(_draft(document), facts=facts, source=source)
    ordered = story.ordered_boards()
    derived = dict(zip((b.id for b in ordered), boards_derived(ordered, facts)))
    out = to_document(story)
    for board in out["boards"]:
        board["derived"] = to_document(derived[board["id"]])
    out["derived"] = to_document(story_derived(story, ordered, facts,
                                               format_length=format_length))
    return out
