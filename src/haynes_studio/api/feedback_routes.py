"""Production-scoped candidates and people-only feedback and iteration writes."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, Response
from pydantic import Field, StringConstraints
import sqlalchemy as sa

from haynes_studio.canonical.model import to_document
from haynes_studio.db import catalog
from haynes_studio.db.engine import snapshot
from haynes_studio.db.problems import NotFound
from haynes_studio.db.schema import stories
from haynes_studio.feedback import records

from .errors import APIError, ERROR_RESPONSES, forbidden
from .models import Body, TransportModel
from .routes import Cursor, ETAG, IfMatch, Limit, _cursor, _etag, _id, _page, _revision
from .run_routes import _run_access


class CandidateWrite(Body):
    target_id: Annotated[str, StringConstraints(max_length=64)]


class FeedbackWrite(Body):
    text: Annotated[str, StringConstraints(max_length=records.MAX_TEXT)]
    board_ids: list[str] = Field(default_factory=list, max_length=records.MAX_BOARDS)
    replaces_id: str | None = None


class IterationWrite(Body):
    note_ids: list[str] = Field(min_length=1, max_length=records.MAX_NOTES)


class Attribution(TransportModel):
    kind: Literal["human", "agent"]
    display_name: str | None = None
    key_id: str | None = None


class FeedbackNote(TransportModel):
    id: str
    candidate_id: str
    text: str
    board_ids: list[str]
    replaces_id: str | None
    written_by: Attribution
    written_at: datetime


class Candidate(TransportModel):
    id: str
    run_id: str
    target_id: str
    presented_by: Attribution
    presented_at: datetime


class AnsweringRun(TransportModel):
    id: str
    number: int


class CandidateDetails(Candidate):
    notes: list[FeedbackNote]
    answering_runs: list[AnsweringRun]


class Iteration(TransportModel):
    candidate_id: str
    run_id: str
    note_ids: list[str]
    started_by: Attribution
    started_at: datetime
    started_revision: int


class IterationStarted(TransportModel):
    revision: int
    iteration: Iteration


class IterationCleared(TransportModel):
    revision: int
    cleared: bool


class CandidatePage(TransportModel):
    items: list[CandidateDetails]
    next_cursor: str | None
    revision: int
    iteration: Iteration | None


def transport_models():
    return (CandidateWrite, FeedbackWrite, IterationWrite, Attribution, FeedbackNote,
            Candidate, AnsweringRun, CandidateDetails, Iteration, IterationStarted, IterationCleared, CandidatePage)


def _by(actor):
    return {**to_document(actor.principal), "display_name": actor.display_name}


def _person(actor):
    if actor.principal.kind != "human":
        raise forbidden("feedback.person_required", "Feedback and iteration require a signed-in person")


def _run_to_present(conn, actor, run_id):
    try:
        run = _run_access(conn, actor, "runs:queue", run_id)
    except NotFound:
        delivery = catalog.get_delivery(conn, run_id)
        if delivery is None or delivery.document["store"]["adapter"] != "legacy_wan_ledger":
            raise
        actor.require("runs:queue", delivery.production_id)
        raise APIError(422, "candidate.legacy_run", "An imported run cannot be presented") from None
    document = run["document"]
    if document["status"] == "imported" or document.get("legacy") is not None:
        raise APIError(422, "candidate.legacy_run", "An imported run cannot be presented")
    if document["status"] != "succeeded" or not document.get("finished_at"):
        raise APIError(422, "candidate.run_unfinished", "Present a successful, finished run")
    return run


def _unique_ids(values, prefix, field):
    ids = [_id(value, prefix, f"/{field}/{index}") for index, value in enumerate(values)]
    if len(ids) != len(set(ids)):
        raise APIError(422, "feedback.duplicate_reference", "Use each ID once", path=f"/{field}")
    return ids


def build_router(CurrentActor, authenticated_route):
    router = APIRouter(prefix="/v1", tags=["feedback"], responses=ERROR_RESPONSES,
                       route_class=authenticated_route)

    @router.post("/runs/{id}/candidates", response_model=Candidate, status_code=201,
                 responses={200: {"model": Candidate}}, operation_id="present_candidate")
    def present_candidate(id: str, body: CandidateWrite, request: Request, response: Response,
                          actor: CurrentActor):
        with request.app.state.engine.begin() as conn:
            run = _run_to_present(conn, actor, _id(id, "run"))
            if not body.target_id.strip():
                raise APIError(422, "candidate.target_required", "Choose a target", path="/target_id")
            pin = (run["snapshot"] or {}).get("format_version")
            if pin is None:
                raise APIError(422, "candidate.format_missing", "This run froze no format recipe")
            if not any(target["id"] == body.target_id for target in pin["recipe"]["targets"]):
                raise APIError(422, "candidate.target_unknown", "This target is outside the frozen recipe",
                               path="/target_id")
            candidate, created = records.present(conn, run["id"], body.target_id, _by(actor))
            if not created:
                response.status_code = 200
            return candidate

    @router.get("/stories/{id}/candidates", response_model=CandidatePage,
                responses={200: {"headers": ETAG}}, operation_id="list_candidates")
    def list_candidates(id: str, request: Request, response: Response, actor: CurrentActor,
                        run_id: str | None = None, cursor: Cursor = None, limit: Limit = 50,
                        candidate_id: str | None = None,
                        note_ids: Annotated[list[str] | None, Query(min_length=1, max_length=records.MAX_NOTES)] = None):
        with snapshot(request.app.state.engine) as conn:
            story = conn.execute(sa.select(stories.c.production_id, stories.c.document["revision"].label("revision"))
                                 .where(stories.c.id == _id(id, "sty"))).one_or_none()
            productions = actor.productions("read")
            if story is None or (productions is not None and story.production_id not in productions):
                raise NotFound
            if run_id is not None and _run_access(conn, actor, "read", run_id)["story_id"] != id:
                raise NotFound
            rows = records.list_candidates(
                conn, id, run_id, _cursor(cursor, "cnd"), limit + 1,
                candidate_id=_id(candidate_id, "cnd", "/candidate_id") if candidate_id is not None else None,
                note_ids=_unique_ids(note_ids, "fbk", "note_ids") if note_ids is not None else None,
            )
            return _etag(response, {**_page(rows, limit), "revision": story.revision,
                                    "iteration": records.draft_iteration(conn, id)})

    @router.post("/candidates/{id}/feedback", response_model=FeedbackNote, status_code=201,
                 operation_id="add_candidate_feedback")
    def add_candidate_feedback(id: str, body: FeedbackWrite, request: Request, actor: CurrentActor):
        _person(actor)
        with request.app.state.engine.begin() as conn:
            candidate = records.get_candidate(conn, _id(id, "cnd"))
            row = _run_access(conn, actor, "read", candidate["run_id"])
            text = body.text.strip()
            if not text:
                raise APIError(422, "feedback.text_required", "Enter a feedback note", path="/text")
            board_ids = _unique_ids(body.board_ids, "brd", "board_ids")
            frozen_ids = set(row["snapshot"]["story"]["board_order"])
            for index, board_id in enumerate(board_ids):
                if board_id not in frozen_ids:
                    raise APIError(422, "feedback.board_unknown", "This board is outside the frozen run",
                                   path=f"/board_ids/{index}", board_id=board_id)
            replaces_id = body.replaces_id
            if replaces_id is not None:
                _id(replaces_id, "fbk", "/replaces_id")
                if not records.note_ids_belong(conn, id, [replaces_id]):
                    raise APIError(422, "feedback.note_unknown", "This note belongs to another candidate or is absent",
                                   path="/replaces_id")
            note = records.append_note(conn, id, text=text, board_ids=board_ids, replaces_id=replaces_id,
                                       actor=_by(actor))
            if note is None:
                raise APIError(409, "feedback.already_corrected", "This note already has a correction")
            return note

    @router.post("/candidates/{id}/iterations", response_model=IterationStarted, status_code=201,
                 responses={201: {"headers": ETAG}}, operation_id="start_feedback_iteration")
    def start_feedback_iteration(id: str, body: IterationWrite, request: Request, response: Response,
                                 actor: CurrentActor, if_match: IfMatch):
        _person(actor)
        with request.app.state.engine.begin() as conn:
            candidate = records.get_candidate(conn, _id(id, "cnd"))
            _run_access(conn, actor, "read", candidate["run_id"])
            note_ids = _unique_ids(body.note_ids, "fbk", "note_ids")
            if not records.note_ids_belong(conn, id, note_ids):
                raise APIError(422, "feedback.note_unknown", "Select notes on this candidate", path="/note_ids")
            iteration = records.start_iteration(conn, candidate, _revision(if_match), note_ids, _by(actor))
            return _etag(response, {"revision": iteration["started_revision"], "iteration": iteration})

    @router.delete("/stories/{id}/feedback-iteration", response_model=IterationCleared,
                   responses={200: {"headers": ETAG}}, operation_id="clear_feedback_iteration")
    def clear_feedback_iteration(id: str, request: Request, response: Response,
                                 actor: CurrentActor, if_match: IfMatch):
        _person(actor)
        with request.app.state.engine.begin() as conn:
            result = records.clear_iteration(
                conn, _id(id, "sty"), _revision(if_match), _by(actor),
                production_ids=actor.productions("draft:write"),
            )
            return _etag(response, result)

    return router
