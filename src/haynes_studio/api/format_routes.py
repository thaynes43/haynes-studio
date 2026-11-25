"""Routes for shared format recipes and local target-account metadata."""

from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from pydantic import StringConstraints

from haynes_studio.db.engine import snapshot
from haynes_studio.db.problems import NotFound
from haynes_studio.formats import records
from haynes_studio.formats.recipe import valid_slug

from .errors import APIError, ERROR_RESPONSES, forbidden
from .models import Body, Document, Page, TransportModel
from .routes import Cursor, Limit, _cursor, _id, _page

FormatID = Annotated[str, StringConstraints(
    max_length=64, pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$",
)]
FormatName = Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True)]
FormatCursor = Annotated[str | None, Query(max_length=64)]
VERSION_LOCATION = {201: {"headers": {"Location": {
    "schema": {"type": "string"}, "description": "Path to the new format version",
}}}}


class FormatRecipe(Document):
    pass


class FormatSummary(TransportModel):
    id: FormatID
    name: FormatName


class FormatCreate(Body):
    id: FormatID
    name: FormatName
    recipe: FormatRecipe


class VersionSummary(TransportModel):
    id: str
    format_id: FormatID
    number: int
    sha256: str


class VersionView(VersionSummary):
    recipe: FormatRecipe


def transport_models():
    return (FormatRecipe, FormatSummary, FormatCreate, VersionSummary, VersionView,
            Page[FormatSummary], Page[VersionSummary])


def _require(actor, scope: str) -> None:
    # The format catalog is shared. Agent grants are still provisioned per production.
    allowed = actor.productions(scope)
    if allowed is not None and not allowed:
        raise forbidden()


def _slug(value: str, path: str = "/id") -> str:
    if not valid_slug(value):
        raise APIError(422, "schema.invalid", "Expected a lowercase format slug", path=path)
    return value


def _location(response: Response, version: dict) -> dict:
    response.headers["Location"] = f'/v1/format-versions/{version["id"]}'
    return version


def build_router(CurrentActor, authenticated_route):
    router = APIRouter(prefix="/v1", tags=["formats"], responses=ERROR_RESPONSES,
                       route_class=authenticated_route)

    @router.post("/formats", response_model=VersionView, status_code=201,
                 responses=VERSION_LOCATION, operation_id="create_format")
    def create_format(body: FormatCreate, actor: CurrentActor, request: Request, response: Response):
        _require(actor, "formats:write")
        with request.app.state.engine.begin() as conn:
            version = records.create(conn, _slug(body.id), body.name, body.recipe.root)
            if version is None:
                raise APIError(409, "format.id_duplicate", "That format slug is already in use",
                               path="/id", existing_entity_id=body.id)
        return _location(response, version)

    @router.get("/formats", response_model=Page[FormatSummary], operation_id="list_formats")
    def list_formats(actor: CurrentActor, request: Request,
                     cursor: FormatCursor = None, limit: Limit = 50):
        _require(actor, "read")
        after = _slug(cursor, "/cursor") if cursor is not None else None
        with snapshot(request.app.state.engine) as conn:
            return _page(records.list_formats(conn, after, limit + 1), limit)

    @router.post("/formats/{id}/versions", response_model=VersionView, status_code=201,
                 responses=VERSION_LOCATION, operation_id="add_format_version")
    def add_version(id: str, body: FormatRecipe, actor: CurrentActor, request: Request, response: Response):
        _require(actor, "formats:write")
        with request.app.state.engine.begin() as conn:
            version = records.add_version(conn, _slug(id), body.root)
        return _location(response, version)

    @router.get("/formats/{id}/versions", response_model=Page[VersionSummary],
                operation_id="list_format_versions")
    def list_versions(id: str, actor: CurrentActor, request: Request,
                      cursor: Cursor = None, limit: Limit = 50):
        _require(actor, "read")
        with snapshot(request.app.state.engine) as conn:
            versions = records.list_versions(conn, _slug(id), _cursor(cursor, "fmv"), limit + 1)
        return _page(versions, limit)

    @router.get("/format-versions/{id}", response_model=VersionView, operation_id="get_format_version")
    def get_version(id: str, actor: CurrentActor, request: Request):
        _require(actor, "read")
        with snapshot(request.app.state.engine) as conn:
            version = records.version(conn, _id(id, "fmv"))
            if version is None:
                raise NotFound
        return version

    return router
