# Candidate feedback and iterations

A candidate presents one successful Studio run for one target in that run's
frozen format recipe. Presentation records the target key, the verified
presenter and the time. Each run can be presented once per target. A repeated
presentation returns the original record. A presentation is private Studio
metadata. Go-live remains its own decision on a run's exact master.

In **Productions**, open a story and select a finished run. Choose a target,
then add a note under its candidate. Use the frozen board picker to attach a
note to one or more boards. Leave it empty for a note about the whole candidate.
Correct a note by appending a replacement. The original and the correction
both remain in the review history.

Select the notes for the next draft and choose **Start an iteration**. Open
the draft to edit it or hand the selected notes to an agent. If the draft
revision changed, the page reloads it, keeps the note being typed, and waits
for another explicit start.

## API

| Method and path | Body and result | Access |
| --- | --- | --- |
| `POST /v1/runs/{id}/candidates` | Send `{target_id}`. Returns the `cnd_` record with HTTP 201 on first presentation and 200 on repeat. | `runs:queue` in the run's production |
| `GET /v1/stories/{id}/candidates` | Cursor page of candidates with their notes and direct answering runs. Use optional `run_id` to select that run's candidates. The response includes the current iteration, story revision and its ETag. | Production `read` |
| `POST /v1/candidates/{id}/feedback` | Send `{text, board_ids?, replaces_id?}`. Returns the appended `fbk_` note with HTTP 201. | Signed-in person |
| `POST /v1/candidates/{id}/iterations` | Send `{note_ids}` and the current story ETag in `If-Match`. Returns HTTP 201, the iteration and the next revision and ETag. | Signed-in person |
| `DELETE /v1/stories/{id}/feedback-iteration` | Send the current story ETag in `If-Match`. Returns the revision, ETag and whether the reference was cleared. | Signed-in person |
| `GET /v1/runs/{id}` | Returns `answers: {candidate_id, run_id, note_ids}` when its draft named feedback. Here `run_id` names the earlier run. The story's run list includes the same field. | Production `read` |

Run and candidate reads return 404 for an unknown or inaccessible production
record. Feedback text is trimmed and limited to 4,000 characters. Each note
can name up to 256 distinct stable board IDs from the run's frozen snapshot,
including boards later removed from the draft. A correction references a note
on the same candidate. Each note can have one direct correction. A later
correction can target that successor.

An iteration can select 1–64 distinct notes on one candidate. Its write
advances the current story revision and records the selected feedback under
the same lock as board writes. The editor continues from that draft, with the
existing agent acknowledgments for protected boards. Every subsequent enqueue
from the draft records the selected feedback until a person starts another
iteration or clears it. Clearing advances the story revision and records who
cleared the reference and when. Earlier runs and their notes remain in the
history. A repeated enqueue uses the original run's idempotency record.
Each run's go-live history is scoped to its own ID and exact master.

To resolve `answers` via MCP, call `studio_list_candidates` with the run's
`story_id`, `answers.candidate_id` and batches of up to ten `answers.note_ids`.
The same filters are available on the REST candidate list.

## Refusals

| HTTP | Code | Meaning |
| --- | --- | --- |
| 401 | `auth.required` | Use a signed-in session or a credential accepted by the route. Worker tokens are internal. |
| 403 | `auth.forbidden`, `feedback.person_required` | Presenting requires the production grant. Writing notes and starting iterations requires a person. |
| 404 | `not_found` | The requested read is unavailable to this caller. |
| 409 | `conflict.revision` | Reload the current story revision before starting the iteration again. |
| 409 | `feedback.already_corrected` | Select the latest correction to continue the chain. |
| 422 | `candidate.legacy_run`, `candidate.run_unfinished` | Use a successful Studio-built run. |
| 422 | `candidate.target_required`, `candidate.format_missing`, `candidate.target_unknown` | Choose a target in the selected run's frozen recipe. |
| 422 | `feedback.text_required`, `feedback.board_unknown`, `feedback.note_unknown`, `feedback.duplicate_reference` | Enter a note and use distinct references from the frozen run or its candidate as appropriate. |

The database grants the runtime role SELECT and INSERT on candidates, notes
and iteration records. The story stores the current iteration ID. Revision
`0008_candidate_feedback` adds those records and the draft reference.

Source is tracked in [story 448](https://work.haynesnetwork.com/work_packages/448).
