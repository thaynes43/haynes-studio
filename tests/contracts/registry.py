"""Schema type -> validator, for the contract-example harness.

Empty until a story lands the schema and validator for a type (378: the legacy
manifest; 404: production, story, board, timing and methods; later stories for
assets, runs, deliveries and approvals). That story adds one entry here in the same
PR, and the type's examples stop being PENDING. How: docs/process/testing.md,
"Register a validator".

A validator is called as ``validator(document, context=...)`` with context
``read`` (valid examples), ``write`` or ``queue_run`` (invalid cases), and returns
an iterable of violations: objects with ``rule``, ``status`` and ``path``
attributes, or ``(rule, status, path)`` tuples. Status is ``invalid``,
``unavailable``, ``forbidden`` or ``warning``; an empty result means valid.
Keys are names from ``harness.ALL_TYPES``.
"""

from __future__ import annotations

from haynes_studio.canonical import (
    validate_board,
    validate_legacy_import,
    validate_method_capabilities,
    validate_production,
    validate_story,
    validate_story_timing,
)
from haynes_studio.delivery import validate_delivery
from haynes_studio.legacy import validate_manifest
from haynes_studio.library import validate_asset, validate_asset_version
from haynes_studio.voice import validate_job
from tests.canonical.fixtures import board_context, example_context
from tests.contracts.harness import Validator


def _board(document, *, context):
    """Story 404: a board is checked against its story's cast and layouts, with the
    voice, photo and capability facts of the public fixtures (tests/canonical/fixtures.py)."""
    return validate_board(document, context=context, **board_context(document))


def _story(document, *, context):
    return validate_story(document, context=context, facts=example_context().facts)


VALIDATORS: dict[str, Validator] = {
    "legacy.manifest": validate_manifest,  # story 378
    # story 404
    "production": validate_production,
    "story": _story,
    "board": _board,
    "story-timing": validate_story_timing,
    "method-capabilities": validate_method_capabilities,
    "legacy-import": validate_legacy_import,
    # story 382
    "asset": validate_asset,
    "asset-version": validate_asset_version,
    # story 405
    "job": validate_job,
    # story 381
    "delivery": validate_delivery,
}
