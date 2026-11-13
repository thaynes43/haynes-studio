"""The pre-build board voice of contract v1 (story 405, section 10): measured takes, the
assembled track, signatures and reuse, and voice jobs (``studio.job/v1``).

- :mod:`.model`: the engine, a board voice input, and the read-only job model.
- :mod:`.validate`: ``validate_job`` with story 404's contexts.
- :mod:`.jobs`: the job state machine (VOICE-4) and the ``generating`` facts.
- :mod:`.plan`: what a board's voice needs: ``current``, ``existing``, ``assemble``
  (no speech call) or ``synthesize`` (only the changed takes), and the request step.
- :mod:`.track`: 16-bit PCM takes and the track, at the takes' own rate (``wave``).
- :mod:`.build`: make a ``board_voice`` version through the library, run a voice job,
  and the facts story 404 times boards with (VOICE-5, VOICE-6).

Speech goes through an injected client (the Kokoro client of story 425 and its
runner); bytes through injected ``publish`` and ``fetch`` functions. Nothing here
starts a process, opens a socket or knows the store.
"""

from __future__ import annotations

from haynes_studio.voice.build import (
    JobRun,
    Made,
    is_current,
    make_voice,
    run_voice_job,
    voice_facts,
    with_current_voice,
)
from haynes_studio.voice.jobs import cancel, fail, generating, new_job, start, succeed
from haynes_studio.voice.model import Engine, Job, JobError, VoiceInput, VoiceLine
from haynes_studio.voice.plan import (
    ASSEMBLE,
    CURRENT,
    EXISTING,
    SYNTHESIZE,
    VoicePlan,
    VoiceRequest,
    board_voice_versions,
    plan_board_voice,
    request_voice,
)
from haynes_studio.voice.validate import validate_job

__all__ = [
    "ASSEMBLE", "CURRENT", "EXISTING", "SYNTHESIZE", "Engine", "Job", "JobError", "JobRun", "Made",
    "VoiceInput", "VoiceLine", "VoicePlan", "VoiceRequest", "board_voice_versions", "cancel",
    "fail", "generating", "is_current", "make_voice", "new_job", "plan_board_voice",
    "request_voice", "run_voice_job", "start", "succeed", "validate_job", "voice_facts",
    "with_current_voice",
]
