"""Main-thread progress advances without sleeps or real media services."""

import sys
from dataclasses import dataclass
from threading import Event
from types import SimpleNamespace

import httpx
import pytest

from haynes_studio.adapters.comfyui import QueueState, TextToImage
from haynes_studio.build import pipeline
from haynes_studio.queue import worker
from haynes_studio.queue.media_services import ComfyHTTP
from haynes_studio.queue.media_worker import Dispatch, ImageLane, MediaWorker
from haynes_studio.queue.progress import ProgressFile
from haynes_studio.queue.wan import ProductClips, RESTART_ERROR
from haynes_studio.queue.worker import ActiveClaim, BuildWorker
from haynes_studio.queue.worker_api import WorkerAPIError

from .fake_wan import STORY


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def marker(tmp_path):
    clock = Clock()
    return ProgressFile(tmp_path / "progress", clock=clock), clock


def test_marker_age_boundary_and_missing_marker(marker):
    progress, clock = marker
    assert not progress.fresh(30)
    progress()
    assert progress.path.stat().st_mtime == clock()
    clock.advance(30)
    assert progress.fresh(30)
    clock.advance(0.01)
    assert not progress.fresh(30)
    progress()
    assert progress.fresh(30)


@pytest.mark.parametrize("seconds", [0, -1, float("nan"), float("inf")])
def test_invalid_age_fails_closed(marker, seconds):
    progress, _ = marker
    progress()
    assert not progress.fresh(seconds)


def test_disabled_directory_and_unreadable_markers_fail_closed(tmp_path, monkeypatch):
    assert not ProgressFile().fresh(30)
    ProgressFile()()
    assert not ProgressFile(tmp_path).fresh(30)
    progress = ProgressFile(tmp_path / "progress")
    progress()

    def denied(_path):
        raise PermissionError()

    monkeypatch.setattr(type(progress.path), "stat", denied)
    assert not progress.fresh(30)


@pytest.mark.parametrize("lane", ["run", "image", "voice"])
@pytest.mark.parametrize("age, expected", [(30, 0), (30.01, 1)])
def test_probe_needs_no_configuration_or_network_and_never_touches(
        marker, monkeypatch, lane, age, expected):
    progress, clock = marker
    progress()
    before = progress.path.stat().st_mtime_ns
    clock.advance(age)
    monkeypatch.setenv("STUDIO_WORKER_PROGRESS_FILE", str(progress.path))
    monkeypatch.delenv("STUDIO_API_URL", raising=False)
    monkeypatch.delenv("STUDIO_WORKER_TOKEN", raising=False)
    monkeypatch.setattr(worker, "ProgressFile", lambda path: ProgressFile(path, clock=clock))
    monkeypatch.setattr(httpx, "Client", lambda **_kwargs: pytest.fail("Probe opened a service client"))
    monkeypatch.setattr(sys, "argv", ["studio-worker", "--lane", lane, "--check-progress", "30"])

    with pytest.raises(SystemExit) as stopped:
        worker.main()

    assert stopped.value.code == expected
    assert progress.path.stat().st_mtime_ns == before


def test_probe_explicit_path_overrides_environment(marker, tmp_path, monkeypatch):
    progress, clock = marker
    progress()
    monkeypatch.setenv("STUDIO_WORKER_PROGRESS_FILE", str(tmp_path / "absent"))
    monkeypatch.setattr(worker, "ProgressFile", lambda path: ProgressFile(path, clock=clock))
    monkeypatch.setattr(sys, "argv", ["studio-worker", "--progress-file", str(progress.path),
                                     "--check-progress", "30"])
    with pytest.raises(SystemExit) as stopped:
        worker.main()
    assert stopped.value.code == 0


@pytest.mark.parametrize("lane", ["run", "image", "voice"])
def test_worker_startup_passes_marker_to_every_lane(marker, tmp_path, monkeypatch, lane):
    progress, clock = marker
    store, stage = tmp_path / "store", tmp_path / "stage"
    store.mkdir()
    stage.mkdir()
    monkeypatch.delenv("STUDIO_MODEL_REGISTER", raising=False)
    for name, value in {
        "STUDIO_API_URL": "http://studio.example.invalid",
        "STUDIO_WAN_URL": "http://wan.example.invalid",
        "STUDIO_WAN_STORY_URL": STORY,
        "STUDIO_STORE_ROOT": str(store),
        "STUDIO_BUILD_STAGE_ROOT": str(stage),
        "STUDIO_WORKER_TOKEN": "s" * 48,
        "STUDIO_ASR_HOST": "asr.example.invalid",
        "STUDIO_TTS_HOST": "tts.example.invalid",
        "STUDIO_COMFYUI_URL": "http://comfyui.example.invalid",
        "STUDIO_WORKER_PROGRESS_FILE": str(progress.path),
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(worker, "ProgressFile", lambda path: ProgressFile(path, clock=clock))
    captured = []

    def serve(instance, once):
        assert once
        captured.append(instance)
        instance.progress()
        assert progress.fresh(1)

    monkeypatch.setattr(worker, "_serve", serve)
    monkeypatch.setattr(sys, "argv", ["studio-worker", "--once", "--lane", lane])
    worker.main()
    assert len(captured) == 1 and captured[0].progress.path == progress.path
    if lane == "image":
        assert captured[0].client.progress is captured[0].progress


@pytest.mark.parametrize("lane", ["run", "image", "voice"])
def test_each_idle_claim_poll_touches_the_marker(marker, lane):
    progress, clock = marker

    def claim(*args):
        assert args == (() if lane == "run" else (lane,))
        assert progress.path.stat().st_mtime == clock()
        return None

    if lane == "run":
        instance = BuildWorker(SimpleNamespace(claim=claim), None, store=None, stage_root=None,
                               register=None, tracker_story=STORY, transcriber=None, progress=progress)
    else:
        instance = MediaWorker(SimpleNamespace(claim=claim), lane=lane, store=None, client=None,
                               progress=progress)
    for _ in range(3):
        clock.advance(30)
        assert instance.tick() is False


@pytest.mark.parametrize("failure", [None, OSError(), WorkerAPIError("work.unavailable", 503)])
def test_serve_loop_updates_at_poll_and_return_boundaries(marker, monkeypatch, failure):
    progress, clock = marker

    class Finished(Exception):
        pass

    calls = 0

    def tick():
        nonlocal calls
        assert progress.path.stat().st_mtime == clock()
        calls += 1
        if calls == 3:
            raise Finished()
        clock.advance(10)
        if failure is not None:
            raise failure
        return False

    def pause(seconds):
        assert seconds == worker.IDLE_SECONDS
        assert progress.path.stat().st_mtime == clock()
        clock.advance(seconds)

    monkeypatch.setattr(worker, "sleep", pause)
    with pytest.raises(Finished):
        worker._serve(SimpleNamespace(tick=tick, progress=progress), False)
    assert calls == 3


def test_background_lease_heartbeats_cannot_hide_a_stalled_main_thread(marker):
    progress, clock = marker
    heartbeats = []
    claim = SimpleNamespace(heartbeat=lambda value: heartbeats.append(value) or {"cancel_requested": False})
    active = ActiveClaim(claim, progress=progress)
    active.progress("rendering")

    class Done:
        calls = 0

        def wait(self, seconds):
            assert seconds == worker.HEARTBEAT_SECONDS
            self.calls += 1
            clock.advance(seconds)
            return self.calls == 4

    active.done = Done()
    active._maintain()
    assert len(heartbeats) == 4
    assert not progress.fresh(30)
    active.progress("delivery")
    assert progress.fresh(1)


def test_a_twenty_minute_wan_clip_stays_fresh_through_every_poll(marker):
    progress, clock = marker
    started = clock()
    recorded = []
    claim = SimpleNamespace(body={"run": {}},
                            heartbeat=lambda _value: {"cancel_requested": False},
                            attempt=lambda *args: recorded.append(args))
    active = ActiveClaim(claim, progress=progress)
    polls = []

    def status(_attempt):
        assert progress.path.stat().st_mtime == clock()
        polls.append(clock())
        if clock() - started >= 1200:
            return {"state": "failed", "error": RESTART_ERROR}
        return {"state": "running"}

    def pause(seconds):
        assert seconds == 5
        clock.advance(seconds)
        assert progress.fresh(6)

    clips = ProductClips(claim, SimpleNamespace(status=status), story=STORY,
                         progress=active.progress, clock=clock, pause=pause)
    assert clips._poll({"job_id": "clip-demo", "state": "sent"}) is None
    assert len(polls) == 241 and polls[-1] - polls[0] == 1200
    assert recorded == [("clip-demo", "restart_failed")]


def test_each_pipeline_artifact_and_early_mix_check_refreshes_progress(marker):
    progress, clock = marker
    # Exercise the actual content-chain driver with cheap artifact makers. No
    # encoders, GPU calls or real waits are needed to cover every artifact kind.
    build = pipeline._Build.__new__(pipeline._Build)
    build.on_step = progress
    build.boards, build.passes = ["board-demo"], []
    build.cache = SimpleNamespace(stats=SimpleNamespace(made=[]))
    build.sources = SimpleNamespace(stopped=None)
    build.timer = clock
    seen = []

    def route(key):
        assert progress.path.stat().st_mtime == clock()
        assert build.where[1] == key.kind
        seen.append(key.kind)
        clock.advance(30)
        return "a" * 64

    build.route = route
    chain = pipeline._Chain(build)
    kinds = [pipeline.S2V_DRIVE_TRACK, pipeline.S2V_CLIP, pipeline.KEYED_FRAMES,
             pipeline.SEGMENT, pipeline.FILM_PICTURE, pipeline.MIX, pipeline.MASTER,
             pipeline.PROXY, pipeline.CHECK_RESULT]
    for kind in kinds:
        chain(SimpleNamespace(kind=kind, value=kind))
    assert seen == kinds

    def mix(_key):
        assert progress.path.stat().st_mtime == clock()
        assert build.where == (None, pipeline.MIX)
        clock.advance(30)
        return SimpleNamespace(sha256="a" * 64)

    def checks(*_args):
        assert progress.path.stat().st_mtime == clock()
        assert build.where == (None, "checks")
        return []

    build.sound = SimpleNamespace(mix=mix, checks=checks)
    assert pipeline._early_mix(build, SimpleNamespace(mix=SimpleNamespace(key="mix"))) == []


def test_build_worker_passes_progress_into_the_pipeline(marker, tmp_path, monkeypatch):
    progress, clock = marker
    instance = BuildWorker(None, None, store=None, stage_root=tmp_path, register=None,
                           tracker_story=STORY, transcriber=None, progress=progress)
    claim = SimpleNamespace(body={"run": {"id": "run-demo"}, "actor": {}})
    active = SimpleNamespace(before_delivery=lambda: None)
    monkeypatch.setattr(worker, "BuildStageStore", lambda *_args, **_kwargs: None)
    called = []

    def build_story(_inputs, **kwargs):
        queued = kwargs["queued"]
        clock.advance(30)
        queued.on_step()
        assert progress.path.stat().st_mtime == clock()
        assert queued.before_delivery is active.before_delivery
        called.append(True)
        return SimpleNamespace(run={"status": "succeeded"})

    monkeypatch.setattr(worker, "build_story", build_story)
    assert instance._render(claim, active, SimpleNamespace(), None) == {"status": "succeeded"}
    assert called == [True]


def test_image_lane_waiting_on_shared_queue_keeps_main_thread_progress(marker):
    progress, clock = marker
    active = SimpleNamespace(touch_progress=progress, lost=Event())
    dispatch = Dispatch(active)
    polls = []

    def queue():
        assert progress.path.stat().st_mtime == clock()
        polls.append(clock())
        return QueueState(0, 1 if len(polls) < 3 else 0)

    @dataclass
    class Result:
        waited_s: float = 1.0

    client = SimpleNamespace(queue=queue, render=lambda _request, **_kwargs: Result())
    lane = ImageLane(client, dispatch, clock=clock, pause=clock.advance)
    assert lane.render(object()).waited_s == 21.0
    assert len(polls) == 3


def test_media_dispatch_refreshes_progress_before_publish_and_heartbeat(marker):
    progress, clock = marker
    calls = []

    def record(event):
        assert progress.path.stat().st_mtime == clock()
        calls.append(event)

    claim = SimpleNamespace(publish=lambda: record("publish"), heartbeat=lambda: record("heartbeat"))
    dispatch = Dispatch(SimpleNamespace(touch_progress=progress, lost=Event(), claim=claim))
    for _ in range(2):
        clock.advance(30)
        dispatch()
    assert calls == ["publish", "heartbeat"]


def test_comfy_history_polling_touches_on_each_service_request(marker):
    progress, clock = marker
    history_polls = []
    prompt_id = "aaa5b8d4-a7a1-4b88-b705-a9a3cb055bee"

    def serve(request):
        assert progress.path.stat().st_mtime == clock()
        clock.advance(1)
        if request.url.path == "/queue":
            return httpx.Response(200, json={"queue_running": [], "queue_pending": []})
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": prompt_id})
        assert request.url.path == f"/history/{prompt_id}"
        history_polls.append(clock())
        return httpx.Response(200, json={prompt_id: {"status": {"completed": len(history_polls) == 3}}})

    with httpx.Client(base_url="http://image.example.invalid", transport=httpx.MockTransport(serve)) as http:
        client = ComfyHTTP(http, clock=clock, pause=clock.advance, progress=progress)
        sentinel = object()
        client._image = lambda *_args: sentinel
        result = client.render(TextToImage("job-demo", "asset-candidate", "A tabletop", 1, 64, 64),
                               before_submit=lambda: None)
    assert result is sentinel and len(history_polls) == 3
