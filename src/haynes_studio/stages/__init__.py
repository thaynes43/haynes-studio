"""Stages of a build (story 379): the create-only stage commit and the fail-fast
checks a build runs before its first renderer call.

- :mod:`.commit`: :func:`commit_stage` (blobs first, then one completion record) and
  :func:`completed_stage` (readers trust only completed stages).
- :mod:`.preflight`: :func:`preflight` and :func:`ensure_buildable`.

Reference: ``docs/reference/store-and-stages.md``.
"""

from __future__ import annotations

from haynes_studio.stages.commit import StageOutput, commit_stage, completed_stage
from haynes_studio.stages.preflight import (
    ASSET_UNRESOLVED,
    DEFINITION_ONLY,
    BlobRef,
    PreflightError,
    PreflightReport,
    Problem,
    ResolvedVersion,
    ensure_buildable,
    preflight,
    references,
)

__all__ = [
    "ASSET_UNRESOLVED", "BlobRef", "DEFINITION_ONLY", "PreflightError", "PreflightReport",
    "Problem", "ResolvedVersion", "StageOutput", "commit_stage", "completed_stage",
    "ensure_buildable", "preflight", "references",
]
