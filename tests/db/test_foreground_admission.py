"""Frozen Build and photo admission pairs through the HTTP API and CPU workers."""

import asyncio
import base64
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
import sqlalchemy as sa
from PIL import Image

from haynes_studio.build.prebuild import snapshot_bytes
from haynes_studio.canonical.ids import Minter
from haynes_studio.canonical.model import Principal
from haynes_studio.db import catalog, drafts, jobs, runs
from haynes_studio.db.catalog import record_asset_version
from haynes_studio.db.schema import media_jobs
from haynes_studio.errors import ContractError
from haynes_studio.library import Library
from haynes_studio.library.model import signature
from haynes_studio.library.resolve import story_references
from haynes_studio.mcp.server import create_app
from haynes_studio.motion.winter_menu import complete_block
from haynes_studio.queue.inputs import estimate, freeze, prepare_queue
from haynes_studio.queue.media_inputs import checked_photo, documents, photo_plan, photo_request
from haynes_studio.queue.wan import ProductWan
from haynes_studio.queue.worker import BuildWorker
from haynes_studio.render.encode import decode_frames
from haynes_studio.store import blob_locator
from haynes_studio.voice.jobs import new_job
from haynes_studio.voice.model import Job
from tests.build_story import fixtures as f
from tests.db.test_media_jobs import PROVENANCE, current_board, image_worker, patch, success, upload
from tests.db.test_run_queue import (
    STORY, add_sound_bed, engine, owner_engine, queue, queue_run, read_run, runtime_db, runtime_role,
    service, worker_api,
)
from tests.db.test_studio_api import client, new_production, register_agent
from tests.layered import media
from tests.layered.test_foreground_roles import RED_BOX, SIZE, png
from tests.mcp.client import API_URL, UPLOAD_URL, call, connect, fail
from tests.queue.fake_wan import FakeWan

pytestmark = pytest.mark.db
MASK = f.ident("asv", 70)
PLAIN = f.ident("asv", 71)
SOURCE = (108, 192)


def setting(still, loop=None):
    return {"asset_version_id": still, "motion_asset_version_id": loop,
            "foreground_edge_px": None, "foreground_feather_px": None, "legacy_fire": None}


def install_sets(q, tmp_path, *, defect=None, loop_source=None):
    root = tmp_path / "role-store"
    root.mkdir()
    world = f.World(root, f.LocalStore(root))
    doll = Image.new("RGBA", SIZE)
    doll.paste((255, 0, 0, 255), RED_BOX)
    still = world.still(f.STILL["a"], 10, png(doll))
    world.loop(f.LOOP["a"], 20, still_sha=still, clip=media.doll_clip(f.LOOP_N, moving=False),
               start=media.start_image(tint=0))
    world.voice(f.VOICE["a"], 30, f.STOCK["a"])
    still_size = (109, 192) if defect == "decoded_still_size" else SOURCE
    plate_sha = world.still(f.PLATE, 40, png(Image.new("RGB", still_size)), kind="set")
    plate = world.docs[-1]
    plate["content"].update(width=SOURCE[0], height=SOURCE[1])
    original = {**deepcopy(plate), "id": PLAIN}
    plate["number"] = 2
    world.docs.insert(world.docs.index(plate), original)
    mask_size = (109, 192) if defect == "wrong_size" else still_size
    mask_image = Image.new("L", mask_size, 255)
    if defect == "non_binary":
        mask_image.putpixel((0, 0), 127)
    mask_sha = world.still(MASK, 70, png(mask_image))
    mask = world.docs[-1]
    mask.update(kind="prop", capabilities=["mask"], attributes={})
    mask["content"].update(width=SOURCE[0], height=SOURCE[1])
    if defect == "catalogue_mask_size":
        mask["content"].update(width=109, height=192)
    elif defect == "no_mask_capability":
        mask["capabilities"] = ["opaque_photo"]
    elif defect == "non_png_type":
        mask["content"]["media_type"] = "image/webp"  # The bytes still decode as PNG.
    if defect == "candidate":
        mask["state"] = "candidate"
    plate["occlusion"] = {"foreground": [{
        "key": "table", "layer_order": 30,
        "mask": {"version_id": MASK, "sha256": "a" * 64 if defect == "stale" else mask_sha,
                 "still_sha256": plate_sha, "width": SOURCE[0], "height": SOURCE[1]},
    }]}
    if loop_source is not None:
        world.loop(f.SET_LOOP, 41, still_sha=plate_sha, clip=media.set_clip(f.SET_N),
                   start=media.set_plate(), subject="set", frames=f.SET_N)
        loop = world.docs[-1]
        if loop_source != "discovered":
            del loop["motion"]["still_sha256"]
            loop["motion"] = complete_block(loop["motion"], loop["content"]["sha256"])
        if loop_source != "absent":
            source = PLAIN if loop_source == "plain" else f.PLATE
            loop["provenance"]["generator"]["source_asset_version_ids"] = [source]
    add_sound_bed(q, tmp_path)
    ids = {doc["id"]: Minter().mint("asv") for doc in world.docs}
    assets = {id_: Minter().mint("ast") for id_ in {doc["asset_id"] for doc in world.docs}}
    other = new_production(q.browser, q.csrf) if defect == "wrong_scope" else q.production_id
    with q.engine.begin() as conn:
        for doc in world.docs:
            old_id = doc["id"]
            if old_id == MASK and defect == "missing_version":
                continue
            doc.update(id=ids[old_id], asset_id=assets[doc["asset_id"]])
            source_key = "fixture:role:" + doc["asset_id"]
            doc["provenance"]["source_key"] = source_key
            if doc["legacy"] is not None:
                doc["legacy"]["source_key"] = source_key
            if (content := doc["content"]) is not None:
                scope = other if old_id == MASK else q.production_id
                doc["scope"] = {"production_id": scope}
                if old_id != MASK or defect != "missing_bytes":
                    with world.store.open(content["locator"]) as data:
                        q.store.publish(data, scope=scope, media_type=content["media_type"])
                content["locator"] = blob_locator(scope, content["sha256"], content["media_type"])
            if doc.get("occlusion"):
                doc["occlusion"]["foreground"][0]["mask"]["version_id"] = ids[MASK]
            if doc.get("motion"):
                generator = doc["provenance"]["generator"]
                if "source_asset_version_ids" in generator:
                    generator["source_asset_version_ids"] = [ids[id_] for id_ in generator["source_asset_version_ids"]]
                digest = doc["motion"]["source"]["image_sha256"]
                with world.store.open(blob_locator(f.PRODUCTION, digest, "image/png")) as start:
                    q.store.publish(start, scope=q.production_id, media_type="image/png", expected_sha256=digest)
            record_asset_version(conn, doc)

    update_story(q, {
        "cast": [{"slot": "a", "name": "Synthetic cast", "voice_version_id": ids[f.VOICE["a"]]}],
        "set": setting(ids[PLAIN]),
        "layouts": {"default": {"height": 480, "bottom": 1360, "x": .5}},
        "motion_style": {"idle_scale": 0},
    })
    patch(q, q.board_id, {
        "cast": [{"slot": "a", "asset_version_id": ids[f.STILL["a"]], "motion_asset_version_id": ids[f.LOOP["a"]]}],
        "layout": {"preset": "default", "foreground": True},
        "method": {"layer": "layered", "motion": "i2v"},
        "photo": {"current_version_id": None, "prompt": None, "input_asset_version_ids": []},
    })
    return ids, mask_sha


def update_story(q, fields):
    path = f"/v1/stories/{q.story_id}"
    current = q.browser.get(path)
    return success(q.browser.patch(path, json=fields, headers={**q.csrf, "If-Match": current.headers["etag"]}))


def select_set(q, still, loop=None):
    return update_story(q, {"set": setting(still, loop)})


def build(q, key):
    revision = success(q.browser.get(f"/v1/stories/{q.story_id}"))["revision"]
    return queue_run(q, key, rev=revision)


def photo(q, key):
    return q.browser.post(f"/v1/boards/{q.board_id}/photo-jobs", json={},
                          headers={**q.csrf, "Idempotency-Key": key})


def set_foreground(q, enabled):
    patch(q, q.board_id, {"layout": {"preset": "default", "foreground": enabled}})


def run_worker(q, wan_client):
    return BuildWorker(worker_api(q), ProductWan(wan_client), store=q.store, stage_root=q.stage_root,
                       register=f.register(), tracker_story=STORY,
                       clock=q.clock.monotonic, pause=q.clock.advance,
                       transcriber=SimpleNamespace(name="Fixture ASR", transcribe=lambda _: ""))


def film_frame(q, run_id):
    run, _ = read_run(q, run_id)
    assert run["status"] == "succeeded", run["error"]
    locator = blob_locator(q.production_id, run["outputs"]["master_sha256"], "video/mp4")
    with q.store.open(locator) as master:
        return next(decode_frames(master))


def assert_refused(response, code):
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == code, response.text


def test_same_key_build_replay_keeps_frozen_inputs_while_new_build_checks_and_draws_masks(queue, tmp_path):
    q = queue
    ids, mask_sha = install_sets(q, tmp_path)
    original = success(build(q, "original"), 201)
    run_id = original["id"]
    snapshot_url = f"/v1/runs/{run_id}/snapshot"
    snapshot = q.browser.get(snapshot_url)
    assert snapshot.status_code == 200

    select_set(q, ids[f.PLATE])
    set_foreground(q, False)
    replay = success(queue_run(q, "original", rev=original["snapshot"]["story_revision"]))
    assert replay["id"] == run_id
    assert q.browser.get(snapshot_url).content == snapshot.content
    assert_refused(build(q, "new-refused"), "occlusion.foreground_required")
    with q.owner.connect() as conn:
        assert [row["id"] for row in runs.list_story(conn, q.story_id, None, 10)] == [run_id]

    set_foreground(q, True)
    admitted = success(build(q, "new-masked"), 201)["id"]
    frozen = success(q.browser.get(f"/v1/runs/{admitted}/snapshot"))
    assert {"id": ids[MASK], "kind": "prop", "sha256": mask_sha} in frozen["resolved_asset_versions"]
    assert frozen["toolchain_request"]["foreground_roles"] == [role_pin(ids, mask_sha)]
    select_set(q, ids[PLAIN])
    with FakeWan().client() as wan_client:
        worker = run_worker(q, wan_client)
        assert worker.tick() and worker.tick()
    assert np.count_nonzero(film_frame(q, run_id)) > 0
    assert np.count_nonzero(film_frame(q, admitted)) == 0


def role_pin(ids, digest):
    return {"key": "table", "layer_order": 30, "version_id": ids[MASK], "sha256": digest,
            "width": SOURCE[0], "height": SOURCE[1]}


def test_photo_reclaim_draws_frozen_inputs_while_new_photo_checks_and_draws_masks(queue, tmp_path):
    q = queue
    ids, mask_sha = install_sets(q, tmp_path)
    old_id = success(photo(q, "original"), 202)["id"]
    expire_image_claim(q, old_id)
    select_set(q, ids[f.PLATE])
    assert success(photo(q, "original"))["id"] == old_id
    new_id = success(photo(q, "new-layered"), 202)["id"]
    with q.owner.connect() as conn:
        row = jobs.get(conn, new_id)
    tampered = deepcopy(row["inputs"])
    assert tampered["foreground_roles"] == [role_pin(ids, mask_sha)]
    tampered["foreground_roles"][0]["layer_order"] = 5
    with pytest.raises(ContractError) as error:
        checked_photo(Job.from_document(row["document"]), tampered)
    assert [issue.rule for issue in error.value.violations] == ["job.input_changed"]
    worker, runner = image_worker(q)
    assert worker.tick() and worker.tick()
    assert not runner.calls
    for job_id, is_current, covered in ((old_id, False, False), (new_id, True, True)):
        result = success(q.browser.get(f"/v1/jobs/{job_id}"))
        assert result["status"] == "succeeded", result["error"]
        assert result["result_is_current"] is is_current
        sources = result["photo"]["source_assets"]
        if covered:
            assert {"version_id": ids[MASK], "sha256": mask_sha} in sources
        else:
            assert sources[0]["version_id"] == ids[PLAIN] and len(sources) == 2
        version = success(q.browser.get(f"/v1/jobs/{job_id}/result"))
        if is_current:
            board = current_board(q, q.board_id)
            assert board["photo"]["current_version_id"] == version["id"]
            assert board["derived"]["photo_state"] == "current"
        digest = version["content"]["sha256"]
        media = q.browser.get(f"/v1/jobs/{job_id}/media/{digest}")
        assert media.status_code == 200
        with Image.open(BytesIO(media.content)) as image:
            assert bool(np.count_nonzero(np.asarray(image))) is not covered
    patch(q, q.board_id, {"method": {"layer": "whole_frame", "motion": "i2v"}, "cast": []})
    assert_refused(photo(q, "new-whole-frame"), "occlusion.unsupported")
    assert_refused(build(q, "new-whole-frame"), "occlusion.unsupported")
    select_set(q, None)
    patch(q, q.board_id, {"photo": {"current_version_id": None, "prompt": "A workshop",
                                   "input_asset_version_ids": [ids[f.PLATE]]}})
    assert_refused(photo(q, "new-direct-reference"), "occlusion.unsupported")
    with q.owner.connect() as conn:
        assert set(conn.scalars(sa.select(media_jobs.c.id))) == {old_id, new_id}


def select_set_with_ordinary_mask_reference(q, ids):
    select_set(q, ids[f.PLATE])
    patch(q, q.board_id, {"photo": {"current_version_id": None, "prompt": None,
                                   "input_asset_version_ids": [ids[MASK]]}})


def test_generic_queued_build_does_not_turn_an_ordinary_reference_into_a_role(queue, tmp_path):
    q = queue
    ids, mask_sha = install_sets(q, tmp_path)
    select_set_with_ordinary_mask_reference(q, ids)
    with q.engine.begin() as conn:
        story = drafts.get_draft(conn, q.story_id).exchange()
        refs = {ref.version_id for ref in story_references(story)}
        prepared = prepare_queue(story, catalog.build_library(conn, story, refs))
        prepared.ensure_buildable()
        snapshot, frozen = freeze(prepared, studio=q.app.state.build_revision)
        assert {"id": ids[MASK], "kind": "prop", "sha256": mask_sha} in snapshot["resolved_asset_versions"]
        assert "foreground_roles" not in snapshot["toolchain_request"]
        data, digest = snapshot_bytes(snapshot)
        q.store.publish(data, scope=q.production_id, media_type="application/json", expected_sha256=digest)
        run = runs.enqueue(conn, snapshot=snapshot, snapshot_sha256=digest, library=frozen,
                           actor=f.OPERATOR["operator"], key="generic", estimate=estimate(prepared))
    with FakeWan().client() as wan_client:
        assert run_worker(q, wan_client).tick()

    # The reviewed region contains the doll's blue jacket against the black still.
    region = film_frame(q, run["id"])[1050:1080, 475:515]
    jacket = (region[..., 2] > 128) & (region[..., 0] < 80) & (region[..., 1] < 110)
    # PostgreSQL control on main 7fd085d, with the additive declaration omitted.
    assert np.count_nonzero(jacket) == 1_200


def expire_image_claim(q, job_id):
    claim = worker_api(q, lane="image").claim("image")
    assert claim.identity["job_id"] == job_id
    with q.owner.begin() as conn:
        conn.execute(media_jobs.update().where(media_jobs.c.id == job_id).values(
            claim_until=sa.func.clock_timestamp() - timedelta(seconds=1),
        ))


def test_legacy_photo_reclaim_uses_its_unmasked_signature_with_an_ordinary_reference(queue, tmp_path):
    q = queue
    ids, _ = install_sets(q, tmp_path)
    select_set_with_ordinary_mask_reference(q, ids)
    with q.engine.begin() as conn:
        draft = drafts.get_draft(conn, q.story_id)
        story, library = drafts.board_snapshot(conn, draft, q.board_id)
        frozen = {"story": story, "seed": 0, "library": documents(library)}
        assert ids[MASK] in library.versions
        # Sign using the original unmasked inputs. The job's frozen library still
        # contains the declaring set and the mask's ordinary reference.
        unmasked = deepcopy(frozen["library"])
        for version in unmasked:
            version.pop("occlusion", None)
        plan = photo_plan(story, q.board_id, Library.from_version_documents(unmasked))
        job = new_job("photo", q.board_id, photo_request(plan, 0), now=f.NOW,
                      by=Principal.from_document(f.OPERATOR["operator"]))
        jobs.enqueue(conn, job, position=jobs.lock_lane(conn, "image"), production=q.production_id,
                     story=q.story_id, board=q.board_id, inputs=frozen, key="legacy", signature=signature({}))
    expire_image_claim(q, job.id)
    worker, runner = image_worker(q)
    assert worker.tick()
    assert not runner.calls
    result = success(q.browser.get(f"/v1/jobs/{job.id}"))
    assert result["status"] == "succeeded", result["error"]
    assert result["result_is_current"]
    version = success(q.browser.get(f"/v1/jobs/{job.id}/result"))
    response = q.browser.get(f'/v1/jobs/{job.id}/media/{version["content"]["sha256"]}')
    assert response.status_code == 200
    # PNG from the successful reclaim of the same fixture on main 7fd085d.
    assert sha256(response.content).hexdigest() == "42390182c7c9499e4cd43492e7eb8cf809c6b36ce7ff18783e5efeb68fcc1c81"


@pytest.mark.parametrize("transport", ["http", "mcp"])
def test_external_photo_upload_checks_declaring_set_before_writing(queue, tmp_path, transport):
    q = queue
    ids, _ = install_sets(q, tmp_path)
    q.agent = client(q.app)
    _, q.auth = register_agent(q.owner, {q.production_id: ["read", "assets:upload"]})
    patch(q, q.board_id, {
        "method": {"layer": "whole_frame", "motion": "i2v"}, "cast": [],
        "photo": {"current_version_id": None, "prompt": "A workshop", "input_asset_version_ids": []},
    })
    data = png(Image.new("RGB", SOURCE, "white"))

    def attempt(still, refused):
        provenance = {**PROVENANCE, "source_asset_version_ids": [still]}
        if transport == "http":
            response = upload(q, q.board_id, data, provenance)
            if refused:
                assert_refused(response, "occlusion.unsupported")
                return None
            return success(response, 201)

        async def mcp():
            app = create_app(API_URL, api_transport=httpx.ASGITransport(app=q.app))
            revision = current_board(q, q.board_id)["revision"]
            async with app.router.lifespan_context(app), connect(app, q.auth["Authorization"], url=UPLOAD_URL) as session:
                op = fail if refused else call
                return await op(session, "studio_upload_photo", board_id=q.board_id, revision=revision,
                                media_type="image/png", data_base64=base64.b64encode(data).decode("ascii"),
                                provenance=provenance)

        outcome = asyncio.run(mcp())
        if refused:
            assert outcome["code"] == "occlusion.unsupported"
            return None
        return outcome

    select_set(q, ids[f.PLATE])
    assert_refused(photo(q, "blocked-generation"), "occlusion.unsupported")
    assert_refused(build(q, "blocked-build"), "occlusion.unsupported")
    attempt(ids[f.PLATE], refused=True)
    versions_url = f"/v1/boards/{q.board_id}/photo-versions"
    assert len(success(q.browser.get(versions_url))["items"]) == 1  # Existing fixture photo.
    select_set(q, ids[PLAIN])
    uploaded = attempt(ids[PLAIN], refused=False)
    assert not uploaded["selected"]  # D42 preserves the human-edited board's selection.
    assert uploaded["board_revision"] is None
    versions = success(q.browser.get(versions_url))["items"]
    assert len(versions) == 2
    [version] = [item for item in versions if item["id"] == uploaded["version"]["id"]]
    assert version["provenance"]["generator"]["source_asset_version_ids"] == [ids[PLAIN]]
    assert version["content"]["sha256"] == sha256(data).hexdigest()


@pytest.mark.parametrize(("defect", "code"), [
    ("missing_version", "mask_missing"), ("missing_bytes", "mask_missing"), ("stale", "mask_stale"),
    ("wrong_scope", "mask_missing"), ("wrong_size", "mask_size"),
    ("candidate", "mask_not_ready"), ("non_binary", "mask_invalid"),
    ("catalogue_mask_size", "mask_size"), ("decoded_still_size", "mask_size"),
    ("no_mask_capability", "mask_not_ready"), ("non_png_type", "mask_not_ready"),
])
def test_new_build_and_photo_refuse_unusable_masks_before_creating_rows(queue, tmp_path, defect, code):
    ids, _ = install_sets(queue, tmp_path, defect=defect)
    select_set(queue, ids[f.PLATE])
    assert_refused(build(queue, defect), f"occlusion.{code}")
    assert_refused(photo(queue, defect), f"occlusion.{code}")
    with queue.owner.connect() as conn:
        assert runs.list_story(conn, queue.story_id, None, 10) == []
        assert conn.scalar(sa.select(sa.func.count()).select_from(media_jobs)) == 0


def test_catalogue_does_not_load_foreground_masks_from_another_production(queue, tmp_path):
    ids, _ = install_sets(queue, tmp_path, defect="wrong_scope")
    with queue.owner.connect() as conn:
        foreign = catalog.version_library(conn, version_id=ids[MASK]).version(ids[MASK])
        with queue.store.open(foreign.content.locator) as data:
            assert sha256(data.read()).hexdigest() == foreign.content.sha256
        library = catalog.load_library(conn, {ids[f.PLATE]}, queue.production_id)
        expanded = catalog.with_foreground_masks(conn, library, ids[f.PLATE], queue.production_id)
        assert expanded.get(ids[MASK]) is None


@pytest.mark.parametrize("source", ["masked", "discovered", "plain", "absent"])
def test_new_build_uses_recorded_loop_provenance_without_inferring_from_bytes(queue, tmp_path, source):
    ids, _ = install_sets(queue, tmp_path, loop_source=source)
    if source == "discovered":
        select_set(queue, ids[PLAIN])
    elif source == "absent":
        select_set(queue, ids[f.PLATE], ids[f.SET_LOOP])
    else:
        select_set(queue, None, ids[f.SET_LOOP])
    response = build(queue, source)
    if source == "plain":
        admitted = success(response, 201)
        frozen = success(queue.browser.get(f'/v1/runs/{admitted["id"]}/snapshot'))
        assert ids[PLAIN] not in {entry["id"] for entry in frozen["resolved_asset_versions"]}
    else:
        assert_refused(response, "occlusion.unsupported")
        with queue.owner.connect() as conn:
            assert runs.list_story(conn, queue.story_id, None, 10) == []
    if source == "masked":
        assert_refused(photo(queue, "layered-masked-loop"), "occlusion.unsupported")
        patch(queue, queue.board_id, {
            "method": {"layer": "whole_frame", "motion": "i2v"}, "cast": [],
            "photo": {"current_version_id": None, "prompt": "A workshop", "input_asset_version_ids": []},
        })
        success(photo(queue, "whole-frame-ignores-loop"), 202)
