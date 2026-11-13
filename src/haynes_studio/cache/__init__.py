"""Cache keys, the picture segment cache and the splice (story 380, contract section 4).

- :mod:`.keys`: canonical key documents and one pure key function per artifact of the
  section 4 table, with :data:`~.keys.INVENTORY`.
- :mod:`.plan`: every artifact's key for one story, in dependency order
  (:func:`~.plan.plan_story`), and :func:`~.plan.diff` of two plans.
- :mod:`.artifacts`: :class:`~.artifacts.ArtifactCache`, one completed stage per key on
  the store of story 379; it never deletes, evicts or overwrites.
- :mod:`.build`: :class:`~.build.PictureBuilder`, segments and the film picture through
  the cache.

Rendering, encoding, the board clock and the splice are in :mod:`haynes_studio.render`.
Reference: ``docs/reference/cache-and-splice.md``.
"""

from __future__ import annotations

from haynes_studio.cache.artifacts import (
    ArtifactCache,
    CachedArtifact,
    RunSearch,
    StageFinder,
    stage_name,
)
from haynes_studio.cache.errors import CacheError
from haynes_studio.cache.keys import INVENTORY, KINDS, SCHEME, CacheKey, make_key
from haynes_studio.cache.plan import (
    BoardVoice,
    KeyDiff,
    MediaFormat,
    StoryPlan,
    TakeFacts,
    Toolchain,
    diff,
    plan_story,
)

__all__ = [
    "ArtifactCache", "BoardVoice", "CacheError", "CacheKey", "CachedArtifact", "INVENTORY",
    "KINDS", "KeyDiff", "MediaFormat", "RunSearch", "SCHEME", "StageFinder", "StoryPlan",
    "TakeFacts", "Toolchain", "diff", "make_key", "plan_story", "stage_name",
]
