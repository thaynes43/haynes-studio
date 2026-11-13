"""The film's sound and master through the cache (story 841).

:class:`SoundBuilder` is a ``content`` source for
:func:`~haynes_studio.cache.plan.plan_story`, as story 380's
:class:`~haynes_studio.cache.build.PictureBuilder` is for picture, and chains behind it:

    sound = SoundBuilder(cache, story=story, upstream=adapters)
    picture = PictureBuilder(cache, renderer, upstream=sound)
    plan = plan_story(story, ..., toolchain=sound_toolchain(toolchain), content=picture)
    result = film_sound(story, plan, sound)

For a ``mix`` key it returns the cached mix, or mixes and commits it with its placement
record; for a ``master`` key the cached master, or muxes the cached film picture with
the cached mix, checks it and commits it. Every other kind goes to ``upstream``. Both
are completed stages found again by their keys (P-27): a second build of an unchanged
story mixes and muxes nothing, and a mix-only edit (a cue, a bed, a level, the loudness
target) changes the mix and master keys and no picture key, so no picture is made.

With ``story`` given, every sound cue is checked against its own board before anything
is mixed (TIME-10, ``cue.out_of_range``), so a cue outside its board fails without a
mix or a master. :func:`film_sound` collects the mix, the master, the placement record
with the story's identifiers, and the sound checks of :mod:`haynes_studio.mix.checks`.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from haynes_studio.cache.artifacts import ArtifactCache, CachedArtifact
from haynes_studio.cache.errors import ENTRY_INVALID, CacheError
from haynes_studio.cache.keys import MASTER, MIX, CacheKey, make_key
from haynes_studio.cache.plan import StoryPlan, Toolchain
from haynes_studio.canonical.model import SoundCue, Story
from haynes_studio.mix import checks as sound_checks
from haynes_studio.mix.errors import CHECK_FAILED, CONSERVATION, CUE_OUT_OF_RANGE, MixError
from haynes_studio.mix.master import MUX, MuxSettings, mux
from haynes_studio.mix.mixer import MIXER, MixerSettings, MixResult, Reader, mix
from haynes_studio.store import (
    BLOB_MISSING,
    HASH_MISMATCH,
    Store,
    StoreError,
    blob_locator,
    canonical_json,
)
from haynes_studio.timebase import SAMPLES_PER_FRAME, frames_for_ms

WAV, MP4, JSON = "audio/wav", "video/mp4", "application/json"
PLACEMENT = "mix_placement"  # proposal: the placement record's cache kind


def placement_key(mix_key: CacheKey) -> CacheKey:
    """The placement record's key: the mix key's own inputs under kind
    ``mix_placement`` (proposal), so it is found exactly when the mix is."""
    return make_key(PLACEMENT, {k: v for k, v in mix_key.inputs().items()
                                if k not in ("kind", "scheme")})


def sound_toolchain(toolchain: Toolchain, *, mixer: MixerSettings = MIXER,
                    mux_settings: MuxSettings = MUX) -> Toolchain:
    """``toolchain`` naming this mixer and mux (the key inputs a build must match)."""
    return dataclasses.replace(toolchain, mixer=mixer.version(), mux=mux_settings.key_inputs())


def store_reader(store: Store, production_id: str) -> Reader:
    """Reads a WAV input by hash from the production's folder, else the library's,
    and re-hashes the bytes it read (``store.hash_mismatch``); neither holds it:
    ``store.blob_missing``."""

    def read(sha256: str, where: str) -> bytes:
        for scope in (production_id, "library"):
            locator = blob_locator(scope, sha256, WAV)
            try:
                with store.open(locator) as handle:
                    data = handle.read()
            except StoreError as error:
                if error.code == BLOB_MISSING:
                    continue
                raise
            if hashlib.sha256(data).hexdigest() != sha256:
                raise StoreError(HASH_MISMATCH, f"{where} is not the bytes its key names",
                                 locator=locator)
            return data
        raise StoreError(BLOB_MISSING, f"{where}: no WAV of this hash in the production or "
                         f"the library", locator=blob_locator(production_id, sha256, WAV))
    return read


@dataclass(frozen=True)
class BoardRange:
    """One board on the film clock, as the mix key and the story give it."""

    board_id: str
    start_frame: int
    frames: int
    track: int | None  # index of its voice track in the key

    @property
    def start_sample(self) -> int:
        return self.start_frame * SAMPLES_PER_FRAME

    @property
    def end_sample(self) -> int:
        return (self.start_frame + self.frames) * SAMPLES_PER_FRAME


def board_ranges(story: Story, document: Mapping[str, Any]) -> list[BoardRange]:
    """Each board's film range from the mix key ``document`` and the story: a spoken
    board's frames from its track's last line end plus its tail (TIME-3), a silent
    board's from its hold (TIME-4). The key's start frames and length must agree
    (``time.conservation``)."""
    tracks = list(document["voice_tracks"])
    out, at, t = [], 0, 0
    for board in story.ordered_boards():
        if board.spoken:
            if t >= len(tracks) or tracks[t]["start_frame"] != at:
                raise MixError(CONSERVATION, "the mix key's voice tracks do not start where the "
                               "story's spoken boards do (TIME-7)", where=board.id)
            content_ms = tracks[t]["spans"][-1][1] + board.timing.tail_ms
            out.append(BoardRange(board.id, at, frames_for_ms(content_ms), t))
            t += 1
        else:
            out.append(BoardRange(board.id, at, frames_for_ms(board.timing.hold_ms), None))
        at += out[-1].frames
    if t != len(tracks) or at != document["frames"]:
        raise MixError(CONSERVATION, f"the story's boards hold {at} frames and {t} voice tracks, "
                       f"the mix key {document['frames']} and {len(tracks)} (TIME-11)")
    return out


def sound_cues(story: Story) -> list[tuple[str, SoundCue]]:
    """Every sound cue in film order: by board order, then the board's cue order (the
    order of the mix key's ``sounds``)."""
    return [(board.id, cue) for board in story.ordered_boards() for cue in board.cues
            if isinstance(cue, SoundCue)]


def check_cues(story: Story, document: Mapping[str, Any]) -> None:
    """TIME-10: every sound cue starts inside its own board, ``[0, board length)``."""
    ranges = {r.board_id: r for r in board_ranges(story, document)}
    cues, sounds = sound_cues(story), list(document["sounds"])
    if len(cues) != len(sounds):
        raise MixError(CONSERVATION, f"the story has {len(cues)} sound cues, the mix key "
                       f"{len(sounds)}")
    for (board_id, cue), sound in zip(cues, sounds):
        board = ranges[board_id]
        start = sound["start_sample"]
        if not board.start_sample <= start < board.end_sample:
            offset = start - board.start_sample
            raise MixError(CUE_OUT_OF_RANGE, f"cue {cue.id} starts {offset} samples into board "
                           f"{board_id}, outside its [0, {board.frames * SAMPLES_PER_FRAME}) "
                           f"(TIME-10)", where=f"{board_id}/{cue.id}")


def label_placement(story: Story, document: Mapping[str, Any],
                    placement: Mapping[str, Any]) -> dict[str, Any]:
    """The placement record of one run: the cached record (no identifiers) with each
    line's board and line ID, each sound's board and cue ID, and each bed's ID."""
    ranges = board_ranges(story, document)
    spoken = [r for r in ranges if r.track is not None]
    boards = {board.id: board for board in story.ordered_boards()}
    cues = sound_cues(story)
    out = json.loads(json.dumps(placement))
    for line in out["lines"]:
        board = boards[spoken[line["track"]].board_id]
        line["board_id"], line["line_id"] = board.id, board.lines[line["line"]].id
    for sound in out["sounds"]:
        sound["board_id"], sound["cue_id"] = cues[sound["sound"]][0], cues[sound["sound"]][1].id
    for bed in out["beds"]:
        bed["bed_id"] = story.beds[bed["bed"]].id
    out["boards"] = [{"board_id": r.board_id, "start_frame": r.start_frame, "frames": r.frames,
                      "start_sample": r.start_sample, "end_sample": r.end_sample} for r in ranges]
    return out


@dataclass
class SoundStats:
    """What one builder did: keys mixed, muxed and checked (hits are not listed)."""

    mixed: list[str] = field(default_factory=list)
    muxed: list[str] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)


class SoundBuilder:
    """Makes the mix and the master through ``cache`` (see the module docstring)."""

    def __init__(self, cache: ArtifactCache, *, story: Story | None = None,
                 read_input: Reader | None = None,
                 upstream: Callable[[CacheKey], str] | None = None,
                 mixer: MixerSettings = MIXER, mux_settings: MuxSettings = MUX,
                 workdir: str | os.PathLike[str] | None = None):
        self.cache = cache
        self.story = story
        self.read_input = read_input or store_reader(cache.store, cache.production_id)
        self.upstream = upstream
        self.mixer = mixer
        self.mux_settings = mux_settings
        self.workdir = workdir
        self.stats = SoundStats()
        self._made: dict[str, MixResult] = {}

    def __call__(self, key: CacheKey) -> str:
        if key.kind == MIX:
            return self.mix(key).sha256
        if key.kind == MASTER:
            return self.master(key).sha256
        if self.upstream is None:
            raise LookupError(f"no source for {key.kind} artifacts")
        return self.upstream(key)

    # The mix -------------------------------------------------------------------------

    def _mixed(self, key: CacheKey) -> MixResult:
        if key.value not in self._made:
            self._made[key.value] = mix(key.document, self.read_input, settings=self.mixer)
            self.stats.mixed.append(key.value)
        return self._made[key.value]

    def mix(self, key: CacheKey) -> CachedArtifact:
        """The mix: a hit, or mixed and committed with its placement record (the record
        first, so a found mix always has one)."""
        if key.kind != MIX:
            raise CacheError(ENTRY_INVALID, f"not a mix key: {key.kind}", where=key.value)
        if key.document["mixer"] != self.mixer.version():
            raise CacheError(ENTRY_INVALID, f"the key names mixer {key.document['mixer']!r}, "
                             f"this builder's is {self.mixer.version()!r}", where=key.value)
        if self.story is not None:
            check_cues(self.story, key.document)
        found = self.cache.lookup(key, WAV)
        if found is not None and self.cache.lookup(placement_key(key), JSON) is not None:
            return found
        self.cache.get_or_make(placement_key(key),
                               lambda: canonical_json(self._mixed(key).placement), JSON)
        return found or self.cache.get_or_make(key, lambda: self._mixed(key).wav, WAV)

    def placement(self, key: CacheKey) -> dict[str, Any]:
        """The cached placement record of a mix key (no identifiers)."""
        found = self.cache.lookup(placement_key(key), JSON)
        if found is None:
            raise CacheError(ENTRY_INVALID, "the mix has no placement record", where=key.value)
        return json.loads(self._production_bytes(found.sha256, JSON))

    # The master ----------------------------------------------------------------------

    def _production_bytes(self, sha256: str, media_type: str) -> bytes:
        locator = blob_locator(self.cache.production_id, sha256, media_type)
        with self.cache.store.open(locator) as handle:
            data = handle.read()
        if hashlib.sha256(data).hexdigest() != sha256:
            raise StoreError(HASH_MISMATCH, "not the bytes the key names", locator=locator)
        return data

    def master(self, key: CacheKey) -> CachedArtifact:
        """The master: a hit, or the key's film picture and mix (read from the
        production's folder by hash, re-hashed) muxed, checked and committed."""
        if key.kind != MASTER:
            raise CacheError(ENTRY_INVALID, f"not a master key: {key.kind}", where=key.value)
        if dict(key.document["mux"]) != self.mux_settings.key_inputs():
            raise CacheError(ENTRY_INVALID, "the key names other mux settings than this "
                             "builder's", where=key.value)
        return self.cache.get_or_make(key, lambda: self._mux(key), MP4)

    def _mux(self, key: CacheKey) -> bytes:
        picture = self._production_bytes(key.document["picture"], MP4)
        mix_wav = self._production_bytes(key.document["mix"], WAV)
        made = mux(picture, mix_wav, settings=self.mux_settings, workdir=self.workdir)
        self.stats.muxed.append(key.value)
        return made.data

    # Checks --------------------------------------------------------------------------

    def checks(self, mix_key: CacheKey, mix_sha: str, master_sha: str | None) -> list[CheckResult]:
        """Every sound check of :mod:`~haynes_studio.mix.checks` on the mix and the
        master, each a cached check result found again by its key."""
        out: list[CheckResult] = []
        measured: dict[str, sound_checks.Measured] = {}
        for check in sound_checks.CHECKS:
            on = check.split(".", 1)[0]
            artifact = mix_sha if on == sound_checks.MIX else master_sha
            if artifact is None:
                continue
            key = sound_checks.check_key(check, artifact, mix_key.document)

            def make(check: str = check, on: str = on, artifact: str = artifact,
                     key: CacheKey = key) -> bytes:
                if on not in measured:
                    data = self._production_bytes(artifact, WAV if on == sound_checks.MIX else MP4)
                    measured[on] = (sound_checks.measure_mix(data) if on == sound_checks.MIX
                                    else sound_checks.measure_master(data))
                self.stats.checked.append(key.value)
                return canonical_json(sound_checks.evaluate(check, key, measured[on]))
            found = self.cache.get_or_make(key, make, JSON)
            document = json.loads(self._production_bytes(found.sha256, JSON))
            out.append(CheckResult(check=check, key=key, sha256=found.sha256, document=document))
        return out


@dataclass(frozen=True)
class CheckResult:
    """One sound check: its key, the result's hash and the result document."""

    check: str
    key: CacheKey
    sha256: str
    document: Mapping[str, Any]

    @property
    def passed(self) -> bool:
        return bool(self.document["passed"])


@dataclass(frozen=True)
class FilmSound:
    """The film's sound for one run: the cached mix and master, the run's placement
    record (with identifiers) and the sound checks."""

    mix: CachedArtifact
    master: CachedArtifact
    placement: Mapping[str, Any]
    checks: tuple[CheckResult, ...]

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.checks)

    def ensure_passed(self) -> None:
        """Raise ``mix.check_failed`` naming every check that did not pass."""
        failed = [f"{r.check} {dict(r.document['measured'])} against "
                  f"{dict(r.document['thresholds'])}" for r in self.checks if not r.passed]
        if failed:
            raise MixError(CHECK_FAILED, "; ".join(failed))


def film_sound(story: Story, plan: StoryPlan, builder: SoundBuilder) -> FilmSound:
    """The mix, the master, the placement record and the sound checks of a story whose
    plan was made with ``builder`` in its content chain. Everything is found by key (a
    plan made that way has already made it); a plan whose mix or master content is not
    the cached artifact's is ``cache.entry_invalid``."""
    check_cues(story, plan.mix.key.document)
    made_mix = builder.mix(plan.mix.key)
    if made_mix.sha256 != plan.mix.content:
        raise CacheError(ENTRY_INVALID, "the plan's mix is not the cached mix: plan with the "
                         "sound builder as content", where=plan.mix.key.value)
    made_master = builder.master(plan.master.key)
    if made_master.sha256 != plan.master.content:
        raise CacheError(ENTRY_INVALID, "the plan's master is not the cached master",
                         where=plan.master.key.value)
    placement = label_placement(story, plan.mix.key.document, builder.placement(plan.mix.key))
    results = builder.checks(plan.mix.key, made_mix.sha256, made_master.sha256)
    return FilmSound(mix=made_mix, master=made_master, placement=placement,
                     checks=tuple(results))


__all__ = [
    "BoardRange", "CheckResult", "FilmSound", "PLACEMENT", "SoundBuilder",
    "SoundStats", "board_ranges", "check_cues", "film_sound", "label_placement",
    "placement_key", "sound_cues", "sound_toolchain", "store_reader",
]
