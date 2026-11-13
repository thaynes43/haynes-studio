"""The two phases and the workers (story 406): the service phase fills the cache through
the clip sources and nothing else; the offline phase renders from the cache and refuses
any service call, naming the missing artifact; ``--workers 2`` gives the same frames as
one worker."""

from __future__ import annotations

import copy

import numpy as np

from haynes_studio.build import offline_sources
from haynes_studio.render.encode import decode_frames
from haynes_studio.store import blob_locator
from tests.build import fixtures as f


def film_frames(world, run):
    locator = blob_locator(f.PRODUCTION, run["outputs"]["picture_sha256"], "video/mp4")
    with world.store.open(locator) as handle:
        return list(decode_frames(handle.read()))


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


def test_the_service_phase_fills_the_cache_then_the_offline_phase_builds(world, voiced, first):
    document, library = voiced
    edited = copy.deepcopy(document)
    f.board_of(edited, f.B3)["seeds"]["i2v:frame"] = 36
    sources = f.sources()
    service = f.build(world, edited, library, phase="service", source=sources)
    run = service.run
    assert run["status"] == "cancelled" and run["phase"] == "service"
    assert "service phase complete" in run["transitions"][-1]["reason"]
    assert len(sources.i2v.calls) == 1 and sources.s2v.calls == []
    kinds = {key.split(":")[0] for key in service.made}
    assert service.plan is not None
    made_names = {n for n, p in service.plan.artifacts.items() if p.key.value in service.made}
    assert made_names == {f"{f.B3}/whole_frame_clip"}  # clips only: no segment, film or sound
    assert kinds
    offline = f.build(world, edited, library, phase="offline", source=offline_sources())
    assert offline.run["status"] == "succeeded"
    names = {n for n, p in offline.plan.artifacts.items() if p.key.value in offline.made}
    assert f"{f.B3}/whole_frame_clip" not in names and f"{f.B3}/segment" in names


def test_two_workers_give_the_same_frames_as_one(tmp_path, first, world):
    other = f.make_world(tmp_path / "workers")
    document, library = f.voiced(other)
    built = f.build(other, document, library, workers=2)
    run = built.run
    assert run["status"] == "succeeded", run["error"]
    assert built.plan.keys() == first.plan.keys()  # the same story, the same keys
    segments = {built.plan.artifacts[f"{b}/segment"].key.value for b in (f.B1, f.B2, f.B3)}
    assert segments <= set(built.made)
    assert all(stage["report"] is not None for stage in run["stages"])  # from the workers
    ours, theirs = film_frames(world, first.run), film_frames(other, run)
    assert len(ours) == len(theirs) == 42
    assert all(np.array_equal(a, b) for a, b in zip(ours, theirs))
