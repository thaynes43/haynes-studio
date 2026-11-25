"""Production-scoped release packages and approver-only manual drops."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Request, Response
from pydantic import AwareDatetime, Field, StringConstraints

from haynes_studio.adapters.errors import contains_credentials_in_prose
from haynes_studio.canonical.model import to_document
from haynes_studio.db import catalog, runs
from haynes_studio.db.engine import snapshot
from haynes_studio.db.problems import NotFound
from haynes_studio.delivery.model import LEGACY_WAN_LEDGER
from haynes_studio.golive import checks, packages
from haynes_studio.golive.policy import require_approver
from haynes_studio.queue.protocol import SHA256

from .approval_routes import AllowedDecision, DeniedDecision, _decision, _refusal
from .errors import APIError, ERROR_RESPONSES
from .models import Body, JsonObject, TransportModel
from .routes import _id


class ReleasePackageWrite(Body):
    target_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]


class PublicationWrite(Body):
    package_sha256: SHA256
    location: Annotated[str, StringConstraints(min_length=1, max_length=2048, strip_whitespace=True)]
    published_at: Annotated[AwareDatetime, Field(strict=False)] | None = None


class TargetRules(TransportModel):
    max_length_ms: int | None
    ai_label_required: bool | None
    aspect: str | None


class ReleaseTarget(TransportModel):
    id: str
    name: str
    platform: Literal["youtube-shorts"]
    state: Literal["existing", "placeholder"]
    account_id: str | None
    owner_note: str | None
    rules: TargetRules


class ReleaseMaster(TransportModel):
    sha256: SHA256
    bytes: int
    media_type: Literal["video/mp4"]


class ReleasePackage(TransportModel):
    schema_version: Literal["studio.release-package/v1"] = Field(alias="schema")
    run_id: str
    run_snapshot_sha256: SHA256
    delivery_id: str
    format_version_id: str
    format_sha256: SHA256
    master: ReleaseMaster
    target: ReleaseTarget
    description: str
    checklist: list[str]
    release_checks: JsonObject
    target_checks: JsonObject


class PublicationSummary(TransportModel):
    schema_version: Literal["studio.publication/v1"] = Field(alias="schema")
    id: str
    package_sha256: SHA256
    approval_id: str
    run_id: str
    master_sha256: SHA256
    location: str
    recorded_by_display_name: str | None
    recorded_at: datetime
    published_at: datetime | None


class Publication(PublicationSummary):
    recorded_by: dict[str, str]


class ReleasePackageReceipt(TransportModel):
    sha256: SHA256
    bytes: int


class ReleasePackageView(ReleasePackageReceipt):
    package: ReleasePackage
    state: Literal["held", "releasable"]
    held_reason: Literal["release.approval_required"] | None
    approval_id: str | None
    publication: PublicationSummary | None
    record_publication: AllowedDecision | DeniedDecision


class ReleasePackageList(TransportModel):
    targets: list[ReleaseTarget]
    items: list[ReleasePackageView]


def transport_models():
    return (ReleasePackageWrite, PublicationWrite, TargetRules, ReleaseTarget, ReleaseMaster,
            ReleasePackage, PublicationSummary, Publication, ReleasePackageReceipt, ReleasePackageView,
            ReleasePackageList)


def _in_scope(actor, scope, production_id):
    allowed = actor.productions(scope)
    if allowed is not None and production_id not in allowed:
        raise NotFound


def _run(conn, id, actor, scope, *, lock=False):
    row = runs.get(conn, _id(id, "run"), lock=lock)
    _in_scope(actor, scope, row["production_id"])
    return row


def _to_prepare(conn, id, actor):
    try:
        return _run(conn, id, actor, "runs:queue", lock=True)
    except NotFound:
        legacy = catalog.get_delivery(conn, id)
        if legacy is None or legacy.document["store"]["adapter"] != LEGACY_WAN_LEDGER:
            raise
        _in_scope(actor, "runs:queue", legacy.production_id)
        checks.refuse_legacy(None, legacy.document)
        raise


def _require_releasable(approval, publication):
    if publication is not None:
        raise APIError(409, "release.already_published", "This package already has a publication record")
    if approval is None:
        raise APIError(409, "release.approval_required", "The exact run and master need an active approval")


def _view(conn, index, document, identity_refusal):
    approval = packages.approval_for(conn, document)
    publication = packages.publication_for(conn, index["sha256"])
    return {
        "sha256": index["sha256"], "bytes": index["bytes"], "package": document,
        "state": "releasable" if approval is not None else "held",
        "approval_id": approval["id"] if approval is not None else None,
        "held_reason": "release.approval_required" if approval is None else None,
        "publication": publication,
        "record_publication": _decision(identity_refusal or _refusal(_require_releasable, approval, publication)),
    }


def build_routers(CurrentActor, authenticated_route, approval_route):
    router = APIRouter(prefix="/v1", tags=["release"], responses=ERROR_RESPONSES,
                       route_class=authenticated_route)
    approver = APIRouter(prefix="/v1", tags=["release"], responses=ERROR_RESPONSES,
                         route_class=approval_route)

    @router.get("/runs/{id}/release-packages", response_model=ReleasePackageList,
                operation_id="list_release_packages")
    def list_release_packages(id: str, request: Request, actor: CurrentActor):
        state = request.app.state
        with snapshot(state.engine) as conn:
            row = _run(conn, id, actor, "read")
            refusal = _refusal(require_approver, actor, state.oidc.settings, runs.database_time(conn))
            return {"targets": packages.targets(row["snapshot"]), "items": [
                _view(conn, item, packages.load(state.store, row["production_id"], item), refusal)
                for item in packages.for_run(conn, row["id"])
            ]}

    @router.post("/runs/{id}/release-packages", status_code=201, response_model=ReleasePackageReceipt,
                 responses={200: {"model": ReleasePackageReceipt}}, operation_id="prepare_release_package")
    def prepare_release_package(id: str, body: ReleasePackageWrite, request: Request,
                                response: Response, actor: CurrentActor):
        state = request.app.state
        with state.engine.begin() as conn:
            row = _to_prepare(conn, id, actor)
            for item in packages.for_run(conn, row["id"]):
                if item["target_id"] == body.target_id:
                    packages.load(state.store, row["production_id"], item)
                    response.status_code = 200
                    return dict(item)
            delivery_row = catalog.get_delivery(conn, row["id"])
            delivery = delivery_row.document if delivery_row is not None else None
            master_sha256 = delivery["master"]["sha256"] if delivery is not None else None
            run = row["document"]
            verified = checks.verify_delivery(run, delivery, master_sha256)
            saved = packages.saved_checks(conn, state.store, row, delivery)
            evidence = checks.checked_evidence(run, verified, True, saved)
            document = packages.build(run, row["snapshot"], delivery, body.target_id, evidence)
            return packages.save(conn, state.store, row["production_id"], document)

    @approver.post("/runs/{id}/publications", status_code=201, response_model=Publication,
                   operation_id="record_publication")
    def record_publication(id: str, body: PublicationWrite, request: Request, actor: CurrentActor):
        state = request.app.state
        with state.engine.begin() as conn:
            # Approve and withdraw take the same run lock. It also fences duplicate drops.
            row = _run(conn, id, actor, "read", lock=True)
            now = runs.database_time(conn)
            require_approver(actor, state.oidc.settings, now)
            index = next((item for item in packages.for_run(conn, row["id"])
                          if item["sha256"] == body.package_sha256), None)
            if index is None:
                raise NotFound
            document = packages.load(state.store, row["production_id"], index)
            approval = packages.approval_for(conn, document)
            _require_releasable(approval, packages.publication_for(conn, body.package_sha256))
            if not body.location.isprintable() or contains_credentials_in_prose(body.location):
                raise APIError(422, "release.location_invalid", "Enter a single public location without credentials",
                               path="/location")
            if body.published_at is not None and body.published_at > now:
                raise APIError(422, "release.publication_in_future", "Enter a publication time in the past",
                               path="/published_at")
            return packages.record_publication(conn, body.package_sha256, approval, body.location,
                                               to_document(actor.principal), actor.display_name, now,
                                               body.published_at)

    return router, approver
