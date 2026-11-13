"""Read-only models of the pre-build board voice (contract section 10) and of
``studio.job/v1`` (section 2, VOICE-4).

- :class:`Engine`: the stock TTS engine a take is signed and made with. Kokoro-82M
  v1.0 today; no model digest is recorded yet, so the model name stands in, as VOICE-3
  allows for legacy takes and story 382's library does.
- :class:`VoiceInput` and :class:`VoiceLine`: what one board voice version is made
  from (each line's speaker, NFC text, stock voice and take signature, plus the lead
  and the gaps). A voice job records it, so a worker needs only the job.
- :class:`Job`: one asynchronous job. Its contract fields are ``id``, ``kind``,
  ``target_id``, ``input_signature``, ``status``, ``result_version_id``,
  ``result_is_current`` and ``error``; the rest are proposals of story 405.

Signatures are the library's (:func:`haynes_studio.library.model.take_signature` and
:func:`~haynes_studio.library.model.input_signature`); nothing here re-derives them.
Nothing here reads files or calls services.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from haynes_studio.canonical.jsonvalues import normalize
from haynes_studio.canonical.model import Principal, to_document
from haynes_studio.library.model import KOKORO, input_signature, take_signature
from haynes_studio.timebase import HOLD_MAX_MS

JOB_SCHEMA = "studio.job/v1"
JOB_FILE = "studio.job.v1.schema.json"

VOICE, PHOTO, ASSET_CANDIDATE = "voice", "photo", "asset_candidate"
JOB_KINDS = (VOICE, PHOTO, ASSET_CANDIDATE)
QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED = (
    "queued", "running", "succeeded", "failed", "cancelled")
STATUSES = (QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED)
IN_FLIGHT = frozenset({QUEUED, RUNNING})
TERMINAL = frozenset({SUCCEEDED, FAILED, CANCELLED})

# The Kokoro client of story 425 sends only a voice and a text (as poc/studio.py did),
# so the server's default speed applies. Takes are signed with 1.0, as the contract's
# board voice example and story 382 sign legacy takes. Always this float: a speed read
# back from normalized JSON would be the integer 1 and sign differently.
SPEED = 1.0

# Proposal (story 405): the version of the track assembler below (takes placed at
# their TIME-2 offsets, silence between them, at the takes' own sample rate). The
# contract's cache table lists an assembler version among the track's key inputs.
ASSEMBLER = "studio.voice.track/1"

# Proposal (story 405): time bounds of a board voice, checked before any speech call and
# before the track buffer is sized. A lead, a gap and one take are each at most the
# contract's longest silent hold (TIME-4, 120000 ms); a track is at most 600000 ms.
LEAD_MAX_MS = GAP_MAX_MS = TAKE_MAX_MS = HOLD_MAX_MS
TRACK_MAX_MS = 600_000
LINES_MAX = 256  # lines in one board voice (proposal, story 405): each costs a call or a read

# Proposal: the service text a generated version names as its engine, as the legacy
# import names "ai/deploy/kokoro (Wyoming)" from speech.json.
KOKORO_SERVICE = "ai/deploy/kokoro (Wyoming)"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class Engine:
    """The TTS engine. ``digest`` is the model weights' ``sha256:<hex>`` once it is
    recorded; until then the takes are signed with the model name (VOICE-3)."""

    model: str = KOKORO
    digest: str | None = None
    service: str = KOKORO_SERVICE

    def __post_init__(self) -> None:
        if self.digest is not None and not _DIGEST.fullmatch(self.digest):
            raise ValueError("an engine digest is sha256:<64 lower-case hex digits>")

    @property
    def signing_name(self) -> str:
        """The ``engine`` a take signature names: the digest, else the model name."""
        return self.digest or self.model


@dataclass(frozen=True, slots=True)
class VoiceLine:
    """One line of a board voice input: who says what, in which stock voice."""

    line_id: str
    speaker: str
    text: str
    voice_version_id: str
    voice_id: str
    signature: str


@dataclass(frozen=True, slots=True)
class VoiceInput:
    """What one board voice version is made from (VOICE-2, VOICE-3). ``engine`` is the
    signing name; ``name`` names the board's voice asset if this makes the first one."""

    production_id: str
    story_id: str
    name: str
    engine: str
    model: str
    lead_ms: int
    gaps_ms: tuple[int, ...]
    lines: tuple[VoiceLine, ...]

    @property
    def input_signature(self) -> str:
        """VOICE-3 version signature: the take signatures plus lead and gaps."""
        return input_signature([line.signature for line in self.lines], self.lead_ms,
                               list(self.gaps_ms))

    @classmethod
    def from_document(cls, doc: Mapping[str, Any] | None) -> VoiceInput | None:
        if doc is None:
            return None
        doc = normalize(doc)
        return cls(production_id=doc["production_id"], story_id=doc["story_id"],
                   name=doc["name"], engine=doc["engine"], model=doc["model"],
                   lead_ms=doc["lead_ms"], gaps_ms=tuple(doc["gaps_ms"]),
                   lines=tuple(VoiceLine(**line) for line in doc["lines"]))


def line_signature(engine: str, voice_id: str, text: str) -> str:
    """A take signature (VOICE-3) at the fixed :data:`SPEED`; the library signs the
    NFC form of the text."""
    return take_signature(engine, voice_id, text, SPEED)


@dataclass(frozen=True, slots=True)
class JobError:
    """Why a job failed: a rule or adapter code and a short message (proposal)."""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class Job:
    """One ``studio.job/v1`` record. Built by :mod:`.jobs`; every change returns a new
    value, and a terminal job never changes again."""

    id: str
    kind: str
    target_id: str
    input_signature: str
    status: str
    result_version_id: str | None
    result_is_current: bool | None
    error: JobError | None
    created_by: Principal
    created_at: str
    updated_at: str
    voice: VoiceInput | None = None

    @property
    def in_flight(self) -> bool:
        return self.status in IN_FLIGHT

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL

    @classmethod
    def from_document(cls, doc: Mapping[str, Any]) -> Job:
        """The model of a document that has passed :func:`~.validate.validate_job`."""
        doc = normalize(doc)
        error = doc["error"]
        return cls(id=doc["id"], kind=doc["kind"], target_id=doc["target_id"],
                   input_signature=doc["input_signature"], status=doc["status"],
                   result_version_id=doc["result_version_id"],
                   result_is_current=doc["result_is_current"],
                   error=None if error is None else JobError(**error),
                   created_by=Principal.from_document(doc["created_by"]),
                   created_at=doc["created_at"], updated_at=doc["updated_at"],
                   voice=VoiceInput.from_document(doc.get("voice")))

    def to_document(self) -> dict[str, Any]:
        return {"schema": JOB_SCHEMA, **to_document(self)}


__all__ = [
    "ASSEMBLER", "ASSET_CANDIDATE", "CANCELLED", "FAILED", "GAP_MAX_MS", "IN_FLIGHT", "JOB_FILE",
    "JOB_KINDS", "JOB_SCHEMA", "KOKORO_SERVICE", "LEAD_MAX_MS", "LINES_MAX", "PHOTO", "QUEUED", "RUNNING",
    "SPEED", "STATUSES", "SUCCEEDED", "TAKE_MAX_MS", "TERMINAL", "TRACK_MAX_MS", "VOICE", "Engine",
    "Job", "JobError", "VoiceInput", "VoiceLine", "line_signature",
]
