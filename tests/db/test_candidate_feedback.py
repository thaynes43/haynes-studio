"""Candidate and iteration acceptance through the restricted API runtime role."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, ProgrammingError

from haynes_studio.api.auth import Actor
from haynes_studio.build.validate import validate_run
from haynes_studio.canonical.ids import Minter
from haynes_studio.db import runs
from haynes_studio.drafting.declaration import READ_TOKEN_HEADER
from haynes_studio.db.schema import candidate_feedback, feedback_iteration_clears, feedback_iterations, run_candidates, stories
from tests.db.test_formats import create_format, pin
from tests.db.test_go_live import finished_fixture
from tests.db.test_run_queue import queue, queue_run, worker_credentials
from tests.db.test_studio_api import (
    client, engine, new_production, owner_engine, register_agent, runtime_db, runtime_role, service, sign_in,
)
from tests.formats.fixtures import doll_short

pytestmark = pytest.mark.db


def body(response, status):
    assert response.status_code == status, response.text
    return response.json()


def refuse(response, status, code):
    assert body(response, status)["error"]["code"] == code


def finish(q, run, **kwargs):
    return finished_fixture(SimpleNamespace(owner=q.owner, story=q.story_id, production=q.production_id),
                            queued_id=run["id"], **kwargs)


def queue_formatted(q, *, failed=None):
    payload = doll_short()
    payload["id"] = "feedback-" + q.story_id.removeprefix("sty_").lower()
    first = payload["recipe"]["targets"][0]
    payload["recipe"]["targets"].append({**first, "id": "fixture-reels", "name": "Fixture Reels"})
    version = create_format(q, payload)
    body(pin(q, version["id"]), 200)
    run = body(queue_run(q, "original", rev=4), 201)
    held = finish(q, run, failure=failed)
    return run, held, first["id"]


def present(q, run, target, *, headers=None):
    return q.browser.post(f'/v1/runs/{run["id"]}/candidates', json={"target_id": target},
                          headers=q.csrf if headers is None else headers)


def note(q, candidate, text, *, boards=(), replaces=None, headers=None):
    return q.browser.post(f'/v1/candidates/{candidate["id"]}/feedback',
                          json={"text": text, "board_ids": list(boards), "replaces_id": replaces},
                          headers=q.csrf if headers is None else headers)


def start(q, candidate, rev, notes, *, headers=None):
    return q.browser.post(f'/v1/candidates/{candidate["id"]}/iterations',
                          json={"note_ids": notes}, headers={
                              **(q.csrf if headers is None else headers), "If-Match": str(rev),
                          })


def test_targets_and_board_ids_are_from_the_frozen_run(queue):
    q = queue
    run, _, target = queue_formatted(q)
    # The draft loses its old pin and board. Its replacement board must not
    # become a target for notes on a run that never contained it.
    body(pin(q, None, revision=4), 200)
    deleted = q.browser.delete(f"/v1/boards/{q.board_id}", headers={**q.csrf, "If-Match": "2"})
    assert deleted.status_code == 204, deleted.text
    replacement = body(q.browser.post(f"/v1/stories/{q.story_id}/boards", json={},
                                     headers={**q.csrf, "If-Match": "6"}), 201)

    for blank in ("", " \t"):
        refuse(present(q, run, blank), 422, "candidate.target_required")
    refuse(present(q, run, "retired-target"), 422, "candidate.target_unknown")
    key_id, agent = register_agent(q.owner, {q.production_id: ["runs:queue"]})
    first = body(present(q, run, target, headers=agent), 201)
    assert first["run_id"] == run["id"] and first["target_id"] == target
    assert first["presented_by"]["key_id"] == key_id
    assert body(present(q, run, target), 200) == first
    second = body(present(q, run, "fixture-reels"), 201)
    assert second["id"] != first["id"]

    refuse(note(q, first, " ", boards=[q.board_id]), 422, "feedback.text_required")
    refuse(note(q, first, "Present-day board", boards=[replacement["id"]]), 422, "feedback.board_unknown")
    refuse(note(q, first, "Duplicated", boards=[q.board_id, q.board_id]), 422, "feedback.duplicate_reference")
    saved = body(note(q, first, "Keep the opening", boards=[q.board_id]), 201)
    assert saved["candidate_id"] == first["id"] and saved["board_ids"] == [q.board_id]
    assert saved["written_by"] == {"kind": "human", "display_name": "Fixture Person", "key_id": None}
    refuse(note(q, second, "Wrong candidate", replaces=saved["id"]), 422, "feedback.note_unknown")
    corrected = body(note(q, first, "Keep the opening a little longer", replaces=saved["id"]), 201)
    refuse(note(q, first, "Already corrected", replaces=saved["id"]), 409, "feedback.already_corrected")

    list_path = f"/v1/stories/{q.story_id}/candidates"
    first_page = body(q.browser.get(list_path, params={"limit": 1}), 200)
    last_page = body(q.browser.get(list_path, params={"cursor": first_page["next_cursor"], "limit": 1}), 200)
    assert last_page["next_cursor"] is None
    items = {item["id"]: item for item in first_page["items"] + last_page["items"]}
    assert items[first["id"]]["notes"] == [saved, corrected]
    assert items[second["id"]]["notes"] == []
    assert first_page["revision"] == 7 and first_page["iteration"] is None
    filtered = body(q.browser.get(list_path, params={
        "candidate_id": first["id"], "note_ids": [saved["id"]],
    }), 200)
    assert filtered["items"] == [{**items[first["id"]], "notes": [saved]}]


def test_iteration_preserves_approval_and_person_edits_and_queues_lineage(queue):
    q = queue
    q.clock.now = datetime.now(UTC)
    run, held, target = queue_formatted(q)
    q.app.state.oidc.settings = replace(q.app.state.oidc.settings,
                                      go_live_approver_subjects=frozenset({"one"}))
    previous = f'/v1/runs/{run["id"]}'
    snapshot_bytes = q.browser.get(previous + "/snapshot").content
    approval = body(q.browser.post(held.path, json=held.body, headers=q.csrf), 201)
    original = body(q.browser.get(previous), 200)
    delivery = body(q.browser.get(previous + "/delivery"), 200)
    first = body(present(q, run, target), 201)
    second = body(present(q, run, "fixture-reels"), 201)
    response = body(note(q, first, "Leave room for the glance", boards=[q.board_id]), 201)
    note_id = response["id"]

    story_path = f"/v1/stories/{q.story_id}"
    board_path = f"/v1/boards/{q.board_id}"
    draft = body(q.browser.patch(story_path, json={"title": "Human cut"},
                               headers={**q.csrf, "If-Match": "4"}), 200)
    assert draft["revision"] == 5
    person_board = body(q.browser.patch(board_path, json={"title": "Person's direction"},
                                      headers={**q.csrf, "If-Match": "2"}), 200)
    refuse(start(q, first, 4, [note_id]), 409, "conflict.revision")
    refuse(start(q, second, 6, [note_id]), 422, "feedback.note_unknown")
    refuse(start(q, first, 6, []), 422, "schema.invalid")
    assert body(q.browser.get(story_path + "/candidates"), 200)["iteration"] is None

    started = start(q, first, 6, [note_id])
    iteration = body(started, 201)
    assert started.headers["etag"] == '"7"'
    assert iteration["revision"] == iteration["iteration"]["started_revision"] == 7
    lineage = {"candidate_id": first["id"], "run_id": run["id"], "note_ids": [note_id]}
    assert {key: iteration["iteration"][key] for key in lineage} == lineage
    assert body(q.browser.get(board_path), 200) == person_board
    assert body(q.browser.get(story_path), 200)["title"] == "Human cut"

    _, agent = register_agent(q.owner, {q.production_id: ["read", "draft:write", "runs:queue"]})
    refused = q.browser.patch(board_path, json={"title": "Unacknowledged takeover"},
                              headers={**agent, "If-Match": "3"})
    refuse(refused, 409, "draft.protected")
    read = q.browser.get(board_path, headers=agent)
    revised = body(q.browser.patch(board_path, json={
        "title": "Agent's acknowledged revision",
        "acknowledge_person_edit": {"board_revision": 3, "read_token": read.headers[READ_TOKEN_HEADER]},
    }, headers={**agent, "If-Match": "3"}), 200)
    assert revised["title"] == "Agent's acknowledged revision"
    continued = body(queue_run(q, "answers-feedback", rev=8, headers=agent), 201)
    assert body(queue_run(q, "answers-feedback", rev=8, headers=agent), 200) == continued
    assert continued["answers"] == lineage
    assert continued["active_approval_id"] is None
    continued_review = f'/v1/runs/{continued["id"]}/go-live-approvals'
    assert body(q.browser.get(continued_review), 200)["approvals"] == []
    assert continued["snapshot"]["sha256"] != original["snapshot"]["sha256"]
    assert continued["snapshot"]["story_revision"] == 8
    with q.owner.connect() as conn:
        assert not validate_run(runs.get(conn, continued["id"])["document"])
    current = body(q.browser.get(story_path + "/candidates", headers=agent), 200)
    assert current["iteration"] == iteration["iteration"]
    first_read = next(item for item in current["items"] if item["id"] == first["id"])
    assert first_read["answering_runs"] == [{"id": continued["id"], "number": continued["number"]}]
    assert first_read["notes"] == [response]
    assert body(q.browser.get(f'/v1/runs/{continued["id"]}', headers=agent), 200)["answers"] == lineage
    assert body(q.browser.get(previous), 200) == original
    assert body(q.browser.get(previous + "/delivery"), 200) == delivery
    assert q.browser.get(previous + "/snapshot").content == snapshot_bytes
    assert body(q.browser.get(held.path), 200)["approvals"] == [approval]


def test_feedback_requires_a_person_and_reads_hide_other_productions(queue):
    q = queue
    run, _, target = queue_formatted(q)
    candidate = body(present(q, run, target), 201)
    story_path = f"/v1/stories/{q.story_id}/candidates"
    _, reader = register_agent(q.owner, {q.production_id: ["read", "draft:write"]})
    _, no_read = register_agent(q.owner, {q.production_id: ["runs:queue"]})
    other = new_production(q.browser, q.csrf)
    _, outsider = register_agent(q.owner, {other: ["read", "runs:queue"]})
    worker = worker_credentials(q.owner)

    refuse(present(q, run, target, headers=reader), 403, "auth.forbidden")
    for creds in (reader, no_read, outsider):
        refuse(note(q, candidate, "Agent feedback", headers=creds), 403, "feedback.person_required")
        refuse(start(q, candidate, 4, [Minter().mint("fbk")], headers=creds), 403, "feedback.person_required")
    refuse(note(q, candidate, "Worker feedback", headers=worker), 401, "auth.required")
    refuse(start(q, candidate, 4, [Minter().mint("fbk")], headers=worker), 401, "auth.required")

    for creds in (no_read, outsider):
        refuse(q.browser.get(story_path, headers=creds), 404, "not_found")
        refuse(q.browser.get(f'/v1/runs/{run["id"]}', headers=creds), 404, "not_found")
    page = body(q.browser.get(story_path, headers=reader), 200)
    assert page["items"] == [{**candidate, "notes": [], "answering_runs": []}]


def test_refuses_unfinished_runs_and_runs_without_a_recipe(queue):
    q = queue
    run = body(queue_run(q, "unpublished"), 201)
    refuse(present(q, run, "fixture-target"), 422, "candidate.run_unfinished")
    finish(q, run)
    refuse(present(q, run, "fixture-target"), 422, "candidate.format_missing")


def test_clear_iteration_is_a_persons_revisioned_write_and_preserves_history(queue):
    q = queue
    run, _, target = queue_formatted(q)
    candidate = body(present(q, run, target), 201)
    saved = body(note(q, candidate, "Hold the reaction"), 201)
    body(start(q, candidate, 4, [saved["id"]]), 201)
    before = body(queue_run(q, "before-clear", rev=5), 201)
    assert before["answers"]["note_ids"] == [saved["id"]]
    path = f"/v1/stories/{q.story_id}/feedback-iteration"
    _, agent = register_agent(q.owner, {q.production_id: ["read", "draft:write"]})
    refuse(q.browser.delete(path, headers={**agent, "If-Match": "5"}), 403, "feedback.person_required")
    refuse(q.browser.delete(path, headers={**q.csrf, "If-Match": "4"}), 409, "conflict.revision")
    response = q.browser.delete(path, headers={**q.csrf, "If-Match": "5"})
    assert body(response, 200) == {"revision": 6, "cleared": True}
    assert response.headers["etag"] == '"6"'
    assert body(q.browser.delete(path, headers={**q.csrf, "If-Match": "6"}), 200) == {
        "revision": 6, "cleared": False,
    }
    page = body(q.browser.get(f"/v1/stories/{q.story_id}/candidates"), 200)
    assert page["iteration"] is None and page["items"][0]["notes"] == [saved]
    assert "answers" not in body(queue_run(q, "after-clear", rev=6), 201)
    assert body(q.browser.get(f'/v1/runs/{before["id"]}'), 200)["answers"] == before["answers"]
    with q.owner.connect() as conn:
        audit = conn.execute(sa.select(feedback_iteration_clears)).mappings().one()
        assert audit["story_id"] == q.story_id and audit["revision"] == 6
        assert audit["document"]["cleared_by"]["kind"] == "human" and audit["document"]["cleared_at"]


def test_db_refuses_to_reference_another_storys_iteration(queue, engine):
    q = queue
    run, _, target = queue_formatted(q)
    candidate = body(present(q, run, target), 201)
    saved = body(note(q, candidate, "Held note"), 201)
    body(start(q, candidate, 4, [saved["id"]]), 201)
    other = body(q.browser.post(f"/v1/productions/{q.production_id}/media-types/short/stories",
                                json={"title": "Another fixture story"}, headers=q.csrf), 201)["id"]
    with engine.connect() as conn:
        iteration = conn.scalar(sa.select(stories.c.feedback_iteration_id).where(stories.c.id == q.story_id))
    with pytest.raises(IntegrityError) as denied, engine.begin() as conn:
        conn.execute(stories.update().where(stories.c.id == other).values(feedback_iteration_id=iteration))
    assert denied.value.orig.diag.constraint_name == "stories_feedback_iteration_same_story"


def test_clear_iteration_hides_stories_outside_the_persons_draft_scope(queue, monkeypatch):
    q = queue
    run, _, target = queue_formatted(q)
    candidate = body(present(q, run, target), 201)
    saved = body(note(q, candidate, "Retain this", boards=[q.board_id]), 201)
    started = body(start(q, candidate, 4, [saved["id"]]), 201)
    other = new_production(q.browser, q.csrf)
    outsider = client(q.app)
    csrf = sign_in(outsider, q.issuer, "two")
    original = Actor.productions
    monkeypatch.setattr(Actor, "productions", lambda actor, scope: (
        frozenset({other}) if actor.principal.sub == "two" and scope == "draft:write" else original(actor, scope)
    ))
    base = f"/v1/stories/{q.story_id}"
    for revision in ("4", "5"):
        refuse(outsider.delete(base + "/feedback-iteration", headers={**csrf, "If-Match": revision}), 404, "not_found")
    current = body(q.browser.get(base + "/candidates"), 200)
    assert current["revision"] == started["revision"]
    assert current["iteration"] == started["iteration"]


@pytest.mark.parametrize("table", [run_candidates, candidate_feedback, feedback_iterations],
                         ids=lambda table: table.name)
def test_runtime_role_cannot_edit_or_delete_feedback_records(engine, table):
    for statement in (table.update().values(id="unreachable"), table.delete()):
        with pytest.raises(ProgrammingError, match="permission denied"), engine.begin() as conn:
            conn.execute(statement.where(table.c.id == "unreachable"))
