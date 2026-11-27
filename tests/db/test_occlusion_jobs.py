"""The public queue, worker routes and real segmentation socket with synthetic media."""

import asyncio
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import pytest
import sqlalchemy as sa
from PIL import Image

from haynes_studio.adapters.segmentation import SegmentationClient
from haynes_studio.canonical.ids import Minter
from haynes_studio.db.catalog import record_asset_version
from haynes_studio.db.migrate import migrate
from haynes_studio.db.schema import asset_sources, media_jobs, queue_lane_events, worker_lane_grants
from haynes_studio.errors import ContractError
from haynes_studio.mcp.server import create_app
from haynes_studio.queue.media_worker import MediaWorker
from haynes_studio.queue.worker_api import WorkerAPIError
from haynes_studio.segmentation.backend import Engine
from haynes_studio.segmentation.profile import Profile, SegmentationError, digest
from haynes_studio.segmentation.service import listening
from haynes_studio.store import blob_locator, canonical_json
from haynes_studio.voice import validate_job
from tests.assets.test_occlusion import SIZE, detector, library_image, png, segmenter
from tests.db.test_foreground_admission import build, install_sets, photo, select_set
from tests.db.test_matte_jobs import conflict, expire, row_of
from tests.db.test_media_jobs import image_worker, job, studio, success
from tests.db.test_run_queue import queue, worker_api, worker_credentials
from tests.db.test_studio_api import engine, new_production, owner_engine, runtime_db, runtime_role, service
from tests.mcp.client import API_URL, call, connect, fail

pytestmark = pytest.mark.db
PATH = "/v1/asset-jobs/occlusion"
DIRECT = {"kind": "box", "xyxy": [10, 10, 40, 35]}
PNG = "image/png"
JSON = "application/json"


class SyntheticProfile(Profile):
    def verify(self, root):
        return digest(self.manifest())


def fake_graph(weights, phase, strategy):
    def observe(image, hint):
        if image.getpixel((0, 0))[0] == 80:
            raise SegmentationError("inference_failed")
        return segmenter(image, hint)

    return detector, observe


@pytest.fixture
def serving(tmp_path):
    profile = SyntheticProfile("sha256:" + "c" * 64, "d" * 40, "e" * 64, (("synthetic", "1"),))
    scratch = tmp_path / "segmentation"
    scratch.mkdir()
    with TemporaryDirectory(prefix="studio971-sock-") as directory:
        client = SegmentationClient(profile, digest(profile.manifest()), scratch=scratch,
                                    socket=Path(directory) / "segment.sock")
        with Engine(scratch, tmp_path, profile, factory=fake_graph) as backend, listening(client.socket, backend):
            yield client


@pytest.fixture
def enabled(studio, serving):
    studio.app.state.segmentation = serving.profile
    yield studio
    with studio.owner.begin() as conn:
        for table in (media_jobs, queue_lane_events, worker_lane_grants):
            conn.execute(table.delete().where(table.c.lane == "occlusion"))


def record(s, doc):
    with s.owner.begin() as conn:
        record_asset_version(conn, doc)


def stored(s, *, kind="set", production=None, color=50, occlusion=None, record_version=True):
    image = Image.new("RGB", SIZE, (color, 60, 70)) if kind == "set" else Image.new("RGBA", SIZE)
    if kind != "set":
        image.paste((color, 60, 70, 255), (5, 5, 45, 40))
    outcome, _ = library_image(s.store, image, kind, production_id=production,
                               key=f"still-{Minter().mint('asv')}")
    source = outcome.library.document(outcome.version.id)
    if occlusion is not None:
        source["occlusion"] = occlusion
    if record_version:
        record(s, source)
    return source


def enqueue(s, source, key, *, kind="foreground", target="table", label=None, hint=DIRECT, headers=None):
    browser, headers = (s.browser, s.csrf) if headers is None else (s.agent, headers)
    return browser.post(PATH, headers={**headers, "Idempotency-Key": key}, json={
        "source_version_id": source["id"], "kind": kind, "key": target, "label": label, "hint": hint,
    })


def worker(s, serving, *, api=None):
    return MediaWorker(api or worker_api(s, lane="occlusion"), lane="occlusion", store=s.store, client=serving)


def recorded_masks(s):
    with s.owner.connect() as conn:
        return set(conn.scalars(sa.select(asset_sources.c.source_key).where(
            asset_sources.c.source_key.like("occlusion:%"),
        )))


def test_human_scope_replay_and_promoted_result(enabled, serving, monkeypatch):
    s = enabled
    source = stored(s, production=s.production_id)
    assert enqueue(s, source, "agent-denied", headers=s.auth).status_code == 403
    queued = success(enqueue(s, source, "one-target"), 202)
    assert queued["target_id"] == source["id"] and queued["kind"] == "occlusion"
    identifier = queued["id"]
    assert success(enqueue(s, source, "one-target")) == queued
    mismatch = enqueue(s, source, "one-target", target="other")
    assert mismatch.status_code == 422 and mismatch.json()["error"]["code"] == "idempotency.mismatch"
    assert enqueue(s, source, "bad-hint", hint={"kind": "point", "xy": list(SIZE)}).status_code == 422
    legacy = stored(s, production=s.production_id, record_version=False)
    legacy["provenance"]["generator"]["params"] = {
        "occlusion": {"focal_props": [{"key": "cup", "label": "cup", "hint": DIRECT}]},
    }
    record(s, legacy)
    assert enqueue(s, legacy, "free-form", kind="prop", target="cup", hint=None).status_code == 422
    assert s.agent.get(f"/v1/jobs/{identifier}", headers=s.outsider).status_code == 404
    other_lane = worker_api(s, lane="image")
    with pytest.raises(WorkerAPIError, match="work.lane_forbidden"):
        other_lane.claim("occlusion")
    api = worker_api(s, lane="occlusion")
    original_post = api.client.post

    def checked_post(url, **kwargs):
        response = original_post(url, **kwargs)
        if url.endswith("/complete"):
            assert response.status_code == 200, response.text
        return response

    monkeypatch.setattr(api.client, "post", checked_post)
    assert worker(s, serving, api=api).tick()
    finished = job(s, identifier)
    assert not validate_job(finished)
    assert finished["status"] == "succeeded" and finished["result_is_current"] is False, finished["error"]
    result = success(s.browser.get(f"/v1/jobs/{identifier}/result"))
    assert result["capabilities"] == ["mask"] and result["state"] == "promoted"
    assert result["scope"] == source["scope"]
    preview = s.browser.get(f"/v1/jobs/{identifier}/media/{result['content']['sha256']}")
    assert preview.status_code == 200 and digest(preview.content) == result["content"]["sha256"]
    binding = result["segmentation"]
    assert binding["source_version_id"] == source["id"]
    assert binding["still_sha256"] == source["content"]["sha256"]
    assert binding["request_sha256"] == digest(canonical_json(finished["occlusion"]["request"]))
    assert binding["profile_sha256"] == serving.profile_sha256
    s.app.state.segmentation = None
    assert success(enqueue(s, source, "one-target"))["result_version_id"] == result["id"]
    assert enqueue(s, source, "new-without-pin").status_code == 503
    assert success(s.browser.get("/v1/queue/lanes"))["items"][-1]["lane"] == "occlusion"

    async def read_mcp():
        app = create_app(API_URL, api_transport=httpx.ASGITransport(app=s.app))
        async with app.router.lifespan_context(app):
            async with connect(app, s.reader["Authorization"]) as session:
                result = await call(session, "studio_get_job", job_id=identifier)
                assert result["occlusion"] == finished["occlusion"]
            async with connect(app, s.outsider["Authorization"]) as session:
                assert (await fail(session, "studio_get_job", job_id=identifier))["code"] == "not_found"

    asyncio.run(read_mcp())


@pytest.mark.parametrize("dispatched", [False, True])
def test_expired_claim_reuses_signed_inputs_and_fences_duplicate_completion(enabled, serving, monkeypatch, dispatched):
    s = enabled
    source = stored(s, production=s.production_id)
    identifier = success(enqueue(s, source, "reclaim"), 202)["id"]
    first = worker_api(s, lane="occlusion").claim("occlusion")
    if dispatched:
        first.publish()
    expire(s, identifier)
    lane = "/v1/queue/lanes/occlusion"
    success(s.browser.put(lane, headers=s.csrf, json={"paused": True}))
    replacement = worker_api(s, lane="occlusion")
    assert replacement.claim("occlusion") is None
    assert success(enqueue(s, source, "reclaim"))["status"] == "running"
    success(s.browser.put(lane, headers=s.csrf, json={"paused": False}))
    current = replacement.claim("occlusion")
    assert current.identity["fence"] == first.identity["fence"] + 1
    assert current.body["inputs"] == first.body["inputs"]
    assert current.body["job"]["input_signature"] == first.body["job"]["input_signature"]
    monkeypatch.setattr(replacement, "claim", lambda lane: current)
    completion = current.complete
    seen = []

    def complete(body):
        conflict(lambda: first.complete(body))
        seen.append(body)
        return completion(body)

    monkeypatch.setattr(current, "complete", complete)
    assert worker(s, serving, api=replacement).tick()
    assert job(s, identifier)["status"] == "succeeded"
    conflict(lambda: completion(seen[0]))
    assert f"occlusion:{identifier}" in recorded_masks(s)


@pytest.mark.parametrize(("color", "label", "hint", "status", "reason"), [
    (50, "no match", None, "needs_hint", "no_match"),
    (80, "table", DIRECT, "failed", "inference_failed"),
])
def test_diagnostic_receipt_creates_no_mask_and_new_key_can_retry(enabled, serving, color, label, hint, status, reason):
    s = enabled
    source = stored(s, color=color, production=s.production_id)
    baseline = recorded_masks(s)
    written = []
    original = s.store.publish

    def record_write(data, **kwargs):
        written.append(kwargs["media_type"])
        return original(data, **kwargs)

    s.store.publish = record_write
    identifier = success(enqueue(s, source, "diagnostic", kind="prop", label=label, hint=hint), 202)["id"]
    run = worker(s, serving)
    assert run.tick()
    result = job(s, identifier)
    assert not validate_job(result)
    assert result["status"] == "failed" and result["result_version_id"] is None
    assert result["error"]["code"] == f"occlusion.{reason}"
    diagnostic = result["error"]["diagnostic"]
    assert diagnostic["status"] == status
    assert s.store.verify(blob_locator(s.production_id, diagnostic["receipt_sha256"], JSON),
                          diagnostic["receipt_sha256"]) == "present"
    assert written == [JSON] and recorded_masks(s) == baseline
    assert s.browser.get(f"/v1/jobs/{identifier}/result").status_code == 404
    same = success(enqueue(s, source, "diagnostic", kind="prop", label=label, hint=hint))
    assert same["status"] == "failed" and same["id"] == identifier
    if status == "needs_hint":
        retry = success(enqueue(s, source, "corrected-hint", kind="prop", label=label, hint=DIRECT), 202)
        assert retry["id"] != identifier and run.tick()
        assert job(s, retry["id"])["status"] == "succeeded"


def test_completion_refuses_mismatched_still_receipt_and_mask(enabled, serving, monkeypatch):
    s = enabled
    source = stored(s, production=s.production_id)
    other = stored(s, production=s.production_id, color=51)
    api = worker_api(s, lane="occlusion")
    run = worker(s, serving, api=api)
    other_job = success(enqueue(s, other, "other-still"), 202)["id"]
    assert run.tick()
    other_result = success(s.browser.get(f"/v1/jobs/{other_job}/result"))
    other_receipt = other_result["segmentation"]["receipt_sha256"]
    with s.store.open(blob_locator(s.production_id, other_receipt, JSON)) as handle:
        other_bytes = handle.read()
    identifier = success(enqueue(s, source, "verify-result"), 202)["id"]
    current = api.claim("occlusion")
    monkeypatch.setattr(api, "claim", lambda lane: current)
    complete = current.complete
    open_blob = s.store.open
    baseline = recorded_masks(s)

    def refused(body):
        with pytest.raises(WorkerAPIError) as error:
            complete(body)
        assert error.value.status == 422 and error.value.code == "work.result_invalid"
        assert recorded_masks(s) == baseline
        assert job(s, identifier)["status"] == "running"

    def validate(body):
        result = body["result"]
        refused({"result": {**result, "receipt": {"sha256": other_receipt, "bytes": len(other_bytes)}}})
        wrong = s.store.publish(png(Image.new("L", SIZE, 255)), scope=s.production_id, media_type=PNG)
        refused({"result": {**result, "mask": {"sha256": wrong.sha256, "bytes": wrong.bytes}}})
        refused({"result": {**result, "mask": None}})
        with monkeypatch.context() as patch:
            patch.setattr(s.store, "open", lambda locator: open_blob(
                other["content"]["locator"] if locator == source["content"]["locator"] else locator,
            ))
            refused(body)
        return complete(body)

    monkeypatch.setattr(current, "complete", validate)
    assert run.tick()
    assert job(s, identifier)["status"] == "succeeded"
    assert recorded_masks(s) - baseline == {f"occlusion:{identifier}"}


def focal(prop, hint):
    return {"focal_props": [{
        "key": "cup", "label": "cup", "depth": "separate", "layer_order": 15,
        "source_asset_version_id": prop["id"], "hint": hint,
    }]}


@pytest.mark.parametrize("prop_first", [False, True])
@pytest.mark.parametrize("in_bounds", [False, True])
def test_catalog_checks_focal_prop_bounds_in_either_insert_order(studio, prop_first, in_bounds):
    s = studio
    prop = stored(s, kind="prop", production=s.production_id, record_version=False)
    # Only one measured dimension is enough to enforce its own bound.
    del prop["content"]["height"]
    hint = {"kind": "box", "xyxy": [10, 10, SIZE[0] if in_bounds else SIZE[0] + 1, SIZE[1]]}
    plate = stored(s, production=s.production_id, occlusion=focal(prop, hint), record_version=False)
    first, second = (prop, plate) if prop_first else (plate, prop)
    record(s, first)
    if in_bounds:
        record(s, second)
    else:
        with pytest.raises(ContractError, match="occlusion.hint_bounds"):
            record(s, second)


def test_stored_focal_hint_and_output_follow_the_sets_scope(enabled, serving):
    s = enabled
    common = stored(s, kind="prop")
    plate = stored(s, production=s.production_id, occlusion=focal(common, DIRECT))
    conflict = enqueue(s, plate, "override", kind="prop", target="cup", label="forged", hint=None)
    assert conflict.status_code == 422 and conflict.json()["error"]["code"] == "occlusion.declared_target"
    response = enqueue(s, plate, "declared-cup", kind="prop", target="cup", hint=None)
    identifier = success(response, 202)["id"]
    queued = job(s, identifier)["occlusion"]
    assert queued["set_version_id"] == plate["id"] and queued["source_version_id"] == common["id"]
    assert queued["request"]["hint"] == DIRECT and queued["request"]["target"]["label"] == "cup"
    assert worker(s, serving).tick()
    mask = success(s.browser.get(f"/v1/jobs/{identifier}/result"))
    assert mask["scope"] == plate["scope"] and mask["kind"] == "prop"
    assert mask["segmentation"]["still_sha256"] == common["content"]["sha256"]

    other = new_production(s.browser, s.csrf)
    foreign = stored(s, kind="prop", production=other)
    denied = stored(s, production=s.production_id, occlusion=focal(foreign, DIRECT))
    assert enqueue(s, denied, "foreign-cup", kind="prop", target="cup", hint=None).status_code == 404
    common_id = success(enqueue(s, common, "shared-cup", kind="prop", label="cup"), 202)["id"]
    assert worker(s, serving).tick()
    result = success(s.browser.get(f"/v1/jobs/{common_id}/result"))
    assert result["scope"] == {"production_id": None}
    assert s.agent.get(f"/v1/jobs/{common_id}", headers=s.reader).status_code == 404


def test_admission_uses_actual_dimensions_when_catalog_omits_them(enabled):
    s = enabled
    prop = stored(s, kind="prop", production=s.production_id, record_version=False)
    del prop["content"]["width"]
    record(s, prop)
    plate = stored(s, production=s.production_id, occlusion=focal(prop, {"kind": "point", "xy": [SIZE[0], 20]}))
    res = enqueue(s, plate, "unknown-width", kind="prop", target="cup", hint=None)
    assert res.status_code == 422 and res.json()["error"]["code"] == "occlusion.invalid_input"


def test_produced_mask_pins_through_new_photo_and_build_admissions(queue, serving, tmp_path):
    q = queue
    install_sets(q, tmp_path)
    q.app.state.segmentation = serving.profile
    origin = stored(q, production=q.production_id)
    identifier = success(enqueue(q, origin, "role-mask"), 202)["id"]
    try:
        assert worker(q, serving).tick()
        mask = success(q.browser.get(f"/v1/jobs/{identifier}/result"))
        pin = {"version_id": mask["id"], "sha256": mask["content"]["sha256"],
               "still_sha256": origin["content"]["sha256"], "width": SIZE[0], "height": SIZE[1]}
        declared = {**deepcopy(origin), "id": Minter().mint("asv"), "number": 2,
                    "occlusion": {"foreground": [{"key": "table", "layer_order": 30, "mask": pin}]}}
        record(q, declared)
        select_set(q, declared["id"])
        run_id = success(build(q, "build-role-pin"), 201)["id"]
        frozen = success(q.browser.get(f"/v1/runs/{run_id}/snapshot"))
        assert frozen["toolchain_request"]["foreground_roles"][0]["version_id"] == mask["id"]
        photo_id = success(photo(q, "job-role-pin"), 202)["id"]
        assert row_of(q, photo_id)["inputs"]["foreground_roles"][0]["version_id"] == mask["id"]
        assert image_worker(q)[0].tick() and job(q, photo_id)["status"] == "succeeded"

        other = stored(q, production=q.production_id, color=51)
        wrong_pin = {**pin, "still_sha256": other["content"]["sha256"]}
        wrong = {**other, "id": Minter().mint("asv"), "number": 2,
                 "occlusion": {"foreground": [{"key": "table", "layer_order": 30, "mask": wrong_pin}]}}
        record(q, wrong)
        select_set(q, wrong["id"])
        for response in (photo(q, "wrong-job-mask"), build(q, "wrong-build-mask")):
            assert response.status_code == 422 and response.json()["error"]["code"] == "occlusion.mask_stale"

        hints_only = {**origin, "id": Minter().mint("asv"), "number": 3,
                      "occlusion": {"focal_props": [{"key": "cup", "label": "cup", "depth": "unspecified"}]}}
        record(q, hints_only)
        q.app.state.segmentation = None
        select_set(q, hints_only["id"])
        legacy = success(build(q, "hints-only-build"), 201)["id"]
        snapshot = success(q.browser.get(f"/v1/runs/{legacy}/snapshot"))
        assert "foreground_roles" not in snapshot["toolchain_request"]
        old_photo = success(photo(q, "hints-only-photo"), 202)["id"]
        assert "foreground_roles" not in row_of(q, old_photo)["inputs"]
    finally:
        with q.owner.begin() as conn:
            for table in (media_jobs, queue_lane_events, worker_lane_grants):
                conn.execute(table.delete().where(table.c.lane == "occlusion"))


def test_lane_migration_preserves_existing_work_and_refuses_to_erase_occlusion(enabled, runtime_role):
    s = enabled
    source = stored(s, production=s.production_id)
    migrate(s.owner, "downgrade", "0013_matte_jobs")
    try:
        assert enqueue(s, source, "before-migration").status_code == 503
        assert "occlusion" not in {lane["lane"] for lane in success(s.browser.get("/v1/queue/lanes"))["items"]}
        previous = success(s.browser.post("/v1/asset-jobs", headers={**s.csrf, "Idempotency-Key": "old-image"},
                                          json={"kind": "prop", "name": "Synthetic cup", "prompt": "A cup"}), 202)
        saved = row_of(s, previous["id"])
    finally:
        migrate(s.owner, runtime_role=runtime_role[0])
    assert row_of(s, previous["id"]) == saved
    assert worker_api(s, lane="image").claim("image").identity["job_id"] == previous["id"]
    queued = success(enqueue(s, source, "after-migration"), 202)
    with pytest.raises(sa.exc.IntegrityError):
        migrate(s.owner, "downgrade", "0013_matte_jobs")
    assert job(s, queued["id"])["status"] == "queued"
