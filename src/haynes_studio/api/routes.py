"""The /v1 metadata routes owned by story 409."""

import hmac
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query, Request, Response
from pydantic import ValidationError

from haynes_studio.canonical.ids import is_id
from haynes_studio.canonical.model import to_document
from haynes_studio.db import catalog, drafts, identity
from haynes_studio.db.engine import snapshot
from haynes_studio.db.problems import NotFound
from haynes_studio.drafting.declaration import READ_TOKEN_HEADER, PersonEditAcknowledgment
from haynes_studio.errors import pointer
from haynes_studio.library.resolve import board_references

from .errors import APIError, ERROR_RESPONSES
from .models import (
    AssetDetail, AssetVersion, Board, BoardCreate, BoardOrder, BoardPatch, BoardRemoval,
    Delivery, Me, MediaKind, Page,
    Production, ProductionCreate, Selections, SelectionWrite, Story, StoryCreate, StoryPatch, Timing,
)

Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=30,
    description="Pass next_cursor from the previous page under the same filters")]
IfMatch = Annotated[str, Header(alias="If-Match", max_length=21,
    description='Current integer revision, quoted as an ETag, for example "3"')]
_REVISION = re.compile(r'(?:("(?:0|[1-9][0-9]{0,18})")|((?:0|[1-9][0-9]{0,18})))')
ETAG = {"ETag": {"schema": {"type": "string"}, "description": "The entity revision"}}


def _revision(value: str, *, zero: bool = False):
    if _REVISION.fullmatch(value) is not None:
        rev = int(value.strip('"'))
        if (zero or rev > 0) and rev < 2**63 - 1:
            return rev
    raise APIError(422, "schema.invalid", "If-Match must contain one integer revision",
                   path="/revision")


def _id(value: str, prefix: str, path: str = "/id") -> str:
    if not is_id(value):
        raise APIError(422, "id.malformed", "Expected a canonical identifier", path=path)
    if not is_id(value, prefix):
        raise APIError(422, "id.type_mismatch", f"Expected a {prefix}_ identifier", path=path)
    return value


def _cursor(value: str | None, prefix: str):
    return None if value is None else _id(value, prefix, "/cursor")


def _page(items: list[dict], limit: int) -> dict:
    return {"items": items[:limit], "next_cursor": items[limit - 1]["id"] if len(items) > limit else None}


def _etag(response: Response, doc: dict) -> dict:
    response.headers["ETag"] = f'"{doc["revision"]}"'
    return doc


def _story_access(conn, actor, scope, id):
    actor.require(scope, drafts.story_production(conn, _id(id, "sty")))


def _board_access(conn, actor, scope, id) -> str:
    story_id = drafts.board_story(conn, _id(id, "brd"))
    _story_access(conn, actor, scope, story_id)
    return story_id


def _board_read_token(request: Request, key_id: str, board_id: str, revision: int) -> str:
    payload = f"{key_id}:{board_id}:{revision}".encode()
    return hmac.digest(request.app.state.board_read_key, payload, "sha256").hex()


def _acknowledged_revision(request: Request, actor, board_id: str,
                           ack: PersonEditAcknowledgment | None) -> int | None:
    if ack is None or actor.principal.kind != "agent":
        return None
    token = _board_read_token(request, actor.principal.key_id, board_id, ack.board_revision)
    if not hmac.compare_digest(ack.read_token, token):
        raise APIError(422, "draft.invalid_read_token", "Read the board at this revision with this key",
                       path="/acknowledge_person_edit/read_token")
    return ack.board_revision


def build_router(CurrentActor, authenticated_route):
    router = APIRouter(prefix="/v1", responses=ERROR_RESPONSES, route_class=authenticated_route)

    @router.get("/me", tags=["identity"], response_model=Me, response_model_exclude_none=True,
                operation_id="get_me")
    def me(actor: CurrentActor):
        result = {"principal": to_document(actor.principal), "display_name": actor.display_name,
                  "csrf_token": actor.csrf}
        if actor.principal.kind == "agent":
            result["production_scopes"] = {id_: sorted(scopes) for id_, scopes in actor.grants.items()}
        return result


    @router.get("/me/selections", tags=["identity"], response_model=Selections,
                responses={200: {"headers": ETAG}}, operation_id="get_selections")
    def get_selections(request: Request, response: Response, actor: CurrentActor):
        actor.human()
        with snapshot(request.app.state.engine) as conn:
            return _etag(response, identity.get_selections(conn, actor.principal.iss, actor.principal.sub))


    @router.put("/me/selections", tags=["identity"], response_model=Selections,
                responses={200: {"headers": ETAG}}, operation_id="put_selections")
    def put_selections(body: SelectionWrite, request: Request, response: Response, actor: CurrentActor,
                       if_match: IfMatch):
        actor.human()
        with request.app.state.engine.begin() as conn:
            return _etag(response, identity.put_selections(
                conn, actor.principal.iss, actor.principal.sub, _revision(if_match, zero=True), body.values,
            ))


    @router.get("/productions", tags=["productions"], response_model=Page[Production],
                operation_id="list_productions")
    def list_productions(request: Request, actor: CurrentActor, cursor: Cursor = None, limit: Limit = 50):
        with snapshot(request.app.state.engine) as conn:
            docs = drafts.list_productions(conn, actor.productions("read"), _cursor(cursor, "prd"), limit + 1)
        return _page(docs, limit)


    @router.post("/productions", tags=["productions"], response_model=Production, status_code=201,
                 responses={201: {"headers": ETAG}}, operation_id="create_production")
    def create_production(body: ProductionCreate, request: Request, response: Response, actor: CurrentActor):
        actor.human()
        with request.app.state.engine.begin() as conn:
            doc = drafts.create_production(conn, body.name, body.labels, to_document(actor.principal))
        response.headers["Location"] = f'/v1/productions/{doc["id"]}'
        return _etag(response, doc)


    @router.get("/productions/{id}", tags=["productions"], response_model=Production,
                responses={200: {"headers": ETAG}}, operation_id="get_production")
    def get_production(id: str, request: Request, response: Response, actor: CurrentActor):
        actor.require("read", _id(id, "prd"))
        with snapshot(request.app.state.engine) as conn:
            return _etag(response, drafts.production(conn, id))


    @router.put("/productions/{id}/media-types/{kind}", tags=["productions"], response_model=Production,
                responses={200: {"headers": ETAG}}, operation_id="enable_media_type")
    def enable_media_type(id: str, kind: MediaKind, request: Request, response: Response,
                          actor: CurrentActor, if_match: IfMatch):
        actor.human()
        with request.app.state.engine.begin() as conn:
            doc = drafts.enable_media_type(conn, _id(id, "prd"), kind, _revision(if_match))
        return _etag(response, doc)


    @router.get("/productions/{id}/media-types/{kind}/stories", tags=["stories"],
                response_model=Page[Story], operation_id="list_stories")
    def list_stories(id: str, kind: MediaKind, request: Request, actor: CurrentActor,
                     publication: Literal["published", "unpublished"] | None = None,
                     approved: bool | None = None, cursor: Cursor = None, limit: Limit = 50):
        actor.require("read", _id(id, "prd"))
        after = _cursor(cursor, "sty")
        with snapshot(request.app.state.engine) as conn:
            published = publication == "published" if publication is not None else None
            return _page(drafts.list_stories(conn, id, kind, after, limit + 1,
                                            published=published, approved=approved), limit)


    @router.post("/productions/{id}/media-types/{kind}/stories", tags=["stories"],
                 response_model=Story, status_code=201, responses={201: {"headers": ETAG}},
                 operation_id="create_story")
    def create_story(id: str, kind: MediaKind, body: StoryCreate, request: Request, response: Response,
                     actor: CurrentActor):
        actor.require("draft:write", _id(id, "prd"))
        with request.app.state.engine.begin() as conn:
            draft = drafts.create_story(conn, id, kind, body.root, to_document(actor.principal))
            doc = draft.summary(conn)
        response.headers["Location"] = f'/v1/stories/{doc["id"]}'
        return _etag(response, doc)


    @router.get("/stories/{id}", tags=["stories"], response_model=Story,
                responses={200: {"headers": ETAG}}, operation_id="get_story")
    def get_story(id: str, request: Request, response: Response, actor: CurrentActor):
        with snapshot(request.app.state.engine) as conn:
            _story_access(conn, actor, "read", id)
            return _etag(response, drafts.get_draft(conn, id).summary(conn))


    @router.patch("/stories/{id}", tags=["stories"], response_model=Story,
                  responses={200: {"headers": ETAG}}, operation_id="update_story")
    def update_story(id: str, body: StoryPatch, request: Request, response: Response, actor: CurrentActor,
                     if_match: IfMatch):
        with request.app.state.engine.begin() as conn:
            _story_access(conn, actor, "draft:write", id)
            doc = drafts.edit_story(conn, id, _revision(if_match), body.root).summary(conn)
        return _etag(response, doc)


    @router.get("/stories/{id}/timing", tags=["stories"], response_model=Timing,
                operation_id="get_story_timing")
    def get_story_timing(id: str, request: Request, actor: CurrentActor):
        with snapshot(request.app.state.engine) as conn:
            _story_access(conn, actor, "read", id)
            return drafts.get_draft(conn, id).timing(conn)


    @router.post("/stories/{id}/boards", tags=["boards"], response_model=Board, status_code=201,
                 responses={201: {"headers": ETAG}}, operation_id="create_board")
    def create_board(id: str, body: BoardCreate, request: Request, response: Response, actor: CurrentActor,
                     if_match: IfMatch):
        with request.app.state.engine.begin() as conn:
            _story_access(conn, actor, "draft:write", id)
            draft, board_id = drafts.add_board(conn, id, _revision(if_match), body.root,
                                               to_document(actor.principal))
            doc = draft.board(conn, board_id)
        response.headers["Location"] = f"/v1/boards/{board_id}"
        return _etag(response, doc)


    @router.get("/boards/{id}", tags=["boards"], response_model=Board, responses={200: {"headers": {
        **ETAG, READ_TOKEN_HEADER: {
            "schema": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "description": "For agent reads. Bound to the agent key, board ID and board revision.",
        },
    }}}, operation_id="get_board")
    def get_board(id: str, request: Request, response: Response, actor: CurrentActor):
        with snapshot(request.app.state.engine) as conn:
            story_id = _board_access(conn, actor, "read", id)
            doc = drafts.get_draft(conn, story_id).board(conn, id)
        if actor.principal.kind == "agent":
            response.headers[READ_TOKEN_HEADER] = _board_read_token(
                request, actor.principal.key_id, id, doc["revision"])
        return _etag(response, doc)


    @router.patch("/boards/{id}", tags=["boards"], response_model=Board,
                  responses={200: {"headers": ETAG}}, operation_id="update_board")
    def update_board(id: str, body: BoardPatch, request: Request, response: Response, actor: CurrentActor,
                     if_match: IfMatch):
        with request.app.state.engine.begin() as conn:
            story_id = _board_access(conn, actor, "draft:write", id)
            fields = dict(body.root)
            ack = None
            if "acknowledge_person_edit" in fields:
                try:
                    ack = PersonEditAcknowledgment.model_validate(fields.pop("acknowledge_person_edit"))
                except ValidationError as error:
                    first = error.errors(include_input=False)[0]
                    raise APIError(422, "schema.invalid", "Invalid board acknowledgment",
                                   path=pointer("acknowledge_person_edit", *first["loc"])) from None
            doc = drafts.edit_board(
                conn, story_id, id, _revision(if_match), fields, to_document(actor.principal),
                acknowledgment=_acknowledged_revision(request, actor, id, ack),
            ).board(conn, id)
        return _etag(response, doc)


    @router.put("/stories/{id}/board-order", tags=["boards"], response_model=Story,
                responses={200: {"headers": ETAG}}, operation_id="reorder_boards")
    def reorder_boards(id: str, body: BoardOrder, request: Request, response: Response,
                       actor: CurrentActor, if_match: IfMatch):
        with request.app.state.engine.begin() as conn:
            _story_access(conn, actor, "draft:write", id)
            order = [_id(board, "brd", f"/board_order/{index}") for index, board in enumerate(body.board_order)]
            acknowledgments = {}
            if actor.principal.kind == "agent":
                acknowledgments = {
                    board_id: _acknowledged_revision(request, actor, board_id, ack)
                    for board_id, ack in (body.acknowledge_person_edit or {}).items()
                }
            doc = drafts.reorder(
                conn, id, _revision(if_match), order, to_document(actor.principal),
                acknowledgments=acknowledgments,
            ).summary(conn)
        return _etag(response, doc)


    @router.delete("/boards/{id}", tags=["boards"], status_code=204, response_class=Response,
                   operation_id="remove_board")
    def remove_board(id: str, request: Request, actor: CurrentActor, if_match: IfMatch,
                     body: BoardRemoval | None = None):
        with request.app.state.engine.begin() as conn:
            story_id = _board_access(conn, actor, "draft:write", id)
            drafts.remove_board(
                conn, story_id, id, _revision(if_match), to_document(actor.principal),
                acknowledgment=_acknowledged_revision(
                    request, actor, id, body.acknowledge_person_edit if body else None),
            )
        return Response(status_code=204)


    @router.get("/assets", tags=["library"], response_model=Page[AssetVersion],
                operation_id="search_assets")
    def search_assets(request: Request, actor: CurrentActor,
                      kind: Annotated[str | None, Query(max_length=40)] = None,
                      label: Annotated[list[str] | None, Query()] = None,
                      production: Annotated[str | None, Query(max_length=30)] = None,
                      board: Annotated[str | None, Query(max_length=30)] = None,
                      cursor: Cursor = None, limit: Limit = 50):
        if production is not None:
            actor.require("read", _id(production, "prd", "/production"))
        with snapshot(request.app.state.engine) as conn:
            versions = None
            if board is not None:
                story_id = _board_access(conn, actor, "read", board)
                draft = drafts.get_draft(conn, story_id)
                if production is not None and production != draft.story["production_id"]:
                    raise NotFound
                versions = {ref.version_id for ref in board_references(draft.boards[board])}
            docs = catalog.find_assets(conn, actor.productions("read"), kind=kind, labels=label or [],
                                       production_id=production, version_ids=versions,
                                       after=_cursor(cursor, "asv"), limit=limit + 1)
        return _page(docs, limit)


    @router.get("/assets/{id}", tags=["library"], response_model=AssetDetail, operation_id="get_asset")
    def get_asset(id: str, request: Request, actor: CurrentActor, cursor: Cursor = None, limit: Limit = 50):
        with snapshot(request.app.state.engine) as conn:
            asset, versions = catalog.get_asset(conn, _id(id, "ast"), actor.productions("read"),
                                                after=_cursor(cursor, "asv"), limit=limit + 1)
        page = _page(versions, limit)
        return {"asset": asset, "versions": page["items"], "next_cursor": page["next_cursor"]}


    @router.get("/runs/{id}/delivery", tags=["deliveries"], response_model=Delivery,
                operation_id="get_delivery")
    def get_delivery(id: str, request: Request, actor: CurrentActor):
        with snapshot(request.app.state.engine) as conn:
            row = catalog.get_delivery(conn, _id(id, "run"))
            if row is None:
                raise NotFound
            actor.require("read", row.production_id)
            return row.document

    return router
