"""People-only go-live review and decision routes."""

from typing import Annotated, Literal

from fastapi import APIRouter, Request
from pydantic import Field, StringConstraints

from haynes_studio.canonical.model import to_document
from haynes_studio.db import catalog, runs
from haynes_studio.db.engine import snapshot
from haynes_studio.db.problems import NotFound
from haynes_studio.golive import checks, packages, records
from haynes_studio.golive.checks import licence_register as licence_register
from haynes_studio.golive.policy import require_allowlisted_approver, require_approver

from .errors import APIError, ERROR_RESPONSES
from .models import Body, JsonObject, TransportModel
from .routes import _id
from .run_routes import _run_access


class ApprovalWrite(Body):
    master_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    platform_setting: bool = False


class ApprovalState(TransportModel):
    state: Literal["active", "withdrawn"]
    withdrawal: JsonObject | None
    publication_ids: list[str]


class ApprovalHistoryItem(TransportModel):
    schema_version: Literal["studio.go-live-approval/v1"] = Field(alias="schema")
    id: str
    run_id: str
    run_snapshot_sha256: str
    delivery_id: str
    master_sha256: str
    approver: dict[str, str] | None = None
    approver_display_name: str | None
    auth_time: str | None = None
    approved_at: str
    release_checks: JsonObject
    derived: ApprovalState


class ApprovalView(ApprovalHistoryItem):
    approver: dict[str, str]
    auth_time: str


class AllowedDecision(TransportModel):
    allowed: Literal[True]


class DeniedDecision(TransportModel):
    allowed: Literal[False]
    code: str


class ApprovalReview(TransportModel):
    run_id: str
    master_sha256: str | None
    approve: AllowedDecision | DeniedDecision
    withdraw: AllowedDecision | DeniedDecision
    release_checks: JsonObject | None
    approvals: list[ApprovalHistoryItem]


def _check_approval(run, delivery, master_sha256, platform_setting, active, saved, *, preview=False):
    evidence = active_refusal = None
    try:
        verified = checks.verify_delivery(run, delivery, master_sha256)
        evidence = {"delivery": verified}
        if active is not None:
            active_refusal = APIError(409, "approval.already_active", "The run already has an active approval")
            if not preview:
                raise active_refusal
        evidence = checks.checked_evidence(run, verified, platform_setting, saved())
    except APIError as error:
        if not preview:
            raise
        if evidence is not None and error.details["code"] == "approval.licence_missing":
            evidence["licences"] = error.details["evidence"]
        return evidence, active_refusal or error
    return evidence, active_refusal


def _require_active(active_id, approval_id=None):
    if active_id is None or (approval_id is not None and approval_id != active_id):
        raise APIError(409, "approval.already_withdrawn", "The approval has already been withdrawn")


def _refusal(check, *args):
    try:
        check(*args)
    except APIError as error:
        return error
    return None


def _decision(refusal):
    return {"allowed": True} if refusal is None else {"allowed": False, "code": refusal.details["code"]}


def _delivery(conn, run_id):
    delivery = catalog.get_delivery(conn, run_id)
    return delivery.document if delivery else None


def build_router(CurrentActor, approval_route):
    router = APIRouter(prefix="/v1", tags=["go-live"], responses=ERROR_RESPONSES,
                       route_class=approval_route)

    @router.get("/runs/{id}/go-live-approvals", response_model=ApprovalReview,
                response_model_exclude_unset=True, operation_id="get_go_live_approvals")
    def get_go_live_approvals(id: str, request: Request, actor: CurrentActor):
        state = request.app.state
        with snapshot(state.engine) as conn:
            row = _run_access(conn, actor, "read", id)
            identity_refusal = _refusal(require_approver, actor, state.oidc.settings,
                                        runs.database_time(conn))
            delivery = _delivery(conn, row["id"])
            master = delivery["master"]["sha256"] if delivery else None
            active = conn.scalar(records.active_id(row["id"]))
            evidence, approval_refusal = _check_approval(
                row["document"], delivery, master, True, active,
                lambda: packages.saved_checks(conn, state.store, row, delivery), preview=True,
            )
            show_identity = _refusal(require_allowlisted_approver, actor, state.oidc.settings) is None
            return {
                "run_id": row["id"], "master_sha256": master,
                "approve": _decision(identity_refusal or approval_refusal),
                "withdraw": _decision(identity_refusal or _refusal(_require_active, active)),
                "release_checks": evidence,
                "approvals": records.history(conn, row["id"], show_identity=show_identity),
            }

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
                checks.refuse_legacy(None, _delivery(conn, id))
                raise
            run = row["document"]
            delivery = _delivery(conn, row["id"])
            evidence, _ = _check_approval(
                run, delivery, body.master_sha256, body.platform_setting,
                conn.scalar(records.active_id(row["id"])),
                lambda: packages.saved_checks(conn, state.store, row, delivery),
            )
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
            _require_active(conn.scalar(records.active_id(approval["run_id"])), approval["id"])
            now = runs.database_time(conn)
            require_approver(actor, state.oidc.settings, now)
            return records.record_withdrawal(conn, approval, to_document(actor.principal),
                                             runs.timestamp(actor.auth_time), runs.timestamp(now))

    return router
