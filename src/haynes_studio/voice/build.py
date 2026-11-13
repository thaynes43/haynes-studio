"""Making a board voice version and finishing its job (VOICE-2 to VOICE-6).

:func:`make_voice` turns a :class:`~haynes_studio.voice.model.VoiceInput` into one
``board_voice`` asset version through the library: reused takes are read back by hash
and re-measured, the others go to the speech client (the Kokoro client of story 425
behind its injected runner), every take is published, and the assembled track is
published and recorded on the version. Durations are TIME-1 from sample counts and
offsets TIME-2, through :mod:`haynes_studio.timebase`. Bytes leave only through the
injected ``publish`` and come back only through the injected ``fetch``; nothing here
knows the store.

:func:`run_voice_job` is the worker's whole step: start the job, make the version,
then succeed it with ``result_is_current`` from the board as drafted when it finishes
(VOICE-4). A result is always kept as a version; it becomes the board's current voice
only if the board's signature still matches, and otherwise stays, stale. Nothing is
overwritten or deleted. A failure fails the job and creates no version (blobs already
published stay; they are harmless orphans, section 8).
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from haynes_studio.adapters.errors import AdapterError
from haynes_studio.adapters.kokoro import SpeechRequest, SpeechTake
from haynes_studio.canonical.facts import Facts
from haynes_studio.canonical.ids import Minter
from haynes_studio.canonical.model import Principal
from haynes_studio.errors import ContractError, Violation
from haynes_studio.library import Library, import_version
from haynes_studio.library.library import VersionRequest
from haynes_studio.library.model import (
    BOARD,
    AssetVersion,
    BoardVoice,
    Content,
    Licence,
    Scope,
    Take,
    locator_for,
)
from haynes_studio.library.resolve import BYTES_MISSING
from haynes_studio.library.validate import LOCATOR_INVALID
from haynes_studio.library.winter_menu import LICENCE_NOTES
from haynes_studio.timebase import line_spans, take_duration_ms
from haynes_studio.voice.jobs import fail, generating, start, succeed
from haynes_studio.voice.model import (
    ASSEMBLER,
    RUNNING,
    SPEED,
    VOICE,
    Engine,
    Job,
    VoiceInput,
)
from haynes_studio.voice.plan import (
    board_voice_key,
    board_voice_versions,
    drafted_input,
    reusable_takes,
    same_input,
)
from haynes_studio.voice.track import Pcm, assemble, read_wav

WAV = "audio/wav"
ENGINE_MISMATCH = "voice.engine_mismatch"  # proposal: a job planned for another engine
HASH_MISMATCH = "store.hash_mismatch"  # proposal: publish answered another hash


class Speech(Protocol):
    """What :class:`haynes_studio.adapters.kokoro.KokoroClient` offers."""

    def synthesize(self, request: SpeechRequest) -> SpeechTake: ...


Publish = Callable[[bytes, str], tuple[str, str]]
"""``publish(data, media_type) -> (sha256, locator)``: store bytes create-only in the
production's folder (story 379's adapter, or an in-memory one in tests)."""

Fetch = Callable[[str, str], bytes | None]
"""``fetch(locator, sha256) -> bytes`` or None when the store does not hold them."""


def _error(rule: str, path: str, message: str) -> ContractError:
    return ContractError("<voice>", [Violation(rule, path, message)])


@dataclass(frozen=True)
class Made:
    """The version :func:`make_voice` made or found. ``created`` is False when a version
    of this board already was the input (no call was made); ``synthesized`` lists the
    line IDs that went to the speech client."""

    library: Library
    version: AssetVersion
    created: bool
    synthesized: tuple[str, ...]
    reused: tuple[str, ...]


def _publish(publish: Publish, data: bytes, production_id: str, path: str) -> Content:
    sha256 = hashlib.sha256(data).hexdigest()
    answered, locator = publish(data, WAV)
    if answered != sha256:
        raise _error(HASH_MISMATCH, path, "the store answered another hash than the bytes'")
    if locator != locator_for(sha256, WAV, production_id):
        raise _error(LOCATOR_INVALID, path,
                     "the store must place a take or track at its hash in the production's folder")
    return Content(sha256=sha256, bytes=len(data), media_type=WAV, locator=locator)


def _fetch(fetch: Fetch, take: Take, production_id: str, path: str) -> Pcm:
    data = fetch(locator_for(take.sha256, WAV, production_id), take.sha256)
    if data is None:
        raise _error(BYTES_MISSING, path,
                     f"the store does not hold take {take.sha256[:12]}... to reuse it")
    if hashlib.sha256(data).hexdigest() != take.sha256:
        raise _error(BYTES_MISSING, path,
                     f"the store's bytes for take {take.sha256[:12]}... have another hash")
    return read_wav(data, path)


def make_voice(voice: VoiceInput, board_id: str, library: Library, *, speech: Speech,
               publish: Publish, fetch: Fetch, by: Principal, now: str,
               minter: Minter | None = None, engine: Engine = Engine()) -> Made:
    """One board voice version for ``voice`` (VOICE-2). Takes whose signature a version
    of this board holds are read back (``fetch``), checked by hash and re-measured;
    only the others go to ``speech``, after every reused take was found, so a missing
    take costs no call. If a version of this board already is the input, it is
    returned and nothing is called or published."""
    if (engine.model, engine.signing_name) != (voice.model, voice.engine):
        raise _error(ENGINE_MISMATCH, "/voice/engine",
                     f"the input was signed for {voice.engine!r} ({voice.model}); this worker "
                     f"runs {engine.signing_name!r}")
    versions = board_voice_versions(library, board_id)
    existing = next((v for v in versions if same_input(v, voice)), None)
    if existing is not None:
        return Made(library, existing, False, (), ())
    pool = reusable_takes(versions)
    production = voice.production_id
    pcms: dict[int, Pcm] = {}
    reused: dict[int, Take] = {}
    requests: dict[int, SpeechRequest] = {}
    for i, line in enumerate(voice.lines):  # check everything first: fail before any call
        if line.signature in pool:
            reused[i] = pool[line.signature][0]
            pcms[i] = _fetch(fetch, reused[i], production, f"/voice/lines/{i}")
        else:
            requests[i] = SpeechRequest(voice=line.voice_id, text=line.text)
    hashes = {i: take.sha256 for i, take in reused.items()}
    for i, request in requests.items():
        answer = speech.synthesize(request)
        pcms[i] = read_wav(answer.wav, f"/voice/lines/{i}")
        hashes[i] = _publish(publish, answer.wav, production, f"/voice/lines/{i}").sha256
    ordered = [pcms[i] for i in range(len(voice.lines))]
    durations = [take_duration_ms(pcm.frames, pcm.rate) for pcm in ordered]  # TIME-1
    spans = line_spans(voice.lead_ms, durations, (None, *voice.gaps_ms))  # TIME-2
    track = _publish(publish, assemble(ordered, [s.start_ms for s in spans], spans[-1].end_ms),
                     production, "/voice/track")
    takes = tuple(
        Take(line_id=line.line_id, speaker=line.speaker, text=line.text,
             voice_version_id=line.voice_version_id, engine=voice.engine, voice_id=line.voice_id,
             sha256=hashes[i], sample_rate=pcm.rate, samples=pcm.frames,
             duration_ms=durations[i], duration_source="samples", offset_ms=spans[i].start_ms,
             heard=reused[i].heard if i in reused else None,
             heard_matches=reused[i].heard_matches if i in reused else None,
             signature=line.signature)
        for i, (line, pcm) in enumerate(zip(voice.lines, ordered)))
    board_voice = BoardVoice(input_signature=voice.input_signature, lead_ms=voice.lead_ms,
                             gaps_ms=voice.gaps_ms, speech_end_ms=spans[-1].end_ms, track=track,
                             takes=takes)
    generator: dict[str, Any] = {
        "role": "voice", "engine": engine.service, "model": engine.model,
        "params": {"speed": SPEED, "assembler": ASSEMBLER},
        "source_asset_version_ids": sorted({line.voice_version_id for line in voice.lines}),
    }
    if engine.digest:
        generator["files_sha256"] = {"model": engine.digest.removeprefix("sha256:")}
    version = VersionRequest(
        kind="board_voice", name=voice.name,
        scope=Scope(production, story_id=voice.story_id, board_id=board_id), state=BOARD,
        capabilities=("board_voice",), content=None, voice=board_voice,
        provenance={"origin": "generated", "generator": generator, "external": None,
                    "source_key": board_voice_key(board_id)},
        licence=Licence.unknown(LICENCE_NOTES["voice"]))
    outcome = import_version(library, version, by=by, now=now, minter=minter)
    return Made(outcome.library, outcome.version, outcome.created,
                tuple(line.line_id for i, line in enumerate(voice.lines) if i not in reused),
                tuple(line.line_id for i, line in enumerate(voice.lines) if i in reused))


def is_current(job: Job, story: Mapping[str, Any], library: Library) -> bool:
    """VOICE-4: does the board, as drafted now, still have the input the job started
    from? False when the board changed, became silent, left the story, or the draft
    no longer validates."""
    if job.voice is None:
        return False
    try:
        drafted = drafted_input(story, job.target_id, library, model=job.voice.model,
                                signing_name=job.voice.engine)
    except ContractError:
        return False
    return (drafted.input_signature == job.input_signature
            and [(line.line_id, line.speaker, line.voice_version_id) for line in drafted.lines]
            == [(line.line_id, line.speaker, line.voice_version_id) for line in job.voice.lines])


@dataclass(frozen=True)
class JobRun:
    """One worker step: the terminal job, the library with its result, and whether the
    board now points at the result (``make_current``, the job's
    ``result_is_current``)."""

    job: Job
    library: Library
    version: AssetVersion | None
    created: bool
    synthesized: tuple[str, ...]

    @property
    def make_current(self) -> bool:
        return bool(self.job.result_is_current)


def run_voice_job(job: Job, library: Library, *, draft: Callable[[], Mapping[str, Any]],
                  speech: Speech, publish: Publish, fetch: Fetch, by: Principal, now: str,
                  minter: Minter | None = None, engine: Engine = Engine()) -> JobRun:
    """Start a queued voice job (a running one continues), make its version, and
    succeed it with ``result_is_current`` from ``draft()``, the story as it is when the
    job finishes. A terminal job is refused (``job.transition``) before anything runs.
    A rule or adapter error fails the job with its code; the library is then unchanged.
    Any other exception propagates and leaves the job running, for the caller's worker
    loop to fail."""
    if job.kind != VOICE or job.voice is None:
        raise _error("schema.invalid", "/kind", "not a voice job")
    running = job if job.status == RUNNING else start(job, now=now)  # a terminal job: refused
    try:
        made = make_voice(running.voice, running.target_id, library, speech=speech,
                          publish=publish, fetch=fetch, by=by, now=now, minter=minter,
                          engine=engine)
    except ContractError as error:
        first = error.violations[0]
        return JobRun(fail(running, first.rule, first.message, now=now), library, None, False, ())
    except AdapterError as error:
        return JobRun(fail(running, error.code, f"{error.label}: {error.message}", now=now),
                      library, None, False, ())
    current = is_current(running, draft(), made.library)
    done = succeed(running, made.version.id, is_current=current, now=now)
    return JobRun(done, made.library, made.version, made.created, made.synthesized)


def with_current_voice(story: Mapping[str, Any], board_id: str, version_id: str) -> dict[str, Any]:
    """A copy of the story whose board now names ``version_id`` as its current voice.
    The API bumps revisions; this only moves the pointer (proposal)."""
    out = copy.deepcopy(dict(story))
    board = next((b for b in out.get("boards") or [] if b.get("id") == board_id), None)
    if board is None:
        raise _error("ref.unknown", "/boards", f"the story has no board {board_id}")
    board["voice"]["current_version_id"] = version_id
    return out


def voice_facts(library: Library, story: Mapping[str, Any], jobs: Iterable[Job] = ()) -> Facts:
    """Story 404's facts for this story: the library's measured takes and currency
    (VOICE-5), plus every board with a voice or photo job in flight (VOICE-6:
    ``queue_run`` refuses it as ``asset.generating``)."""
    return library.facts(story).merged(generating(jobs))


__all__ = [
    "ENGINE_MISMATCH", "HASH_MISMATCH", "WAV", "Fetch", "JobRun", "Made", "Publish", "Speech",
    "is_current", "make_voice", "run_voice_job", "voice_facts", "with_current_voice",
]
