"""Apply a stored draft through the conditional board mutations."""

from collections import defaultdict

from haynes_studio.db import drafts
from haynes_studio.db.problems import DraftProtected, require_revision
from haynes_studio.jsonio import thaw

from .document import Draft


def apply(conn, draft: Draft, version_id: str, revision: int, by: dict) -> dict:
    story = drafts.get_draft(conn, draft.story_id, lock=True)
    require_revision(story.story["revision"], revision)
    draft.require_set(story.story["set"])

    pristine = story.highest_board == 0
    existing = defaultdict(list)
    results = []
    for board_id in story.story["board_order"]:
        board = story.boards[board_id]
        stamp = board.get("draft_application")
        if stamp is None:
            results.append(_result(None, board_id, "conflict", "unstamped_board"))
        else:
            existing[stamp["board_key"]].append(board)

    for proposal in draft.boards:
        key = proposal.key
        matches = existing.get(key, [])
        if len(matches) > 1:
            results.extend(_result(key, board["id"], "conflict", "ambiguous_board_key") for board in matches)
            continue
        held = matches[0] if matches else None
        if held is not None:
            board_id = held["id"]
            stamp = held["draft_application"]
            try:
                drafts.check_archive_board(held, by)
            except DraftProtected as error:
                reason = "edited_by_person" if error.person_edit else "draft.protected"
                results.append(_result(key, board_id, "conflict", reason))
                continue
            if stamp.get("archive_version_id") == version_id:
                results.append(_result(key, board_id, "skipped", "already_applied"))
                continue
        elif not pristine:
            results.append(_result(key, None, "conflict", "unbound_board_key"))
            continue

        fields = thaw(proposal.fields)
        declaration = fields["draft_application"] = {
            "board_key": key, "draft_sha256": draft.sha256, "model": draft.model, "session": draft.session,
        }
        if held is None:
            story, board_id = drafts.add_board(conn, draft.story_id, revision, fields, by,
                                               archive_version_id=version_id)
            reason = "created"
        else:
            declaration.update(previous_draft_sha256=stamp["draft_sha256"], story_revision=revision)
            story = drafts.edit_board(conn, draft.story_id, board_id, held["revision"], fields, by,
                                      archive_version_id=version_id)
            reason = "updated"
        revision = story.story["revision"]
        results.append(_result(key, board_id, "applied", reason))

    proposed = {proposal.key for proposal in draft.boards}
    for key, boards in existing.items():
        if key not in proposed:
            for board in boards:
                stamp = board["draft_application"]
                edited = "person_edit" in stamp or "person_edit" in board
                results.append(_result(key, board["id"], "conflict" if edited else "skipped",
                                       "edited_by_person" if edited else "not_targeted"))

    return {"story_id": draft.story_id, "archive_version_id": version_id,
            "revision": revision, "boards": results}


def _result(key, board_id, outcome, reason):
    return {"key": key, "board_id": board_id, "outcome": outcome, "reason": reason}
