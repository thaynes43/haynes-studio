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

from haynes_studio.legacy import validate_manifest
from tests.contracts.harness import Validator

VALIDATORS: dict[str, Validator] = {
    "legacy.manifest": validate_manifest,  # story 378
}
