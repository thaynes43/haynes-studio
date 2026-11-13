"""The job state machine (contract section 2 and VOICE-4), as pure functions on
:class:`~haynes_studio.voice.model.Job` values.

::

    queued ──start──> running ──succeed──> succeeded (result kept; current or stale)
      │                  ├────fail──────> failed
      └──cancel──┐       └────cancel────> cancelled
                 └──────────────────────> cancelled

A terminal job (``succeeded``, ``failed``, ``cancelled``) never changes again, and
nothing else moves (``job.transition``, status ``conflict``; proposal). A job that
finishes is ``succeeded`` whether or not its result is still the board's current
signature: ``result_is_current`` says which, and the result version is kept either
way (VOICE-4). Every change sets ``updated_at``; nothing is deleted.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from types import MappingProxyType

from haynes_studio.canonical.facts import Facts
from haynes_studio.canonical.ids import Minter, is_id
from haynes_studio.canonical.model import Principal
from haynes_studio.errors import ContractError, Violation, blocking
from haynes_studio.voice.model import (
    CANCELLED,
    FAILED,
    PHOTO,
    QUEUED,
    RUNNING,
    SUCCEEDED,
    VOICE,
    Job,
    JobError,
    VoiceInput,
)
from haynes_studio.voice.validate import validate_job

TRANSITION = "job.transition"  # proposal: a move the state machine does not allow
CONFLICT = "conflict"
ERROR_MESSAGE_LIMIT = 500

ALLOWED: Mapping[str, frozenset[str]] = MappingProxyType({
    QUEUED: frozenset({RUNNING, CANCELLED}),
    RUNNING: frozenset({SUCCEEDED, FAILED, CANCELLED}),
    SUCCEEDED: frozenset(),
    FAILED: frozenset(),
    CANCELLED: frozenset(),
})


def _checked(job: Job) -> Job:
    problems = blocking(validate_job(job.to_document(), context="write"))
    if problems:
        raise ContractError(job.id, problems)
    return job


def new_job(kind: str, target_id: str, input_signature: str, *, by: Principal, now: str,
            minter: Minter | None = None, voice: VoiceInput | None = None) -> Job:
    """A ``queued`` job. A voice job carries the input it must make (``voice``), and
    its ``input_signature`` is that input's signature."""
    job = Job(id=(minter or Minter()).mint("job"), kind=kind, target_id=target_id,
              input_signature=input_signature, status=QUEUED, result_version_id=None,
              result_is_current=None, error=None, created_by=by, created_at=now,
              updated_at=now, voice=voice)
    return _checked(job)


def _move(job: Job, to: str, now: str, **changes) -> Job:
    if to not in ALLOWED[job.status]:
        why = ("a terminal job never changes" if not ALLOWED[job.status]
               else f"{job.status} moves only to {', '.join(sorted(ALLOWED[job.status]))}")
        raise ContractError(job.id, [Violation(TRANSITION, "/status",
                                               f"{job.status} -> {to} is not allowed: {why}",
                                               CONFLICT)])
    return _checked(replace(job, status=to, updated_at=now, **changes))


def start(job: Job, *, now: str) -> Job:
    """``queued`` to ``running``: a worker has claimed it."""
    return _move(job, RUNNING, now)


def succeed(job: Job, result_version_id: str, *, is_current: bool, now: str) -> Job:
    """``running`` to ``succeeded``. The result is a kept version either way;
    ``is_current`` says whether the board's signature still matched (VOICE-4)."""
    if not is_id(result_version_id, "asv"):
        raise ContractError(job.id, [Violation("id.malformed", "/result_version_id",
                                               "must be an asv_ ID")])
    return _move(job, SUCCEEDED, now, result_version_id=result_version_id,
                 result_is_current=bool(is_current))


def fail(job: Job, code: str, message: str, *, now: str) -> Job:
    """``running`` to ``failed``, with the code and a short message."""
    printable = "".join(ch if ch.isprintable() else " " for ch in str(message))
    text = " ".join(printable.split())[:ERROR_MESSAGE_LIMIT] or code
    return _move(job, FAILED, now, error=JobError(code=code, message=text))


def cancel(job: Job, *, now: str) -> Job:
    """``queued`` or ``running`` to ``cancelled``. A worker that finishes after this
    cannot succeed the job; a version it already made stays in the library."""
    return _move(job, CANCELLED, now)


def generating(jobs: Iterable[Job]) -> Facts:
    """Story 404's ``generating`` facts: each board with a voice or photo job in flight,
    so its state reads ``generating`` and ``queue_run`` refuses it
    (``asset.generating``)."""
    return Facts.build(generating=[(job.target_id, job.kind) for job in jobs
                                   if job.in_flight and job.kind in (VOICE, PHOTO)])


__all__ = ["ALLOWED", "TRANSITION", "cancel", "fail", "generating", "new_job", "start",
           "succeed"]
