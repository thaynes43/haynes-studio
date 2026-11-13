"""The two phases and the workers (story 406): the service phase makes only what needs
a service (clips, and the transcript check of a master the cache holds) and nothing
else; the offline phase renders from the cache and refuses any service call, naming
the missing artifact; ``--workers 2`` gives the same frames as one worker."""

from __future__ import annotations

import copy

import numpy as np

from haynes_studio.build import offline_sources
from haynes_studio.render.encode import decode_frames
from haynes_studio.store import blob_locator
from tests.build_story import fixtures as f


def film_frames(world, run):
    locator = blob_locator(f.PRODUCTION, run["outputs"]["picture_sha256"], "video/mp4")
    with world.store.open(locator) as handle:
        return list(decode_frames(handle.read()))


def made_names(result, plan=None) -> set[str]:
    """The planned artifacts a build made, by name (a failed build has no plan of its
    own: name its keys with another plan of the same story)."""
    plan = plan or result.plan
    return {n for n, p in plan.artifacts.items() if p.key.value in result.made}


def test_an_offline_build_of_a_cached_story_needs_no_client(world, voiced, first):
    document, library = voiced
    built = f.build(world, document, library, phase="offline", source=offline_sources())
    assert built.run["status"] == "succeeded" and built.run["phase"] == "offline"
    assert built.made == ()


def test_the_offline_phase_refuses_a_service_call_naming_the_missing_artifact(world, voiced, first):
    document, library = voiced
    edited = copy.deepcopy(document)
    f.board_of(edited, f.B3)["seeds"]["i2v:frame"] = 35  # a clip no run made
    built = f.build(world, edited, library, phase="offline", source=offline_sources())
    run = built.run
    assert run["status"] == "failed"
    assert run["error"]["code"] == "build.offline_missing"
    assert run["error"]["board_id"] == f.B3 and run["error"]["stage"] == "whole_frame_clip"
    assert "--phase service" in run["error"]["message"]
    assert "sha256:" in run["error"]["message"]  # names the artifact's key


def test_the_service_phase_fills_the_cache_and_the_offline_phase_never_asks_the_recognizer(
        world, voiced, first):
    document, library = voiced
    edited = copy.deepcopy(document)
    f.board_of(edited, f.B3)["seeds"]["i2v:frame"] = 36
    # 1. The service phase makes the clip, and nothing else: no master is cached, so no
    #    transcript is asked for either.
    sources = f.sources()
    recognizer, whisper = f.transcriber()
    service = f.build(world, edited, library, phase="service", source=sources, recognizer=recognizer)
    run = service.run
    assert run["status"] == "cancelled" and run["phase"] == "service"
    assert "service phase complete" in run["transitions"][-1]["reason"]
    assert len(sources.i2v.calls) == 1 and sources.s2v.calls == [] and whisper.heard == []
    assert made_names(service) == {f"{f.B3}/whole_frame_clip"}
    b3 = next(s for s in run["stages"] if s["board_id"] == f.B3)
    assert b3["segment_sha256"] is None and b3["segment_key"] is None  # not made: not recorded
    assert {a["name"] for a in b3["artifacts"]} == {"whole_frame_clip"}
    # 2. The offline phase renders the picture and the master, then stops at the
    #    transcript check, a service call, naming it; the recognizer is never asked.
    recognizer, whisper = f.transcriber()
    offline = f.build(world, edited, library, phase="offline", source=offline_sources(),
                      recognizer=recognizer)
    assert offline.run["status"] == "failed" and whisper.heard == []
    assert offline.run["error"]["code"] == "build.offline_missing"
    assert offline.run["error"]["stage"] == "check_result" and "transcript" in offline.run["error"]["message"]
    offline_made = offline
    # 3. The service phase checks the cached master's transcript, and makes nothing else.
    recognizer, whisper = f.transcriber()
    checked = f.build(world, edited, library, phase="service", source=f.sources(), recognizer=recognizer)
    assert checked.run["status"] == "cancelled" and len(whisper.heard) == 1
    assert made_names(checked) == {"check/master.transcript"}
    # 4. Offline, everything is cached: the delivery is made, nothing is asked.
    done = f.build(world, edited, library, phase="offline", source=offline_sources())
    assert done.run["status"] == "succeeded"
    assert made_names(done) <= {"film/proxy"} and done.source_calls == 0
    assert {f"{f.B3}/segment", "film/picture", "film/master"} <= made_names(offline_made, done.plan)


def test_a_failed_transcript_in_the_service_phase_fails_the_run(world, voiced, first):
    # Review finding 3. New tolerances key a new transcript check of the master the
    # cache already holds (the master's own key is unchanged), so the service phase
    # checks it: a fail ends the run failed, never "service phase complete".
    document, library = voiced
    edited = copy.deepcopy(document)
    edited["checks"]["asr_tolerances"] = {"2": "two", "3": "three"}
    recognizer, whisper = f.transcriber("stop team two")
    made = f.build(world, edited, library, phase="service", source=f.sources(), recognizer=recognizer)
    run = made.run
    assert run["status"] == "failed" and len(whisper.heard) == 1
    assert run["error"]["code"] == "build.check_failed" and run["error"]["stage"] == "checks"
    assert "master.transcript" in run["error"]["message"] and run["delivery_id"] is None
    assert [(c["check"], c["result"]) for c in run["checks"]] == [("master.transcript", "fail")]
    assert made_names(made) == {"check/master.transcript"}
    # A later service phase reads that cached failure: failed again, nothing asked.
    recognizer, whisper = f.transcriber()
    again = f.build(world, edited, library, phase="service", source=f.sources(), recognizer=recognizer)
    assert again.run["status"] == "failed" and again.run["error"]["code"] == "build.check_failed"
    assert whisper.heard == [] and again.made == ()


def test_two_workers_give_the_same_frames_as_one(tmp_path, first, world):
    other = f.make_world(tmp_path / "workers")
    document, library = f.voiced(other)
    built = f.build(other, document, library, workers=2)
    run = built.run
    assert run["status"] == "succeeded", run["error"]
    assert built.plan.keys() == first.plan.keys()  # the same story, the same keys
    segments = {built.plan.artifacts[f"{b}/segment"].key.value for b in (f.B1, f.B2, f.B3)}
    assert set(built.worker_made) == segments  # rendered by the worker processes
    assert all(stage["report"] is not None and stage["render_s"] is not None for stage in run["stages"])
    # What the first pass made (clips, keyed frames) keeps its record and its time.
    b1 = next(s for s in run["stages"] if s["board_id"] == f.B1)
    s2v = next(c for c in b1["clips"] if c["role"] == "s2v_clip")
    assert s2v["made"] and s2v["render_s"] is not None
    keyed = next(a for a in b1["artifacts"] if a["name"] == "keyed/a")
    assert keyed["made"] and keyed["seconds"] is not None
    ours, theirs = film_frames(world, first.run), film_frames(other, run)
    assert len(ours) == len(theirs) == 42
    assert all(np.array_equal(a, b) for a, b in zip(ours, theirs))
