"""HTTP operations for escalation operators, workers and the named responder."""

from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query, Request, Response
from pydantic import Field, StringConstraints

from haynes_studio.canonical.model import to_document
from haynes_studio.db import runs
from haynes_studio.db.engine import snapshot
from haynes_studio.db.problems import NotFound
from haynes_studio.db.schema import productions
from haynes_studio.escalation import lifecycle, responder, storage
from haynes_studio.queue.protocol import ClaimFence, Reason
from haynes_studio.store.layout import is_sha256

from .auth import WorkerRoute
from .errors import APIError, ERROR_RESPONSES
from .models import Body, Page, TransportModel
from .routes import _id
from .run_routes import _lock, _run_access

BoardId = Annotated[str, StringConstraints(pattern=r"^brd_[0-7][0-9A-HJKMNP-TV-Z]{25}$",
                                           min_length=30, max_length=30)]
RunId = Annotated[str, StringConstraints(pattern=r"^run_[0-7][0-9A-HJKMNP-TV-Z]{25}$",
                                         min_length=30, max_length=30)]
CallbackKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128,
                                    pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
Count = Annotated[int, Field(ge=0, le=2**53 - 1)]


class EscalationView(TransportModel):
    package: dict
    sha256: str
    state: Literal["proposed", "authorized", "declined", "requested", "done", "failed", "escalate", "cancelled"]
    expired: bool
    transitions: list[dict]


class Authorization(Body):
    acknowledge_board_ids: list[BoardId] = Field(default_factory=list, max_length=1)


class Usage(Body):
    elapsed_seconds: Count
    input_tokens: Count | None = None
    output_tokens: Count | None = None
    cost_usd: Annotated[float, Field(ge=0, le=1_000_000, allow_inf_nan=False)] | None = None


class Callback(Body):
    outcome: Literal["done", "failed", "escalate"]
    summary: Reason
    usage: Usage | Literal["unknown"]
    changed_board_ids: list[BoardId] = Field(max_length=1)
    queued_run_ids: list[RunId] = Field(default_factory=list, max_length=1)


class FailureObservation(ClaimFence):
    attempt: Annotated[int, Field(ge=1, le=2**31 - 1)]
    error_code: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    board_id: BoardId | None
    result: dict


def transport_models():
    return EscalationView, Page[EscalationView], Authorization, Usage, Callback, FailureObservation


def _digest(value, path):
    if not is_sha256(value):
        raise APIError(422, "schema.invalid", "Expected a lower-case SHA-256", path=path)
    return value


def build_router(CurrentActor, authenticated_route):
    router = APIRouter(prefix="/v1", tags=["escalations"], responses=ERROR_RESPONSES,
                       route_class=authenticated_route)
    base = "/productions/{production_id}/escalations"
    package = base + "/{package_id}"

    @router.get(base, response_model=Page[EscalationView], operation_id="list_escalation_packages")
    def list_packages(production_id: str, request: Request, actor: CurrentActor,
                      cursor: str | None = None, limit: Annotated[int, Query(ge=1, le=20)] = 10):
        _id(production_id, "prd", "/production_id")
        actor.require("read", production_id)
        after = _digest(cursor, "/cursor") if cursor is not None else ""
        with snapshot(request.app.state.engine) as conn:
            if conn.scalar(productions.select().with_only_columns(productions.c.id)
                           .where(productions.c.id == production_id)) is None:
                raise NotFound
            rows = storage.list_packages(conn, production_id, after, limit + 1)
            now = runs.database_time(conn)
            return {"items": [storage.view(conn, row, now) for row in rows[:limit]],
                    "next_cursor": rows[limit - 1]["id"] if len(rows) > limit else None}

    @router.get(package, response_model=EscalationView, operation_id="get_escalation_package")
    def get_package(production_id: str, package_id: str, request: Request, actor: CurrentActor):
        _id(production_id, "prd", "/production_id")
        actor.require("read", production_id)
        with snapshot(request.app.state.engine) as conn:
            row = storage.get_package(conn, _digest(package_id, "/package_id"), production_id)
            return storage.view(conn, row, runs.database_time(conn))

    @router.get("/runs/{run_id}/escalation-checks/{record_sha256}", operation_id="get_escalation_check")
    def get_check(run_id: str, record_sha256: str, request: Request, actor: CurrentActor):
        with snapshot(request.app.state.engine) as conn:
            _run_access(conn, actor, "read", run_id)
            return storage.get_result(conn, run_id, _digest(record_sha256, "/record_sha256"))

    def decide(production_id, package_id, request, actor, decision, board_ids=()):
        _id(production_id, "prd", "/production_id")
        _digest(package_id, "/package_id")
        with request.app.state.engine.begin() as conn:
            return lifecycle.decide(conn, production_id, package_id, decision,
                                    actor=to_document(actor.principal),
                                    settings=request.app.state.escalation,
                                    acknowledged_boards=board_ids)

    @router.post(package + "/authorize", response_model=EscalationView, operation_id="authorize_escalation")
    def authorize(production_id: str, package_id: str, request: Request, actor: CurrentActor,
                  body: Authorization | None = None):
        return decide(production_id, package_id, request, actor, "authorize",
                      body.acknowledge_board_ids if body else ())

    @router.post(package + "/decline", response_model=EscalationView, operation_id="decline_escalation")
    def decline(production_id: str, package_id: str, request: Request, actor: CurrentActor):
        return decide(production_id, package_id, request, actor, "decline")

    @router.post(package + "/cancel", response_model=EscalationView, operation_id="cancel_escalation")
    def cancel(production_id: str, package_id: str, request: Request, actor: CurrentActor):
        return decide(production_id, package_id, request, actor, "cancel")

    @router.post(package + "/callback", response_model=EscalationView, operation_id="report_escalation")
    def callback(production_id: str, package_id: str, body: Callback, request: Request,
                 actor: CurrentActor, idempotency_key: CallbackKey):
        _id(production_id, "prd", "/production_id")
        _digest(package_id, "/package_id")
        if len(request.headers.getlist("Idempotency-Key")) != 1:
            raise APIError(422, "schema.invalid", "Supply one Idempotency-Key")
        actor.require("read", production_id)
        with request.app.state.engine.begin() as conn:
            return responder.report(conn, production_id, package_id, actor=to_document(actor.principal),
                                    idempotency_key=idempotency_key, report=body.model_dump(mode="json"))

    return router


def worker_router():
    router = APIRouter(prefix="/internal/v1/work", route_class=WorkerRoute, include_in_schema=False)

    @router.post("/escalation-check-failure", status_code=204, operation_id="record_escalation_check")
    def observe(body: FailureObservation, request: Request):
        with request.app.state.engine.begin() as conn:
            row, _ = _lock(conn, request, body)
            lifecycle.record_failure(
                conn, row, actor=to_document(request.state.principal),
                attempt=body.attempt, error_code=body.error_code, board_id=body.board_id,
                result=body.result, settings=request.app.state.escalation,
            )
        return Response(status_code=204)

    return router
