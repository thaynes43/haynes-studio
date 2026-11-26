"""The serving Studio revision and this revision share the queue during a rollout."""

import subprocess
from pathlib import Path
from types import ModuleType

import pytest

from haynes_studio.adapters import wan
from haynes_studio.api.app import create_app
from haynes_studio.db import runs
from haynes_studio.queue.wan import ProductWan, product_request
from haynes_studio.queue.worker import BuildWorker
from haynes_studio.queue.worker_api import WorkerAPI

from tests.build_story.fixtures import register
from tests.db.test_run_queue import (
    LocalWorkerHTTP, _dispatch_to_fake_wan, _expire_run_claim, _pause_run_lane,
    database_time, queue, queue_run, read_run, request_for, worker_credentials,
)
from tests.db.test_studio_api import engine, owner_engine, runtime_db, runtime_role, service
from tests.queue.fake_wan import FakeWan, STORY

pytestmark = pytest.mark.db
SERVING_REVISION = "470a90af73a2201e6542b5d867853dce6facad04"
ROOT = Path(__file__).resolve().parents[2]


def _serving_module(name):
    """Load the pinned source alongside the current module without replacing imports."""
    package, module_name = name.rsplit(".", 1)
    path = f"src/{name.replace('.', '/')}.py"
    source = subprocess.check_output(["git", "show", f"{SERVING_REVISION}:{path}"], cwd=ROOT)
    module = ModuleType(f"{package}._serving_{module_name}")
    module.__package__ = package
    module.__file__ = f"{SERVING_REVISION}:{path}"
    exec(compile(source, module.__file__, "exec"), vars(module))
    return module


@pytest.fixture(scope="module")
def serving_worker():
    worker = _serving_module("haynes_studio.queue.worker")
    old_wan = _serving_module("haynes_studio.queue.wan")
    old_http = _serving_module("haynes_studio.queue.worker_api")
    for name in ("AttemptFailed", "BuildCancelled", "LanePaused", "ProductClips", "ProductWan"):
        setattr(worker, name, getattr(old_wan, name))
    worker.WorkerAPIError = old_http.WorkerAPIError
    worker.WorkerAPI = old_http.WorkerAPI
    return worker


@pytest.fixture(scope="module")
def serving_api():
    app = _serving_module("haynes_studio.api.app")
    api = _serving_module("haynes_studio.api.run_routes")
    app.run_routes = api
    api.runs = app.runs = _serving_module("haynes_studio.db.runs")
    api.jobs = _serving_module("haynes_studio.db.jobs")
    api.WorkClaim = _serving_module("haynes_studio.queue.protocol").WorkClaim
    return app.create_app


@pytest.mark.parametrize("enabled", [False, True], ids=["switch-unset", "switch-on"])
@pytest.mark.parametrize("older", ["worker", "api"])
@pytest.mark.parametrize("recorded", [True, False], ids=["verified-id", "missing-id"])
def test_serving_and_new_revisions_leave_paused_wan_work_in_place(
    queue, monkeypatch, serving_worker, serving_api, enabled, older, recorded,
):
    q = queue
    if enabled:
        monkeypatch.setenv("STUDIO_PAUSED_RECONCILE", "1")
    else:
        monkeypatch.delenv("STUDIO_PAUSED_RECONCILE", raising=False)
    monkeypatch.setattr(runs, "database_time", database_time)
    monkeypatch.setattr(wan, "measure_clip", lambda data: wan.Measured(5, 64, 64, "24"))
    q.app.state.build_revision = "git:new-worker"
    app_factory = serving_api if older == "api" else create_app
    app = app_factory(q.engine, q.store, q.app.state.oidc, build_stage_root=q.stage_root)
    if older == "worker":
        assert app.state.paused_reconcile is enabled
        worker_type, api_type, wan_type = serving_worker.BuildWorker, serving_worker.WorkerAPI, serving_worker.ProductWan
    else:
        worker_type, api_type, wan_type = BuildWorker, WorkerAPI, ProductWan

    identifier = queue_run(q, "mixed-version-head").json()["id"]
    # Even the serving API must accept the new worker's capability header while open.
    old = WorkerAPI(LocalWorkerHTTP(app, worker_credentials(q.owner))).claim()
    fake = FakeWan()
    with fake.client() as wan_http:
        transport = ProductWan(wan_http)
        if recorded:
            _dispatch_to_fake_wan(q, old, transport)
        else:
            request = request_for(q)
            body = product_request(request)
            attempt = old.reserve("i2v", body)
            transport.stage(request.image_png, body["image_sha256"], "png")
            old.attempt(attempt["job_id"], "sent")
        _pause_run_lane(q, True)
        _expire_run_claim(q, identifier)
        before, _ = read_run(q, identifier)
        fake.events.clear()

        api = api_type(LocalWorkerHTTP(app, worker_credentials(q.owner)))
        worker = worker_type(api, wan_type(wan_http), store=q.store, stage_root=q.stage_root,
                             register=register(), tracker_story=STORY, transcriber=None,
                             studio=f"git:{SERVING_REVISION}" if older == "worker" else "git:new-worker",
                             clock=q.clock.monotonic, pause=q.clock.advance)
        assert not worker.tick()
        assert not fake.events
    assert read_run(q, identifier)[0] == before
    assert before["status"] == "running" and before["wan_attempts"][0]["state"] == "sent"
