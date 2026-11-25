"""The two human-only go-live operations."""

from functools import cache
from typing import Annotated, Literal

from fastapi import APIRouter, Request
from pydantic import Field, StringConstraints

from haynes_studio.build.provenance import Register
from haynes_studio.canonical.model import to_document
from haynes_studio.db import catalog, runs
from haynes_studio.db.problems import NotFound
from haynes_studio.golive import checks, records
from haynes_studio.golive.policy import require_approver
from haynes_studio.model_register import load_model_register

from .errors import APIError, ERROR_RESPONSES
from .models import Body, JsonObject, TransportModel
from .routes import _id


class ApprovalWrite(Body):
    master_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    platform_setting: bool = False


class ApprovalState(TransportModel):
    state: Literal["active", "withdrawn"]
    withdrawal: JsonObject | None
    publication_ids: list[str]


class ApprovalView(TransportModel):
    schema_version: Literal["studio.go-live-approval/v1"] = Field(alias="schema")
    id: str
    run_id: str
    run_snapshot_sha256: str
    delivery_id: str
    master_sha256: str
    approver: dict[str, str]
    approver_display_name: str | None
    auth_time: str
    approved_at: str
    release_checks: JsonObject
    derived: ApprovalState


@cache
def licence_register() -> Register:
    try:
        return Register(load_model_register())
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise APIError(503, "approval.licence_register_unavailable",
                       "The model licence register could not be read") from error


def build_router(CurrentActor, approval_route):
    router = APIRouter(prefix="/v1", tags=["go-live"], responses=ERROR_RESPONSES,
                       route_class=approval_route)

    @router.post("/runs/{id}/go-live-approvals", status_code=201, response_model=ApprovalView,
                 operation_id="approve_go_live")
    def approve_go_live(id: str, body: ApprovalWrite, request: Request, actor: CurrentActor):
        state = request.app.state
        with state.engine.begin() as conn:
            id = _id(id, "run")
            try:
                row = runs.get(conn, id, lock=True)
            except NotFound:
                # Trusted legacy imports have only a delivery in the API database.
                legacy = catalog.get_delivery(conn, id)
                checks.refuse_legacy(None, legacy.document if legacy else None)
                raise
            run = row["document"]
            delivery = catalog.get_delivery(conn, row["id"])
            delivery_check = checks.verify_delivery(run, delivery.document if delivery else None,
                                                    body.master_sha256)
            if conn.scalar(records.active_id(row["id"])) is not None:
                raise APIError(409, "approval.already_active", "The run already has an active approval")
            evidence = checks.release_checks(run, delivery_check, body.platform_setting, licence_register())
            now = runs.database_time(conn)
            require_approver(actor, state.oidc.settings, now)
            return records.record_approval(conn, run, body.master_sha256, to_document(actor.principal),
                                           actor.display_name, runs.timestamp(actor.auth_time),
                                           runs.timestamp(now), evidence)

    @router.post("/go-live-approvals/{id}/withdraw", status_code=201, response_model=ApprovalView,
                 operation_id="withdraw_go_live")
    def withdraw_go_live(id: str, request: Request, actor: CurrentActor):
        state = request.app.state
        with state.engine.begin() as conn:
            approval = records.get(conn, _id(id, "apr"))
            runs.get(conn, approval["run_id"], lock=True)
            if records.get_withdrawal(conn, approval["id"]) is not None:
                raise APIError(409, "approval.already_withdrawn", "The approval has already been withdrawn")
            now = runs.database_time(conn)
            require_approver(actor, state.oidc.settings, now)
            return records.record_withdrawal(conn, approval, to_document(actor.principal),
                                             runs.timestamp(actor.auth_time), runs.timestamp(now))

    return router
