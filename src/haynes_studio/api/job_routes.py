"""Public asynchronous media operations and the direct D42 upload."""

from io import BytesIO
from threading import Lock
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Request, Response
from pydantic import Field, StringConstraints, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from haynes_studio.adapters.errors import AdapterError
from haynes_studio.assets.candidate import plan_candidate
from haynes_studio.canonical.ids import Minter, is_id
from haynes_studio.db import catalog, drafts, jobs
from haynes_studio.db.engine import snapshot
from haynes_studio.db.problems import NotFound, require_revision
from haynes_studio.db.runs import database_time, timestamp
from haynes_studio.jsonio import parse_strict
from haynes_studio.layered.errors import LayeredError
from haynes_studio.library.model import signature, version_document
from haynes_studio.photo.build import METHOD_INVALID, ExternalProvenance, import_photo
from haynes_studio.photo.plan import WHOLE_FRAME
from haynes_studio.photo_limits import TIMEOUT_CODE, TIMEOUT_MESSAGE, UploadBodyTimeout
from haynes_studio.photo.validation import MAX_UPLOAD_BYTES
from haynes_studio.queue.media_inputs import documents, photo_plan, photo_request, provenance
from haynes_studio.voice.jobs import new_job
from haynes_studio.voice.plan import plan_board_voice

from .errors import APIError, ERROR_RESPONSES, ErrorEnvelope, missing
from .media_completion import record_board_photo
from .models import AssetVersion, Body, Document, ExternalPhotoDeclaration, Nonempty, Page, Title, TransportModel
from .routes import ETAG, Cursor, IfMatch, Limit, _board_access, _cursor, _id, _page, _revision

IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", pattern=r"^[!-~]{1,255}$")]
UploadDeclaration = Annotated[str | None, Header(alias="X-Studio-Photo-Provenance",
    description="Strict ASCII JSON with Unicode escapes. See ExternalPhotoDeclaration.")]
Seed = Annotated[int, Field(ge=0, le=2**53 - 1)]
UPLOAD_MIMES = ("image/png", "image/jpeg", "image/webp")
_upload_slot = Lock()


class VoiceRequest(Body):
    pass


class PhotoRequest(Body):
    seed: Seed = 0


class CandidateRequest(Body):
    kind: Literal["cast", "costume", "set", "prop"]
    name: Title
    prompt: Annotated[str, StringConstraints(min_length=1, max_length=1800)]
    production_id: str | None = None
    labels: list[Nonempty] = Field(default_factory=list, max_length=100)
    seed: Seed = 0


class JobStatus(TransportModel):
    schema_: Literal["studio.job/v1"] = Field(alias="schema")
    id: str
    kind: Literal["voice", "photo", "asset_candidate"]
    target_id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    result_version_id: str | None
    result_is_current: bool | None
    error: dict | None
    updated_at: str


JOB_RESPONSES = {code: {"model": JobStatus, "headers": {"Location": {
    "schema": {"type": "string"}, "description": "Job status path",
}}} for code in (200, 202)}


class JobView(Document):
    pass


class PhotoUploadView(TransportModel):
    version: AssetVersion
    selected: bool
    board_revision: int | None


def transport_models():
    return (VoiceRequest, PhotoRequest, CandidateRequest, JobStatus, JobView, PhotoUploadView,
            Page[JobStatus])


def _queued(response, row, *, created):
    if not created:
        response.status_code = 200
    response.headers["Location"] = f'/v1/jobs/{row["id"]}'
    return row["document"]


def job_access(conn, actor, job_id):
    row = jobs.get(conn, job_id)
    allowed = actor.productions("read")
    if allowed is not None and (row["kind"] == "asset_candidate" or row["production_id"] not in allowed):
        raise NotFound
    return row


def _board_job(request, response, actor, board_id, key, kind, body):
    lane = "voice" if kind == "voice" else "image"
    fingerprint = signature(body.model_dump(exclude_unset=True))
    by = actor.principal
    with request.app.state.engine.begin() as conn:
        story_id = drafts.board_story(conn, _id(board_id, "brd"), include_tombstone=True)
        actor.require("assets:generate", drafts.story_production(conn, story_id))
        draft = drafts.get_draft(conn, story_id, lock=True)
        position = jobs.lock_lane(conn, lane)
        existing = jobs.lookup(conn, kind, board_id, by, key, fingerprint)
        if existing is not None:
            return _queued(response, existing, created=False)
        story, library = drafts.board_snapshot(conn, draft, board_id)
        now = timestamp(database_time(conn))
        if kind == "voice":
            voice = plan_board_voice(story, board_id, library).input
            job = new_job(kind, board_id, voice.input_signature, by=by, now=now, voice=voice)
            frozen = {"selected_version_id": story["boards"][0]["voice"]["current_version_id"]}
        else:
            plan = photo_plan(story, board_id, library)
            job = new_job(kind, board_id, photo_request(plan, body.seed), by=by, now=now)
            frozen = {"story": story, "seed": body.seed, "library": documents(library)}
        row = jobs.enqueue(conn, job, position=position, production=story["production_id"],
                           story=story_id, board=board_id, inputs=frozen, key=key, signature=fingerprint)
    return _queued(response, row, created=True)


def _provenance(request, value):
    invalid = APIError(422, "prov.external_incomplete", "Supply one valid D42 provenance declaration",
                       path="/provenance")
    values = request.headers.getlist("X-Studio-Photo-Provenance")
    if value is None or len(values) != 1 or len(value) > 64 * 1024:
        raise invalid
    try:
        value.encode("ascii")
        declaration = ExternalPhotoDeclaration.model_validate(parse_strict(value))
    except (ValueError, ValidationError, RecursionError):
        raise invalid from None
    for name in (declaration.model, declaration.session, declaration.harness):
        if any(part in (".", "..") for part in name.replace("\\", "/").split("/")):
            raise invalid
    if any(name in request.headers for name in ("content-disposition", "x-filename")):
        raise invalid
    return ExternalProvenance(**declaration.model_dump())


def _upload_inputs(state, actor, board_id, revision, declared):
    with snapshot(state.engine) as conn:
        story_id = _board_access(conn, actor, "assets:upload", board_id)
        draft = drafts.get_draft(conn, story_id)
        story, library = drafts.board_snapshot(conn, draft, board_id, declared.source_asset_version_ids)
        board = story["boards"][0]
        require_revision(board["revision"], revision)
        if board["method"]["layer"] != WHOLE_FRAME:
            raise APIError(422, METHOD_INVALID, "Layered board photos come from the compositor",
                           path="/method/layer")
        # The current ID fences selection. Bytes are required only for media
        # that is actually used as a source for the replacement.
        return story_id, photo_plan(story, board_id, library), library


def _write_upload(state, actor, story_id, prepared):
    with state.engine.begin() as conn:
        draft = drafts.get_draft(conn, story_id, lock=True)
        now = timestamp(database_time(conn))
        document, revision = record_board_photo(conn, state.store, draft, prepared, actor.principal, now)
        return {"version": document, "selected": revision is not None, "board_revision": revision}


def build_router(CurrentActor, authenticated_route):
    router = APIRouter(prefix="/v1", tags=["media jobs"], route_class=authenticated_route,
                       responses=ERROR_RESPONSES)

    @router.post("/boards/{id}/voice-jobs", operation_id="generate_board_voice", status_code=202,
                 response_model=JobStatus, responses=JOB_RESPONSES)
    def generate_voice(id: str, body: VoiceRequest, request: Request, response: Response,
                       actor: CurrentActor, idempotency_key: IdempotencyKey):
        return _board_job(request, response, actor, id, idempotency_key, "voice", body)

    @router.post("/boards/{id}/photo-jobs", operation_id="generate_board_photo", status_code=202,
                 response_model=JobStatus, responses=JOB_RESPONSES)
    def generate_photo(id: str, body: PhotoRequest, request: Request, response: Response,
                       actor: CurrentActor, idempotency_key: IdempotencyKey):
        try:
            return _board_job(request, response, actor, id, idempotency_key, "photo", body)
        except (AdapterError, LayeredError) as error:
            raise APIError(422, error.code, str(error), path="/photo") from error

    @router.post("/asset-jobs", operation_id="generate_asset_candidate", status_code=202,
                 response_model=JobStatus, responses=JOB_RESPONSES)
    def generate_candidate(body: CandidateRequest, request: Request, response: Response,
                           actor: CurrentActor, idempotency_key: IdempotencyKey):
        actor.human()
        inputs = body.model_dump()
        fingerprint = signature(body.model_dump(exclude_unset=True))
        by = actor.principal
        production = body.production_id
        with request.app.state.engine.begin() as conn:
            position = jobs.lock_lane(conn, "image")
            existing = jobs.lookup(conn, "asset_candidate", "asset-jobs", by, idempotency_key, fingerprint)
            if existing is not None:
                return _queued(response, existing, created=False)
            if production is not None:
                drafts.production(conn, _id(production, "prd", "/production_id"))
            minter = Minter()
            job_id, asset_id = minter.mint("job"), minter.mint("ast")
            try:
                plan = plan_candidate(job_id=job_id, asset_id=asset_id, by=by, **inputs)
            except AdapterError as error:
                raise APIError(422, error.code, error.message, path="/prompt") from error
            now = timestamp(database_time(conn))
            # The ID participates in the candidate source key. Reuse that exact mint.
            job = new_job("asset_candidate", asset_id, plan.input_signature, by=by, now=now,
                          job_id=job_id)
            frozen = {**inputs, "name": plan.name, "prompt": plan.request.prompt,
                      "labels": list(plan.labels)}
            row = jobs.enqueue(conn, job, position=position, production=production, inputs=frozen,
                               key=idempotency_key, signature=fingerprint)
        return _queued(response, row, created=True)

    @router.get("/jobs/{id}", response_model=JobView, operation_id="get_job")
    def get_job(id: str, request: Request, actor: CurrentActor):
        with snapshot(request.app.state.engine) as conn:
            row = job_access(conn, actor, _id(id, "job"))
            document = jobs.job_document(row)
            return {**document, **provenance(document, row["inputs"])}

    @router.get("/jobs/{id}/result", response_model=AssetVersion, operation_id="get_job_result")
    def get_job_result(id: str, request: Request, actor: CurrentActor):
        if actor.principal.kind != "human" or not is_id(id, "job"):
            raise missing()
        with snapshot(request.app.state.engine) as conn:
            row = job_access(conn, actor, id)
            version_id = row["document"]["result_version_id"]
            if version_id is None:
                raise NotFound
            library = catalog.version_library(conn, version_id=version_id)
            version = library.get(version_id)
            if version is None:
                raise NotFound
            asset = library.asset_of(version_id)
            if asset.scope.production_id != row["production_id"]:
                raise NotFound
            return version_document(version, asset)

    @router.get("/boards/{id}/jobs", response_model=Page[JobStatus], operation_id="list_board_jobs")
    def list_jobs(id: str, request: Request, actor: CurrentActor, cursor: Cursor = None, limit: Limit = 50):
        with snapshot(request.app.state.engine) as conn:
            _board_access(conn, actor, "read", id)
            rows = jobs.list_board(conn, id, _cursor(cursor, "job"), limit + 1)
            return _page([row["document"] for row in rows], limit)

    @router.get("/boards/{id}/voice-versions", response_model=Page[AssetVersion],
                operation_id="list_board_voice_versions")
    @router.get("/boards/{id}/photo-versions", response_model=Page[AssetVersion],
                operation_id="list_board_photo_versions")
    def list_versions(id: str, request: Request, actor: CurrentActor, cursor: Cursor = None, limit: Limit = 50):
        kind = "board_voice" if request.url.path.endswith("/voice-versions") else "photo"
        with snapshot(request.app.state.engine) as conn:
            _board_access(conn, actor, "read", id)
            items = catalog.board_versions(conn, id, kind, _cursor(cursor, "asv"), limit + 1)
            return _page(items, limit)

    @router.post("/asset-versions/{id}/promote", response_model=AssetVersion, operation_id="promote_asset_version")
    def promote(id: str, request: Request, actor: CurrentActor):
        actor.human()
        with request.app.state.engine.begin() as conn:
            return catalog.promote_version(conn, _id(id, "asv"), actor.principal, timestamp(database_time(conn)))

    class RawPhotoRoute(authenticated_route):
        body_limit = MAX_UPLOAD_BYTES

        def too_large(self):
            return APIError(413, "photo.too_large", "An upload can be at most 20 MiB", path="/photo")

    upload = APIRouter(route_class=RawPhotoRoute)

    @upload.post("/boards/{id}/photo-versions", status_code=201, operation_id="upload_board_photo",
                 response_model=PhotoUploadView, responses={
                     201: {"headers": ETAG},
                     408: {"model": ErrorEnvelope, "description": "The photo upload body timed out"},
                 },
                 openapi_extra={"requestBody": {
                     "required": True, "content": {mime: {"schema": {"type": "string", "format": "binary"}}
                                                    for mime in UPLOAD_MIMES},
                 }})
    async def upload_photo(id: str, request: Request, response: Response, actor: CurrentActor, if_match: IfMatch,
                           declaration: UploadDeclaration = None):
        if actor.principal.kind != "agent":
            raise APIError(403, "auth.forbidden", "D42 uploads require an agent key")
        declared = _provenance(request, declaration)
        state = request.app.state
        story_id, plan, library = await run_in_threadpool(
            _upload_inputs, state, actor, id, _revision(if_match), declared,
        )
        media_type = request.headers.get("content-type", "")
        if media_type not in UPLOAD_MIMES or request.headers.get("content-encoding", "identity") != "identity":
            raise APIError(422, "photo.image_invalid", "Supply an uncompressed PNG, JPEG or WebP body",
                           path="/photo")
        if not _upload_slot.acquire(blocking=False):
            raise APIError(503, "photo.upload_busy", "Another photo upload is in progress. Retry shortly",
                           headers={"Retry-After": "1"})
        try:
            # BytesIO can hand off its final bytes without retaining a bytearray
            # alongside them. The route counts incoming bytes before each write.
            with BytesIO() as content:
                async for chunk in state.upload_body_limits.stream(request):
                    content.write(chunk)
                data = content.getvalue()
            prepared = await run_in_threadpool(import_photo, plan, library, data=data,
                                               media_type=media_type, declared=declared, by=actor.principal)
            del data
            result = await run_in_threadpool(_write_upload, state, actor, story_id, prepared)
        except UploadBodyTimeout as error:
            raise APIError(408, TIMEOUT_CODE, TIMEOUT_MESSAGE, path="/photo") from error
        except ClientDisconnect as error:
            raise APIError(400, "photo.upload_disconnected", "The client disconnected during upload",
                           path="/photo") from error
        finally:
            _upload_slot.release()
        if result["board_revision"] is not None:
            response.headers["ETag"] = f'"{result["board_revision"]}"'
        return result

    router.include_router(upload)
    return router
