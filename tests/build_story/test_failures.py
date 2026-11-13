"""Every way a build stops (story 406's failure table): each ends the run ``failed``
with its code, its board where it has one, and its stage, never ``succeeded``, and
delivers nothing. Completed stages stay for the next run."""

from __future__ import annotations

import copy

import pytest

import haynes_studio.build.pipeline as pipeline
from haynes_studio.build import BuildError, ClipSources, RunRecords, offline_sources
from haynes_studio.delivery import read_delivery
from haynes_studio.delivery.errors import NOT_VERIFIED, PROXY_INVALID, DeliveryError
from haynes_studio.layered import FakeS2VSource
from haynes_studio.store import StoreError
from haynes_studio.store.errors import COLLISION, HASH_MISMATCH
from haynes_studio.voice import Engine
from haynes_studio.wholeframe.fake import FakeClipSource
from tests.build_story import fixtures as f


def assert_failed(world, result, code, board=None, stage=None):
    run = result.run
    assert run["status"] == "failed", run.get("error")
    assert run["error"]["code"] == code, run["error"]
    if board is not None:
        assert run["error"]["board_id"] == board
    if stage is not None:
        assert run["error"]["stage"] == stage
    assert run["delivery_id"] is None and run["outputs"] is None
    assert read_delivery(world.store, production_id=f.PRODUCTION, run_id=run["id"]) is None
    assert [t["to"] for t in run["transitions"]] == ["queued", "running", "failed"]
    assert RunRecords(world.store, f.PRODUCTION).latest(run["id"])["status"] == "failed"
    return run


def test_a_failed_clip_fails_the_run_on_its_board(world, voiced, first):
    document, library = voiced
    edited = copy.deepcopy(document)
    f.board_of(edited, f.B1)["seeds"]["s2v:a"] = 12  # a re-roll: a new clip is asked for
    bad = ClipSources(s2v=FakeS2VSource(draw=f.s2v_draw, extra=4, seed=999), i2v=FakeClipSource())
    run = assert_failed(world, f.build(world, edited, library, source=bad), "layered.clip_invalid",
                        board=f.B1, stage="s2v_clip")
    assert run["error"]["board_number"] == 1


def test_a_refused_method_fails_the_run_before_any_clip(world, voiced, first):
    document, library = voiced
    edited = copy.deepcopy(document)
    f.board_of(edited, f.B1)["method"] = {"layer": "whole_frame", "motion": "s2v"}  # saved with a warning
    sources = f.sources()
    run = assert_failed(world, f.build(world, edited, library, source=sources), "method.unavailable",
                        board=f.B1, stage="prebuild")
    assert sources.s2v.calls == [] and sources.i2v.calls == []
    assert run["error"]["problems"][0]["board_id"] == f.B1


def test_a_missing_voice_fails_the_run(world, voiced, first):
    _, library = voiced
    sources = f.sources()
    run = assert_failed(world, f.build(world, f.story_document(), library, source=sources),
                        "voice.absent", board=f.B1, stage="prebuild")
    assert sources.s2v.calls == []
    assert run["snapshot"]["sha256"]  # the run still pins what it was asked to build


def test_a_stale_voice_fails_the_run(world, voiced, first):
    document, library = voiced
    edited = copy.deepcopy(document)
    f.board_of(edited, f.B1)["lines"][0]["text"] = "Go, team three."  # not voiced again
    assert_failed(world, f.build(world, edited, library), "voice.stale", board=f.B1, stage="prebuild")


def test_a_voice_signed_with_another_engine_is_stale(world, first, tmp_path):
    # VOICE-9 (story 849): the check names the current engine, so takes signed with
    # another (here, a recorded model digest) are stale until voiced again.
    client, _ = f.kokoro()
    other = Engine(digest="sha256:" + "ab" * 32)
    made = f.make_story_voices(f.story_document(), world.library(), store=world.store,
                               speech=client, by=f.OPERATOR, now=f.NOW, engine=other)
    assert made.ok
    assert_failed(world, f.build(world, made.story, made.library), "voice.stale", board=f.B1,
                  stage="prebuild")


def test_a_failed_check_fails_the_run_and_delivers_nothing(world, voiced, first):
    document, library = voiced
    edited = copy.deepcopy(document)
    f.board_of(edited, f.B3)["seeds"]["i2v:frame"] = 34  # a new master, never checked
    run = assert_failed(world, f.build(world, edited, library, heard="stop team two"),
                        "build.check_failed", stage="checks")
    assert "master.transcript" in run["error"]["message"]
    transcript = next(c for c in run["checks"] if c["check"] == "master.transcript")
    assert transcript["result"] == "fail"
    assert run["stages"]  # what was made is recorded, and stays cached


def test_a_failed_delivery_fails_the_run(world, voiced, first, monkeypatch):
    document, library = voiced

    def refuse(*args, **kwargs):
        raise DeliveryError(PROXY_INVALID, "the proxy made from the master failed its checks")
    monkeypatch.setattr(pipeline, "deliver", refuse)
    run = assert_failed(world, f.build(world, document, library), PROXY_INVALID, stage="delivery")
    assert all(c["result"] != "fail" for c in run["checks"])


def test_a_delivery_that_does_not_read_back_fails_the_run(world, voiced, first, monkeypatch):
    document, library = voiced
    monkeypatch.setattr(pipeline, "read_delivery", lambda *args, **kwargs: None)
    result = f.build(world, document, library)
    assert result.run["status"] == "failed"
    assert result.run["error"]["code"] == "build.delivery_unverified"
    # deliver returned, so its delivery is published: the failed run names it.
    published = read_delivery(world.store, production_id=f.PRODUCTION, run_id=result.run["id"])
    assert published is not None and result.run["delivery_id"] == published.id
    assert published.id in result.run["error"]["message"]


def test_a_delivery_whose_read_back_raises_is_named_on_the_failed_run(world, voiced, first,
                                                                      monkeypatch):
    # Review finding 2: the read-back raises (a blob that does not re-hash), and the
    # delivery deliver returned is still named, found without that read.
    document, library = voiced

    def damaged(*args, **kwargs):
        raise StoreError(HASH_MISMATCH, "output 'master' of the completed stage is mismatch")
    monkeypatch.setattr(pipeline, "read_delivery", damaged)
    run = f.build(world, document, library).run
    assert run["status"] == "failed" and run["error"]["code"] == HASH_MISMATCH
    assert run["error"]["stage"] == "delivery"
    published = read_delivery(world.store, production_id=f.PRODUCTION, run_id=run["id"])
    assert published is not None and run["delivery_id"] == published.id
    assert published.id in run["error"]["message"]
    stored = RunRecords(world.store, f.PRODUCTION).latest(run["id"])
    assert stored["status"] == "failed" and stored["delivery_id"] == published.id


def test_a_delivery_stage_left_by_a_failed_deliver_is_named_from_its_own_record(
        world, voiced, first, monkeypatch):
    # deliver raised after its stage completed, and the stage does not read back: the
    # delivery is named from the stage's own document, not from the read that failed.
    document, library = voiced
    real = pipeline.deliver

    def published_then_failed(*args, **kwargs):
        real(*args, **kwargs)
        raise DeliveryError(NOT_VERIFIED, "the published proxy did not re-hash")

    def damaged(*args, **kwargs):
        raise StoreError(HASH_MISMATCH, "output 'proxy' of the completed stage is mismatch")
    monkeypatch.setattr(pipeline, "deliver", published_then_failed)
    monkeypatch.setattr(pipeline, "read_delivery", damaged)
    run = f.build(world, document, library).run
    assert run["status"] == "failed" and run["error"]["code"] == NOT_VERIFIED
    published = read_delivery(world.store, production_id=f.PRODUCTION, run_id=run["id"])
    assert published is not None and run["delivery_id"] == published.id
    assert published.id in run["error"]["message"]


def refuse_failure_writes(monkeypatch, error: Exception) -> None:
    """Every write of a ``failed`` run raises ``error`` (the store, or another writer)."""
    real = RunRecords.write

    def write(self, run):
        if run["status"] == "failed":
            raise error
        return real(self, run)
    monkeypatch.setattr(RunRecords, "write", write)


def test_a_failure_the_store_cannot_record_names_the_run_and_its_delivery(world, voiced, first,
                                                                        monkeypatch):
    # Review finding 2: a store error writing the failure is neither a quiet return nor
    # an unrelated exception: the build raises build.run_unrecorded naming both.
    document, library = voiced
    monkeypatch.setattr(pipeline, "read_delivery", lambda *args, **kwargs: None)
    refuse_failure_writes(monkeypatch, StoreError(COLLISION, "another record holds that version"))
    with pytest.raises(BuildError) as raised:
        f.build(world, document, library)
    error = raised.value
    assert error.code == "build.run_unrecorded", error
    published = read_delivery(world.store, production_id=f.PRODUCTION, run_id=error.run_id)
    assert published is not None and error.delivery_id == published.id
    for text in (error.run_id, published.id, "`running`", COLLISION, "build.delivery_unverified"):
        assert text in error.message
    assert RunRecords(world.store, f.PRODUCTION).latest(error.run_id)["status"] == "running"


def test_a_transition_error_writing_a_failure_raises_naming_the_run(world, voiced, first,
                                                                   monkeypatch):
    document, library = voiced
    edited = copy.deepcopy(document)
    f.board_of(edited, f.B3)["seeds"]["i2v:frame"] = 40  # a clip no run made
    refuse_failure_writes(monkeypatch, BuildError("run.transition", "moved by another writer"))
    with pytest.raises(BuildError) as raised:
        f.build(world, edited, library, phase="offline", source=offline_sources())
    error = raised.value
    assert error.code == "build.run_unrecorded", error
    assert error.delivery_id is None and "no delivery of this run was published" in error.message
    for text in (error.run_id, "`running`", "run.transition", "build.offline_missing"):
        assert text in error.message
    assert RunRecords(world.store, f.PRODUCTION).latest(error.run_id)["status"] == "running"


def test_a_story_whose_assets_do_not_resolve_makes_no_run(world, voiced, first):
    document, _ = voiced
    library = world.library(without=frozenset({f.PHOTO}))
    before = len(f.local_run_ids(world.store, f.PRODUCTION))
    with pytest.raises(Exception) as error:
        f.build(world, document, library)
    assert "asset.unresolved" in str(error.value) or "ref.unknown" in str(error.value)
    assert len(f.local_run_ids(world.store, f.PRODUCTION)) == before


@pytest.mark.xfail(strict=True, reason="observation O-406-1: deliver's proxy is refused "
                   "(delivery.proxy_invalid, audio a few samples short) when the film's frame "
                   "count is not a multiple of 3; story 381's package, not changed here")
def test_a_film_of_43_frames_delivers(world, voiced, first):
    document, library = voiced
    edited = copy.deepcopy(document)
    f.board_of(edited, f.B3)["timing"]["hold_ms"] = 540  # 13 frames: 43 in all
    result = f.build(world, edited, library)
    assert result.run["status"] == "succeeded", result.run["error"]


def test_an_adapter_refusal_fails_the_run_before_any_clip(world, voiced, first):
    # The whole-frame adapter's own check runs in the pre-build check: it draws no
    # camera cue, so the run stops on that board before its clip is asked for.
    document, library = voiced
    edited = copy.deepcopy(document)
    f.board_of(edited, f.B3)["cues"] = [{
        "id": f.ident("cue", 1), "type": "camera", "anchor": {"at_ms": 0}, "duration_ms": 200,
        "zoom_from": 1.0, "zoom_to": 1.1, "center_px": [540, 960], "easing": "ease_out_cubic"}]
    sources = f.sources()
    run = assert_failed(world, f.build(world, edited, library, source=sources),
                        "wholeframe.unsupported", board=f.B3, stage="prebuild")
    assert sources.i2v.calls == [] and run["error"]["problems"][0]["field"] == "/cues/0"


def test_a_cast_still_without_a_loop_fails_the_run(world, voiced, first):
    # The motion resolver runs in the pre-build check (Build generates no loop, Q-457-1).
    document, _ = voiced
    library = f.voiced(world)[1]
    library = f.Library.from_version_documents(
        [d for d in library.documents() if d["id"] != f.LOOP["b"]])
    assert_failed(world, f.build(world, document, library), "motion.clip_absent", board=f.B1,
                  stage="prebuild")


def test_a_board_voice_without_a_track_fails_the_run(world, voiced, first):
    # A legacy import's board voice keeps one WAV per line and no assembled track
    # (observation O-406-2); the picture's envelope and the mix read the track.
    document, library = voiced
    version_id = f.board_of(document, f.B1)["voice"]["current_version_id"]
    docs = []
    for doc in library.documents():
        if doc["id"] == version_id:
            doc = copy.deepcopy(doc)
            doc["voice"]["track"] = None
            doc["voice"]["track_note"] = "Legacy kept one WAV per line; no assembled board track."
        docs.append(doc)
    sources = f.sources()
    result = f.build(world, document, f.Library.from_version_documents(docs), source=sources)
    assert_failed(world, result, "build.voice_track_missing", board=f.B1, stage="voice")
    assert sources.s2v.calls == []


def test_a_success_record_that_would_not_validate_stops_the_run_before_delivery(
        world, voiced, first, monkeypatch):
    # The success record is checked before deliver is called, so a record that could
    # not be written never leaves a published delivery behind a failed run.
    document, library = voiced
    real = pipeline.provenance

    def credits_a_check_engine(**kwargs):
        prov = real(**kwargs)
        prov["public"]["credits"].append({"engine_key": "asr", "text": "Checks: a recognizer"})
        return prov
    monkeypatch.setattr(pipeline, "provenance", credits_a_check_engine)
    run = assert_failed(world, f.build(world, document, library), "build.internal")
    assert "credit.outside_video_sound" in run["error"]["message"]
