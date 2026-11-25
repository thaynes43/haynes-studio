"""Scoped public run routes and worker-only queue transactions."""

import os
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Request, Response

from haynes_studio.build.prebuild import snapshot_bytes
from haynes_studio.build.validate import validate_run
from haynes_studio.canonical.model import to_document
from haynes_studio.db import catalog, drafts, jobs, queue_controls, runs
from haynes_studio.golive import records as go_live
from haynes_studio.db.engine import snapshot
from haynes_studio.db.problems import StaleRevision, require_valid
from haynes_studio.delivery import read_delivery
from haynes_studio.delivery.errors import DeliveryError
from haynes_studio.library.resolve import story_references
from haynes_studio.queue import inputs
from haynes_studio.queue.protocol import (
    SHA256, ClaimFence, Heartbeat, JobId, Payload, Progress, Reason, Reservation, WanResult,
    MediaCompletion, MediaFailure, MediaFence, MediaHeartbeat, WorkAttempt, WorkClaim,
    WorkCompletion, WorkFailure, WorkLane, WorkReserve,
)
from haynes_studio.queue.staging import BuildStageStore, publish_staged_delivery
from haynes_studio.store import StoreError

from . import media_work
from .auth import WorkerRoute
from .errors import APIError, ERROR_RESPONSES, forbidden
from .models import Body, Document, Page, TransportModel
from .routes import Cursor, ETAG, IfMatch, Limit, _cursor, _etag, _id, _page, _revision, _story_access

IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", pattern=r"^[!-~]{1,255}$")]


class RunView(Document):
    pass


class QueueWait(TransportModel):
    ahead: int
    wall_s: tuple[int, int] | None
    uncertain: Literal[True]
    basis: str


class EstimateRange(TransportModel):
    gpu_wall_s: tuple[int, int] | None
    cpu_wall_s: tuple[int, int] | None
    basis: str
    uncertain: Literal[True]


class MethodEstimate(TransportModel):
    method: str
    chunks: int
    gpu_wall_s: tuple[int, int]


class EstimateView(TransportModel):
    estimate: EstimateRange
    methods: list[MethodEstimate]
    queue_wait: QueueWait
    problems: list[dict]


class CheckOverride(Payload):
    artifact: SHA256
    reason: Reason


class CheckOverrideView(CheckOverride):
    check: Literal["layered.decal_gate"]
    by: dict
    at: str


class QueueLaneUpdate(Body):
    paused: bool


class QueueLaneStatus(TransportModel):
    lane: WorkLane
    paused: bool
    changed_by: dict | None
    changed_at: datetime | None


class QueueStatus(TransportModel):
    items: list[QueueLaneStatus]


def transport_models():
    """Build these models with the other API transports before mounting routes."""
    return (
        RunView, Page[RunView], QueueWait, EstimateRange, MethodEstimate, EstimateView,
        CheckOverride, CheckOverrideView, ClaimFence, Progress, Heartbeat, Reservation,
        WanResult, WorkReserve, WorkAttempt, WorkCompletion, WorkFailure, WorkClaim,
        MediaFence, MediaHeartbeat, MediaCompletion, MediaFailure,
        QueueLaneUpdate, QueueLaneStatus, QueueStatus,
    )


def _prepare(conn, draft):
    story = draft.exchange()
    refs = {item.version_id for item in story_references(story)}
    return inputs.prepare_queue(story, catalog.build_library(conn, story, refs),
                                jobs=jobs.active_for_story(conn, story["id"]))


def _read_view(conn, row, *, detail=True, worker_present=None):
    view = runs.view(conn, row, detail=detail)
    view["active_approval_id"] = (conn.scalar(go_live.active_id(row["id"]))
                                  if view["status"] == "succeeded" else None)
    if view["status"] == "queued":
        if worker_present is None:
            worker_present = runs.worker_present(conn)
        view["queue_wait"] = inputs.queue_wait(runs.ahead(conn, row["position"]))
        if not worker_present:
            view["wait_reason"] = "gpu_unavailable"
        if view["wait_reason"] is not None:
            view["queue_wait"]["wall_s"] = None
    else:
        view["queue_wait"] = None
    return view


def _run_access(conn, actor, scope, run_id, *, lock=False):
    row = runs.get(conn, _id(run_id, "run"), lock=lock)
    actor.require(scope, row["production_id"])
    return row


def build_router(CurrentActor, authenticated_route):
    router = APIRouter(prefix="/v1", responses=ERROR_RESPONSES, route_class=authenticated_route,
                       tags=["runs"])

    @router.get("/queue/lanes", response_model=QueueStatus, operation_id="get_queue_lanes")
    def get_queue_lanes(request: Request, actor: CurrentActor):
        actor.human()
        with snapshot(request.app.state.engine) as conn:
            return {"items": queue_controls.status(conn)}

    @router.put("/queue/lanes/{lane}", response_model=QueueLaneStatus, operation_id="set_queue_lane")
    def set_queue_lane(lane: WorkLane, body: QueueLaneUpdate, request: Request, actor: CurrentActor):
        actor.human()
        with request.app.state.engine.begin() as conn:
            return queue_controls.set_paused(conn, lane, body.paused, to_document(actor.principal),
                                             runs.database_time)

    @router.get("/stories/{id}/estimate", response_model=EstimateView, operation_id="estimate_run")
    def estimate_run(id: str, request: Request, actor: CurrentActor):
        with snapshot(request.app.state.engine) as conn:
            _story_access(conn, actor, "read", id)
            prepared = _prepare(conn, drafts.get_draft(conn, id))
            wait = inputs.queue_wait(runs.ahead(conn))
            if not runs.worker_present(conn):
                wait["wall_s"] = None
            return {**inputs.estimate(prepared), "queue_wait": wait}

    @router.post("/stories/{id}/runs", response_model=RunView, status_code=201,
                 responses={200: {"headers": ETAG}, 201: {"headers": ETAG}}, operation_id="queue_run")
    def queue_run(id: str, request: Request, response: Response, actor: CurrentActor,
                  if_match: IfMatch, idempotency_key: IdempotencyKey):
        revision = _revision(if_match)
        principal = to_document(actor.principal)
        store = request.app.state.store
        with request.app.state.engine.begin() as conn:
            _story_access(conn, actor, "runs:queue", id)
            # Draft mutations use the same story row, including board edits.
            draft = drafts.get_draft(conn, id, lock=True)
            row = runs.lookup_idempotency(conn, id, principal, idempotency_key, revision)
            if row is not None:
                response.status_code = 200
            else:
                current = draft.story["revision"]
                if current != revision:
                    raise StaleRevision(current)
                prepared = _prepare(conn, draft)
                prepared.ensure_buildable()
                frozen, library = inputs.freeze(prepared, studio=request.app.state.build_revision)
                data, sha = snapshot_bytes(frozen)
                try:
                    store.publish(data, scope=draft.story["production_id"], media_type="application/json",
                                  expected_sha256=sha)
                except (OSError, StoreError) as error:
                    raise APIError(503, "run.snapshot_store_unavailable",
                                   "The snapshot could not be stored") from error
                row = runs.enqueue(conn, snapshot=frozen, snapshot_sha256=sha, library=library,
                                   actor=principal, key=idempotency_key,
                                   estimate=inputs.estimate(prepared))
            response.headers["Location"] = f'/v1/runs/{row["id"]}'
            return _etag(response, _read_view(conn, row))

    @router.get("/stories/{id}/runs", response_model=Page[RunView], operation_id="list_runs")
    def list_runs(id: str, request: Request, actor: CurrentActor,
                  cursor: Cursor = None, limit: Limit = 50):
        with snapshot(request.app.state.engine) as conn:
            _story_access(conn, actor, "read", id)
            rows = runs.list_story(conn, id, _cursor(cursor, "run"), limit + 1)
            queued = any(row["document"]["status"] == "queued" for row in rows)
            present = runs.worker_present(conn) if queued else None
            return _page([_read_view(conn, row, detail=False, worker_present=present)
                          for row in rows], limit)

    @router.get("/runs/{id}", response_model=RunView, responses={200: {"headers": ETAG}},
                operation_id="get_run")
    def get_run(id: str, request: Request, response: Response, actor: CurrentActor):
        with snapshot(request.app.state.engine) as conn:
            return _etag(response, _read_view(conn, _run_access(conn, actor, "read", id)))

    @router.post("/runs/{id}/cancel", response_model=RunView, responses={200: {"headers": ETAG}},
                 operation_id="cancel_run")
    def cancel_run(id: str, request: Request, response: Response, actor: CurrentActor, if_match: IfMatch):
        with request.app.state.engine.begin() as conn:
            row = _run_access(conn, actor, "runs:queue", id, lock=True)
            row = runs.cancel(conn, row, _revision(if_match), to_document(actor.principal))
            return _etag(response, _read_view(conn, row))

    @router.post("/runs/{id}/checks/{check}/overrides", status_code=201,
                 response_model=CheckOverrideView, operation_id="record_check_override")
    def record_check_override(id: str, check: str, body: CheckOverride, request: Request,
                              actor: CurrentActor, if_match: IfMatch):
        actor.human()
        if check != runs.CHECK_OVERRIDABLE:
            raise forbidden("check.not_overridable", "Only the visual decal check supports an override")
        with request.app.state.engine.begin() as conn:
            row = _run_access(conn, actor, "runs:queue", id, lock=True)
            return runs.record_override(conn, row, _revision(if_match), artifact=body.artifact,
                                        reason=body.reason, actor=to_document(actor.principal))

    return router


def _lock(conn, request, body):
    if not body.valid_run():
        _id(body.run_id, "run", "/run_id")
    return runs.lock_claim(conn, body.run_id, request.state.principal.worker_id, body.fence)


def _delivery(conn, request, row, body):
    state = request.app.state
    failure = APIError(503, "work.delivery_unverified", "The worker's delivery could not be verified")
    if state.build_stage_root is None:
        raise failure
    try:
        staging = BuildStageStore(state.build_stage_root, row["id"], state.store)
        delivery = read_delivery(staging, production_id=row["production_id"], run_id=row["id"])
        if (delivery is None or delivery.id != body.delivery_id or delivery.proxy is None or
                delivery.master.sha256 != body.outputs.get("master_sha256") or
                delivery.proxy.sha256 != body.outputs.get("proxy_sha256") or
                delivery.verification.decoded_frames != body.outputs.get("frames")):
            raise failure
        publish_staged_delivery(staging, state.store, row["production_id"], row["id"])
    except (OSError, StoreError, DeliveryError) as error:
        raise failure from error
    catalog.record_delivery(conn, row["story_id"], to_document(delivery))


def worker_router():
    router = APIRouter(prefix="/internal/v1/work", responses=ERROR_RESPONSES, route_class=WorkerRoute,
                       include_in_schema=False)

    @router.post("/claim", operation_id="claim_work")
    def claim_work(request: Request, body: WorkClaim | None = None):
        lane = "run" if body is None else body.lane
        worker_id = request.state.principal.worker_id
        with request.app.state.engine.begin() as conn:
            claim = runs.claim(conn, worker_id) if lane == "run" else media_work.claim(conn, worker_id, lane)
        return claim if claim is not None else Response(status_code=204)

    @router.post("/heartbeat", operation_id="heartbeat_work")
    def heartbeat_work(body: Heartbeat | MediaHeartbeat, request: Request):
        with request.app.state.engine.begin() as conn:
            if isinstance(body, MediaHeartbeat):
                row, now = media_work.lock(conn, request, body)
                return jobs.heartbeat(conn, row, now)
            row, now = _lock(conn, request, body)
            return runs.heartbeat(conn, row, now, body.progress.model_dump() if body.progress else None)

    @router.post("/resume", operation_id="resume_work")
    def resume_work(body: ClaimFence, request: Request):
        actor = to_document(request.state.principal)
        with request.app.state.engine.begin() as conn:
            row, now = _lock(conn, request, body)
            return runs.resume(conn, row, now, actor)

    @router.post("/attempts", operation_id="reserve_wan_attempt")
    def reserve_wan_attempt(body: WorkReserve, request: Request):
        if not body.proposal.supported():
            raise APIError(422, "wan.profile", "The request does not match a supported Wan profile")
        with request.app.state.engine.begin() as conn:
            row, now = _lock(conn, request, body)
            return dict(runs.reserve_attempt(conn, row, now, body.proposal.kind, body.proposal.product_request()))

    @router.post("/attempts/{job_id}", operation_id="update_wan_attempt")
    def update_wan_attempt(job_id: JobId, body: WorkAttempt, request: Request):
        if (body.state == "succeeded") != (body.result is not None):
            raise APIError(422, "wan.result", "A verified result is required only for a successful attempt")
        with request.app.state.engine.begin() as conn:
            row, now = _lock(conn, request, body)
            return dict(runs.attempt_action(conn, row, now, job_id, body.state,
                                          body.result.model_dump() if body.result else None))

    @router.post("/publish", status_code=204, operation_id="publish_work")
    def publish_work(body: ClaimFence | MediaFence, request: Request):
        with request.app.state.engine.begin() as conn:
            if isinstance(body, MediaFence):
                row, now = media_work.lock(conn, request, body)
                jobs.dispatch(conn, row, now)
            else:
                row, _ = _lock(conn, request, body)
                runs.publish(conn, row)
        return Response(status_code=204)

    @router.post("/complete", operation_id="complete_work")
    def complete_work(body: WorkCompletion | MediaCompletion, request: Request):
        if isinstance(body, MediaCompletion):
            with request.app.state.engine.begin() as conn:
                return media_work.complete(conn, request, body)
        actor = to_document(request.state.principal)
        if any(check.get("result") == "fail" for check in body.checks):
            raise APIError(422, "work.check_failed", "A successful run cannot have a failed delivery check")
        with request.app.state.engine.begin() as conn:
            row, now = _lock(conn, request, body)
            row = runs.finish(conn, row, now, actor, "succeeded", "Build delivered and verified", {
                **body.model_dump(exclude={"run_id", "fence"}), "error": None,
                "progress": {"percent": 100, "stage": "delivered"},
            })
            require_valid(validate_run(row["document"]))
            _delivery(conn, request, row, body)
            return runs.view(conn, row, detail=False)

    @router.post("/fail", operation_id="fail_work")
    def fail_work(body: WorkFailure | MediaFailure, request: Request):
        if isinstance(body, MediaFailure):
            with request.app.state.engine.begin() as conn:
                return media_work.finish_failure(conn, request, body)
        if (body.status == "queued") != (body.wait_reason is not None):
            raise APIError(422, "work.wait_reason", "A queued run requires a wait reason")
        if body.wan_job_id is not None and body.status not in ("failed", "cancelled"):
            raise APIError(422, "wan.outcome", "Settling Wan work here requires a terminal run outcome")
        if body.admission_busy and body.status != "held":
            raise APIError(422, "wan.outcome", "An unrecorded admission refusal requires a held run")
        actor = to_document(request.state.principal)
        with request.app.state.engine.begin() as conn:
            row, now = _lock(conn, request, body)
            fields = body.model_dump(include={"stages", "checks", "error"}, exclude_none=True)
            if body.status in ("failed", "cancelled"):
                fields["progress"] = {"percent": 100, "stage": body.status}
            row = runs.finish(conn, row, now, actor, body.status, body.reason, fields,
                              wait_reason=body.wait_reason, wan_job_id=body.wan_job_id,
                              admission_busy=body.admission_busy)
            require_valid(validate_run(row["document"]))
            return runs.view(conn, row, detail=False)

    return router


def build_revision_from_environment():
    return os.environ.get("STUDIO_BUILD_REVISION", "git:unknown")
