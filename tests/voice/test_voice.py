"""The board voice end to end, with the Kokoro client of story 425 behind ``FakeRunner``
and an in-memory store: what each edit costs in speech calls, measured durations and
offsets, the stale-result rule (VOICE-4), idempotent requests, stock voices only, and
the facts that time a story and let ``queue_run`` accept it (VOICE-5, VOICE-6). No
service is called."""

from __future__ import annotations

import copy
import dataclasses
import io
import json
import math
import wave

import pytest

from haynes_studio.adapters.fakes import FailingRunner
from haynes_studio.adapters.kokoro import KokoroClient
from haynes_studio.canonical import timing_summary, validate_story
from haynes_studio.errors import ContractError, blocking
from haynes_studio.library import Library, import_version
from haynes_studio.library.model import measured_ms
from haynes_studio.voice import (
    ASSEMBLE,
    CURRENT,
    EXISTING,
    SYNTHESIZE,
    Engine,
    board_voice_versions,
    cancel,
    make_voice,
    plan_board_voice,
    run_voice_job,
    voice_facts,
    with_current_voice,
)
from haynes_studio.voice.plan import board_voice_key
from tests.canonical.fixtures import EXAMPLES
from tests.library.fixtures import BY
from tests.voice.fixtures import (
    LATER,
    RATE,
    fresh_r4,
    generated_r4,
    legacy_r4,
    r4_frames,
    r4_speech,
)

R4_FRAMES = [153, 94, 146, 84, 83, 122, 46, 251, 108]
DIGEST = "sha256:" + "d" * 64


def spoken(studio):
    return [board for board in studio.story["boards"] if board["lines"]]


def queue_problems(studio, jobs=()):
    """The draft's ``queue_run`` problems (derived blocks are the server's, so dropped)."""
    draft = {key: value for key, value in studio.story.items() if key != "derived"}
    draft["boards"] = [{k: v for k, v in board.items() if k != "derived"}
                       for board in studio.story["boards"]]
    return {(v.rule, v.path) for v in blocking(validate_story(
        draft, context="queue_run", facts=voice_facts(studio.library, studio.story, jobs)))}


def plans(studio, engine=Engine()):
    return {board["number"]: plan_board_voice(studio.story, board["id"], studio.library,
                                              engine=engine) for board in spoken(studio)}


# The Winter Menu r4 ----------------------------------------------------------------------


@pytest.mark.parametrize("extra", [0, 11], ids=["exact", "longest-same-duration_s"])
def test_r4_from_matching_takes_is_timed_at_1087_frames(extra):
    """Takes whose sample counts round to the recorded duration_s give durations within
    1 ms of it, and the story is timed at the recorded 1087 frames and can be built."""
    studio = fresh_r4(r4_frames(extra))
    assert timing_summary(studio.story, facts=voice_facts(studio.library, studio.story)).complete is False
    studio.generate_all()
    recorded = {(line["voice"], line["text"]): line["duration_s"] for line in r4_speech()["lines"]}
    measured = 0
    for board in spoken(studio):
        version = studio.current(board["number"])
        for take in version.voice.takes:
            measured += 1
            assert round(take.samples / take.sample_rate, 3) == recorded[(take.voice_id, take.text)]
            assert isinstance(take.duration_ms, int) and take.duration_source == "samples"
            assert take.duration_ms == math.ceil(take.samples * 1000 / take.sample_rate)  # TIME-1
            assert 0 <= take.duration_ms - round(recorded[(take.voice_id, take.text)] * 1000) <= 1
            assert take.duration_ms - round(recorded[(take.voice_id, take.text)] * 1000) == (extra > 0)
    assert measured == len(r4_speech()["lines"]) == studio.calls == 13
    summary = timing_summary(studio.story, facts=voice_facts(studio.library, studio.story))
    assert (summary.complete, summary.frames_known, summary.build_allowed) == (True, 1087, True)
    assert [row.frames for row in summary.boards] == R4_FRAMES
    assert queue_problems(studio) == set()


def test_r4_board_8_offsets_and_track_are_exact_samples():
    """The contract's worked example: B 1900-2903, A 3203-4014, C 4214-5089, D 5339-5851,
    B 6551-7575, B 8475-9627, from sample counts; the track holds each take's samples at
    offset_ms * 24."""
    studio = generated_r4()
    voice = studio.current(8).voice
    spans = [(take.speaker, take.offset_ms, take.offset_ms + take.duration_ms) for take in voice.takes]
    assert spans == [("b", 1900, 2903), ("a", 3203, 4014), ("c", 4214, 5089), ("d", 5339, 5851),
                     ("b", 6551, 7575), ("b", 8475, 9627)]
    assert [take.samples for take in voice.takes] == [24072, 19464, 21000, 12288, 24576, 27648]
    assert (voice.lead_ms, voice.gaps_ms, voice.speech_end_ms) == (1900, (300, 200, 250, 700, 900), 9627)
    track = studio.store.blobs[voice.track.locator]
    with wave.open(io.BytesIO(track), "rb") as reader:
        assert (reader.getframerate(), reader.getnchannels(), reader.getsampwidth()) == (RATE, 1, 2)
        assert reader.getnframes() == 9627 * 24
        pcm = reader.readframes(reader.getnframes())
    cursor = 0
    for take in voice.takes:
        start = take.offset_ms * 24
        assert pcm[cursor * 2:start * 2] == bytes((start - cursor) * 2)  # silence between
        data = studio.store.blobs[next(loc for loc in studio.store.blobs if take.sha256 in loc)]
        with wave.open(io.BytesIO(data), "rb") as reader:
            assert pcm[start * 2:(start + take.samples) * 2] == reader.readframes(take.samples)
        cursor = start + take.samples
    assert voice.track.bytes == len(track) and voice.track.media_type == "audio/wav"


def test_r4_board_8_signs_as_the_contract_example():
    """With the model name standing in for the digest (VOICE-3), a generated board 8
    has the take and input signatures of the contract's board voice example."""
    example = json.loads((EXAMPLES / "valid" / "asset-version-board-voice.json").read_text())
    voice = generated_r4().current(8).voice
    assert voice.input_signature == example["voice"]["input_signature"]
    assert [t.signature for t in voice.takes] == [t["signature"] for t in example["voice"]["takes"]]


def test_the_legacy_r4_library_is_current_and_needs_no_call():
    studio = legacy_r4()
    assert {number: plan.action for number, plan in plans(studio).items()} == dict.fromkeys(
        [1, 2, 3, 4, 5, 6, 8, 9], CURRENT)
    for board in spoken(studio):
        assert studio.request(board["id"]).job is None
    assert studio.calls == 0 and studio.jobs == []


# What each edit costs ----------------------------------------------------------------------


def test_an_unchanged_board_makes_no_call_and_no_version():
    studio = generated_r4()
    calls, versions = studio.calls, len(studio.library.versions)
    for number, plan in plans(studio).items():
        assert (plan.action, plan.speech_calls) == (CURRENT, 0), number
        outcome = studio.request(studio.board(number)["id"])
        assert (outcome.job, outcome.created, outcome.make_current) == (None, False, None)
    assert (studio.calls, len(studio.library.versions)) == (calls, versions)


def test_editing_one_board_regenerates_only_that_board_and_only_its_changed_takes():
    studio = generated_r4()
    before = {board["number"]: board["voice"]["current_version_id"] for board in spoken(studio)}
    old_takes = studio.current(8).voice.takes
    edited = studio.board(8)["lines"][3]
    edited["text"] = "Nay, and again nay!"
    actions = {number: (plan.action, plan.speech_lines) for number, plan in plans(studio).items()}
    assert actions.pop(8) == (SYNTHESIZE, (edited["id"],))
    assert set(actions.values()) == {(CURRENT, ())}
    calls = studio.calls
    outcome, run = studio.generate(studio.board(8)["id"])
    assert studio.calls == calls + 1 and run.synthesized == (edited["id"],)
    assert run.job.result_is_current is True and run.created
    new_takes = studio.current(8).voice.takes
    assert [t.sha256 == o.sha256 for t, o in zip(new_takes, old_takes)] == [True, True, True,
                                                                           False, True, True]
    after = {board["number"]: board["voice"]["current_version_id"] for board in spoken(studio)}
    assert {n for n in after if after[n] != before[n]} == {8}
    assert studio.current(8).number == 2  # the next version of the same asset
    assert timing_summary(studio.story, facts=voice_facts(studio.library, studio.story)).complete


@pytest.mark.parametrize("edit", ["lead", "gap", "both"])
def test_a_lead_or_gap_edit_makes_no_speech_call(edit):
    studio = generated_r4()
    board = studio.board(8)
    old = studio.current(8)
    if edit in ("lead", "both"):
        board["timing"]["lead_ms"] = 1500
    if edit in ("gap", "both"):
        board["lines"][4]["gap_before_ms"] = 400
    plan = plan_board_voice(studio.story, board["id"], studio.library)
    assert (plan.action, plan.speech_calls) == (ASSEMBLE, 0)
    calls, fetched = studio.calls, len(studio.store.fetched)
    outcome, run = studio.generate(board["id"])
    assert studio.calls == calls and run.synthesized == ()
    assert len(studio.store.fetched) - fetched == 6  # every take read back by hash
    new = studio.current(8)
    assert new.id != old.id and run.job.result_is_current
    assert [t.sha256 for t in new.voice.takes] == [t.sha256 for t in old.voice.takes]
    assert new.voice.track.sha256 != old.voice.track.sha256
    lead = 1500 if edit in ("lead", "both") else 1900
    assert new.voice.takes[0].offset_ms == lead
    assert new.voice.input_signature != old.voice.input_signature


def test_a_take_is_reused_by_signature_whichever_line_held_it():
    """Board 8's first "Aye." moves from A (bf_emma) to C (af_nicole): C's own "Aye."
    take already has that signature, so no call is made."""
    studio = generated_r4()
    board = studio.board(8)
    board["lines"][1]["speaker"] = "c"
    plan = plan_board_voice(studio.story, board["id"], studio.library)
    assert (plan.action, plan.speech_calls) == (ASSEMBLE, 0)
    calls = studio.calls
    studio.generate(board["id"])
    takes = studio.current(8).voice.takes
    assert studio.calls == calls and takes[1].sha256 == takes[2].sha256


def test_a_cast_voice_change_resynthesizes_that_speakers_takes_only():
    studio = generated_r4()
    voices = {asset.attributes.get("voice_id"): version.id
              for version in studio.library.versions.values() if version.kind == "voice"
              for asset in [studio.library.asset_of(version.id)]}
    studio.story["cast"][1]["voice_version_id"] = voices["bf_emma"]  # slot b: af_heart -> bf_emma
    actions = {number: plan.action for number, plan in plans(studio).items()}
    b_boards = {b["number"] for b in spoken(studio) if any(l["speaker"] == "b" for l in b["lines"])}
    assert {n for n, action in actions.items() if action != CURRENT} == b_boards == {2, 8, 9}
    plan = plan_board_voice(studio.story, studio.board(8)["id"], studio.library)
    assert plan.speech_lines == tuple(l["id"] for l in studio.board(8)["lines"] if l["speaker"] == "b")


# VOICE-4: jobs that finish late, and idempotent requests ---------------------------------


def test_a_job_that_finishes_after_its_board_changed_is_kept_stale():
    studio = generated_r4()
    board_id = studio.board(8)["id"]
    old = studio.current(8)
    studio.board(8)["lines"][3]["text"] = "Nay, and again nay!"
    outcome = studio.request(board_id)
    assert outcome.created and outcome.job.status == "queued"
    assert queue_problems(studio, studio.jobs) >= {("asset.generating", "/boards/7/voice")}
    studio.board(8)["lines"][5]["text"] = "Bibs on, everyone."  # edited while the job runs
    run = studio.run(outcome.job, now=LATER)
    assert (run.job.status, run.job.result_is_current, run.created) == ("succeeded", False, True)
    assert studio.board(8)["voice"]["current_version_id"] == old.id  # the old voice stays
    assert run.version.id in {v.id for v in board_voice_versions(studio.library, board_id)}  # kept
    assert run.version.voice.input_signature == outcome.job.input_signature
    assert queue_problems(studio, studio.jobs) == {("voice.stale", "/boards/7/voice/current_version_id")}
    # The next job reuses the stale version's new take: only the latest edit is spoken.
    calls = studio.calls
    plan = plan_board_voice(studio.story, board_id, studio.library)
    assert plan.speech_lines == (studio.board(8)["lines"][5]["id"],)
    assert plan.takes[3].from_version_id == run.version.id
    _, second = studio.generate(board_id)
    assert studio.calls == calls + 1 and second.job.result_is_current
    assert queue_problems(studio, studio.jobs) == set()


def test_a_cancelled_job_is_refused_before_anything_runs():
    studio = fresh_r4()
    outcome = studio.request(studio.board(1)["id"])
    with pytest.raises(ContractError) as caught:
        studio.run(cancel(outcome.job, now=LATER))
    assert {v.rule for v in caught.value.violations} == {"job.transition"}
    assert studio.calls == 0 and studio.store.published == []


def test_a_job_whose_board_was_removed_or_silenced_is_not_current():
    studio = fresh_r4()
    board = studio.board(9)
    outcome = studio.request(board["id"])
    silent = {**studio.story, "boards": [b for b in studio.story["boards"] if b["id"] != board["id"]],
              "board_order": [i for i in studio.story["board_order"] if i != board["id"]]}
    run = studio.run(outcome.job, draft=lambda: silent)
    assert (run.job.status, run.job.result_is_current) == ("succeeded", False)
    assert studio.board(9)["voice"]["current_version_id"] is None


def test_a_second_identical_request_creates_nothing():
    studio = fresh_r4()
    board_id = studio.board(8)["id"]
    first = studio.request(board_id)
    again = studio.request(board_id)  # while the first is in flight
    assert first.created and not again.created and again.job == first.job and len(studio.jobs) == 1
    run = studio.run(first.job)
    versions, calls = len(studio.library.versions), studio.calls
    after = studio.request(board_id)  # once it is current
    assert (after.plan.action, after.job, after.created) == (CURRENT, None, False)
    # Making the same input again finds the version: no call, no publication, no version.
    published = len(studio.store.published)
    made = make_voice(first.job.voice, board_id, studio.library, speech=studio.client,
                      publish=studio.store.publish, fetch=studio.store.fetch, by=BY, now=LATER)
    assert (made.created, made.version.id) == (False, run.version.id)
    assert (studio.calls, len(studio.library.versions), len(studio.store.published)) == (
        calls, versions, published)


def test_undoing_an_edit_points_back_at_the_existing_version():
    studio = generated_r4()
    board = studio.board(8)
    old = studio.current(8)
    text = board["lines"][0]["text"]
    board["lines"][0]["text"] = "All opposed?"
    studio.generate(board["id"])
    assert studio.current(8).id != old.id
    board = studio.board(8)
    board["lines"][0]["text"] = text  # undo
    calls, versions = studio.calls, len(studio.library.versions)
    outcome = studio.request(board["id"])
    assert (outcome.plan.action, outcome.job, outcome.make_current) == (EXISTING, None, old.id)
    assert studio.current(8).id == old.id
    assert (studio.calls, len(studio.library.versions)) == (calls, versions)


# Stock voices only (VOICE-1) ------------------------------------------------------------


def _replace_voice(studio, slot, **asset_changes):
    version_id = next(m["voice_version_id"] for m in studio.story["cast"] if m["slot"] == slot)
    library = studio.library
    asset = library.asset_of(version_id)
    changed = dataclasses.replace(asset, **asset_changes)
    studio.library = Library.build([changed if a.id == asset.id else a for a in library.assets.values()],
                                   library.versions.values())


def test_a_non_stock_voice_is_refused_before_any_call():
    studio = fresh_r4()
    _replace_voice(studio, "a", attributes={"voice_id": "af_someone_real", "stock": True})
    with pytest.raises(ContractError) as caught:
        studio.request(studio.board(8)["id"])
    assert "voice.not_stock" in {v.rule for v in caught.value.violations}
    assert studio.calls == 0 and studio.jobs == []
    # Boards without that speaker are unaffected.
    assert studio.request(studio.board(2)["id"]).created


def test_a_cloned_voice_is_refused():
    studio = fresh_r4()
    version_id = studio.story["cast"][0]["voice_version_id"]
    version = studio.library.version(version_id)
    generator = {**version.provenance["generator"], "source_sample_sha256": "e" * 64}
    clone = dataclasses.replace(version, provenance={**version.provenance, "generator": generator})
    studio.library = Library.build(studio.library.assets.values(),
                                   [clone if v.id == version_id else v
                                    for v in studio.library.versions.values()])
    with pytest.raises(ContractError) as caught:
        studio.request(studio.board(1)["id"])
    assert {v.rule for v in caught.value.violations} == {"voice.not_stock"}
    assert studio.calls == 0


def test_a_voice_of_another_model_is_refused():
    studio = fresh_r4(engine=Engine(model="Another-TTS 2"))
    with pytest.raises(ContractError) as caught:
        studio.request(studio.board(1)["id"])
    assert {v.rule for v in caught.value.violations} == {"voice.not_stock"}


def test_a_cast_entry_that_is_not_a_voice_is_refused():
    studio = fresh_r4()
    still = next(v.id for v in studio.library.versions.values() if v.kind == "cast")
    studio.story["cast"][0]["voice_version_id"] = still
    with pytest.raises(ContractError) as caught:
        studio.request(studio.board(1)["id"])
    assert {v.rule for v in caught.value.violations} == {"asset.kind_mismatch"}


def test_a_silent_board_and_an_unknown_board_need_no_voice():
    studio = fresh_r4()
    with pytest.raises(ContractError) as caught:
        studio.request(studio.board(7)["id"])
    assert {v.rule for v in caught.value.violations} == {"voice.not_needed"}
    with pytest.raises(ContractError) as caught:
        studio.request("brd_01M79V9FC0000000000000000Z")
    assert {v.rule for v in caught.value.violations} == {"ref.unknown"}


def test_a_speaker_outside_the_cast_is_story_404s_rule():
    studio = fresh_r4()
    studio.board(1)["lines"][0]["speaker"] = "narrator"
    with pytest.raises(ContractError) as caught:
        studio.request(studio.board(1)["id"])
    assert "voice.speaker_not_in_cast" in {v.rule for v in caught.value.violations}


# Failures and legacy takes ------------------------------------------------------------------


def test_a_failing_speech_service_fails_the_job_and_creates_nothing():
    studio = fresh_r4()
    outcome = studio.request(studio.board(1)["id"])
    library = studio.library
    run = run_voice_job(outcome.job, library, draft=lambda: studio.story,
                        speech=KokoroClient(FailingRunner(1, b"boom")),
                        publish=studio.store.publish, fetch=studio.store.fetch, by=BY, now=LATER)
    assert (run.job.status, run.job.error.code, run.version) == ("failed", "adapter.command_failed", None)
    assert run.library is library and studio.store.published == []


def test_a_gap_edit_on_a_legacy_board_needs_its_takes_bytes():
    """The legacy takes are reusable by signature, so the edit needs no speech call;
    their bytes are not public, so the job fails before any call and makes nothing."""
    studio = legacy_r4()
    board = studio.board(8)
    old = board["voice"]["current_version_id"]
    board["lines"][2]["gap_before_ms"] = 260
    plan = plan_board_voice(studio.story, board["id"], studio.library)
    assert (plan.action, plan.speech_calls) == (ASSEMBLE, 0)
    assert {take.from_version_id for take in plan.takes} == {old}
    versions = len(studio.library.versions)
    _, run = studio.generate(board["id"])
    assert (run.job.status, run.job.error.code) == ("failed", "asset.bytes_missing")
    assert (studio.calls, len(studio.library.versions)) == (0, versions)
    assert studio.board(8)["voice"]["current_version_id"] == old


def test_with_a_recorded_model_digest_takes_are_signed_anew():
    """VOICE-3: legacy takes were signed with the model name. Once a digest is recorded
    every take signs differently, so a request re-synthesizes (the library's facts still
    time the legacy board: they compare lines, speakers, voices, lead and gaps)."""
    studio = legacy_r4(engine=Engine(digest=DIGEST))
    plan = plan_board_voice(studio.story, studio.board(8)["id"], studio.library, engine=studio.engine)
    assert (plan.action, plan.speech_calls) == (SYNTHESIZE, 6)
    assert plan.input.engine == DIGEST
    _, run = studio.generate(studio.board(8)["id"])
    assert run.job.result_is_current and studio.calls == 6
    generator = run.version.provenance["generator"]
    assert generator["files_sha256"] == {"model": "d" * 64}
    assert {take.engine for take in run.version.voice.takes} == {DIGEST}


def test_a_job_for_another_engine_fails():
    studio = fresh_r4()
    outcome = studio.request(studio.board(1)["id"])
    studio.engine = Engine(digest=DIGEST)
    run = studio.run(outcome.job)
    assert (run.job.status, run.job.error.code) == ("failed", "voice.engine_mismatch")


@pytest.mark.parametrize("answer, rule", [
    (lambda sha256, locator: ("0" * 64, locator), "store.hash_mismatch"),
    (lambda sha256, locator: (sha256, locator.replace("productions/", "library/x/")),
     "store.locator_invalid"),
])
def test_a_store_that_answers_wrongly_fails_the_job(answer, rule):
    studio = fresh_r4()
    publish = studio.store.publish
    studio.store.publish = lambda data, media: answer(*publish(data, media))
    _, run = studio.generate(studio.board(1)["id"])
    assert (run.job.status, run.job.error.code) == ("failed", rule)


# Records the library keeps ------------------------------------------------------------------


def test_a_generated_version_is_a_valid_board_voice_record():
    studio = generated_r4()
    version = studio.current(8)
    asset = studio.library.asset_of(version.id)
    assert (version.kind, version.state, version.capabilities, version.content) == (
        "board_voice", "board", ("board_voice",), None)
    assert (asset.scope.board_id, asset.scope.story_id) == (studio.board(8)["id"], studio.story["id"])
    assert version.source_key == board_voice_key(studio.board(8)["id"])
    assert version.origin == "generated" and version.licence.commercial_use == "unknown"
    generator = version.provenance["generator"]
    assert list(generator["source_asset_version_ids"]) == sorted(
        {m["voice_version_id"] for m in studio.story["cast"]})
    assert all(take.duration_ms == measured_ms(take.samples, take.sample_rate)
               for take in version.voice.takes)
    assert studio.library.pin(version.id).startswith("sha256:")
    assert [v.id for v in board_voice_versions(studio.library, studio.board(8)["id"])] == [version.id]


def test_versions_are_never_overwritten():
    studio = generated_r4()
    board_id = studio.board(8)["id"]
    first = studio.current(8)
    snapshot = studio.library.document(first.id)
    for text in ("All opposed?", "All in favour?", "All in favor?"):
        studio.board(8)["lines"][0]["text"] = text
        studio.generate(board_id)
    numbers = [v.number for v in board_voice_versions(studio.library, board_id)]
    assert sorted(numbers) == [1, 2, 3]  # the last text was version 1 again: no new version
    assert studio.current(8).id == first.id
    assert studio.library.document(first.id) == snapshot


# Review follow-ups ---------------------------------------------------------------------------


def test_a_line_readded_with_the_same_text_is_assembled_and_current():
    """Same take signatures and bytes, new line ID: the library's pin is the same, so the
    version goes to the board's lines-keyed asset instead of failing."""
    studio = generated_r4()
    board = studio.board(8)
    board["lines"][0]["id"] = "lin_01MCC5RM00000000000000ZZZZ"
    plan = plan_board_voice(studio.story, board["id"], studio.library)
    assert (plan.action, plan.speech_calls) == (ASSEMBLE, 0)
    outcome, run = studio.generate(board["id"])
    assert (run.job.status, run.job.result_is_current, run.created) == ("succeeded", True, True)
    assert run.version.source_key.startswith(board_voice_key(board["id"]) + ":lines:")
    assert studio.calls == 13 and queue_problems(studio) == set()
    assert studio.request(board["id"]).plan.action == CURRENT


def test_a_cast_voice_version_of_the_same_stock_voice_is_assembled():
    """A second ``voice`` version of af_heart (another asset, as story 382 keys stock
    voices per legacy job): slot b's takes keep their signatures and bytes."""
    studio = generated_r4()
    slot_b = studio.story["cast"][1]["voice_version_id"]
    request = dataclasses.replace(
        _voice_request(studio, slot_b),
        provenance={**studio.library.version(slot_b).provenance, "source_key": "test:voice:af_heart"})
    outcome = import_version(studio.library, request, by=BY, now=LATER)
    assert outcome.created and outcome.version.id != slot_b
    studio.library = outcome.library
    studio.story["cast"][1]["voice_version_id"] = outcome.version.id
    for number in (2, 8, 9):
        plan = plan_board_voice(studio.story, studio.board(number)["id"], studio.library)
        assert (plan.action, plan.speech_calls) == (ASSEMBLE, 0), number
        _, run = studio.generate(studio.board(number)["id"])
        assert run.job.result_is_current, (number, run.job.error)
        assert ":lines:" in run.version.source_key  # the pin was taken on the board's asset
    assert studio.calls == 13 and queue_problems(studio) == set()


def _voice_request(studio, version_id):
    from haynes_studio.library.library import VersionRequest

    version = studio.library.version(version_id)
    asset = studio.library.asset_of(version_id)
    return VersionRequest(kind="voice", name=asset.name, scope=asset.scope,
                          capabilities=version.capabilities, content=None,
                          provenance=version.provenance, licence=version.licence,
                          labels=asset.labels, attributes=asset.attributes)


def test_two_lines_with_one_new_signature_cost_one_call():
    studio = generated_r4()
    board = studio.board(8)
    board["lines"][4]["text"] = board["lines"][5]["text"] = "Order, order!"
    plan = plan_board_voice(studio.story, board["id"], studio.library)
    assert plan.speech_lines == (board["lines"][4]["id"],)
    assert plan.takes[5].same_as == board["lines"][4]["id"]
    calls = studio.calls
    _, run = studio.generate(board["id"])
    takes = run.version.voice.takes
    assert studio.calls == calls + 1 and takes[4].sha256 == takes[5].sha256
    assert run.synthesized == (board["lines"][4]["id"],)


@pytest.mark.parametrize("text", ["x" * 1001, "   "], ids=["too-long", "blank"])
def test_a_line_the_speech_client_would_refuse_is_refused_at_request(text):
    studio = fresh_r4()
    studio.board(1)["lines"][0]["text"] = text
    with pytest.raises(ContractError) as caught:
        studio.request(studio.board(1)["id"])
    assert {(v.rule, v.path) for v in caught.value.violations} == {
        ("voice.request_invalid", "/boards/0/lines/0/text")}
    assert studio.jobs == [] and studio.calls == 0


def test_a_hand_made_job_with_a_non_stock_voice_is_refused_before_any_call():
    studio = fresh_r4()
    job = studio.request(studio.board(1)["id"]).job
    line = dataclasses.replace(job.voice.lines[0], voice_id="af_someone_real")
    forged = dataclasses.replace(job, voice=dataclasses.replace(job.voice, lines=(line,)))
    with pytest.raises(ContractError) as caught:
        studio.run(forged)
    assert "voice.not_stock" in {v.rule for v in caught.value.violations}
    assert studio.calls == 0


def test_an_in_flight_job_for_other_lines_is_not_the_same_request():
    studio = generated_r4()
    board = studio.board(8)
    board["lines"][0]["text"] = "All opposed?"
    first = studio.request(board["id"])
    board["lines"][0]["id"] = "lin_01MCC5RM00000000000000ZZZZ"  # same signature, other line
    second = studio.request(board["id"])
    assert first.created and second.created and second.job.id != first.job.id


def test_a_take_in_another_format_stops_before_the_next_call():
    from haynes_studio.adapters.fakes import synthetic_wav
    from haynes_studio.adapters.kokoro import SpeechTake

    class Shifting:
        calls = 0

        def synthesize(self, request):
            Shifting.calls += 1
            wav = synthetic_wav(4800, rate=24000 if Shifting.calls == 1 else 22050)
            return SpeechTake(wav, "0" * 64, 1, 2, 24000, 4800)

    studio = fresh_r4()
    studio.client = Shifting()
    _, run = studio.generate(studio.board(8)["id"])
    assert (run.job.status, run.job.error.code) == ("failed", "voice.format_mismatch")
    assert Shifting.calls == 2  # of six lines


def test_a_board_silenced_while_its_job_ran_keeps_the_result_stale():
    studio = fresh_r4()
    board = studio.board(9)
    outcome = studio.request(board["id"])
    silent = copy.deepcopy(studio.story)
    target = next(b for b in silent["boards"] if b["id"] == board["id"])
    target.update(lines=[], voice={"style": None, "current_version_id": None},
                  timing={"lead_ms": None, "tail_ms": None, "hold_ms": 1000})
    target["method"]["motion"] = "i2v"
    run = studio.run(outcome.job, draft=lambda: silent)
    assert (run.job.status, run.job.result_is_current, run.created) == ("succeeded", False, True)
    with pytest.raises(ContractError) as caught:
        with_current_voice(silent, board["id"], run.version.id)
    assert {v.rule for v in caught.value.violations} == {"voice.not_needed"}
