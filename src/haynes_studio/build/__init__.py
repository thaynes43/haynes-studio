"""Build a story from its boards (story 406, contract sections 4, 5, 7 and 8).

- :mod:`.pipeline`: :func:`~.pipeline.build_story`, one run from the draft to a
  verified delivery, through the cache, each board by its method's adapter.
- :mod:`.prebuild`: the pre-build check (story 379's, with the adapters' own checks
  and the motion resolver) and the run snapshot.
- :mod:`.run`: run states and transitions, and the run record on the store.
- :mod:`.validate`: ``studio.run/v1`` and ``studio.run-snapshot/v1``.
- :mod:`.sources`: the clip sources of each phase, and :func:`live_clip_sources`, the
  hook the command line asks for live clip sources (not wired yet).
- :mod:`.transcript`: the transcript check behind a :class:`~.transcript.Transcriber`.
- :mod:`.provenance`: engines, licences and public credits from the licence register.
- :mod:`.voice`: a story's board voices before a build (``studio voice``).
- :mod:`.workers`: segments rendered in separate processes (``--workers N``).

Importing this package starts no process and reads no environment. Reference:
``docs/reference/studio-build.md``.
"""

from __future__ import annotations

from haynes_studio.build.errors import BuildError, Failure, failure_of
from haynes_studio.build.pipeline import (
    ALL,
    OFFLINE,
    PHASES,
    SERVICE,
    BuildInputs,
    BuildResult,
    build_story,
    build_toolchain,
    media_format,
)
from haynes_studio.build.run import RunRecords, local_run_ids
from haynes_studio.build.sources import (
    ClipSources,
    OfflineClipSource,
    OfflineS2VSource,
    live_clip_sources,
    offline_sources,
)
from haynes_studio.build.transcript import Transcriber, WhisperTranscriber
from haynes_studio.build.validate import validate_run, validate_run_snapshot
from haynes_studio.build.voice import make_story_voices

__all__ = [
    "ALL", "BuildError", "BuildInputs", "BuildResult", "ClipSources", "Failure", "OFFLINE",
    "OfflineClipSource", "OfflineS2VSource", "PHASES", "RunRecords", "SERVICE", "Transcriber",
    "WhisperTranscriber", "build_story", "build_toolchain", "failure_of", "live_clip_sources",
    "local_run_ids", "make_story_voices", "media_format", "offline_sources", "validate_run",
    "validate_run_snapshot",
]
