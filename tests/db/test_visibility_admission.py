"""New Build visibility through PostgreSQL, the API and a local CPU worker."""

import asyncio
from copy import deepcopy
import json
from typing import get_args

import httpx
import pytest

from haynes_studio.build.prebuild import snapshot_bytes
from haynes_studio.build.validate import validate_run_snapshot
from haynes_studio.db import catalog, drafts, jobs, runs
from haynes_studio.db.runs import database_time
from haynes_studio.db.schema import run_check_overrides
from haynes_studio.layered.renderer import LayeredRenderer
from haynes_studio.library.resolve import story_references
from haynes_studio.mcp.arguments import BOARD_EDIT_FIELDS
from haynes_studio.mcp.server import create_app
from haynes_studio.queue.inputs import estimate, freeze, prepare_queue
from haynes_studio.queue.worker_api import WorkerAPIError
from haynes_studio.render.visibility import VISIBILITY_CHECK
from haynes_studio.store import canonical_json
from tests.build_story import fixtures as f
from tests.db.test_foreground_admission import (
    assert_refused, build, install_sets, photo, run_worker, select_set, update_story,
)
from tests.db.test_media_jobs import current_board, image_worker, patch, success
from tests.db.test_run_queue import engine, owner_engine, queue, queue_run, read_run, runtime_db, runtime_role, service
from tests.db.test_studio_api import register_agent
from tests.mcp.client import API_URL, call, connect, fail
from tests.queue.fake_wan import FakeWan

pytestmark = pytest.mark.db
DECLARATION = {"slot": "a", "frames": [0, 5, 11]}


def snapshot(q, run_id):
    response = q.browser.get(f"/v1/runs/{run_id}/snapshot")
    assert response.status_code == 200
    return response


def visibility_of(run):
    return [check for check in run["checks"] if check["check"] == VISIBILITY_CHECK]


def completion_evidence(result):
    return {key: result[key] for key in ("stages", "outputs", "checks", "provenance", "delivery_id")}


def assert_completion_refused(q, claim, evidence, code):
    with pytest.raises(WorkerAPIError) as refused:
        claim.complete(evidence)
    assert (refused.value.status, refused.value.code) == (422, code)
    run_id = claim.identity["run_id"]
    assert read_run(q, run_id)[0]["delivery_id"] is None
    assert q.store.stage_record(q.production_id, run_id, "delivery") is None


def test_visibility_write_scope_and_old_patch(queue):
    q = queue
    story_path = f"/v1/stories/{q.story_id}"
    board_path = f"/v1/boards/{q.board_id}"
    _, writer = register_agent(q.owner, {q.production_id: ["read", "draft:write"]})
    _, reader = register_agent(q.owner, {q.production_id: ["read"]})
    current = success(q.browser.get(story_path))["revision"]
    for credential in (writer, reader):
        refused = q.browser.post(story_path + "/boards", json={"visibility": DECLARATION},
                                 headers={**credential, "If-Match": str(current)})
        assert refused.status_code == 403
        expected = "visibility.person_required" if credential == writer else "auth.forbidden"
        assert refused.json()["error"]["code"] == expected
    created = success(q.browser.post(story_path + "/boards", json={"visibility": DECLARATION},
                                     headers={**q.csrf, "If-Match": str(current)}), 201)
    assert created["visibility"] == DECLARATION

    for malformed in ([], False, {"slot": "a", "frames": []}, {"slot": "A", "frames": [0]},
                      {"slot": "a", "frames": [-1]}, {"slot": "a", "frames": [0, 0]},
                      {"slot": "a", "frames": [True]}, {"slot": "a", "frames": list(range(17))},
                      {"slot": "a", "frames": [0], "extra": True}):
        baseline = current_board(q, q.board_id)
        refused = q.browser.patch(board_path, json={"visibility": malformed},
                                  headers={**q.csrf, "If-Match": str(baseline["revision"])})
        assert refused.status_code == 422, refused.text
        assert current_board(q, q.board_id) == baseline

    patch(q, q.board_id, {"visibility": DECLARATION})
    kept = patch(q, q.board_id, {"layout": {"preset": "default", "foreground": False}})
    assert kept["visibility"] == DECLARATION
    for value in (None, {}, {"slot": "b", "frames": [0]}):
        headers = {**writer, "If-Match": str(kept["revision"])}
        refusal = q.browser.patch(board_path, json={"visibility": value}, headers=headers)
        assert refusal.status_code == 403 and refusal.json()["error"]["code"] == "visibility.person_required"
    removed = q.browser.delete(board_path, headers=headers)
    assert removed.status_code == 403 and removed.json()["error"]["code"] == "visibility.person_required"

    async def mcp():
        app = create_app(API_URL, api_transport=httpx.ASGITransport(app=q.app))
        async with app.router.lifespan_context(app), connect(app, writer["Authorization"]) as session:
            board = await call(session, "studio_get_board", board_id=q.board_id,
                               fields=list(get_args(BOARD_EDIT_FIELDS)))
            assert board["visibility"] == DECLARATION
            for value in (DECLARATION, None, {}):
                error = await fail(session, "studio_patch_board", board_id=q.board_id,
                                   revision=kept["revision"], patch={"visibility": value})
                assert error["code"] == "visibility.person_required"

    asyncio.run(mcp())
    for empty in (None, {}):
        patch(q, q.board_id, {"visibility": DECLARATION})
        assert "visibility" not in patch(q, q.board_id, {"visibility": empty})
        with q.owner.connect() as conn:
            assert "visibility" not in drafts.get_draft(conn, q.story_id).boards[q.board_id]


def test_visibility_refusals_are_before_run_creation(queue, tmp_path):
    q = queue
    patch(q, q.board_id, {"visibility": DECLARATION})
    assert_refused(build(q, "whole-frame"), "visibility.method_unsupported")
    # The fixture sets up layers and valid assets. The existing declaration stays on the board.
    revision = success(q.browser.get(f"/v1/stories/{q.story_id}"))["revision"]
    install_sets(q, tmp_path, draft_revision=revision)
    patch(q, q.board_id, {"visibility": {"slot": "b", "frames": [0]}})
    assert_refused(build(q, "absent"), "visibility.slot_absent")
    patch(q, q.board_id, {"visibility": {"slot": "a", "frames": [12]}})
    assert_refused(build(q, "too-late"), "visibility.frame_out_of_range")
    patch(q, q.board_id, {
        "lines": [{"speaker": "a", "text": "The voice is still pending", "gap_before_ms": None}],
        "timing": {"lead_ms": 0, "tail_ms": 750, "hold_ms": None},
        "voice": {"style": "cast", "current_version_id": None},
        "method": {"layer": "layered", "motion": "s2v"},
        "seeds": {"s2v:a": 11},
        "visibility": DECLARATION,
    })
    assert_refused(build(q, "unresolved"), "visibility.timing_unavailable")
    with q.owner.connect() as conn:
        assert runs.list_story(conn, q.story_id, None, 10) == []


def test_snapshot_visibility_admission_must_match_the_frozen_board(queue, tmp_path):
    q = queue
    install_sets(q, tmp_path)
    patch(q, q.board_id, {"visibility": DECLARATION})
    run = success(build(q, "declared"), 201)
    frozen = snapshot(q, run["id"]).json()
    assert validate_run_snapshot(frozen) == []
    frozen["visibility_admission"]["boards"][q.board_id]["frames"] = [3]
    assert [(error.rule, error.path) for error in validate_run_snapshot(frozen)] == [
        ("visibility.pin_mismatch", f"/visibility_admission/boards/{q.board_id}"),
    ]


def test_completion_requires_admitted_poses_from_the_staged_segment(queue, tmp_path, monkeypatch):
    q = queue
    monkeypatch.setattr(runs, "database_time", database_time)
    install_sets(q, tmp_path, mask_left=108)
    patch(q, q.board_id, {"visibility": DECLARATION})
    other = success(build(q, "other-segment"), 201)
    with FakeWan().client() as wan:
        worker = run_worker(q, wan)
        assert worker.tick()
        other_result = read_run(q, other["id"])[0]
        assert other_result["status"] == "succeeded", other_result["error"]
        [other_check] = visibility_of(other_result)

        # Move the slot to make another visible segment of the same board and poses.
        update_story(q, {"layouts": {"default": {"height": 480, "bottom": 1360, "x": .55}}})
        current = success(build(q, "delivered-segment"), 201)

        def verify(claim, result):
            evidence = completion_evidence(result)
            [check] = visibility_of(evidence)
            assert check["result"] == other_check["result"] == "pass"
            assert check["measured"]["segment_sha256"] != other_check["measured"]["segment_sha256"]

            missing = {**evidence, "checks": [item for item in evidence["checks"] if item is not check]}
            assert_completion_refused(q, claim, missing, "visibility.check_missing")

            substituted = deepcopy(evidence)
            [forged] = visibility_of(substituted)
            forged["measured"]["poses"] = [{**forged["measured"]["poses"][0], "frame": 3}]
            assert_completion_refused(q, claim, substituted, "visibility.check_failed")

            wrong_segment = {**evidence, "stages": other_result["stages"],
                             "checks": [other_check if item is check else item for item in evidence["checks"]]}
            assert_completion_refused(q, claim, wrong_segment, "visibility.check_failed")
            assert claim.complete(evidence)["status"] == "succeeded"

        monkeypatch.setattr(worker, "_complete", verify)
        assert worker.tick()
    delivered = read_run(q, current["id"])[0]
    assert delivered["status"] == "succeeded" and delivered["delivery_id"]


@pytest.mark.parametrize(("mask_left", "verdict", "error"), [
    (0, "hidden", "build.check_failed"),
    (57, "uncertain", "visibility.review_required"),
])
def test_frozen_build_replay_delivery_and_person_override(queue, tmp_path, monkeypatch, mask_left, verdict, error):
    q = queue
    monkeypatch.setattr(runs, "database_time", database_time)
    ids, _ = install_sets(q, tmp_path, mask_left=mask_left)
    select_set(q, ids[f.PLATE])
    old = success(build(q, "original"), 201)
    legacy_snapshot = snapshot(q, old["id"]).content
    patch(q, q.board_id, {"visibility": DECLARATION})
    new = success(build(q, "declared"), 201)
    frozen = snapshot(q, new["id"]).json()
    assert frozen["visibility_admission"] == {
        "schema": "studio.visibility-admission/v1", "boards": {q.board_id: DECLARATION},
    }
    with FakeWan().client() as wan:
        worker = run_worker(q, wan)
        assert worker.tick() and worker.tick()

    legacy, _ = read_run(q, old["id"])
    assert legacy["status"] == "succeeded" and not visibility_of(legacy)
    checked, etag = read_run(q, new["id"])
    assert checked["status"] == "failed" and checked["delivery_id"] is None
    assert checked["error"]["code"] == error
    [measurement] = visibility_of(checked)
    assert measurement["result"] == "fail" and measurement["measured"]["verdict"] == verdict
    assert measurement["measured"]["measurement_stage"] == "composed_pre_encode"
    assert measurement["measured"]["segment_sha256"] == legacy["stages"][0]["segment_sha256"]
    assert [pose["frame"] for pose in measurement["measured"]["poses"]] == DECLARATION["frames"]
    assert all(pose["unoccluded_pixels"] > 0 for pose in measurement["measured"]["poses"])
    for queued, finished, key in ((old, legacy, "original"), (new, checked, "declared")):
        replay = success(queue_run(q, key, rev=queued["snapshot"]["story_revision"]))
        assert replay["id"] == finished["id"] and replay["checks"] == finished["checks"]
    assert snapshot(q, old["id"]).content == legacy_snapshot

    path = f"/v1/runs/{new['id']}/checks/{VISIBILITY_CHECK}/overrides"
    _, agent = register_agent(q.owner, {q.production_id: ["read", "runs:queue"]})
    body = {"artifact": measurement["artifact"], "reason": "Reviewed the rendered frame"}
    assert q.browser.post(path, json=body, headers={**agent, "If-Match": etag}).status_code == 403
    bad = q.browser.post(path, json={**body, "artifact": "0" * 64}, headers={**q.csrf, "If-Match": etag})
    assert bad.status_code == 409
    if verdict == "hidden":
        refused = q.browser.post(path, json=body, headers={**q.csrf, "If-Match": etag})
        assert refused.status_code == 409 and refused.json()["error"]["code"] == "check.not_overridable"
        assert read_run(q, new["id"]) == (checked, etag)

        # An earlier version could record and freeze a review of hidden evidence.
        decision = {"by": checked["queued_by"], "reason": body["reason"]}
        prior = {**decision, "check": VISIBILITY_CHECK, "artifact": body["artifact"],
                 "at": checked["finished_at"]}
        with q.owner.begin() as conn:
            conn.execute(run_check_overrides.insert().values(
                run_id=new["id"], artifact=body["artifact"], document=prior,
            ))
        fresh = success(build(q, "hidden-fresh"), 201)
        assert snapshot(q, fresh["id"]).json()["visibility_admission"] == frozen["visibility_admission"]
        assert read_run(q, new["id"])[0]["check_overrides"] == [prior]
        with monkeypatch.context() as previous_admission:
            previous_admission.setattr(runs, "visibility_overrides", lambda *_: {body["artifact"]: decision})
            previously_queued = success(build(q, "hidden-previously-queued"), 201)
        previous_snapshot = snapshot(q, previously_queued["id"]).content
        with FakeWan().client() as wan:
            worker = run_worker(q, wan)
            assert worker.tick() and worker.tick()
        for run in (fresh, previously_queued):
            result, _ = read_run(q, run["id"])
            assert result["status"] == "failed" and result["delivery_id"] is None
            assert result["error"]["code"] == "build.check_failed"
            assert visibility_of(result) == [measurement]
            assert q.store.stage_record(q.production_id, run["id"], "delivery") is None
        assert snapshot(q, previously_queued["id"]).content == previous_snapshot
        return

    waiting = success(build(q, "queued-before-review"), 201)
    override = success(q.browser.post(path, json=body, headers={**q.csrf, "If-Match": etag}), 201)
    assert override["by"]["kind"] == "human"
    assert read_run(q, new["id"])[0]["checks"] == checked["checks"]
    repeat = success(build(q, "after-review"), 201)
    carried = {
        body["artifact"]: {"by": override["by"], "reason": body["reason"]},
    }
    assert snapshot(q, repeat["id"]).json()["visibility_admission"]["overrides"] == carried
    assert "overrides" not in snapshot(q, waiting["id"]).json()["visibility_admission"]
    changed_evidence = success(build(q, "changed-evidence"), 201)
    assert snapshot(q, changed_evidence["id"]).json()["visibility_admission"]["overrides"] == carried
    patch(q, q.board_id, {"visibility": {"slot": "a", "frames": [1]}})
    changed = success(build(q, "different-pose"), 201)
    assert "overrides" not in snapshot(q, changed["id"]).json()["visibility_admission"]

    actual_evidence = LayeredRenderer.visibility_evidence

    def different_frame_hash(renderer, key):
        rows = json.loads(actual_evidence(renderer, key))
        rows[0]["frame_sha256"] = "f" * 64
        return canonical_json(rows)

    def verify_override(claim, result):
        evidence = completion_evidence(result)
        substituted = deepcopy(evidence)
        [check] = visibility_of(substituted)
        assert check["result"] == "overridden"
        check["measured"]["segment_sha256"] = "e" * 64
        assert_completion_refused(q, claim, substituted, "visibility.check_failed")
        check["measured"]["segment_sha256"] = measurement["measured"]["segment_sha256"]
        check["measured"]["poses"] = [{**check["measured"]["poses"][0], "frame": 3}]
        assert_completion_refused(q, claim, substituted, "visibility.check_failed")
        assert claim.complete(evidence)["status"] == "succeeded"

    with FakeWan().client() as wan:
        worker = run_worker(q, wan)
        assert worker.tick()
        with monkeypatch.context() as valid_override:
            valid_override.setattr(worker, "_complete", verify_override)
            assert worker.tick()
        with monkeypatch.context() as mismatched_evidence:
            mismatched_evidence.setattr(LayeredRenderer, "visibility_evidence", different_frame_hash)
            assert worker.tick()
        assert worker.tick()
    assert read_run(q, waiting["id"])[0]["status"] == "failed"
    approved, _ = read_run(q, repeat["id"])
    assert approved["status"] == "succeeded" and approved["delivery_id"]
    [check] = visibility_of(approved)
    assert check["result"] == "overridden" and check["measured"] == measurement["measured"]
    altered = read_run(q, changed_evidence["id"])[0]
    assert altered["status"] == "failed" and altered["delivery_id"] is None
    [altered_check] = visibility_of(altered)
    assert altered_check["result"] == "fail" and altered_check["measured"]["verdict"] == verdict
    assert altered_check["artifact"] != measurement["artifact"]
    assert read_run(q, changed["id"])[0]["status"] == "failed"


def test_generic_frozen_build_and_photo_do_not_activate_draft_visibility(queue, tmp_path, monkeypatch):
    q = queue
    monkeypatch.setattr(runs, "database_time", database_time)
    install_sets(q, tmp_path)
    selection = current_board(q, q.board_id)["photo"]
    plain_photo = success(photo(q, "plain"), 202)["id"]
    worker, _ = image_worker(q)
    assert worker.tick()
    patch(q, q.board_id, {"visibility": DECLARATION, "photo": selection})
    assert success(photo(q, "plain"))["id"] == plain_photo
    new_photo = success(photo(q, "with-declaration"), 202)["id"]
    assert worker.tick()
    with q.owner.connect() as conn:
        old_job, new_job = jobs.get(conn, plain_photo), jobs.get(conn, new_photo)
    assert old_job["document"]["status"] == new_job["document"]["status"] == "succeeded"
    assert old_job["document"]["input_signature"] == new_job["document"]["input_signature"]
    assert "visibility" not in new_job["inputs"]["story"]["boards"][0]

    with q.engine.begin() as conn:
        story = drafts.get_draft(conn, q.story_id).exchange()
        refs = {ref.version_id for ref in story_references(story)}
        prepared = prepare_queue(story, catalog.build_library(conn, story, refs))
        frozen, library = freeze(prepared, studio=q.app.state.build_revision)
        assert frozen["story"]["boards"][0]["visibility"] == DECLARATION
        assert "visibility_admission" not in frozen
        data, digest = snapshot_bytes(frozen)
        q.store.publish(data, scope=q.production_id, media_type="application/json")
        old = runs.enqueue(conn, snapshot=frozen, snapshot_sha256=digest, library=library,
                           actor=f.OPERATOR["operator"], key="generic", estimate=estimate(prepared))
    new = success(build(q, "visible"), 201)
    with FakeWan().client() as wan:
        worker = run_worker(q, wan)
        assert worker.tick() and worker.tick()
    legacy, _ = read_run(q, old["id"])
    assert legacy["status"] == "succeeded" and not visibility_of(legacy)
    active, _ = read_run(q, new["id"])
    assert active["status"] == "succeeded"
    [measurement] = visibility_of(active)
    assert measurement["result"] == "pass" and measurement["measured"]["verdict"] == "visible"
    assert active["outputs"]["master_sha256"] == legacy["outputs"]["master_sha256"]
