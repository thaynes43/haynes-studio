"""Private production-scoped archive metadata, exact text reads and draft apply."""

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Request, Response
from pydantic import Field, StringConstraints

from haynes_studio.adapters.errors import contains_credentials_in_prose
from haynes_studio.canonical.model import to_document
from haynes_studio.db import drafts, staging_archive as archive
from haynes_studio.db.engine import snapshot
from haynes_studio.db.problems import NotFound
from haynes_studio.db.schema import format_versions
from haynes_studio.drafting import archive as apply_archive
from haynes_studio.drafting.declaration import SHA256
from haynes_studio.drafting.document import Draft
from haynes_studio.errors import ContractError
from haynes_studio.store import canonical_json

from .errors import APIError, ERROR_RESPONSES
from .models import Body, Page, Title, TransportModel
from .routes import Cursor, ETAG, IfMatch, Limit, _cursor, _etag, _id, _page, _revision
from .run_routes import IdempotencyKey
from .transport import access_log

MAX_TEXT_BYTES = 256 * 1024
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
Kind = Literal["brief", "script", "storyboard"]
SourceLabel = Annotated[str, StringConstraints(max_length=40, pattern=r"^[A-Za-z][A-Za-z0-9]*-[0-9]+$")]
ArchiveText = Annotated[str, Field(description="Exact UTF-8 text, at most 256 KiB after decoding")]
ARCHIVE_SCOPES = {
    "create_archive_record": "archive:write",
    "add_archive_version": "archive:write",
    "list_archive_records": "archive:read",
    "get_archive_record": "archive:read",
    "get_archive_version": "archive:read",
    "apply_archive_storyboard": ["archive:read", "draft:write"],
}


class Original(Body):
    origin: Literal["original"]


class SourceLocator(Body):
    label: SourceLabel
    sha256: SHA256


class Adapted(Body):
    origin: Literal["adapted"]
    source_locator: SourceLocator


Provenance = Annotated[Original | Adapted, Field(discriminator="origin")]


class StoredSourceLocator(TransportModel):
    label: SourceLabel
    hmac_sha256: SHA256


class StoredAdapted(TransportModel):
    origin: Literal["adapted"]
    source_locator: StoredSourceLocator


StoredProvenance = Annotated[Original | StoredAdapted, Field(discriminator="origin")]


class ArchiveVersionWrite(Body):
    text: ArchiveText
    format_version_id: str | None = None
    provenance: Provenance


class ArchiveCreate(ArchiveVersionWrite):
    kind: Kind
    title: Title


class ArchiveAppend(ArchiveVersionWrite):
    revises_version_id: str


class ArchiveRecord(TransportModel):
    id: str
    production_id: str
    kind: Kind
    title: str
    head_version_id: str


class ArchiveVersion(TransportModel):
    id: str
    record_id: str
    number: int
    revises_version_id: str | None
    bytes: int
    sha256: SHA256
    format_version_id: str | None
    provenance: StoredProvenance
    written_by: dict[str, str]
    written_at: datetime


class ArchiveVersionText(ArchiveVersion):
    text: ArchiveText


class ArchiveCreated(ArchiveRecord):
    version: ArchiveVersion


class ArchiveRecordDetail(ArchiveRecord):
    versions: list[ArchiveVersion]
    next_cursor: str | None


class ArchiveApply(Body):
    story_id: str


class ArchiveBoardOutcome(TransportModel):
    key: str | None
    board_id: str | None
    outcome: Literal["applied", "conflict", "skipped"]
    reason: str
    stamped_version_id: str | None = None


class ArchiveApplication(TransportModel):
    story_id: str
    archive_version_id: str
    revision: int
    boards: list[ArchiveBoardOutcome]


def transport_models():
    return (Original, SourceLocator, Adapted, ArchiveVersionWrite, ArchiveCreate, ArchiveAppend, ArchiveRecord,
            ArchiveVersion, ArchiveVersionText, ArchiveCreated, ArchiveRecordDetail, ArchiveApply,
            ArchiveBoardOutcome, ArchiveApplication, Page[ArchiveRecord])


def _text(value: str, path: str) -> bytes:
    try:
        data = value.encode("utf-8")
    except UnicodeError:
        raise APIError(422, "archive.invalid_text", "Expected UTF-8 text", path=path) from None
    if len(data) > MAX_TEXT_BYTES:
        raise APIError(413, "archive.too_large", "Archive text is limited to 256 KiB", path=path)
    if _CONTROL.search(value):
        raise APIError(422, "archive.invalid_text", "Archive text contains a control character", path=path)
    if contains_credentials_in_prose(value):
        raise APIError(422, "archive.credentials", "Remove credentials from archive content", path=path)
    return data


def _decoded_text(value):
    # The outer string can contain JSON escapes. Check the actual compiled board text too.
    if isinstance(value, Mapping):
        for key, item in value.items():
            _decoded_text(key)
            _decoded_text(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _decoded_text(item)
    elif isinstance(value, str):
        _text(value, "/text")


def _board_error(error: ContractError) -> APIError:
    first = error.violations[0]
    # Board diagnostics may contain values from private draft text.
    return APIError(422, first.rule, "Storyboard validation failed", path="/text")


def _validated_version(conn, record, payload):
    data = _text(payload["text"], "/text")
    provenance = payload["provenance"]
    if provenance["origin"] == "adapted":
        _text(provenance["source_locator"]["label"], "/provenance/source_locator/label")
    format_id = payload["format_version_id"]
    if format_id is not None:
        _id(format_id, "fmv", "/format_version_id")
        if conn.scalar(sa.select(format_versions.c.id).where(format_versions.c.id == format_id)) is None:
            raise APIError(422, "ref.unknown", "The format version does not exist", path="/format_version_id")
    if record["kind"] == "storyboard":
        try:
            draft = Draft.parse(data)
            data = draft.archive_bytes()
        except ContractError as error:
            raise _board_error(error) from None
        if draft.production_id != record["production_id"]:
            raise APIError(422, "archive.production_mismatch", "The draft belongs to another production", path="/text")
        _decoded_text((draft.model, draft.session, *(board.fields for board in draft.boards)))
        return _text(data.decode("utf-8"), "/text")
    return data


def _payload(body):
    return body.model_dump(include=set(ArchiveVersionWrite.model_fields))


def _stored_payload(request, production_id, payload):
    provenance = payload["provenance"]
    if provenance["origin"] == "original":
        return payload
    locator = provenance["source_locator"]
    key = hmac.digest(request.app.state.archive_source_key, production_id.encode("ascii"), "sha256")
    digest = hmac.digest(key, bytes.fromhex(locator["sha256"]), "sha256").hex()
    return {**payload, "provenance": {"origin": "adapted", "source_locator": {
        "label": locator["label"], "hmac_sha256": digest,
    }}}


def _read_version(conn, version_id):
    version = archive.version(conn, version_id)
    data = version["text"].encode("utf-8")
    if hashlib.sha256(data).hexdigest() != version["sha256"]:
        raise APIError(500, "archive.text_hash_mismatch", "Stored archive text failed its integrity check")
    return version, data


def _replay(conn, key_hash, request_hash):
    result = archive.previous_request(conn, key_hash)
    if result is not None and result["request_sha256"] != request_hash:
        raise APIError(422, "idempotency.mismatch", "This key already stored a different request")
    return result


def _request_hash(document):
    return hashlib.sha256(canonical_json(document)).hexdigest()


def _audit(action, record, version, request, story_id=None):
    event = {
        "action": f"archive.{action}", "request_id": request.state.request_id,
        "production_id": record["production_id"], "record_id": record["id"], "kind": record["kind"],
        "version_id": version["id"], "bytes": version["bytes"], "sha256": version["sha256"],
    }
    if story_id is not None:
        event["story_id"] = story_id
    access_log.info("%s", json.dumps(event, separators=(",", ":")))


def _visible(actor):
    """Productions whose archive the caller can see at all. None means every production."""
    read, write = actor.productions("archive:read"), actor.productions("archive:write")
    return None if read is None or write is None else read | write


def _location(response, version):
    response.headers["Location"] = f'/v1/archive-versions/{version["id"]}'


def build_router(CurrentActor, authenticated_route):
    router = APIRouter(prefix="/v1", tags=["archive"], responses=ERROR_RESPONSES,
                       route_class=authenticated_route)

    @router.post("/productions/{id}/archive-records", status_code=201, response_model=ArchiveCreated,
                 responses={200: {"model": ArchiveCreated}}, operation_id="create_archive_record")
    def create_record(id: str, body: ArchiveCreate, request: Request, response: Response,
                      actor: CurrentActor, idempotency_key: IdempotencyKey):
        production_id = _id(id, "prd")
        actor.require("archive:write", production_id)
        principal = to_document(actor.principal)
        payload = _payload(body)
        key_hash = archive.request_key("create", production_id, principal, idempotency_key)
        request_hash = _request_hash(body.model_dump())
        with request.app.state.engine.begin() as conn:
            archive.lock(conn, key_hash)
            version = _replay(conn, key_hash, request_hash)
            if version is None:
                drafts.production(conn, production_id)
                _text(body.title, "/title")
                data = _validated_version(conn, {"kind": body.kind, "production_id": production_id}, payload)
                record = archive.create_record(conn, production_id, body.kind, body.title)
                version = archive.append(conn, record["id"], number=1, previous=None, data=data,
                                         payload=_stored_payload(request, production_id, payload),
                                         principal=principal, key_hash=key_hash, request_hash=request_hash)
            else:
                response.status_code = 200
                record = archive.record(conn, version["record_id"])
        if response.status_code != 200:
            _audit("created", record, version, request)
        _location(response, version)
        return {**record, "head_version_id": version["id"], "version": version}

    @router.post("/archive-records/{id}/versions", status_code=201, response_model=ArchiveVersion,
                 responses={200: {"model": ArchiveVersion}}, operation_id="add_archive_version")
    def add_version(id: str, body: ArchiveAppend, request: Request, response: Response,
                    actor: CurrentActor, idempotency_key: IdempotencyKey):
        record_id = _id(id, "arc")
        principal = to_document(actor.principal)
        with request.app.state.engine.begin() as conn:
            # A record the caller cannot see answers like an unknown one.
            record = archive.record(conn, record_id, _visible(actor))
            actor.require("archive:write", record["production_id"])
            key_hash = archive.request_key("append", record_id, principal, idempotency_key)
            request_hash = _request_hash(body.model_dump())
            archive.lock(conn, record_id)
            version = _replay(conn, key_hash, request_hash)
            if version is None:
                previous = _id(body.revises_version_id, "arv", "/revises_version_id")
                head = archive.head(conn, record_id)
                if previous != head["id"]:
                    raise APIError(409, "archive.stale_version", "The archive record has a newer version",
                                   path="/revises_version_id", existing_entity_id=head["id"])
                payload = _payload(body)
                data = _validated_version(conn, record, payload)
                version = archive.append(conn, record_id, number=head["number"] + 1, previous=previous,
                                         payload=_stored_payload(request, record["production_id"], payload),
                                         data=data, principal=principal, key_hash=key_hash,
                                         request_hash=request_hash)
            else:
                response.status_code = 200
        if response.status_code != 200:
            _audit("appended", record, version, request)
        _location(response, version)
        return version

    @router.get("/productions/{id}/archive-records", response_model=Page[ArchiveRecord],
                operation_id="list_archive_records")
    def list_records(id: str, request: Request, actor: CurrentActor, cursor: Cursor = None, limit: Limit = 50):
        production_id = _id(id, "prd")
        actor.require("archive:read", production_id)
        with snapshot(request.app.state.engine) as conn:
            drafts.production(conn, production_id)
            rows = archive.production_records(conn, production_id, _cursor(cursor, "arc"), limit + 1)
        return _page(rows, limit)

    @router.get("/archive-records/{id}", response_model=ArchiveRecordDetail, operation_id="get_archive_record")
    def get_record(id: str, request: Request, actor: CurrentActor, cursor: Cursor = None, limit: Limit = 50):
        with snapshot(request.app.state.engine) as conn:
            record = archive.record(conn, _id(id, "arc"), actor.productions("archive:read"))
            head = archive.head(conn, id)
            page = _page(archive.history(conn, id, _cursor(cursor, "arv"), limit + 1), limit)
        return {**record, "head_version_id": head["id"], "versions": page["items"], "next_cursor": page["next_cursor"]}

    @router.get("/archive-versions/{id}", response_model=ArchiveVersionText, operation_id="get_archive_version")
    def get_version(id: str, request: Request, actor: CurrentActor):
        with snapshot(request.app.state.engine) as conn:
            record = archive.version_record(conn, _id(id, "arv"), actor.productions("archive:read"))
            version, _ = _read_version(conn, id)
        _audit("read", record, version, request)
        return version

    @router.post("/archive-versions/{id}/apply", response_model=ArchiveApplication,
                 response_model_exclude_unset=True, responses={200: {"headers": ETAG}},
                 operation_id="apply_archive_storyboard")
    def apply_version(id: str, body: ArchiveApply, request: Request, response: Response,
                      actor: CurrentActor, if_match: IfMatch):
        with request.app.state.engine.begin() as conn:
            # A version the caller cannot read answers like an unknown one.
            record = archive.version_record(conn, _id(id, "arv"), actor.productions("archive:read"))
            production_id = record["production_id"]
            actor.require("draft:write", production_id)
            story_id = _id(body.story_id, "sty", "/story_id")
            if drafts.story_production(conn, story_id) != production_id:
                raise NotFound
            if record["kind"] != "storyboard":
                raise APIError(422, "archive.not_storyboard", "Only storyboard versions can be applied")
            version, data = _read_version(conn, id)
            try:
                draft = Draft.parse(data)
                if draft.story_id != story_id:
                    raise APIError(422, "archive.story_mismatch", "The draft names another story", path="/story_id")
                result = apply_archive.apply(conn, draft, version, _revision(if_match), to_document(actor.principal))
            except ContractError as error:
                raise _board_error(error) from None
        _audit("applied", record, version, request, story_id)
        return _etag(response, result)

    return router
