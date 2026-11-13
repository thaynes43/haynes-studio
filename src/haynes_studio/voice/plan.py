"""What a board's voice needs (VOICE-1 to VOICE-4): the input as drafted, which takes
can be reused, and whether a voice job is needed at all.

:func:`plan_board_voice` is the one function that answers "what speech calls does this
edit need":

- ``current``: the board's current voice version already is this input; nothing to do.
- ``existing``: another version of this board's voice already is this input (an edit
  was undone, or a stale result has become right again); no call and no new version,
  the board only points at it again.
- ``assemble``: every take is reusable (a lead or gap edit, a reorder of lines, a cast
  voice version with the same stock voice); the track is re-assembled with no speech
  call.
- ``synthesize``: the takes whose signature no version of this board holds go to the
  speech client, and only those.

A take is reusable when any version of this board's voice holds a take with the same
signature (VOICE-3): the current version first, then the others, newest first. A
version "is" an input when its input signature and its lines (ID, speaker, cast voice
version) are the input's. Stock voices only (VOICE-1): a cast voice that is not a
recorded stock voice of the engine's model is refused (``voice.not_stock``) before any
call.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from haynes_studio.canonical import load_story
from haynes_studio.canonical.ids import Minter
from haynes_studio.canonical.model import NARRATOR, Principal
from haynes_studio.errors import ContractError, Violation, blocking, pointer
from haynes_studio.library import Library
from haynes_studio.library.model import AssetVersion, Take, is_stock_voice
from haynes_studio.library.resolve import KIND_MISMATCH
from haynes_studio.library.validate import NOT_STOCK, validate_asset_version
from haynes_studio.voice.jobs import new_job
from haynes_studio.voice.model import VOICE, Engine, Job, VoiceInput, VoiceLine, line_signature

CURRENT, EXISTING, ASSEMBLE, SYNTHESIZE = "current", "existing", "assemble", "synthesize"
ACTIONS = (CURRENT, EXISTING, ASSEMBLE, SYNTHESIZE)

NOT_NEEDED = "voice.not_needed"  # proposal: a silent board has no voice
VOICE_ABSENT = "voice.absent"  # a narrator line without the story's narrator voice
REF_UNKNOWN = "ref.unknown"
SOURCE_KEY_PREFIX = "board-voice:"  # proposal: the source key of a board's generated voice


def board_voice_key(board_id: str) -> str:
    """The source key that names a board's generated voice asset (proposal). A legacy
    import keeps its own asset (``legacy:<job>:speech:shot:<n>``)."""
    return SOURCE_KEY_PREFIX + board_id


def _error(rule: str, path: str, message: str) -> ContractError:
    return ContractError("<voice>", [Violation(rule, path, message)])


def board_voice_versions(library: Library, board_id: str) -> tuple[AssetVersion, ...]:
    """Every ``board_voice`` version scoped to this board, legacy and generated, newest
    ID first: what ``list_board_voice_versions`` lists."""
    found = [version for version in library.versions.values()
             if version.voice is not None
             and library.assets[version.asset_id].scope.board_id == board_id]
    return tuple(sorted(found, key=lambda version: version.id, reverse=True))


def same_input(version: AssetVersion, voice: VoiceInput) -> bool:
    """Is this board voice version that input: the same input signature (takes, lead,
    gaps) and the same lines, speakers and cast voice versions?"""
    takes = version.voice.takes if version.voice is not None else ()
    return (version.voice is not None
            and version.voice.input_signature == voice.input_signature
            and [(t.line_id, t.speaker, t.voice_version_id) for t in takes]
            == [(line.line_id, line.speaker, line.voice_version_id) for line in voice.lines])


def drafted_input(story: Mapping[str, Any], board_id: str, library: Library, *,
                  model: str, signing_name: str) -> VoiceInput:
    """The voice input of a board as drafted now. Raises :class:`ContractError` for a
    story that breaks a rule (story 404's validator, so ``voice.speaker_not_in_cast``
    is its), a board it does not hold (``ref.unknown``), a silent board
    (``voice.not_needed``), a narrator line without a narrator voice
    (``voice.absent``), a cast voice that is not a ``voice`` version
    (``asset.kind_mismatch``) or not a stock voice of ``model`` (``voice.not_stock``)."""
    model_story = load_story(story, facts=library.facts(story), source="<story>")
    if model_story.boards is None:
        raise _error("schema.invalid", "/boards", "the story's boards must be embedded")
    index = next((i for i, board in enumerate(model_story.boards) if board.id == board_id), None)
    if index is None:
        raise _error(REF_UNKNOWN, "/boards", f"the story has no board {board_id}")
    board = model_story.boards[index]
    at = pointer("boards", index)
    if not board.spoken:
        raise _error(NOT_NEEDED, at + "/lines", "a silent board has no voice (TIME-4)")
    cast = {member.slot: member.voice_version_id for member in model_story.cast}
    cast[NARRATOR] = model_story.narrator_voice_version_id
    lines = []
    for i, line in enumerate(board.lines):
        version_id = cast.get(line.speaker)
        if version_id is None:
            raise _error(VOICE_ABSENT, "/narrator_voice_version_id",
                         "a narrator line needs the story's narrator voice")
        voice_id = _stock_voice(library, version_id, model, pointer("boards", index, "lines", i))
        lines.append(VoiceLine(line_id=line.id, speaker=line.speaker, text=line.text,
                               voice_version_id=version_id, voice_id=voice_id,
                               signature=line_signature(signing_name, voice_id, line.text)))
    return VoiceInput(production_id=model_story.production_id, story_id=model_story.id,
                      name=f"{board.title} voice"[:200], engine=signing_name, model=model,
                      lead_ms=board.timing.lead_ms,
                      gaps_ms=tuple(line.gap_before_ms for line in board.lines[1:]),
                      lines=tuple(lines))


def _stock_voice(library: Library, version_id: str, model: str, at: str) -> str:
    """The stock ``voice_id`` a cast voice version declares, after the library's own
    rules (VOICE-1) and a check that it is a voice of the engine's model."""
    version = library.get(version_id)
    if version is None:
        raise _error(REF_UNKNOWN, at + "/speaker", f"the library has no voice {version_id}")
    if version.kind != "voice":
        raise _error(KIND_MISMATCH, at + "/speaker",
                     f"{version_id} is a {version.kind}, not a stock voice")
    problems = blocking(validate_asset_version(library.document(version_id)))
    if problems:
        raise ContractError(version_id, problems)
    voice_id = library.asset_of(version_id).attributes.get("voice_id")
    generator = version.provenance.get("generator") or {}
    if not is_stock_voice(model, voice_id) or generator.get("model") != model:
        raise _error(NOT_STOCK, at + "/speaker",
                     f"{voice_id!r} is not a recorded stock voice of {model!r} (VOICE-1, P-22)")
    return voice_id


def reusable_takes(versions: Iterable[AssetVersion]) -> dict[str, tuple[Take, str]]:
    """Take signature to the first take (and its version ID) that holds it, in the
    order given."""
    pool: dict[str, tuple[Take, str]] = {}
    for version in versions:
        for take in version.voice.takes if version.voice is not None else ():
            pool.setdefault(take.signature, (take, version.id))
    return pool


@dataclass(frozen=True)
class TakePlan:
    """One line: reuse ``reuse`` (from version ``from_version_id``) or synthesize."""

    line_id: str
    signature: str
    reuse: Take | None
    from_version_id: str | None

    @property
    def synthesize(self) -> bool:
        return self.reuse is None


@dataclass(frozen=True)
class VoicePlan:
    board_id: str
    input: VoiceInput
    action: str
    version_id: str | None  # current and existing: the version that already is the input
    takes: tuple[TakePlan, ...]

    @property
    def input_signature(self) -> str:
        return self.input.input_signature

    @property
    def speech_lines(self) -> tuple[str, ...]:
        """The line IDs that would go to the speech client, in order."""
        return tuple(take.line_id for take in self.takes if take.synthesize)

    @property
    def speech_calls(self) -> int:
        return len(self.speech_lines)


def plan_board_voice(story: Mapping[str, Any], board_id: str, library: Library, *,
                     engine: Engine = Engine()) -> VoicePlan:
    """What the board's voice needs now (see the module text). Pure: it reads the
    story and the library and calls nothing."""
    voice = drafted_input(story, board_id, library, model=engine.model,
                          signing_name=engine.signing_name)
    versions = board_voice_versions(library, board_id)
    current_id = _current_version_id(story, board_id)
    ordered = sorted(versions, key=lambda version: version.id != current_id)  # stable
    current = next((v for v in versions if v.id == current_id), None)
    if current is not None and same_input(current, voice):
        return VoicePlan(board_id, voice, CURRENT, current.id, _takes(voice, ordered))
    existing = next((v for v in versions if same_input(v, voice)), None)
    if existing is not None:
        return VoicePlan(board_id, voice, EXISTING, existing.id, _takes(voice, ordered))
    takes = _takes(voice, ordered)
    action = SYNTHESIZE if any(take.synthesize for take in takes) else ASSEMBLE
    return VoicePlan(board_id, voice, action, None, takes)


def _takes(voice: VoiceInput, versions: Iterable[AssetVersion]) -> tuple[TakePlan, ...]:
    pool = reusable_takes(versions)
    out = []
    for line in voice.lines:
        take, version_id = pool.get(line.signature, (None, None))
        out.append(TakePlan(line.line_id, line.signature, take, version_id))
    return tuple(out)


def _current_version_id(story: Mapping[str, Any], board_id: str) -> str | None:
    for board in story.get("boards") or []:
        if isinstance(board, Mapping) and board.get("id") == board_id:
            return (board.get("voice") or {}).get("current_version_id")
    return None


@dataclass(frozen=True)
class VoiceRequest:
    """The answer to "generate this board's voice". ``job`` is None when nothing needs
    making (``current``, or ``existing``: the caller points the board at
    ``plan.version_id``). ``created`` is False when an in-flight job for the same input
    was returned instead of a new one."""

    plan: VoicePlan
    job: Job | None
    created: bool

    @property
    def make_current(self) -> str | None:
        """The version the board must point at with no job, if any (``existing``)."""
        return self.plan.version_id if self.plan.action == EXISTING else None


def request_voice(story: Mapping[str, Any], board_id: str, library: Library, *,
                  jobs: Iterable[Job] = (), by: Principal, now: str,
                  minter: Minter | None = None, engine: Engine = Engine()) -> VoiceRequest:
    """``generate_board_voice``: plan, then queue a voice job only if something must be
    made. A second identical request creates nothing: the board is ``current``, or the
    in-flight job for the same board and input signature is returned."""
    plan = plan_board_voice(story, board_id, library, engine=engine)
    if plan.action in (CURRENT, EXISTING):
        return VoiceRequest(plan, None, False)
    for job in jobs:
        if (job.kind == VOICE and job.in_flight and job.target_id == board_id
                and job.input_signature == plan.input_signature):
            return VoiceRequest(plan, job, False)
    job = new_job(VOICE, board_id, plan.input_signature, by=by, now=now, minter=minter,
                  voice=plan.input)
    return VoiceRequest(plan, job, True)


__all__ = [
    "ACTIONS", "ASSEMBLE", "CURRENT", "EXISTING", "NOT_NEEDED", "SOURCE_KEY_PREFIX", "SYNTHESIZE",
    "TakePlan", "VoicePlan", "VoiceRequest", "board_voice_key", "board_voice_versions",
    "drafted_input", "plan_board_voice", "request_voice", "reusable_takes", "same_input",
]
