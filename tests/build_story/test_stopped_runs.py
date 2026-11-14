"""A run that stops keeps the board stages it finished (story 860 item d, O-428-6).

A run that ends ``failed`` (or ``held``) partway through its plan records the board
stages it completed before it stopped, with their artifacts and seconds, exactly as a
succeeded run records them; a board whose segment it did not reach or did not finish
is not listed. Every build here uses the session's world (fake sources, synthetic
media) and one worker.
"""

from __future__ import annotations

import copy

import pytest

import haynes_studio.build.pipeline as pipeline
from haynes_studio.build import BuildInputs, build_story, local_run_ids, offline_sources
from haynes_studio.library import Library
from haynes_studio.store import StoreError
from haynes_studio.store.errors import HASH_MISMATCH
from tests.build_story import fixtures as f
from tests.layered import media

WEAK = f.ident("asv", 70)  # a loop of doll b whose lettering track is too weak


def stage_of(run, board_id):
    return next(s for s in run["stages"] if s["board_id"] == board_id)


def same_work(stage):
    """What a stage names, apart from whether this run made it and how long it took."""
    return {"board_id": stage["board_id"], "board_number": stage["board_number"],
            "method": stage["method"], "frames": stage["frames"],
            "film_start_frame": stage["film_start_frame"], "compositor": stage["compositor"],
            "segment": (stage["segment_key"], stage["segment_sha256"]),
            "artifacts": [(a["name"], a["kind"], a["key"], a["sha256"]) for a in stage["artifacts"]],
            "clips": [(c["role"], c["slot"], c["sha256"]) for c in stage["clips"]]}


def test_a_run_stopped_at_the_transcript_check_keeps_every_board_stage(world, voiced, first):
    """The documented end of an offline run of a new master: every board is rendered,
    then the transcript check (a service call) stops it with ``build.offline_missing``."""
    document, library = voiced
    edited = copy.deepcopy(document)
    f.board_of(edited, f.B3)["seeds"]["i2v:frame"] = 51  # a new whole-frame clip, so a new master
    service = f.build(world, edited, library, phase="service")
    assert service.run["status"] == "cancelled"
    stopped = f.build(world, edited, library, phase="offline", source=offline_sources())
    run = stopped.run
    assert run["status"] == "failed" and run["error"]["code"] == "build.offline_missing"
    assert run["error"]["stage"] == "check_result"
    assert [s["board_id"] for s in run["stages"]] == [f.B1, f.B2, f.B3]
    b3 = stage_of(run, f.B3)
    segment = next(a for a in b3["artifacts"] if a["name"] == "segment")
    assert segment["made"] and segment["seconds"] is not None and b3["render_s"] is not None
    assert b3["report"] is not None  # rendered in this run: the renderer's report
    assert b3["segment_sha256"] == segment["sha256"]
    assert not any(a["made"] for a in stage_of(run, f.B1)["artifacts"])  # all from the cache

    # The service phase checks the master's transcript; the next offline run delivers.
    assert f.build(world, edited, library, phase="service").run["status"] == "cancelled"
    done = f.build(world, edited, library, phase="offline", source=offline_sources())
    assert done.run["status"] == "succeeded"
    assert [same_work(s) for s in run["stages"]] == [same_work(s) for s in done.run["stages"]]
    assert not stage_of(done.run, f.B3)["artifacts"][-1]["made"]  # reused from the stopped run


def test_a_run_stopped_at_a_missing_clip_keeps_the_boards_before_it(world, voiced, first):
    document, library = voiced
    edited = copy.deepcopy(document)
    f.board_of(edited, f.B3)["seeds"]["i2v:frame"] = 52  # a clip no run made
    run = f.build(world, edited, library, phase="offline", source=offline_sources()).run
    assert run["status"] == "failed" and run["error"]["code"] == "build.offline_missing"
    assert (run["error"]["board_id"], run["error"]["stage"]) == (f.B3, "whole_frame_clip")
    assert [s["board_id"] for s in run["stages"]] == [f.B1, f.B2]  # B3 did not complete
    for board_id in (f.B1, f.B2):
        assert same_work(stage_of(run, board_id)) == same_work(stage_of(first.run, board_id))


def _weak_loop(world, library: Library) -> tuple[Library, dict]:
    """``library`` with a candidate loop of doll b whose track is weak (its new stripes
    on every frame), published to the world's store; only a pin can name it."""
    still_b = next(d for d in world.docs if d["id"] == f.STILL["b"])["content"]["sha256"]
    side = f.World(world.root, world.store)
    side.loop(WEAK, 70, still_sha=still_b, start=media.start_image(tint=f.TINT["b"]),
              clip=media.doll_clip(f.LOOP_N, moving=False, weak=True, tint=f.TINT["b"]))
    doc = side.docs[0]
    doc["state"] = "candidate"
    return Library.from_version_documents([*library.documents(), doc]), doc


def test_a_run_stopped_at_a_segment_keeps_the_boards_before_it_and_not_that_board(
        world, voiced, first):
    document, library = voiced
    library, _ = _weak_loop(world, library)
    edited = copy.deepcopy(document)
    b2 = f.board_of(edited, f.B2)
    next(e for e in b2["cast"] if e["slot"] == "b")["motion_asset_version_id"] = WEAK
    built = f.build(world, edited, library, phase="offline", source=offline_sources())
    run = built.run
    assert run["status"] == "failed", run["error"]
    assert run["error"]["code"] == "layered.decal_weak"
    assert (run["error"]["board_id"], run["error"]["stage"]) == (f.B2, "segment")
    # B2's keyed frames were made, but its segment was refused: B2 is not listed.
    assert any(value for value in built.made)
    assert [s["board_id"] for s in run["stages"]] == [f.B1]
    assert same_work(stage_of(run, f.B1)) == same_work(stage_of(first.run, f.B1))


def test_with_workers_a_stopped_run_keeps_the_boards_the_workers_and_the_cache_completed(
        world, voiced, first):
    """``--workers 2``: B2's segment fails in its worker, B3's (a new clip) is rendered in
    the other, and B1's is found in the cache by the first pass. B1 and B3 completed,
    B2 did not."""
    document, library = voiced
    library, _ = _weak_loop(world, library)
    edited = copy.deepcopy(document)
    b2 = f.board_of(edited, f.B2)
    next(e for e in b2["cast"] if e["slot"] == "b")["motion_asset_version_id"] = WEAK
    f.board_of(edited, f.B3)["seeds"]["i2v:frame"] = 53
    built = f.build(world, edited, library, workers=2)
    run = built.run
    assert run["status"] == "failed", run["error"]
    assert (run["error"]["code"], run["error"]["board_id"]) == ("layered.decal_weak", f.B2)
    assert [s["board_id"] for s in run["stages"]] == [f.B1, f.B3]
    b3 = stage_of(run, f.B3)
    segment = next(a for a in b3["artifacts"] if a["name"] == "segment")
    assert segment["made"] and segment["key"] in built.made  # rendered by a worker
    assert b3["report"] is not None and b3["render_s"] is not None
    assert same_work(stage_of(run, f.B1)) == same_work(stage_of(first.run, f.B1))


def test_a_stopped_full_build_records_what_each_pass_made_as_a_succeeded_run_does(
        world, voiced, first):
    """B1's tail grows, so its drive track is new (made by the local pass), and so are its
    clip (asked of the fake source), keyed frames and segment; then B2 stops the run at
    its weak track. B1's stage says this run made all four, with their seconds."""
    document, library = voiced
    library, _ = _weak_loop(world, library)
    edited = copy.deepcopy(document)
    f.board_of(edited, f.B1)["timing"]["tail_ms"] = 420  # was 340: two more frames
    b2 = f.board_of(edited, f.B2)
    next(e for e in b2["cast"] if e["slot"] == "b")["motion_asset_version_id"] = WEAK
    sources = f.sources()
    run = f.build(world, edited, library, source=sources).run
    assert (run["status"], run["error"]["code"], run["error"]["board_id"]) == (
        "failed", "layered.decal_weak", f.B2)
    assert len(sources.s2v.calls) == 1
    assert [s["board_id"] for s in run["stages"]] == [f.B1]
    b1 = stage_of(run, f.B1)
    made = {a["name"]: (a["made"], a["seconds"] is not None) for a in b1["artifacts"]}
    for name in ("drive/a", "s2v_clip/a", "keyed/a", "segment"):
        assert made[name] == (True, True), name
    assert not made["keyed/b"][0]  # doll b's loop was keyed by an earlier run
    s2v = next(c for c in b1["clips"] if c["role"] == "s2v_clip")
    assert s2v["made"] and s2v["render_s"] is not None and b1["report"] is not None


def test_with_workers_a_stop_in_the_first_pass_keeps_the_boards_it_found_cached(
        world, voiced, first):
    """Review finding 2: the first pass defers every segment, so a stop inside it (B3's
    clip, which no run made) must still find B1's and B2's segments in the cache, as one
    worker does."""
    document, library = voiced
    edited = copy.deepcopy(document)
    f.board_of(edited, f.B3)["seeds"]["i2v:frame"] = 54  # a clip no run made
    one = f.build(world, edited, library, phase="offline", source=offline_sources()).run
    two = f.build(world, edited, library, phase="offline", source=offline_sources(), workers=2).run
    for run in (one, two):
        assert (run["error"]["code"], run["error"]["stage"]) == ("build.offline_missing",
                                                                  "whole_frame_clip")
    assert [same_work(s) for s in two["stages"]] == [same_work(s) for s in one["stages"]]
    assert [s["board_id"] for s in two["stages"]] == [f.B1, f.B2]


def test_with_workers_a_stop_at_the_transcript_check_keeps_what_each_pass_made(
        world, voiced, first):
    """The documented offline stop with ``--workers 2``: B3's new segment is rendered by
    a worker, then the transcript check stops the run; the stages are the next
    succeeded run's, with B3's segment made here."""
    document, library = voiced
    edited = copy.deepcopy(document)
    f.board_of(edited, f.B3)["seeds"]["i2v:frame"] = 55
    assert f.build(world, edited, library, phase="service").run["status"] == "cancelled"
    run = f.build(world, edited, library, phase="offline", source=offline_sources(), workers=2).run
    assert (run["error"]["code"], run["error"]["stage"]) == ("build.offline_missing", "check_result")
    b3 = stage_of(run, f.B3)
    segment = next(a for a in b3["artifacts"] if a["name"] == "segment")
    assert segment["made"] and b3["report"] is not None and b3["render_s"] is not None
    assert f.build(world, edited, library, phase="service").run["status"] == "cancelled"
    done = f.build(world, edited, library, phase="offline", source=offline_sources()).run
    assert done["status"] == "succeeded"
    assert [same_work(s) for s in run["stages"]] == [same_work(s) for s in done["stages"]]


def test_a_register_the_build_cannot_read_still_fails_the_run(world, voiced, first):
    """Review finding 1: reading the register is part of the run, so a register that
    does not read fails the run (recorded), never leaves it ``running``."""
    document, library = voiced
    inputs = BuildInputs(story=document, library=library, register={"engines": [{"role": "video"}]},
                         toolchain=f.toolchain(), studio="git:fixture")
    result = build_story(inputs, store=world.store, phase="offline", sources=offline_sources(),
                         transcriber=None, actor=f.OPERATOR,
                         earlier_runs=local_run_ids(world.store, f.PRODUCTION), minter=f.minter(),
                         now=lambda: f.NOW)
    assert result.run["status"] == "failed" and result.run["stages"] == []


def test_a_reused_layers_keyed_record_that_cannot_be_read_is_left_out_not_a_failure(
        world, voiced, first, monkeypatch):
    """Review finding 3: a reused segment renders nothing, so a keyed-frames record the
    recorder cannot read leaves that layer's result out and never fails the build."""
    document, library = voiced
    keyed_a = next(a["sha256"] for a in stage_of(first.run, f.B1)["artifacts"]
                   if a["name"] == "keyed/a")
    real = pipeline.read_verified

    def damaged(read, sha256, what):
        if sha256 == keyed_a:
            raise StoreError(HASH_MISMATCH, f"{what} is not its bytes")
        return real(read, sha256, what)
    monkeypatch.setattr(pipeline, "read_verified", damaged)
    run = f.build(world, document, library, phase="offline", source=offline_sources()).run
    assert run["status"] == "succeeded", run["error"]
    assert [c["slot"] for c in stage_of(run, f.B1)["checks"]] == ["b"]
    assert stage_of(run, f.B2)["checks"] == stage_of(first.run, f.B2)["checks"]
