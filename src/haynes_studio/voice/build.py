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
only if the board's signature still matches, and otherwise stays, stale. Only the move
this step makes from ``running`` counts: if the stored job is no longer running
(cancelled, or finished by an earlier run), the step changes nothing and moves no
board, and the caller writes a finished job only over a stored running one
(compare-and-set). Nothing is overwritten or deleted. A failure fails the job and
creates no version (blobs already published stay; they are harmless orphans, section 8).
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
from haynes_studio.canonical.validate import SCHEMA_INVALID
from haynes_studio.errors import ContractError, Violation, blocking
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
    signature,
    takes_signature,
)
from haynes_studio.library.resolve import BYTES_MISSING
from haynes_studio.library.validate import LOCATOR_INVALID
from haynes_studio.library.winter_menu import LicenceRegister
from haynes_studio.timebase import line_spans, take_duration_ms
from haynes_studio.voice.jobs import fail, generating, start, succeed
from haynes_studio.voice.model import (
    ASSEMBLER,
    RUNNING,
    SPEED,
    TRACK_MAX_MS,
    VOICE,
    Engine,
    Job,
    VoiceInput,
)
from haynes_studio.voice.plan import (
    NOT_NEEDED,
    board_voice_key,
    board_voice_versions,
    drafted_input,
    same_input,
    same_lines,
    take_sources,
)
from haynes_studio.voice.track import FORMAT_MISMATCH, Pcm, assemble, read_wav
from haynes_studio.voice.validate import validate_job, voice_input_violations

WAV = "audio/wav"
ENGINE_MISMATCH = "voice.engine_mismatch"  # proposal: a job planned for another engine
HASH_MISMATCH = "store.hash_mismatch"  # proposal: publish answered another hash


class Speech(Protocol):
    """What :class:`haynes_studio.adapters.kokoro.KokoroClient` offers."""

    def synthesize(self, request: SpeechRequest) -> SpeechTake: ...


Publish = Callable[[bytes, str], tuple[str, str]]
"""``publish(data, media_type) -> (sha256, locator)``: store bytes create-only in the
production's folder (story 379's adapter, or an in-memory one in tests). The caller
binds it to the job's production; an answer outside that folder fails the job."""

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


def _voice_licence(licences: LicenceRegister | None, model: str) -> Licence:
    """The new version's licence: the voice model's entry in the model licence register
    (story 809) when a register is given, else ``unknown`` with the reason. Never guessed."""
    if licences is None:
        return Licence.unknown("No licence register was given to the voice builder; "
                               "terms not recorded.")
    return licences.licence_for("voice", model)


def make_voice(voice: VoiceInput, board_id: str, library: Library, *, speech: Speech,
               publish: Publish, fetch: Fetch, by: Principal, now: str,
               minter: Minter | None = None, engine: Engine = Engine(),
               licences: LicenceRegister | None = None) -> Made:
    """One board voice version for ``voice`` (VOICE-2). The input is checked first with
    the job's voice rules (:func:`~haynes_studio.voice.validate.voice_input_violations`):
    a voice that is not a recorded stock voice of its model is ``voice.not_stock``
    before any request is built, any call is made or any byte is published (VOICE-1), and
    so are a bad signature, gap count or time bound. Takes come from
    :func:`~haynes_studio.voice.plan.take_sources`, the rule the plan shows: a take a
    version of this board holds is read back (``fetch``), checked by hash and
    re-measured; each new signature goes to ``speech`` once. Every reused take and every
    request is checked before the first call, and each answer's format and the track's
    length so far before it is published and before the next call. If a version of this
    board already is the input, it is returned and nothing is called or published."""
    problems = voice_input_violations(voice)  # stock voices first: nothing is sent unchecked
    if problems:
        raise ContractError("<voice>", problems)
    if (engine.model, engine.signing_name) != (voice.model, voice.engine):
        raise _error(ENGINE_MISMATCH, "/voice/engine",
                     f"the input was signed for {voice.engine!r} ({voice.model}); this worker "
                     f"runs {engine.signing_name!r}")
    versions = board_voice_versions(library, board_id)
    existing = next((v for v in versions if same_input(v, voice)), None)
    if existing is not None:
        return Made(library, existing, False, (), ())
    sources = take_sources(voice, versions)
    production = voice.production_id
    pcms: dict[int, Pcm] = {}
    hashes: dict[int, str] = {}
    requests: dict[int, SpeechRequest] = {}
    index = {line.line_id: i for i, line in enumerate(voice.lines)}
    owners = [i if source.same_as is None else index[source.same_as]
              for i, source in enumerate(sources)]  # the line whose take each line plays
    for i, (line, source) in enumerate(zip(voice.lines, sources)):  # all checks first
        if source.reuse is not None:
            pcms[i] = _fetch(fetch, source.reuse, production, f"/voice/lines/{i}")
            hashes[i] = source.reuse.sha256
        elif source.synthesize:
            requests[i] = SpeechRequest(voice=line.voice_id, text=line.text)
    _check_room(voice, pcms, owners, "/voice")
    shape = next((pcm.shape for pcm in pcms.values()), None)
    for i, request in requests.items():
        answer = speech.synthesize(request)
        pcms[i] = read_wav(answer.wav, f"/voice/lines/{i}")  # 16-bit mono, at most 120000 ms
        shape = shape or pcms[i].shape
        if pcms[i].shape != shape:  # stop before the next paid call
            raise _error(FORMAT_MISMATCH, f"/voice/lines/{i}",
                         f"the take is {pcms[i].shape}, the board's others {shape}; the track "
                         "is assembled without resampling")
        _check_room(voice, pcms, owners, f"/voice/lines/{i}")  # and before publishing it
        hashes[i] = _publish(publish, answer.wav, production, f"/voice/lines/{i}").sha256
    for i, source in enumerate(sources):
        if source.same_as is not None:
            pcms[i], hashes[i] = pcms[index[source.same_as]], hashes[index[source.same_as]]
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
             heard=None, heard_matches=None, signature=line.signature)
        for i, (line, pcm) in enumerate(zip(voice.lines, ordered)))
    board_voice = BoardVoice(input_signature=voice.input_signature, lead_ms=voice.lead_ms,
                             gaps_ms=voice.gaps_ms, speech_end_ms=spans[-1].end_ms, track=track,
                             takes=takes)
    generator: dict[str, Any] = {
        "role": "voice", "engine": engine.service, "model": engine.model,
        # Stored normalized (speed 1); takes are always signed with the float SPEED.
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
                    "source_key": _source_key(library, board_id, voice, board_voice)},
        licence=_voice_licence(licences, voice.model))
    outcome = import_version(library, version, by=by, now=now, minter=minter)
    return Made(outcome.library, outcome.version, outcome.created,
                tuple(voice.lines[i].line_id for i in requests),
                tuple(line.line_id for line, source in zip(voice.lines, sources)
                      if not source.synthesize))


def _check_room(voice: VoiceInput, pcms: Mapping[int, Pcm], owners: list[int], path: str) -> None:
    """The track so far (lead, gaps and every take known now) must be within
    ``TRACK_MAX_MS``, so a track that can only be refused stops before the next call."""
    known = voice.lead_ms + sum(voice.gaps_ms) + sum(
        take_duration_ms(pcms[owner].frames, pcms[owner].rate) for owner in owners if owner in pcms)
    if known > TRACK_MAX_MS:
        raise _error(SCHEMA_INVALID, path, f"the track would be over {TRACK_MAX_MS} ms "
                                           f"({known} ms with the takes so far)")


def _source_key(library: Library, board_id: str, voice: VoiceInput,
                board_voice: BoardVoice) -> str:
    """``board-voice:<board_id>``, the board's one generated voice asset, unless that
    asset already holds a version with this pin for other lines (a line re-added with
    the same text, a cast voice version swapped for another of the same stock voice).
    The library's pin is the input signature and take hashes only, so importing there
    would be ``idempotency.mismatch``; such a version goes to an asset keyed by its lines
    as well (proposal, until the pin covers line identity)."""
    key = board_voice_key(board_id)
    asset = library.by_source_key(key)
    pin = takes_signature(board_voice)
    if asset is None or not any(v.voice is not None and takes_signature(v.voice) == pin
                                for v in library.versions_of(asset.id)):
        return key
    lines = signature([[line.line_id, line.speaker, line.voice_version_id] for line in voice.lines])
    return f"{key}:lines:{lines.removeprefix('sha256:')[:16]}"


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
    return drafted.input_signature == job.input_signature and same_lines(drafted, job.voice)


@dataclass(frozen=True)
class JobRun:
    """One worker step.

    ``moved`` is True when this step moved the job from ``running`` to a terminal
    status (``job``). The caller persists ``library`` first, then writes ``job`` only
    over a stored job that is still ``running`` (compare-and-set). ``make_current`` is
    True only for a move to ``succeeded`` whose result is the board's input as drafted
    now; the caller points the board at ``version`` only if that write succeeded.

    When the stored job was no longer ``running`` (cancelled, or already finished by an
    earlier run), ``moved`` and ``make_current`` are False and ``job`` is the stored job
    unchanged: nothing is written and the board is not moved."""

    job: Job
    library: Library
    version: AssetVersion | None
    created: bool
    synthesized: tuple[str, ...]
    moved: bool = False
    make_current: bool = False


def run_voice_job(job: Job, library: Library, *, draft: Callable[[], Mapping[str, Any]],
                  speech: Speech, publish: Publish, fetch: Fetch, by: Principal, now: str,
                  minter: Minter | None = None, engine: Engine = Engine(),
                  reload: Callable[[], Job] | None = None,
                  licences: LicenceRegister | None = None) -> JobRun:
    """Start a queued voice job (a running one continues), make its version, and
    succeed it with ``result_is_current`` from ``draft()``, the story as it is when the
    job finishes. The job document is validated first (stock voices, signatures, time
    bounds), and :func:`make_voice` checks its input again, so nothing reaches the
    speech client unchecked. A terminal job is refused (``job.transition``) before
    anything runs. A rule or adapter error fails the job with its code; the library is
    then unchanged. Any other exception propagates and leaves the job running, for the
    caller's worker loop to fail.

    ``reload()`` returns the job as stored now. It is read once the work is done: if the
    job is no longer ``running`` (cancelled meanwhile, or finished by an earlier run),
    the result is the stored job unchanged with ``moved`` and ``make_current`` False; a
    version already made stays in the returned library. ``is_current`` is computed only
    for the move this call makes. Either way the caller writes the terminal job only
    over a stored ``running`` one (compare-and-set, see :class:`JobRun`), or a cancel or
    an earlier finish is lost."""
    if job.kind != VOICE or job.voice is None:
        raise _error(SCHEMA_INVALID, "/kind", "not a voice job")
    problems = blocking(validate_job(job.to_document()))  # stock voices, signatures, bounds
    if problems:
        raise ContractError(job.id, problems)
    running = job if job.status == RUNNING else start(job, now=now)  # a terminal job: refused
    try:
        made = make_voice(running.voice, running.target_id, library, speech=speech,
                          publish=publish, fetch=fetch, by=by, now=now, minter=minter,
                          engine=engine, licences=licences)
    except (ContractError, AdapterError) as error:
        stored = _stored(running, reload)
        if stored.status != RUNNING:  # cancelled or finished meanwhile: no change
            return JobRun(stored, library, None, False, ())
        if isinstance(error, ContractError):
            first = error.violations[0]
            failed = fail(running, first.rule, first.message, now=now)
        else:
            failed = fail(running, error.code, f"{error.label}: {error.message}", now=now)
        return JobRun(failed, library, None, False, (), moved=True)
    stored = _stored(running, reload)
    if stored.status != RUNNING:  # cancelled or finished meanwhile: the version stays, unused
        return JobRun(stored, made.library, made.version, made.created, made.synthesized)
    current = is_current(running, draft(), made.library)  # only for this call's move
    done = succeed(running, made.version.id, is_current=current, now=now)
    return JobRun(done, made.library, made.version, made.created, made.synthesized,
                  moved=True, make_current=current)


def _stored(job: Job, reload: Callable[[], Job] | None) -> Job:
    if reload is None:
        return job
    stored = reload()
    if stored.id != job.id:
        raise _error("ref.unknown", "/id", f"reload returned {stored.id}, not {job.id}")
    return stored


def with_current_voice(story: Mapping[str, Any], board_id: str, version_id: str) -> dict[str, Any]:
    """A copy of the story whose board now names ``version_id`` as its current voice.
    The API bumps revisions; this only moves the pointer (proposal)."""
    out = copy.deepcopy(dict(story))
    board = next((b for b in out.get("boards") or [] if b.get("id") == board_id), None)
    if board is None:
        raise _error("ref.unknown", "/boards", f"the story has no board {board_id}")
    if not board.get("lines") or not isinstance(board.get("voice"), dict):
        raise _error(NOT_NEEDED, "/boards", f"board {board_id} is silent: it has no voice")
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
