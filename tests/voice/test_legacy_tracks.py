"""A legacy board voice has no assembled track (story 857, observation O-406-2).

The contract owner's decision: a board voice without a track is not current for a
build. The library's facts mark it stale (``voice.stale`` at ``queue_run``, derived
``voice_state: stale``), and the planner makes a new version with a track: takes whose
bytes the store holds are reused after their hash is checked, only a take it does not
hold is spoken again, and the legacy version stays as it is. The fake speech client
counts every call; ``held_legacy_r4`` stands synthetic WAVs in for the private takes.
No service is called and nothing is written outside ``tmp_path``.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
from types import MappingProxyType

import pytest

from haynes_studio.adapters.fakes import FakeKokoro, FakeRunner
from haynes_studio.adapters.kokoro import KokoroClient
from haynes_studio.build import make_story_voices
from haynes_studio.canonical import timing_summary, validate_story, with_derived
from haynes_studio.canonical.ids import Minter
from haynes_studio.canonical.model import to_document
from haynes_studio.errors import ContractError, blocking
from haynes_studio.library import Library
from haynes_studio.library.model import locator_for
from haynes_studio.store import LocalStore
from haynes_studio.voice import ASSEMBLE, CURRENT, SYNTHESIZE, make_voice, voice_facts
from haynes_studio.voice.plan import board_voice_key, board_voice_versions, plan_board_voice
from tests.canonical.fixtures import NOW
from tests.library.fixtures import BY
from tests.voice.fixtures import LATER, WAV, generated_r4, held_legacy_r4, legacy_r4, r4_frames

R4_FRAMES = [153, 94, 146, 84, 83, 122, 46, 251, 108]


def spoken(studio):
    return [board for board in studio.story["boards"] if board["lines"]]


def stale_everywhere(story) -> set[tuple[str, str]]:
    return {("voice.stale", f"/boards/{i}/voice/current_version_id")
            for i, board in enumerate(story["boards"]) if board["lines"]}


def queue_problems(story, library) -> set[tuple[str, str]]:
    draft = {key: value for key, value in story.items() if key != "derived"}
    draft["boards"] = [{k: v for k, v in board.items() if k != "derived"}
                       for board in story["boards"]]
    return {(v.rule, v.path) for v in blocking(validate_story(
        draft, context="queue_run", facts=voice_facts(library, story)))}


def legacy_documents(studio) -> dict[str, dict]:
    return {v.id: studio.library.document(v.id) for v in studio.library.versions.values()
            if v.voice is not None}


def test_an_imported_r4_story_is_stale_on_every_spoken_board():
    studio = legacy_r4()
    assert len(spoken(studio)) == 8
    assert all(studio.current(b["number"]).voice.track is None for b in spoken(studio))
    assert queue_problems(studio.story, studio.library) == stale_everywhere(studio.story)
    facts = voice_facts(studio.library, studio.story)
    derived = with_derived(studio.story, facts=facts)["boards"]
    states = [board["derived"]["voice_state"] for board in derived]
    assert states == ["stale" if b["lines"] else "not_needed" for b in studio.story["boards"]]
    assert not timing_summary(studio.story, facts=facts).build_allowed


def test_the_planner_assembles_each_legacy_board_from_its_own_takes():
    """Every take is recorded with its signature, so the plan reuses them all; the board's
    current version is not ``current`` (no track) and no other version is the input."""
    studio = legacy_r4()
    for board in spoken(studio):
        plan = plan_board_voice(studio.story, board["id"], studio.library)
        assert (plan.action, plan.version_id, plan.speech_calls) == (ASSEMBLE, None, 0)
        assert {take.from_version_id for take in plan.takes} == {
            board["voice"]["current_version_id"]}


def test_held_legacy_takes_make_a_version_with_a_track_and_no_speech_call():
    studio = held_legacy_r4()
    legacy = legacy_documents(studio)
    before = {b["number"]: studio.current(b["number"]) for b in spoken(studio)}
    studio.generate_all()
    assert studio.calls == 0
    assert len(studio.library.versions) == len(legacy) + len(
        [v for v in studio.library.versions.values() if v.voice is None]) + 8
    for board in spoken(studio):
        old, new = before[board["number"]], studio.current(board["number"])
        assert new.id not in legacy and new.voice.track is not None
        assert [t.sha256 for t in new.voice.takes] == [t.sha256 for t in old.voice.takes]
        assert [t.duration_source for t in new.voice.takes] == ["samples"] * len(old.voice.takes)
        assert new.voice.input_signature == old.voice.input_signature
        assert new.provenance["source_key"] == board_voice_key(board["id"])
        assert new.asset_id != old.asset_id
        assert studio.store.blobs[new.voice.track.locator]  # the assembled track is stored
    # Only the eight tracks were published: a reused take is read, never written again.
    assert [media for _, media in studio.store.published] == [WAV] * 8
    assert {v_id: studio.library.document(v_id) for v_id in legacy} == legacy
    assert queue_problems(studio.story, studio.library) == set()
    summary = timing_summary(studio.story, facts=voice_facts(studio.library, studio.story))
    assert (summary.build_allowed, summary.frames_known) == (True, 1087)
    assert [row.frames for row in summary.boards] == R4_FRAMES
    # A second run makes nothing.
    versions, jobs = len(studio.library.versions), len(studio.jobs)
    for board in spoken(studio):
        outcome = studio.request(board["id"])
        assert (outcome.plan.action, outcome.job) == (CURRENT, None)
    assert (studio.calls, len(studio.library.versions), len(studio.jobs)) == (0, versions, jobs)


def test_only_the_takes_the_store_does_not_hold_are_spoken():
    probe = legacy_r4()
    board_8 = probe.current(8).voice.takes
    board_1 = probe.current(1).voice.takes
    missing = {board_8[1].signature, board_8[4].signature, board_1[0].signature}
    studio = held_legacy_r4(held=lambda signature: signature not in missing)
    legacy = legacy_documents(studio)
    synthesized = {}
    for board in spoken(studio):
        _, run = studio.generate(board["id"])
        assert run.job.status == "succeeded" and run.make_current, run.job.error
        synthesized[board["number"]] = run.synthesized
    assert studio.calls == 3
    assert synthesized == {1: (board_1[0].line_id,), 2: (), 3: (), 4: (), 5: (), 6: (),
                           8: (board_8[1].line_id, board_8[4].line_id), 9: ()}
    for board in spoken(studio):
        assert studio.current(board["number"]).voice.track is not None
    assert {v_id: studio.library.document(v_id) for v_id in legacy} == legacy
    assert queue_problems(studio.story, studio.library) == set()


def test_with_no_take_held_every_line_is_spoken_once():
    """The public library: the legacy takes' bytes are not in the store."""
    studio = legacy_r4()
    legacy = legacy_documents(studio)
    studio.generate_all()
    assert studio.calls == 13
    assert {v_id: studio.library.document(v_id) for v_id in legacy} == legacy
    assert queue_problems(studio.story, studio.library) == set()


def test_held_bytes_with_another_hash_are_refused_before_any_call():
    """A take is reused only after its hash is checked; a ``fetch`` that answers other
    bytes is a store fault, not a take to speak again (proposal). (``studio voice``'s
    ``fetch`` answers None for a blob that does not verify: that is a missing take.)"""
    studio = held_legacy_r4()
    board_id = studio.board(8)["id"]
    plan = plan_board_voice(studio.story, board_id, studio.library)

    def wrong(locator, sha256):
        data = studio.store.fetch(locator, sha256)
        return None if data is None else data + b"\0\0"

    with pytest.raises(ContractError) as refused:
        make_voice(plan.input, board_id, studio.library, speech=studio.client,
                   publish=studio.store.publish, fetch=wrong, by=BY, now=LATER)
    assert [v.rule for v in refused.value.violations] == ["asset.bytes_missing"]
    assert studio.calls == 0 and studio.store.published == []


def test_a_take_of_a_version_with_a_track_must_still_be_held():
    """Story 405's rule is unchanged for a version this worker made: its takes were
    published with it, so one the store lost fails the job (``asset.bytes_missing``)
    and nothing is spoken (proposal: only a legacy take is spoken again)."""
    studio = generated_r4()
    board = studio.board(8)
    take = studio.current(8).voice.takes[2]
    del studio.store.blobs[locator_for(take.sha256, WAV, studio.story["production_id"])]
    board["lines"][2]["gap_before_ms"] = 260
    calls, versions = studio.calls, len(studio.library.versions)
    _, run = studio.generate(board["id"])
    assert (run.job.status, run.job.error.code) == ("failed", "asset.bytes_missing")
    assert (studio.calls, len(studio.library.versions)) == (calls, versions)


@pytest.mark.parametrize("older_held, calls", [(True, 0), (False, 1)], ids=["held", "missing"])
def test_an_unheld_legacy_take_falls_back_to_an_older_one_of_its_signature(older_held, calls):
    """Two versions without a track hold one signature with other bytes; the newer one's
    are not held. Its take leaves the pool, so the older one's is chosen and read in its
    turn: reused when held, else the line is spoken once (never ``bytes_missing``)."""
    signature = legacy_r4().current(1).voice.takes[0].signature
    studio = held_legacy_r4(held=lambda s: older_held or s != signature)
    board_id = studio.board(1)["id"]
    older = studio.current(1)
    minter = Minter(clock=lambda: 1_900_000_000_000, random_bits=lambda: 9)
    asset = dataclasses.replace(studio.library.asset(older.asset_id), id=minter.mint("ast"))
    other = hashlib.sha256(b"bytes no store holds").hexdigest()
    newer = dataclasses.replace(older, id=minter.mint("asv"), asset_id=asset.id,
                                voice=dataclasses.replace(older.voice, takes=(dataclasses.replace(
                                    older.voice.takes[0], sha256=other),)))
    studio.library = Library(
        assets=MappingProxyType({**studio.library.assets, asset.id: asset}),
        versions=MappingProxyType({**studio.library.versions, newer.id: newer}))
    assert [v.id for v in board_voice_versions(studio.library, board_id)] == [newer.id, older.id]
    assert plan_board_voice(studio.story, board_id, studio.library).takes[0].from_version_id \
        == newer.id
    _, run = studio.generate(board_id)
    assert run.job.status == "succeeded", run.job.error
    assert studio.calls == calls and len(run.synthesized) == calls
    # The fake speaks the same WAV for a signature, so a take spoken again has the
    # older take's hash too; what differs is whether a call was made.
    assert run.version.voice.takes[0].sha256 == older.voice.takes[0].sha256 != other


def test_each_held_legacy_take_is_read_once():
    studio = held_legacy_r4()
    board_id = studio.board(8)["id"]
    plan = plan_board_voice(studio.story, board_id, studio.library)
    reads = []

    def counting(locator, sha256):
        reads.append(sha256)
        return studio.store.fetch(locator, sha256)

    made = make_voice(plan.input, board_id, studio.library, speech=studio.client,
                      publish=studio.store.publish, fetch=counting, by=BY, now=LATER)
    assert made.created and made.synthesized == ()
    assert sorted(reads) == sorted(t.sha256 for t in studio.current(8).voice.takes)


def test_a_legacy_board_signed_anew_is_spoken_whatever_is_held():
    """With a recorded model digest no legacy signature matches (VOICE-3): every line of
    the board is spoken, held or not."""
    from haynes_studio.voice import Engine
    studio = held_legacy_r4(engine=Engine(digest="sha256:" + "d" * 64))
    plan = plan_board_voice(studio.story, studio.board(8)["id"], studio.library,
                            engine=studio.engine)
    assert (plan.action, plan.speech_calls) == (SYNTHESIZE, 6)
    _, run = studio.generate(studio.board(8)["id"])
    assert run.job.status == "succeeded" and studio.calls == 6


# ``studio voice`` (story 406's make_story_voices) on a local store ---------------------


def _local(studio, tmp_path, *, drop=()):
    """A local store holding what ``studio``'s memory store holds, except ``drop``."""
    root = tmp_path / "store"
    root.mkdir()
    store = LocalStore(root)
    production = studio.story["production_id"]
    for locator, data in studio.store.blobs.items():
        if hashlib.sha256(data).hexdigest() not in drop:
            blob = store.publish(data, scope=production, media_type=WAV)
            assert blob.locator == locator
    return store


def _voice(story, library, store):
    runner = FakeRunner(FakeKokoro(r4_frames()))
    result = make_story_voices(story, library, store=store, speech=KokoroClient(runner),
                               by=to_document(BY), now=NOW)
    return result, len(runner.calls)


@pytest.mark.parametrize("drop", [0, 2], ids=["all-held", "two-missing"])
def test_studio_voice_makes_an_imported_r4_buildable_in_one_run(tmp_path, drop):
    studio = held_legacy_r4()
    legacy = legacy_documents(studio)
    dropped = [studio.current(8).voice.takes[i] for i in range(drop)]
    store = _local(studio, tmp_path, drop={t.sha256 for t in dropped})
    story = copy.deepcopy(studio.story)
    assert queue_problems(story, studio.library) == stale_everywhere(story)

    result, calls = _voice(story, studio.library, store)
    assert result.ok and calls == drop
    assert [o.action for o in result.outcomes] == ["made"] * 8
    assert {o.board_id: o.synthesized for o in result.outcomes if o.synthesized} == (
        {studio.board(8)["id"]: tuple(t.line_id for t in dropped)} if drop else {})
    for outcome in result.outcomes:
        assert result.library.version(outcome.version_id).voice.track is not None
    assert queue_problems(result.story, result.library) == set()
    assert {v_id: result.library.document(v_id) for v_id in legacy} == legacy
    assert story == studio.story  # the input draft is not changed; the result is new

    again, calls = _voice(result.story, result.library, store)
    assert calls == 0 and [o.action for o in again.outcomes] == ["current"] * 8
    assert again.library.documents() == result.library.documents()
    assert again.story == result.story
