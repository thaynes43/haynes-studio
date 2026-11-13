"""Fixtures for the board voice tests: the Winter Menu r4 story and library from public
files (stories 404 and 382), an in-memory store, and the Kokoro client of story 425
behind ``FakeRunner`` and ``FakeKokoro``. No service is called and no file is written:
every WAV is synthetic and lives in memory."""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field

from haynes_studio.adapters.fakes import FakeKokoro, FakeRunner
from haynes_studio.adapters.kokoro import KokoroClient
from haynes_studio.canonical.ids import Minter
from haynes_studio.jsonio import read_json
from haynes_studio.library import Library
from haynes_studio.library.model import locator_for
from haynes_studio.voice import Engine, request_voice, run_voice_job, with_current_voice
from tests.canonical.fixtures import NOW, TITLE
from tests.library.fixtures import BY, imported, winter_menu

LATER = "2026-11-14T09:00:00Z"
RATE = 24000


def minter() -> Minter:
    return Minter(clock=lambda: 1_800_000_000_000, random_bits=lambda: 7)


class MemoryStore:
    """``publish`` and ``fetch`` over a dict, for one production. Create-only: the same
    locator with other bytes is refused. Records every call."""

    def __init__(self, production_id: str):
        self.production_id = production_id
        self.blobs: dict[str, bytes] = {}
        self.published: list[tuple[str, str]] = []
        self.fetched: list[tuple[str, str]] = []

    def publish(self, data: bytes, media_type: str) -> tuple[str, str]:
        sha256 = hashlib.sha256(data).hexdigest()
        locator = locator_for(sha256, media_type, self.production_id)
        if self.blobs.setdefault(locator, data) != data:
            raise AssertionError("store collision")
        self.published.append((locator, media_type))
        return sha256, locator

    def fetch(self, locator: str, sha256: str) -> bytes | None:
        self.fetched.append((locator, sha256))
        return self.blobs.get(locator)


@dataclass
class Studio:
    """One draft, its library and store, and the fake speech service, as an API would
    hold them. ``generate(board_id)`` is ``generate_board_voice`` followed by the
    worker's run, with the board pointed at a current result."""

    story: dict
    library: Library
    store: MemoryStore
    kokoro: FakeKokoro
    engine: Engine = Engine()
    jobs: list = field(default_factory=list)
    minter: Minter = field(default_factory=minter)

    def __post_init__(self):
        self._runner = FakeRunner(self.kokoro)
        self.client = KokoroClient(self._runner)

    @property
    def calls(self) -> int:
        """Speech calls so far (the runner's command count)."""
        return len(self._runner.calls)

    def board(self, number: int) -> dict:
        return next(b for b in self.story["boards"] if b["number"] == number)

    def request(self, board_id: str, now: str = NOW):
        outcome = request_voice(self.story, board_id, self.library, jobs=self.jobs, by=BY, now=now,
                                minter=self.minter, engine=self.engine)
        if outcome.created:
            self.jobs.append(outcome.job)
        if outcome.make_current:
            self.story = with_current_voice(self.story, board_id, outcome.make_current)
        return outcome

    def run(self, job, *, draft=None, reload=None, now: str = NOW):
        run = run_voice_job(job, self.library, draft=draft or (lambda: self.story),
                            speech=self.client, publish=self.store.publish, fetch=self.store.fetch,
                            by=BY, now=now, minter=self.minter, engine=self.engine,
                            reload=reload)
        self.jobs = [run.job if j.id == run.job.id else j for j in self.jobs]
        self.library = run.library
        if run.make_current:
            self.story = with_current_voice(self.story, job.target_id, run.version.id)
        return run

    def generate(self, board_id: str, now: str = NOW):
        outcome = self.request(board_id, now)
        return outcome, (self.run(outcome.job, now=now) if outcome.job is not None else None)

    def generate_all(self) -> None:
        for board in list(self.story["boards"]):
            if board["lines"]:
                self.generate(board["id"])

    def current(self, number: int):
        return self.library.version(self.board(number)["voice"]["current_version_id"])


def r4_speech() -> Mapping:
    return read_json(TITLE / "evidence-r4" / "speech.json").document


def r4_frames(extra: int = 0) -> dict[tuple[str, str], int]:
    """Frame counts for every r4 take, ``(voice, text)`` to frames: the recorded
    ``duration_s`` at 24 kHz, plus ``extra`` (0 to 11 frames still records the same
    3-decimal ``duration_s``)."""
    return {(line["voice"], line["text"]): round(line["duration_s"] * RATE) + extra
            for line in r4_speech()["lines"]}


def without_board_voices(library: Library) -> Library:
    """The library with its stock voices, stills, set and sounds, and no board voice."""
    return Library.build([a for a in library.assets.values() if a.kind != "board_voice"],
                         [v for v in library.versions.values() if v.kind != "board_voice"])


def fresh_r4(frames: Mapping | None = None, **kwargs) -> Studio:
    """The r4 script as a fresh draft: every spoken board without a voice, and a
    library holding no board voice."""
    story = copy.deepcopy(imported(4).story)
    for board in story["boards"]:
        if board["lines"]:
            board["voice"]["current_version_id"] = None
    return Studio(story=story, library=without_board_voices(winter_menu().library),
                  store=MemoryStore(story["production_id"]),
                  kokoro=FakeKokoro(r4_frames() if frames is None else frames), **kwargs)


def legacy_r4(**kwargs) -> Studio:
    """The r4 story as story 404 imports it, with story 382's library (legacy takes,
    whose bytes are not public)."""
    story = copy.deepcopy(imported(4).story)
    return Studio(story=story, library=winter_menu().library,
                  store=MemoryStore(story["production_id"]), kokoro=FakeKokoro(r4_frames()),
                  **kwargs)


def generated_r4() -> Studio:
    """The fresh r4 draft with every spoken board voiced and current."""
    studio = fresh_r4()
    studio.generate_all()
    return studio
