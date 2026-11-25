# Reference photo composer

The storyboard's Reference photo section edits the selected draft board. The
board's `/photo` child route opens the same storyboard with the composer expanded.

| Action | API |
|---|---|
| Save whole-frame inputs | `PATCH /v1/boards/{id}` with `If-Match` and the full `photo` object. The prompt and ordered version pins save together. |
| Generate or recomposite | `POST /v1/boards/{id}/photo-jobs` with a seed and a fresh `Idempotency-Key` per press. An ambiguous submission can be retried with the original key and seed during the signed-in page session. |
| Read progress | `GET /v1/boards/{id}/jobs` and `GET /v1/queue/lanes`. Studio decides which jobs are queued, running and terminal. |
| Read history and choose a version | `GET /v1/boards/{id}/photo-versions` for provenance, newest first in the picker. Selecting a version patches the board with its revision. A conflict reloads the board and leaves the choice to the person. |
| Display the selected photo | `/v1/media/{sha256}` for the current draft pin, using the same-origin session cookie. An unselected history preview uses `/v1/asset-versions/{id}/media/{sha256}`. |

Inputs save after a short pause in editing or before generation. They remain
editable while a job runs. The browser uses the board's `derived.photo_state`
and the job's `result_is_current`, together with the selected version ID.
Pending inputs are labelled unsaved. While they are unsaved, Studio still
evaluates job completion against the last saved board and updates its selection
under the API's write fence. A layered board uses the set still, cast
stills in draw order, layout, foreground and end camera framing. The composer
offers recomposition through the same image lane.

Imported records with `recorded_without_media: true` show their metadata
without preview or selection. An agent upload shows the declared agent harness
and session, model, prompt, source versions and the recorded received SHA-256.
Agent uploads enter version history through the API and MCP.
[Media operations](studio-api.md#media-operations) · [Board photo planning](studio-photo.md)

## Assets handoff

The outbound route is `/editor/assets?production=<prd>&media=<kind>&story=<sty>&board=<brd>`.
The board filter starts on the draft's references. Production and board scope
follow the editor's breadcrumb and filter rules. Story
[456](https://work.haynesnetwork.com/work_packages/456) owns the Assets page.

After the person chooses a version, call `photoAssetReturn(scope, versionId)`
from `web/src/photo-composer-model.ts`. Pass its `to` and `state` to React
Router's `Link` or `navigate`. The destination is the full board route with
the `/photo` suffix. Navigation state carries `{ photoAssetVersionId: "<asv>" }`.
The composer consumes it once after confirming the target board and finding the
promoted still with media in the production-scoped catalog. Global versions in
the catalog are eligible. A duplicate keeps its existing chip position.
