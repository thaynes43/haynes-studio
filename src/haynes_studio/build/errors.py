"""Build codes (story 406) and how any package's error becomes a run's failure.

A run that stops records one failure: the code, a short message, the board it stopped
on (when there is one) and the stage. :func:`failure_of` reads that from the error
any package raised: every package of the build carries a ``code`` (the store, the
cache, the adapters, the mix, the delivery, the speech and transcript clients) or a
list of violations (a ``ContractError``, the pre-build check's ``PreflightError``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from haynes_studio.errors import ContractError

# Proposals (story 406), not yet in the contract's rule index.
CLIP_SOURCES_UNWIRED = "build.clip_sources_unwired"  # the live clip-source hook is not filled
OFFLINE_MISSING = "build.offline_missing"  # the offline phase needs an artifact no run made
CHECK_FAILED = "build.check_failed"  # a check on the master did not pass; nothing delivered
DELIVERY_UNVERIFIED = "build.delivery_unverified"  # the delivery did not read back as made
RUN_TRANSITION = "run.transition"  # a status change the run's state machine refuses
RUN_UNKNOWN = "run.unknown"  # no such run in the production
VOICE_TRACK_MISSING = "build.voice_track_missing"  # a current board voice with no track
INTERNAL = "build.internal"  # an exception that carries no code (a bug, or the system)

CODES = (CLIP_SOURCES_UNWIRED, OFFLINE_MISSING, CHECK_FAILED, DELIVERY_UNVERIFIED,
         RUN_TRANSITION, RUN_UNKNOWN, VOICE_TRACK_MISSING, INTERNAL)


class BuildError(Exception):
    """A build step refused with a code; ``board_id`` and ``stage`` say where."""

    def __init__(self, code: str, message: str, *, board_id: str | None = None,
                 stage: str | None = None, problems: tuple[dict[str, Any], ...] = ()):
        self.code = code
        self.message = message
        self.board_id = board_id
        self.stage = stage
        self.problems = problems
        where = "".join(f" [{part}]" for part in (board_id, stage) if part)
        super().__init__(f"{code}{where}: {message}")


@dataclass(frozen=True)
class Failure:
    """Why a run stopped: what ``error`` of a failed run records."""

    code: str
    message: str
    board_id: str | None = None
    board_number: int | None = None
    stage: str | None = None
    problems: tuple[dict[str, Any], ...] = field(default=())

    def to_document(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message,
                               "board_id": self.board_id, "board_number": self.board_number,
                               "stage": self.stage}
        if self.problems:
            out["problems"] = [dict(problem) for problem in self.problems]
        return out


_MESSAGE_MAX = 600


def _short(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= _MESSAGE_MAX else text[: _MESSAGE_MAX - 3] + "..."


def failure_of(error: BaseException, *, board_id: str | None = None,
               stage: str | None = None) -> Failure:
    """The failure an error records. A ``BuildError`` keeps its own board and stage;
    another error takes the board and stage the build was at (``board_id``,
    ``stage``). A ``ContractError`` records its first violation's rule and every
    violation as a problem; a pre-build check's problems keep their board."""
    if isinstance(error, BuildError):
        return Failure(error.code, _short(error.message), error.board_id or board_id, None,
                       error.stage or stage, error.problems)
    report = getattr(error, "report", None)
    if report is not None and getattr(report, "blocking", None):  # the pre-build check
        problems = report.blocking
        first = problems[0]
        return Failure(first.rule, _short(str(first)), first.board_id or board_id,
                       first.board_number, stage or "prebuild",
                       tuple({"rule": p.rule, "status": p.status, "board_id": p.board_id,
                              "field": p.field or "", "message": _short(p.message)}
                             for p in problems))
    if isinstance(error, ContractError) and error.violations:
        first = error.violations[0]
        return Failure(first.rule, _short(first.message), board_id, None, stage,
                       tuple({"rule": v.rule, "status": v.status, "path": v.path,
                              "message": _short(v.message)} for v in error.violations))
    code = getattr(error, "code", None)
    if isinstance(code, str) and code:
        message = getattr(error, "message", None) or str(error)
        where = getattr(error, "where", None)  # a plan or cache error names its board
        if isinstance(where, str) and where.startswith("brd_"):
            board_id = where.split("/", 1)[0]
        return Failure(code, _short(message), board_id, None, stage)
    return Failure(INTERNAL, _short(f"{type(error).__name__}: {error}"), board_id, None, stage)


__all__ = ["BuildError", "CODES", "CHECK_FAILED", "CLIP_SOURCES_UNWIRED",
           "DELIVERY_UNVERIFIED", "Failure", "INTERNAL", "OFFLINE_MISSING", "RUN_TRANSITION",
           "RUN_UNKNOWN", "VOICE_TRACK_MISSING", "failure_of"]
