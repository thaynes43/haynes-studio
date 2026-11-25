"""Append feedback and read lineage in the caller's database transaction."""

from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from haynes_studio.canonical.ids import Minter
from haynes_studio.db.problems import NotFound, require_revision
from haynes_studio.db.runs import database_time, timestamp
from haynes_studio.db.schema import candidate_feedback as notes
from haynes_studio.db.schema import feedback_iterations as iterations
from haynes_studio.db.schema import run_candidates as candidates
from haynes_studio.db.schema import runs, stories

MAX_TEXT = 4000
MAX_BOARDS = 256
MAX_NOTES = 64


def present(conn, run_id, target_id, actor):
    row = conn.execute(insert(candidates).values(
        id=Minter().mint("cnd"), run_id=run_id, target_id=target_id,
        presented_by=actor, presented_at=database_time(conn),
    ).on_conflict_do_nothing(index_elements=[candidates.c.run_id, candidates.c.target_id])
        .returning(candidates)).mappings().one_or_none()
    if row is not None:
        return dict(row), True
    # In READ COMMITTED, a subsequent statement can see a concurrent insert
    # that won the unique key, even if it committed during our insert.
    row = conn.execute(sa.select(candidates).where(
        candidates.c.run_id == run_id, candidates.c.target_id == target_id,
    )).mappings().one()
    return dict(row), False


def get_candidate(conn, candidate_id):
    row = conn.execute(sa.select(candidates, runs.c.story_id).join_from(candidates, runs)
                       .where(candidates.c.id == candidate_id)).mappings().one_or_none()
    if row is None:
        raise NotFound
    return row


def append_note(conn, candidate_id, *, text, board_ids, replaces_id, actor):
    row = conn.execute(insert(notes).values(
        id=Minter().mint("fbk"), candidate_id=candidate_id, text=text, board_ids=board_ids,
        replaces_id=replaces_id, written_by=actor, written_at=database_time(conn),
    ).on_conflict_do_nothing(index_elements=[notes.c.replaces_id]).returning(notes)).mappings().one_or_none()
    return dict(row) if row is not None else None


def note_ids_belong(conn, candidate_id, note_ids):
    found = conn.scalars(sa.select(notes.c.id).where(
        notes.c.candidate_id == candidate_id, notes.c.id.in_(note_ids),
    ))
    return set(found) == set(note_ids)


def _iteration_view(row):
    return {key: row[key] for key in ("candidate_id", "run_id", "note_ids",
                                      "started_by", "started_at", "started_revision")}


def draft_iteration(conn, story_id):
    row = conn.execute(sa.select(iterations, candidates.c.run_id)
                       .join_from(stories, iterations).join_from(iterations, candidates)
                       .where(stories.c.id == story_id)).mappings().one_or_none()
    return _iteration_view(row) if row is not None else None


def answers(conn, story_id):
    iteration = draft_iteration(conn, story_id)
    if iteration is not None:
        return {key: iteration[key] for key in ("candidate_id", "run_id", "note_ids")}
    return None


def start_iteration(conn, candidate, revision, note_ids, actor):
    story_id = candidate["story_id"]
    story = conn.scalar(sa.select(stories.c.document).where(stories.c.id == story_id).with_for_update())
    require_revision(story["revision"], revision)
    record = {
        "id": uuid4().hex, "candidate_id": candidate["id"], "note_ids": note_ids,
        "started_by": actor, "started_at": database_time(conn), "started_revision": revision + 1,
    }
    conn.execute(iterations.insert().values(**record))
    # Keep current content and board protections. All board writes use this same story lock.
    updated = {**story, "revision": revision + 1, "updated_at": timestamp(record["started_at"])}
    conn.execute(stories.update().where(stories.c.id == story_id).values(
        document=updated, feedback_iteration_id=record["id"],
    ))
    return _iteration_view({**record, "run_id": candidate["run_id"]})


def list_candidates(conn, story_id, run_id, after, limit):
    stmt = sa.select(candidates).join_from(candidates, runs).where(runs.c.story_id == story_id)
    if run_id is not None:
        stmt = stmt.where(candidates.c.run_id == run_id)
    if after is not None:
        stmt = stmt.where(candidates.c.id > after)
    items = [dict(row, notes=[], answering_runs=[]) for row in conn.execute(
        stmt.order_by(candidates.c.id).limit(limit),
    ).mappings()]
    by_id = {item["id"]: item for item in items}
    if not items:
        return items
    for note in conn.execute(sa.select(notes).where(notes.c.candidate_id.in_(by_id))
                             .order_by(notes.c.written_at, notes.c.id)).mappings():
        by_id[note["candidate_id"]]["notes"].append(dict(note))
    key = sa.literal_column("'answers'")
    answer = runs.c.document.op("->")(key)
    candidate_id = answer.op("->>")(sa.literal_column("'candidate_id'"))
    stmt = (sa.select(runs.c.id, runs.c.number, candidate_id.label("candidate_id"))
            .where(runs.c.story_id == story_id, runs.c.document.has_key(key),
                   candidate_id.in_(by_id)).order_by(runs.c.position))
    for run in conn.execute(stmt).mappings():
        by_id[run["candidate_id"]]["answering_runs"].append({"id": run["id"], "number": run["number"]})
    return items
