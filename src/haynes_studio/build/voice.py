"""Make a story's board voices before a build (``studio voice``; story 406).

Voices are pre-build assets (contract section 10): a build never makes one. For each
spoken board whose voice is not current, this runs story 405's path exactly as the
API's worker will: ``request_voice`` (plan, then a job only if something must be made),
``start``, ``run_voice_job`` with the speech client it is given (story 425's Kokoro
client with its real runner at the command line, a fake in tests), and points the
board at the result when it is current. Takes go to the production's folder of the
store, create-only, and every reused take is read back and re-hashed.

It returns the new draft and library; the command line writes them as new files.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from haynes_studio.canonical.ids import Minter
from haynes_studio.library import Library
from haynes_studio.store import PRESENT, Store
from haynes_studio.voice import (
    Engine,
    request_voice,
    run_voice_job,
    start,
    with_current_voice,
)

WAV = "audio/wav"


@dataclass(frozen=True)
class BoardVoiceOutcome:
    """What happened to one spoken board: ``current`` (nothing to do), ``existing``
    (pointed back at a version it had), ``made`` (a job ran), or ``failed`` with the
    job's code."""

    board_id: str
    action: str
    version_id: str | None
    synthesized: tuple[str, ...] = ()
    code: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class VoiceResult:
    story: dict[str, Any]
    library: Library
    outcomes: tuple[BoardVoiceOutcome, ...] = field(default=())

    @property
    def ok(self) -> bool:
        return all(outcome.code is None for outcome in self.outcomes)


def make_story_voices(story: Mapping[str, Any], library: Library, *, store: Store,
                      speech: Any, by: Mapping[str, Any], now: str,
                      minter: Minter | None = None, licences: Any = None,
                      engine: Engine = Engine()) -> VoiceResult:
    """Make every spoken board's current voice (see the module docstring). A job that
    fails is reported with its code and the next board is still tried; no version is
    made for it."""
    from haynes_studio.canonical.model import Principal
    principal = Principal.from_document(dict(by))
    draft = copy.deepcopy(dict(story))
    production = draft["production_id"]
    minter = minter or Minter()

    def publish(data: bytes, media_type: str) -> tuple[str, str]:
        blob = store.publish(data, scope=production, media_type=media_type)
        return blob.sha256, blob.locator

    def fetch(locator: str, sha256: str) -> bytes | None:
        if store.verify(locator, sha256) != PRESENT:
            return None
        with store.open(locator) as handle:
            return handle.read()

    outcomes = []
    for board in [b for b in draft.get("boards") or [] if b.get("lines")]:
        request = request_voice(draft, board["id"], library, by=principal, now=now, minter=minter,
                                engine=engine)
        if request.job is None:
            target = getattr(request, "make_current", None)
            if target:
                draft = with_current_voice(draft, board["id"], target)
                outcomes.append(BoardVoiceOutcome(board["id"], "existing", target))
            else:
                outcomes.append(BoardVoiceOutcome(board["id"], "current",
                                                  board["voice"]["current_version_id"]))
            continue
        running = start(request.job, now=now)
        run = run_voice_job(running, library, draft=lambda: draft, speech=speech, publish=publish,
                            fetch=fetch, by=principal, now=now, minter=minter, engine=engine,
                            licences=licences)
        library = run.library
        if run.job.status != "succeeded" or run.version is None:
            error = run.job.error
            outcomes.append(BoardVoiceOutcome(board["id"], "failed", None,
                                              code=getattr(error, "code", None) or "voice.failed",
                                              message=getattr(error, "message", None)))
            continue
        if run.make_current:
            draft = with_current_voice(draft, board["id"], run.version.id)
        outcomes.append(BoardVoiceOutcome(board["id"], "made", run.version.id,
                                          synthesized=tuple(run.synthesized)))
    return VoiceResult(draft, library, tuple(outcomes))


__all__ = ["BoardVoiceOutcome", "VoiceResult", "make_story_voices"]
