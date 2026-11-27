# Studio API and MCP reference

API **1.0.0**, OpenAPI **3.1.0**, studio-mcp **1.0.0**.
Source contract build SHA-256 `3e3daa3f30697c24ac1d04b06bca6f96e814c9c596a4dd1c5e30891d9bb2088a`.
The build digest identifies the offline OpenAPI export, MCP tool descriptors and excluded worker route index.

Regenerate this page and its schema data when a PR changes an operation, tool or schema.
The source CI job checks the generated files. From the repository root, run

```sh
uv run --locked python scripts/checks/api_reference.py
```

## Authentication and scopes

A person signs in through `/auth/login` and sends the browser session cookie on
Studio requests. Read `csrf_token` from `/v1/me` and send `X-Studio-CSRF` on
unsafe methods, including logout. An agent presents its scoped key in the
`Authorization: Bearer <key>` header on HTTP or MCP requests. An Authorization
header takes precedence over the browser cookie. MCP authenticates through
`/v1/me` and forwards the caller's key to the API. Workers present a separate
worker bearer on the internal routes. The worker identity must have the lane
it claims, and later writes carry the claim fence.

Agent grants apply per production. Catalog reads need `read` on at least one
production and format writes need an explicit `formats:write` grant on at
least one. Scoped agents can read board jobs with `read`. Candidate jobs need
a signed-in person. Archive application needs both `archive:read` and
`draft:write` on the same production. Package responder keys have a narrower
allowlist. A go-live write needs a configured approver with recent sign-in.
See [Studio API](studio-api.md#browser-agent-and-worker-requests),
[Studio MCP](studio-mcp.md), [formats](formats.md#api-and-scopes),
[escalation](escalation.md#authorization-and-budgets) and [go-live](go-live.md).

A person with key-admin authority issues and revokes agent keys. An agent uses
only the key provisioned to its session. It never creates, copies or asks for
one. Present the secret only in the Authorization header to the configured
Studio API or MCP endpoint. Keep it out of URLs, query strings, tool arguments,
request bodies (including provenance), logs, source, examples and handoffs.
The public `key_` ID identifies a credential record. Use it for permitted
key administration and audit. [Agent key administration](studio-mcp.md#agent-key-administration).

`401 auth.required` calls for a valid session or the already provisioned
credential. On `403 auth.forbidden` or `403 auth.csrf`, check the scope or
browser CSRF context and stop if the operation is outside your authority.
A failed OIDC callback redirects with `auth_error`, for example
`auth.oidc_state`, `auth.oidc_invalid` or `auth.subject_forbidden`.
Some reads return `404 not_found` for both missing and out-of-scope records.
For `422 schema.invalid` or `schema.unknown_field`, correct the indicated field.
`413 request.too_large` calls for a smaller metadata body. Transient outages may
return `503 service_unavailable` or `503 database.failed`. Unexpected failures
may return `500 internal`, `500 database.failed` or `500 request.failed`.
Use `X-Request-ID` or `error.request_id` for diagnosis. MCP tool refusals use
`isError: true` with the code in `structuredContent.error.code`.

## Identifiers

Use returned IDs verbatim. Common prefixes are `prd_` (production), `sty_`
(story), `brd_` (board), `ast_` (asset), `asv_` (asset version), `job_`,
`run_`, `dlv_` (delivery), `fmv_` (format version), `arc_` (archive record)
and `arv_` (archive version). Archive and asset version IDs pin immutable
records. Catalog formats have lowercase slugs. Binary content uses a lowercase
SHA-256 digest. Pass `next_cursor` back as `cursor` with the same filters.
See the [identifier contract](../contracts/studio-contracts-v1.md#identifiers-p-01)
and [staging archive](staging-archive.md).

## Revisions and conflicts

Read the record and send its quoted revision `ETag` as `If-Match` on a
revision-checked write. MCP takes an integer `revision`. Board edits and
removals take the board revision and advance the story revision too. Read the
story again before creating a board, reordering or queueing a run. PATCH replaces
supplied top-level fields. Preserve child IDs on edits and omit IDs for new
lines, notes or cues.

On `409 conflict.revision`, use `current_revision` and the returned ETag to
locate the conflict. Re-read the record, reconcile the changes and resubmit
only the intended edit against the new revision. For `409 draft.protected`,
stop unless a person named that board for the edit. In that case, obtain a fresh
board read token and include its revision in the acknowledgment. On
`409 archive.stale_version`, read the current head before deciding whether to
append another version. Other `409` codes describe a specific rule or state.
For a `412 Precondition Failed` from an intermediary, re-read the representation
and verify the target and preconditions before retrying. Studio's revision
handler returns `409 conflict.revision`. See [agent drafting](agent-drafting.md#re-drafts-and-receipts)
and [staging archive](staging-archive.md).

## Idempotency keys and retries

Use `Idempotency-Key` wherever shown in the HTTP parameters (`idempotency_key`
in the corresponding MCP tool). Use a new key for a new intent. After a lost
reply or retryable failure, replay the same key with the same principal,
operation, target, body and, for run enqueue, revision. A successful replay can
return `200` with the existing ID, including a `RunView` for `queue_run`.
`422 idempotency.mismatch` means that key already identifies a different
request. Recover the original result before deciding whether a separate request
is intended. The escalation callback uses its own `409 escalation.callback_conflict`
for a different key or report. For writes without a replay key, re-read state
before repeating an ambiguous submission.

## Upload provenance

A D42 request uses an agent grant of `assets:upload`, a current board revision
and raw PNG, JPEG or WebP with the matching media type. Send `ExternalPhotoDeclaration`
as ASCII JSON in `X-Studio-Photo-Provenance`. At `/mcp/upload`, send `provenance`
and `data_base64` as arguments. Record the actual model, prompt, session,
harness, ordered source asset-version IDs and `paid_api: false`. An optional
`upload_sha256` asserts the raw hash. Studio computes the received hash and
stores a normalized PNG under its own content hash. Only the received bytes
are used. Check `selected` and `board_revision` in the receipt before editing
again. On `503 photo.upload_busy`, respect `Retry-After`. After `408 photo.upload_timeout`,
check the board revision before resending. [Photo upload](studio-api.md#d42-photo-upload).

## Asynchronous jobs and polling

Generation returns `202` with a job ID and `Location`, or `200` on replay. Poll
`GET /v1/jobs/{id}` or `studio_get_job` for board jobs and production-scoped
matte and occlusion jobs. Check the terminal
status and `result_is_current` before using a version. A job can succeed and
retain its result without changing the board. A person can inspect a private
candidate result and promote it separately. Queueing a run freezes the story
revision and returns `201` with its `Location`. Poll `GET /v1/runs/{id}` or
`studio_get_run` for progress and terminal state. Cancel using the run's current
revision. A cancellation can stay pending while work settles. Use the
scoped HTTP media routes for byte ranges and the delivery endpoint or tool for
metadata. See [media jobs](media-jobs.md), [asset candidates](asset-candidates.md),
[reference photo composer](photo-composer.md), [run queue](run-queue.md),
[candidate feedback](feedback.md) and [release packages](release-package.md).

## Limits

HTTP metadata bodies are limited to 2 MiB. Ordinary MCP calls allow 64 KiB of
arguments, 128 KiB of structured results and a 256 KiB HTTP body. MCP pages
default to 10 items with a maximum of 20. Reduce the page size or request fewer
fields when a result is too large. Archive staging allows 256 KiB of decoded
UTF-8 text and its MCP write calls allow a 2 MiB HTTP body. D42 uploads allow
20 MiB of image bytes, 4096 pixels per side, one upload per process, a default
90-second body deadline and a 15-second idle timeout. The upload MCP endpoint
allows the base64 expansion plus 256 KiB for the envelope and metadata. Format
recipes are limited to 64 KiB of canonical JSON and saved run snapshot reads to
16 MiB. See [Studio MCP limits](studio-mcp.md#tools-and-revisions) and
[archive limits](staging-archive.md#operations).

## HTTP operations (82)

[Schema data](api-reference-data/schemas.json) holds the named HTTP types under `components.schemas`.
Run `uv run --locked studio-api openapi` for the full document, including parameter constraints and response headers.
A `*` marks a required parameter in OpenAPI. Browser writes also require CSRF.
A success status shown alone has no response body schema in OpenAPI.
Error status shows the statuses declared by OpenAPI, including shared responses.

### Archive

| Method and path | Operation ID | Access | Parameters | Request body | Success | Error status |
| --- | --- | --- | --- | --- | --- | --- |
| `GET /v1/archive-records/{id}` | `get_archive_record` | Person or Agent with `archive:read` | Path `id`*<br>Query `cursor`, `limit` | — | 200 `ArchiveRecordDetail` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `POST /v1/archive-records/{id}/versions` | `add_archive_version` | Person or Agent with `archive:write` | Path `id`*<br>Header `Idempotency-Key`*, `X-Studio-CSRF` | `ArchiveAppend` | 200 `ArchiveVersion`<br>201 `ArchiveVersion` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /v1/archive-versions/{id}` | `get_archive_version` | Person or Agent with `archive:read` | Path `id`* | — | 200 `ArchiveVersionText` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `POST /v1/archive-versions/{id}/apply` | `apply_archive_storyboard` | Person or Agent with `archive:read` and `draft:write` | Path `id`*<br>Header `If-Match`*, `X-Studio-CSRF` | `ArchiveApply` | 200 `ArchiveApplication` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /v1/productions/{id}/archive-records` | `list_archive_records` | Person or Agent with `archive:read` | Path `id`*<br>Query `cursor`, `limit` | — | 200 `Page_ArchiveRecord_` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `POST /v1/productions/{id}/archive-records` | `create_archive_record` | Person or Agent with `archive:write` | Path `id`*<br>Header `Idempotency-Key`*, `X-Studio-CSRF` | `ArchiveCreate` | 200 `ArchiveCreated`<br>201 `ArchiveCreated` | 401, 403, 404, 409, 413, 422, 500, 503 |

### Authentication

| Method and path | Operation ID | Access | Parameters | Request body | Success | Error status |
| --- | --- | --- | --- | --- | --- | --- |
| `GET /auth/callback` | `callback` | No Studio credential | Query `state`, `code` | — | 303 | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /auth/login` | `login` | No Studio credential | Query `return_to`, `fresh` | — | 303 | 401, 403, 404, 409, 413, 422, 500, 503 |
| `POST /auth/logout` | `logout` | Person | Header `X-Studio-CSRF` | — | 204 | 401, 403, 404, 409, 413, 422, 500, 503 |

### Boards

| Method and path | Operation ID | Access | Parameters | Request body | Success | Error status |
| --- | --- | --- | --- | --- | --- | --- |
| `DELETE /v1/boards/{id}` | `remove_board` | Person or Agent with `draft:write` | Path `id`*<br>Header `If-Match`*, `X-Studio-CSRF` | `BoardRemoval` or `null` (optional) | 204 | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /v1/boards/{id}` | `get_board` | Person or Agent with `read` | Path `id`* | — | 200 `Board` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `PATCH /v1/boards/{id}` | `update_board` | Person or Agent with `draft:write` | Path `id`*<br>Header `If-Match`*, `X-Studio-CSRF` | `BoardPatch` | 200 `Board` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `PUT /v1/stories/{id}/board-order` | `reorder_boards` | Person or Agent with `draft:write` | Path `id`*<br>Header `If-Match`*, `X-Studio-CSRF` | `BoardOrder` | 200 `Story` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `POST /v1/stories/{id}/boards` | `create_board` | Person or Agent with `draft:write` | Path `id`*<br>Header `If-Match`*, `X-Studio-CSRF` | `BoardCreate` | 201 `Board` | 401, 403, 404, 409, 413, 422, 500, 503 |

### Deliveries

| Method and path | Operation ID | Access | Parameters | Request body | Success | Error status |
| --- | --- | --- | --- | --- | --- | --- |
| `GET /v1/runs/{id}/delivery` | `get_delivery` | Person or Agent with `read` | Path `id`* | — | 200 `Delivery` | 401, 403, 404, 409, 413, 422, 500, 503 |

### Escalations

| Method and path | Operation ID | Access | Parameters | Request body | Success | Error status |
| --- | --- | --- | --- | --- | --- | --- |
| `GET /v1/productions/{production_id}/escalations` | `list_escalation_packages` | Person or Agent with `read` | Path `production_id`*<br>Query `cursor`, `limit` | — | 200 `Page_EscalationView_` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /v1/productions/{production_id}/escalations/{package_id}` | `get_escalation_package` | Person or Agent with `read` | Path `production_id`*, `package_id`* | — | 200 `EscalationView` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `POST /v1/productions/{production_id}/escalations/{package_id}/authorize` | `authorize_escalation` | Person | Path `production_id`*, `package_id`*<br>Header `X-Studio-CSRF` | `Authorization` or `null` (optional) | 200 `EscalationView` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `POST /v1/productions/{production_id}/escalations/{package_id}/callback` | `report_escalation` | Package responder with `read` | Path `production_id`*, `package_id`*<br>Header `Idempotency-Key`* | `Callback` | 200 `EscalationView` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `POST /v1/productions/{production_id}/escalations/{package_id}/cancel` | `cancel_escalation` | Person | Path `production_id`*, `package_id`*<br>Header `X-Studio-CSRF` | — | 200 `EscalationView` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `POST /v1/productions/{production_id}/escalations/{package_id}/decline` | `decline_escalation` | Person | Path `production_id`*, `package_id`*<br>Header `X-Studio-CSRF` | — | 200 `EscalationView` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /v1/runs/{run_id}/escalation-checks/{record_sha256}` | `get_escalation_check` | Person or Agent with `read` | Path `run_id`*, `record_sha256`* | — | 200 schema unspecified | 401, 403, 404, 409, 413, 422, 500, 503 |

### Feedback

| Method and path | Operation ID | Access | Parameters | Request body | Success | Error status |
| --- | --- | --- | --- | --- | --- | --- |
| `POST /v1/candidates/{id}/feedback` | `add_candidate_feedback` | Person | Path `id`*<br>Header `X-Studio-CSRF` | `FeedbackWrite` | 201 `FeedbackNote` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `POST /v1/candidates/{id}/iterations` | `start_feedback_iteration` | Person | Path `id`*<br>Header `If-Match`*, `X-Studio-CSRF` | `IterationWrite` | 201 `IterationStarted` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `POST /v1/runs/{id}/candidates` | `present_candidate` | Person or Agent with `runs:queue` | Path `id`*<br>Header `X-Studio-CSRF` | `CandidateWrite` | 200 `Candidate`<br>201 `Candidate` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /v1/stories/{id}/candidates` | `list_candidates` | Person or Agent with `read` | Path `id`*<br>Query `run_id`, `cursor`, `limit`, `candidate_id`, `note_ids` | — | 200 `CandidatePage` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `DELETE /v1/stories/{id}/feedback-iteration` | `clear_feedback_iteration` | Person | Path `id`*<br>Header `If-Match`*, `X-Studio-CSRF` | — | 200 `IterationCleared` | 401, 403, 404, 409, 413, 422, 500, 503 |

### Formats

| Method and path | Operation ID | Access | Parameters | Request body | Success | Error status |
| --- | --- | --- | --- | --- | --- | --- |
| `GET /v1/format-versions/{id}` | `get_format_version` | Person or Agent with `read` | Path `id`* | — | 200 `VersionView` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /v1/formats` | `list_formats` | Person or Agent with `read` | Query `cursor`, `limit` | — | 200 `Page_FormatSummary_` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `POST /v1/formats` | `create_format` | Person or Agent with `formats:write` | Header `X-Studio-CSRF` | `FormatCreate` | 201 `VersionView` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /v1/formats/{id}/versions` | `list_format_versions` | Person or Agent with `read` | Path `id`*<br>Query `cursor`, `limit` | — | 200 `Page_VersionSummary_` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `POST /v1/formats/{id}/versions` | `add_format_version` | Person or Agent with `formats:write` | Path `id`*<br>Header `X-Studio-CSRF` | `FormatRecipe` | 201 `VersionView` | 401, 403, 404, 409, 413, 422, 500, 503 |

### Go-live

| Method and path | Operation ID | Access | Parameters | Request body | Success | Error status |
| --- | --- | --- | --- | --- | --- | --- |
| `POST /v1/go-live-approvals/{id}/withdraw` | `withdraw_go_live` | Person with `go_live:approve` | Path `id`*<br>Header `X-Studio-CSRF` | — | 201 `ApprovalView` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /v1/runs/{id}/go-live-approvals` | `get_go_live_approvals` | Person | Path `id`* | — | 200 `ApprovalReview` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `POST /v1/runs/{id}/go-live-approvals` | `approve_go_live` | Person with `go_live:approve` | Path `id`*<br>Header `X-Studio-CSRF` | `ApprovalWrite` | 201 `ApprovalResult` | 401, 403, 404, 409, 413, 422, 500, 503 |

### Identity

| Method and path | Operation ID | Access | Parameters | Request body | Success | Error status |
| --- | --- | --- | --- | --- | --- | --- |
| `GET /v1/me` | `get_me` | Person or Agent with any valid key | — | — | 200 `Me` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /v1/me/selections` | `get_selections` | Person | — | — | 200 `Selections` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `PUT /v1/me/selections` | `put_selections` | Person | Header `If-Match`*, `X-Studio-CSRF` | `SelectionWrite` | 200 `Selections` | 401, 403, 404, 409, 413, 422, 500, 503 |

### Library

| Method and path | Operation ID | Access | Parameters | Request body | Success | Error status |
| --- | --- | --- | --- | --- | --- | --- |
| `GET /v1/assets` | `search_assets` | Person or Agent with `read` | Query `kind`, `label`, `production`, `board`, `cursor`, `limit` | — | 200 `Page_AssetVersion_` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /v1/assets/{id}` | `get_asset` | Person or Agent with `read` | Path `id`*<br>Query `cursor`, `limit` | — | 200 `AssetDetail` | 401, 403, 404, 409, 413, 422, 500, 503 |

### Media

| Method and path | Operation ID | Access | Parameters | Request body | Success | Error status |
| --- | --- | --- | --- | --- | --- | --- |
| `GET /v1/asset-versions/{id}/media/{sha256}` | `get_version_media` | Person | Path `id`*, `sha256`*<br>Header `Range`, `If-Range` | — | 200 bytes (`application/octet-stream`)<br>206 bytes (`application/octet-stream`) | 401, 403, 404, 409, 413, 416, 422, 500, 503 |
| `HEAD /v1/asset-versions/{id}/media/{sha256}` | `head_version_media` | Person | Path `id`*, `sha256`*<br>Header `Range`, `If-Range` | — | 200<br>206 | 401, 403, 404, 409, 413, 416, 422, 500, 503 |
| `GET /v1/jobs/{id}/media/{sha256}` | `get_job_media` | Person | Path `id`*, `sha256`*<br>Header `Range`, `If-Range` | — | 200 bytes (`application/octet-stream`)<br>206 bytes (`application/octet-stream`) | 401, 403, 404, 409, 413, 416, 422, 500, 503 |
| `HEAD /v1/jobs/{id}/media/{sha256}` | `head_job_media` | Person | Path `id`*, `sha256`*<br>Header `Range`, `If-Range` | — | 200<br>206 | 401, 403, 404, 409, 413, 416, 422, 500, 503 |
| `GET /v1/media/{sha256}` | `get_media` | Person or Agent with `read` | Path `sha256`*<br>Header `Range`, `If-Range` | — | 200 bytes (`application/octet-stream`)<br>206 bytes (`application/octet-stream`) | 401, 403, 404, 409, 413, 416, 422, 500, 503 |
| `HEAD /v1/media/{sha256}` | `head_media` | Person or Agent with `read` | Path `sha256`*<br>Header `Range`, `If-Range` | — | 200<br>206 | 401, 403, 404, 409, 413, 416, 422, 500, 503 |

### Media jobs

| Method and path | Operation ID | Access | Parameters | Request body | Success | Error status |
| --- | --- | --- | --- | --- | --- | --- |
| `POST /v1/asset-jobs` | `generate_asset_candidate` | Person | Header `Idempotency-Key`*, `X-Studio-CSRF` | `CandidateRequest` | 200 `JobStatus`<br>202 `JobStatus` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `POST /v1/asset-jobs/matte` | `request_matte` | Person | Header `Idempotency-Key`*, `X-Studio-CSRF` | `MatteRequest` | 200 `JobStatus`<br>202 `JobStatus` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `POST /v1/asset-jobs/occlusion` | `request_occlusion` | Person | Header `Idempotency-Key`*, `X-Studio-CSRF` | `OcclusionRequest` | 200 `JobStatus`<br>202 `JobStatus` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `POST /v1/asset-versions/{id}/promote` | `promote_asset_version` | Person | Path `id`*<br>Header `X-Studio-CSRF` | — | 200 `AssetVersion` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /v1/boards/{id}/jobs` | `list_board_jobs` | Person or Agent with `read` | Path `id`*<br>Query `cursor`, `limit` | — | 200 `Page_JobStatus_` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `POST /v1/boards/{id}/photo-jobs` | `generate_board_photo` | Person or Agent with `assets:generate` | Path `id`*<br>Header `Idempotency-Key`*, `X-Studio-CSRF` | `PhotoRequest` | 200 `JobStatus`<br>202 `JobStatus` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /v1/boards/{id}/photo-versions` | `list_board_photo_versions` | Person or Agent with `read` | Path `id`*<br>Query `cursor`, `limit` | — | 200 `Page_AssetVersion_` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `POST /v1/boards/{id}/photo-versions` | `upload_board_photo` | Agent with `assets:upload` | Path `id`*<br>Header `If-Match`*, `X-Studio-Photo-Provenance`* (`ExternalPhotoDeclaration`) | bytes (`image/jpeg`, `image/png`, `image/webp`) | 201 `PhotoUploadView` | 401, 403, 404, 408, 409, 413, 422, 500, 503 |
| `POST /v1/boards/{id}/voice-jobs` | `generate_board_voice` | Person or Agent with `assets:generate` | Path `id`*<br>Header `Idempotency-Key`*, `X-Studio-CSRF` | `VoiceRequest` | 200 `JobStatus`<br>202 `JobStatus` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /v1/boards/{id}/voice-versions` | `list_board_voice_versions` | Person or Agent with `read` | Path `id`*<br>Query `cursor`, `limit` | — | 200 `Page_AssetVersion_` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /v1/jobs/{id}` | `get_job` | Person or Agent with `read` (board and production-scoped matte or occlusion jobs) | Path `id`* | — | 200 `JobView` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /v1/jobs/{id}/result` | `get_job_result` | Person | Path `id`* | — | 200 `AssetVersion` | 401, 403, 404, 409, 413, 422, 500, 503 |

### Probes

| Method and path | Operation ID | Access | Parameters | Request body | Success | Error status |
| --- | --- | --- | --- | --- | --- | --- |
| `GET /healthz` | `healthz` | No Studio credential | — | — | 204 | — |
| `GET /readyz` | `readyz` | No Studio credential | — | — | 204 | 503 |

### Productions

| Method and path | Operation ID | Access | Parameters | Request body | Success | Error status |
| --- | --- | --- | --- | --- | --- | --- |
| `GET /v1/productions` | `list_productions` | Person or Agent with `read` | Query `cursor`, `limit` | — | 200 `Page_Production_` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `POST /v1/productions` | `create_production` | Person | Header `X-Studio-CSRF` | `ProductionCreate` | 201 `Production` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /v1/productions/{id}` | `get_production` | Person or Agent with `read` | Path `id`* | — | 200 `Production` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `PUT /v1/productions/{id}/media-types/{kind}` | `enable_media_type` | Person | Path `id`*, `kind`*<br>Header `If-Match`*, `X-Studio-CSRF` | — | 200 `Production` | 401, 403, 404, 409, 413, 422, 500, 503 |

### Release

| Method and path | Operation ID | Access | Parameters | Request body | Success | Error status |
| --- | --- | --- | --- | --- | --- | --- |
| `POST /v1/runs/{id}/publications` | `record_publication` | Person with `go_live:approve` | Path `id`*<br>Header `Idempotency-Key`*, `X-Studio-CSRF` | `PublicationWrite` | 200 `Publication`<br>201 `Publication` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /v1/runs/{id}/release-packages` | `list_release_packages` | Person or Agent with `read` | Path `id`* | — | 200 `ReleasePackageList` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `POST /v1/runs/{id}/release-packages` | `prepare_release_package` | Person or Agent with `runs:queue` | Path `id`*<br>Header `X-Studio-CSRF` | `ReleasePackageWrite` | 200 `ReleasePackageReceipt`<br>201 `ReleasePackageReceipt` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /v1/runs/{id}/release-packages/{digest}/download` | `download_release_package` | Person or Agent with `read` | Path `id`*, `digest`* | — | 200 inline object | 401, 403, 404, 409, 413, 422, 500, 503 |

### Runs

| Method and path | Operation ID | Access | Parameters | Request body | Success | Error status |
| --- | --- | --- | --- | --- | --- | --- |
| `GET /v1/queue/lanes` | `get_queue_lanes` | Person | — | — | 200 `QueueStatus` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `PUT /v1/queue/lanes/{lane}` | `set_queue_lane` | Person | Path `lane`*<br>Header `X-Studio-CSRF` | `QueueLaneUpdate` | 200 `QueueLaneStatus` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /v1/runs/{id}` | `get_run` | Person or Agent with `read` | Path `id`* | — | 200 `RunView` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `POST /v1/runs/{id}/cancel` | `cancel_run` | Person or Agent with `runs:queue` | Path `id`*<br>Header `If-Match`*, `X-Studio-CSRF` | — | 200 `RunView` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `POST /v1/runs/{id}/checks/{check}/overrides` | `record_check_override` | Person | Path `id`*, `check`*<br>Header `If-Match`*, `X-Studio-CSRF` | `CheckOverride` | 201 `CheckOverrideView` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /v1/runs/{id}/snapshot` | `get_run_snapshot` | Person or Agent with `read` | Path `id`*<br>Header `If-None-Match` | — | 200 `RunSnapshot`<br>304 | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /v1/stories/{id}/estimate` | `estimate_run` | Person or Agent with `read` | Path `id`* | — | 200 `EstimateView` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /v1/stories/{id}/runs` | `list_runs` | Person or Agent with `read` | Path `id`*<br>Query `cursor`, `limit` | — | 200 `Page_RunView_` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `POST /v1/stories/{id}/runs` | `queue_run` | Person or Agent with `runs:queue` | Path `id`*<br>Header `If-Match`*, `Idempotency-Key`*, `X-Studio-CSRF` | — | 200<br>201 `RunView` | 401, 403, 404, 409, 413, 422, 500, 503 |

### Stories

| Method and path | Operation ID | Access | Parameters | Request body | Success | Error status |
| --- | --- | --- | --- | --- | --- | --- |
| `GET /v1/productions/{id}/media-types/{kind}/stories` | `list_stories` | Person or Agent with `read` | Path `id`*, `kind`*<br>Query `publication`, `approved`, `cursor`, `limit` | — | 200 `Page_Story_` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `POST /v1/productions/{id}/media-types/{kind}/stories` | `create_story` | Person or Agent with `draft:write` | Path `id`*, `kind`*<br>Header `X-Studio-CSRF` | `StoryCreate` | 201 `Story` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /v1/stories/{id}` | `get_story` | Person or Agent with `read` | Path `id`* | — | 200 `Story` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `PATCH /v1/stories/{id}` | `update_story` | Person or Agent with `draft:write` | Path `id`*<br>Header `If-Match`*, `X-Studio-CSRF` | `StoryPatch` | 200 `Story` | 401, 403, 404, 409, 413, 422, 500, 503 |
| `GET /v1/stories/{id}/timing` | `get_story_timing` | Person or Agent with `read` | Path `id`* | — | 200 `Timing` | 401, 403, 404, 409, 413, 422, 500, 503 |

### Stable errors

JSON errors use the OpenAPI `ErrorEnvelope`. Common codes and recovery steps appear above.
The table lists stable operation-specific codes recorded in the handlers and guides.
Contract validation can also return rule codes from the [rule index](../contracts/studio-contracts-v1.md#15-rule-index).
HEAD responses carry status and headers without an error body.

| Operation | HTTP status | Stable `error.code` values |
| --- | --- | --- |
| `login` | 422 | `auth.return_to_invalid` |
| `request_matte` | 422 | `adapter.request_invalid`, `idempotency.mismatch` |
| `request_occlusion` | 422 | `idempotency.mismatch`, `occlusion.declared_target`, `occlusion.invalid_input` |
| `request_occlusion` | 503 | `occlusion.store_unavailable`, `occlusion.unavailable` |
| `create_production` | 409 | `production.name_duplicate` |
| `create_story`, `update_story` | 409 | `story.title_duplicate` |
| `get_production`, `list_stories`, `create_story`, `get_story`, `update_story`, `get_story_timing`, `get_board`, `create_board`, `update_board`, `reorder_boards`, `remove_board` | 422 | `id.malformed`, `id.type_mismatch` |
| `put_selections`, `enable_media_type`, `update_story`, `create_board`, `update_board`, `reorder_boards`, `remove_board`, `queue_run`, `cancel_run`, `record_check_override`, `upload_board_photo`, `apply_archive_storyboard`, `start_feedback_iteration`, `clear_feedback_iteration` | 409 | `conflict.revision` |
| `update_board`, `reorder_boards`, `remove_board` | 409 | `draft.protected` |
| `update_board`, `reorder_boards`, `remove_board` | 422 | `draft.invalid_read_token` |
| `generate_board_voice`, `generate_board_photo`, `generate_asset_candidate`, `queue_run`, `create_archive_record`, `add_archive_version`, `record_publication` | 422 | `idempotency.mismatch` |
| `upload_board_photo` | 422 | `prov.external_incomplete`, `photo.image_invalid`, `photo.hash_mismatch`, `photo.method_invalid`, `asset.recorded_without_media` |
| `upload_board_photo` | 413 | `photo.too_large` |
| `upload_board_photo` | 408 | `photo.upload_timeout` |
| `upload_board_photo` | 503 | `photo.upload_busy` |
| `promote_asset_version` | 422 | `asset.recorded_without_media` |
| `get_media`, `get_job_media`, `get_version_media` | 416 | `media.range_unsatisfied` |
| `get_media`, `get_job_media`, `get_version_media` | 503 | `store.failed` |
| `queue_run` | 422 | `method.unavailable`, `voice.absent`, `voice.stale`, `photo.absent`, `asset.generating`, `run.snapshot_too_large` |
| `cancel_run` | 409 | `run.transition` |
| `record_check_override` | 403 | `check.not_overridable` |
| `record_check_override` | 409 | `check.not_overridable`, `check.override_exists` |
| `get_run_snapshot` | 404 | `run.snapshot_missing` |
| `get_run_snapshot` | 503 | `run.snapshot_lost`, `run.snapshot_changed`, `run.snapshot_too_large`, `run.snapshot_store_unavailable` |
| `create_format` | 409 | `format.id_duplicate` |
| `create_format`, `add_format_version` | 422 | `format.frame_mismatch`, `format.target_invalid`, `format.length_invalid`, `format.credential`, `format.recipe_too_large` |
| `create_archive_record`, `add_archive_version` | 422 | `archive.invalid_text`, `archive.credentials`, `ref.unknown`, `archive.production_mismatch` |
| `create_archive_record`, `add_archive_version` | 413 | `archive.too_large` |
| `add_archive_version` | 409 | `archive.stale_version` |
| `get_archive_version` | 500 | `archive.text_hash_mismatch` |
| `apply_archive_storyboard` | 422 | `archive.not_storyboard`, `archive.story_mismatch` |
| `authorize_escalation`, `decline_escalation`, `cancel_escalation`, `report_escalation` | 409 | `escalation.state` |
| `authorize_escalation`, `decline_escalation`, `cancel_escalation` | 403 | `escalation.person_required` |
| `authorize_escalation` | 409 | `escalation.expired`, `escalation.override` |
| `authorize_escalation` | 422 | `escalation.board` |
| `report_escalation` | 409 | `escalation.expired`, `escalation.callback_conflict` |
| `report_escalation` | 403 | `escalation.responder_scope` |
| `report_escalation` | 422 | `escalation.changed_ids` |
| `present_candidate` | 422 | `candidate.legacy_run`, `candidate.run_unfinished`, `candidate.target_required`, `candidate.format_missing`, `candidate.target_unknown` |
| `add_candidate_feedback`, `start_feedback_iteration`, `clear_feedback_iteration` | 403 | `feedback.person_required` |
| `list_candidates` | 422 | `feedback.duplicate_reference` |
| `add_candidate_feedback` | 422 | `feedback.text_required`, `feedback.board_unknown`, `feedback.note_unknown`, `feedback.duplicate_reference` |
| `start_feedback_iteration` | 422 | `feedback.note_unknown`, `feedback.duplicate_reference` |
| `add_candidate_feedback` | 409 | `feedback.already_corrected` |
| `approve_go_live`, `withdraw_go_live`, `record_publication` | 403 | `approval.approver_not_configured`, `approval.subject_not_permitted`, `approval.group_not_permitted`, `approval.approver_not_permitted`, `approval.worker_not_permitted`, `approval.sign_in_again` |
| `approve_go_live` | 409 | `approval.already_active` |
| `get_go_live_approvals` | 403 | `approval.approver_not_permitted`, `approval.worker_not_permitted` |
| `withdraw_go_live` | 409 | `approval.already_withdrawn` |
| `approve_go_live` | 422 | `approval.legacy_run`, `approval.run_unfinished`, `approval.delivery_unverified`, `approval.delivery_mismatch`, `approval.not_exact_run`, `approval.provenance_missing`, `approval.licence_missing`, `approval.ai_label_missing` |
| `approve_go_live`, `prepare_release_package`, `record_publication` | 503 | `approval.licence_register_unavailable`, `release.package_record_changed` |
| `prepare_release_package` | 422 | `release.format_missing`, `release.target_unknown`, `release.maximum_unset`, `release.over_length`, `release.aspect_mismatch` |
| `download_release_package`, `prepare_release_package` | 503 | `release.store_unavailable`, `release.package_changed` |
| `record_publication` | 409 | `release.approval_required`, `release.already_published` |
| `record_publication` | 422 | `release.location_invalid`, `release.publication_before_approval`, `release.publication_in_future` |

## MCP tools (34)

[Schema data](api-reference-data/schemas.json) holds each full `inputSchema` under `tools.<name>`.
Use the linked operation guides for result projections. Tool parameters are JSON arguments.
Tools use `/mcp` except for the one marked `/mcp/upload`.

| Tool | Agent scope | Input schema | HTTP operation |
| --- | --- | --- | --- |
| `studio_add_archive_version` | `archive:write` | `AddArchiveVersion` (requires `text`, `provenance`, `revises_version_id`, `record_id`, `idempotency_key`) | `add_archive_version` · `POST /v1/archive-records/{id}/versions` |
| `studio_add_board` | `draft:write` | `AddBoard` (requires `story_id`, `revision`, `fields`) | `create_board` · `POST /v1/stories/{id}/boards` |
| `studio_apply_archive_storyboard` | `archive:read` and `draft:write` | `ApplyArchiveStoryboard` (requires `story_id`, `version_id`, `revision`) | `apply_archive_storyboard` · `POST /v1/archive-versions/{id}/apply` |
| `studio_cancel_run` | `runs:queue` | `CancelRun` (requires `run_id`, `revision`) | `cancel_run` · `POST /v1/runs/{id}/cancel` |
| `studio_create_archive_record` | `archive:write` | `CreateArchiveRecord` (requires `text`, `provenance`, `kind`, `title`, `production_id`, `idempotency_key`) | `create_archive_record` · `POST /v1/productions/{id}/archive-records` |
| `studio_create_story` | `draft:write` | `CreateStory` (requires `production_id`, `kind`, `fields`) | `create_story` · `POST /v1/productions/{id}/media-types/{kind}/stories` |
| `studio_estimate_run` | `read` | `Story` (requires `story_id`) | `estimate_run` · `GET /v1/stories/{id}/estimate` |
| `studio_generate_photo` | `assets:generate` | `GeneratePhoto` (requires `board_id`, `idempotency_key`) | `generate_board_photo` · `POST /v1/boards/{id}/photo-jobs` |
| `studio_generate_voice` | `assets:generate` | `GenerateVoice` (requires `board_id`, `idempotency_key`) | `generate_board_voice` · `POST /v1/boards/{id}/voice-jobs` |
| `studio_get_archive_record` | `archive:read` | `ArchiveRecord` (requires `record_id`) | `get_archive_record` · `GET /v1/archive-records/{id}` |
| `studio_get_archive_version` | `archive:read` | `ArchiveVersion` (requires `version_id`) | `get_archive_version` · `GET /v1/archive-versions/{id}` |
| `studio_get_asset` | `read` | `Asset` (requires `asset_id`) | `get_asset` · `GET /v1/assets/{id}` |
| `studio_get_board` | `read` | `GetBoard` (requires `board_id`) | `get_board` · `GET /v1/boards/{id}` |
| `studio_get_delivery` | `read` | `Delivery` (requires `run_id`) | `get_delivery` · `GET /v1/runs/{id}/delivery` |
| `studio_get_format_version` | `read` | `FormatVersion` (requires `version_id`) | `get_format_version` · `GET /v1/format-versions/{id}` |
| `studio_get_job` | `read` | `GetJob` (requires `job_id`) | `get_job` · `GET /v1/jobs/{id}` |
| `studio_get_production` | `read` | `Production` (requires `production_id`) | `get_production` · `GET /v1/productions/{id}` |
| `studio_get_run` | `read` | `Delivery` (requires `run_id`) | `get_run` · `GET /v1/runs/{id}` |
| `studio_get_story_summary` | `read` | `StorySummary` (requires `story_id`) | `get_story` · `GET /v1/stories/{id}` |
| `studio_get_story_timing` | `read` | `StoryPage` (requires `story_id`) | `get_story_timing` · `GET /v1/stories/{id}/timing` |
| `studio_list_archive_records` | `archive:read` | `ListArchiveRecords` (requires `production_id`) | `list_archive_records` · `GET /v1/productions/{id}/archive-records` |
| `studio_list_candidates` | `read` | `Candidates` (requires `story_id`) | `list_candidates` · `GET /v1/stories/{id}/candidates` |
| `studio_list_format_versions` | `read` | `ListFormatVersions` (requires `format_id`) | `list_format_versions` · `GET /v1/formats/{id}/versions` |
| `studio_list_formats` | `read` | `ListFormats` | `list_formats` · `GET /v1/formats` |
| `studio_list_productions` | `read` | `ListProductions` | `list_productions` · `GET /v1/productions` |
| `studio_list_runs` | `read` | `Runs` (requires `story_id`) | `list_runs` · `GET /v1/stories/{id}/runs` |
| `studio_list_stories` | `read` | `ListStories` (requires `production_id`, `kind`) | `list_stories` · `GET /v1/productions/{id}/media-types/{kind}/stories` |
| `studio_patch_board` | `draft:write` | `PatchBoard` (requires `board_id`, `revision`, `patch`) | `update_board` · `PATCH /v1/boards/{id}` |
| `studio_patch_story` | `draft:write` | `PatchStory` (requires `story_id`, `revision`, `patch`) | `update_story` · `PATCH /v1/stories/{id}` |
| `studio_queue_run` | `runs:queue` | `QueueRun` (requires `story_id`, `revision`, `idempotency_key`) | `queue_run` · `POST /v1/stories/{id}/runs` |
| `studio_remove_board` | `draft:write` | `RemoveBoard` (requires `board_id`, `revision`) | `remove_board` · `DELETE /v1/boards/{id}` |
| `studio_reorder_boards` | `draft:write` | `ReorderBoards` (requires `story_id`, `revision`, `board_order`) | `reorder_boards` · `PUT /v1/stories/{id}/board-order` |
| `studio_search_assets` | `read` | `SearchAssets` | `search_assets` · `GET /v1/assets` |
| `studio_upload_photo` (`/mcp/upload`) | `assets:upload` | `UploadPhoto` (requires `board_id`, `revision`, `media_type`, `data_base64`, `provenance`) | `upload_board_photo` · `POST /v1/boards/{id}/photo-versions` |

## Examples

[Synthetic examples](api-reference-data/examples.json) show one schema-checked payload per family.
They describe individual request or response parts. Use the HTTP or MCP table for the rest of the call.

| Family | Validated part |
| --- | --- |
| Archive | `studio_create_archive_record` arguments |
| Authentication | `login` return_to parameter |
| Boards | `studio_add_board` arguments |
| Deliveries | `studio_get_delivery` arguments |
| Escalations | `authorize_escalation` request |
| Feedback | `add_candidate_feedback` request |
| Formats | `studio_list_format_versions` arguments |
| Go-live | `approve_go_live` request |
| Identity | `get_me` response |
| Library | `studio_search_assets` arguments |
| Media | `get_media` Range parameter |
| Media jobs | `studio_generate_photo` arguments |
| Photo upload | `upload_board_photo` X-Studio-Photo-Provenance parameter |
| Probes | `healthz` 204 response without a body |
| Productions | `create_production` request |
| Release | `prepare_release_package` request |
| Runs | `studio_queue_run` arguments |
| Stories | `create_story` request |

## Parity gaps

### API operations with no MCP tool

| Method and path | Operation ID | Reason |
| --- | --- | --- |
| `GET /auth/callback` | `callback` | Browser OIDC session flow. [Browser authentication](studio-api.md#browser-agent-and-worker-requests). |
| `GET /auth/login` | `login` | Browser OIDC session flow. [Browser authentication](studio-api.md#browser-agent-and-worker-requests). |
| `POST /auth/logout` | `logout` | Browser OIDC session flow. [Browser authentication](studio-api.md#browser-agent-and-worker-requests). |
| `GET /healthz` | `healthz` | Service probes. [API boundaries](../contracts/studio-contracts-v1.md#12-api-ui-and-mcp-boundaries). |
| `GET /readyz` | `readyz` | Service probes. [API boundaries](../contracts/studio-contracts-v1.md#12-api-ui-and-mcp-boundaries). |
| `POST /v1/asset-jobs` | `generate_asset_candidate` | Signed-in person required. [Asset candidates](asset-candidates.md#api-and-ui-integration). |
| `POST /v1/asset-jobs/matte` | `request_matte` | Signed-in person required. Production-scoped status is available via studio_get_job. [Matte requests](studio-api.md#matte-requests-and-reads). |
| `POST /v1/asset-jobs/occlusion` | `request_occlusion` | Signed-in person required. Production-scoped job reads are available via studio_get_job. [Occlusion jobs](segmentation-adapter.md#occlusion-jobs). |
| `GET /v1/asset-versions/{id}/media/{sha256}` | `get_version_media` | MCP returns compact metadata and excludes byte reads. [MCP boundaries](../contracts/studio-contracts-v1.md#boundaries-d41). |
| `HEAD /v1/asset-versions/{id}/media/{sha256}` | `head_version_media` | MCP returns compact metadata and excludes byte reads. [MCP boundaries](../contracts/studio-contracts-v1.md#boundaries-d41). |
| `POST /v1/asset-versions/{id}/promote` | `promote_asset_version` | Signed-in person required. [Asset candidates](asset-candidates.md#api-and-ui-integration). |
| `GET /v1/boards/{id}/jobs` | `list_board_jobs` | unrecorded |
| `GET /v1/boards/{id}/photo-versions` | `list_board_photo_versions` | unrecorded |
| `GET /v1/boards/{id}/voice-versions` | `list_board_voice_versions` | unrecorded |
| `POST /v1/candidates/{id}/feedback` | `add_candidate_feedback` | Signed-in person required. See the HTTP access column. |
| `POST /v1/candidates/{id}/iterations` | `start_feedback_iteration` | Signed-in person required. See the HTTP access column. |
| `POST /v1/formats` | `create_format` | MCP exposes recipe reads. Authoring is over HTTP. [Format scopes](formats.md#api-and-scopes). |
| `POST /v1/formats/{id}/versions` | `add_format_version` | MCP exposes recipe reads. Authoring is over HTTP. [Format scopes](formats.md#api-and-scopes). |
| `POST /v1/go-live-approvals/{id}/withdraw` | `withdraw_go_live` | Go-live and publication are reserved for people. [MCP boundaries](../contracts/studio-contracts-v1.md#boundaries-d41) and [release packages](release-package.md#api). |
| `GET /v1/jobs/{id}/media/{sha256}` | `get_job_media` | MCP returns compact metadata and excludes byte reads. [MCP boundaries](../contracts/studio-contracts-v1.md#boundaries-d41). |
| `HEAD /v1/jobs/{id}/media/{sha256}` | `head_job_media` | MCP returns compact metadata and excludes byte reads. [MCP boundaries](../contracts/studio-contracts-v1.md#boundaries-d41). |
| `GET /v1/jobs/{id}/result` | `get_job_result` | Signed-in person required. [Asset candidates](asset-candidates.md#api-and-ui-integration). |
| `GET /v1/me` | `get_me` | MCP uses this as its bearer identity check. [MCP transport](studio-mcp.md). |
| `GET /v1/me/selections` | `get_selections` | Signed-in person required. See the HTTP access column. |
| `PUT /v1/me/selections` | `put_selections` | Signed-in person required. See the HTTP access column. |
| `GET /v1/media/{sha256}` | `get_media` | MCP returns compact metadata and excludes byte reads. [MCP boundaries](../contracts/studio-contracts-v1.md#boundaries-d41). |
| `HEAD /v1/media/{sha256}` | `head_media` | MCP returns compact metadata and excludes byte reads. [MCP boundaries](../contracts/studio-contracts-v1.md#boundaries-d41). |
| `POST /v1/productions` | `create_production` | Signed-in person required. See the HTTP access column. |
| `PUT /v1/productions/{id}/media-types/{kind}` | `enable_media_type` | Signed-in person required. See the HTTP access column. |
| `GET /v1/productions/{production_id}/escalations` | `list_escalation_packages` | unrecorded |
| `GET /v1/productions/{production_id}/escalations/{package_id}` | `get_escalation_package` | unrecorded |
| `POST /v1/productions/{production_id}/escalations/{package_id}/authorize` | `authorize_escalation` | Signed-in operator decision. [Escalation operations](escalation.md#operator-and-responder-operations). |
| `POST /v1/productions/{production_id}/escalations/{package_id}/callback` | `report_escalation` | HTTP callback for the exact package responder. [Escalation operations](escalation.md#operator-and-responder-operations). |
| `POST /v1/productions/{production_id}/escalations/{package_id}/cancel` | `cancel_escalation` | Signed-in operator decision. [Escalation operations](escalation.md#operator-and-responder-operations). |
| `POST /v1/productions/{production_id}/escalations/{package_id}/decline` | `decline_escalation` | Signed-in operator decision. [Escalation operations](escalation.md#operator-and-responder-operations). |
| `GET /v1/queue/lanes` | `get_queue_lanes` | Signed-in person required. Each lane reports whether it has a live claim. [Queue controls](studio-api.md#queue-controls). |
| `PUT /v1/queue/lanes/{lane}` | `set_queue_lane` | Signed-in person required. Pause holds queued work while workers can settle previously dispatched jobs. [Queue controls](studio-api.md#queue-controls). |
| `POST /v1/runs/{id}/candidates` | `present_candidate` | unrecorded |
| `POST /v1/runs/{id}/checks/{check}/overrides` | `record_check_override` | A person can override a failed decal check or review an uncertain visibility result. Hidden visibility always blocks delivery. [Film visibility](film-visibility.md) and [operation parity](studio-operation-parity.md). |
| `GET /v1/runs/{id}/go-live-approvals` | `get_go_live_approvals` | Go-live and publication are reserved for people. [MCP boundaries](../contracts/studio-contracts-v1.md#boundaries-d41) and [release packages](release-package.md#api). |
| `POST /v1/runs/{id}/go-live-approvals` | `approve_go_live` | Go-live and publication are reserved for people. [MCP boundaries](../contracts/studio-contracts-v1.md#boundaries-d41) and [release packages](release-package.md#api). |
| `POST /v1/runs/{id}/publications` | `record_publication` | Go-live and publication are reserved for people. [MCP boundaries](../contracts/studio-contracts-v1.md#boundaries-d41) and [release packages](release-package.md#api). |
| `GET /v1/runs/{id}/release-packages` | `list_release_packages` | unrecorded |
| `POST /v1/runs/{id}/release-packages` | `prepare_release_package` | unrecorded |
| `GET /v1/runs/{id}/release-packages/{digest}/download` | `download_release_package` | unrecorded |
| `GET /v1/runs/{id}/snapshot` | `get_run_snapshot` | unrecorded |
| `GET /v1/runs/{run_id}/escalation-checks/{record_sha256}` | `get_escalation_check` | unrecorded |
| `DELETE /v1/stories/{id}/feedback-iteration` | `clear_feedback_iteration` | Signed-in person required. See the HTTP access column. |
| `POST /internal/v1/work/attempts` | `reserve_wan_attempt` | Internal worker protocol excluded from OpenAPI. [Run queue](run-queue.md#claims-and-reconciliation) and [media workers](media-jobs.md#claims-and-results). |
| `POST /internal/v1/work/attempts/{job_id}` | `update_wan_attempt` | Internal worker protocol excluded from OpenAPI. [Run queue](run-queue.md#claims-and-reconciliation) and [media workers](media-jobs.md#claims-and-results). |
| `POST /internal/v1/work/claim` | `claim_work` | Internal worker protocol excluded from OpenAPI. [Run queue](run-queue.md#claims-and-reconciliation) and [media workers](media-jobs.md#claims-and-results). |
| `POST /internal/v1/work/complete` | `complete_work` | Internal worker protocol excluded from OpenAPI. [Run queue](run-queue.md#claims-and-reconciliation) and [media workers](media-jobs.md#claims-and-results). |
| `POST /internal/v1/work/escalation-check-failure` | `record_escalation_check` | Internal worker protocol excluded from OpenAPI. [Run queue](run-queue.md#claims-and-reconciliation) and [media workers](media-jobs.md#claims-and-results). |
| `POST /internal/v1/work/fail` | `fail_work` | Internal worker protocol excluded from OpenAPI. [Run queue](run-queue.md#claims-and-reconciliation) and [media workers](media-jobs.md#claims-and-results). |
| `POST /internal/v1/work/heartbeat` | `heartbeat_work` | Internal worker protocol excluded from OpenAPI. [Run queue](run-queue.md#claims-and-reconciliation) and [media workers](media-jobs.md#claims-and-results). |
| `POST /internal/v1/work/publish` | `publish_work` | Internal worker protocol excluded from OpenAPI. [Run queue](run-queue.md#claims-and-reconciliation) and [media workers](media-jobs.md#claims-and-results). |
| `POST /internal/v1/work/release-matte` | `release_matte_work` | Internal worker protocol excluded from OpenAPI. [Run queue](run-queue.md#claims-and-reconciliation) and [media workers](media-jobs.md#claims-and-results). |
| `POST /internal/v1/work/resume` | `resume_work` | Internal worker protocol excluded from OpenAPI. [Run queue](run-queue.md#claims-and-reconciliation) and [media workers](media-jobs.md#claims-and-results). |

### MCP tools with no API operation

Every registered MCP tool forwards to an HTTP operation.

## Not documented

The following worker-only HTTP contracts are outside the published OpenAPI document.
They require a worker bearer, its lane grant and the current claim fence for claim mutations.

| Method and path | Operation ID | Access | Reason |
| --- | --- | --- | --- |
| `POST /internal/v1/work/attempts` | `reserve_wan_attempt` | Worker | Internal worker protocol excluded from OpenAPI. [Run queue](run-queue.md#claims-and-reconciliation) and [media workers](media-jobs.md#claims-and-results). |
| `POST /internal/v1/work/attempts/{job_id}` | `update_wan_attempt` | Worker | Internal worker protocol excluded from OpenAPI. [Run queue](run-queue.md#claims-and-reconciliation) and [media workers](media-jobs.md#claims-and-results). |
| `POST /internal/v1/work/claim` | `claim_work` | Worker | Internal worker protocol excluded from OpenAPI. [Run queue](run-queue.md#claims-and-reconciliation) and [media workers](media-jobs.md#claims-and-results). |
| `POST /internal/v1/work/complete` | `complete_work` | Worker | Internal worker protocol excluded from OpenAPI. [Run queue](run-queue.md#claims-and-reconciliation) and [media workers](media-jobs.md#claims-and-results). |
| `POST /internal/v1/work/escalation-check-failure` | `record_escalation_check` | Worker | Internal worker protocol excluded from OpenAPI. [Run queue](run-queue.md#claims-and-reconciliation) and [media workers](media-jobs.md#claims-and-results). |
| `POST /internal/v1/work/fail` | `fail_work` | Worker | Internal worker protocol excluded from OpenAPI. [Run queue](run-queue.md#claims-and-reconciliation) and [media workers](media-jobs.md#claims-and-results). |
| `POST /internal/v1/work/heartbeat` | `heartbeat_work` | Worker | Internal worker protocol excluded from OpenAPI. [Run queue](run-queue.md#claims-and-reconciliation) and [media workers](media-jobs.md#claims-and-results). |
| `POST /internal/v1/work/publish` | `publish_work` | Worker | Internal worker protocol excluded from OpenAPI. [Run queue](run-queue.md#claims-and-reconciliation) and [media workers](media-jobs.md#claims-and-results). |
| `POST /internal/v1/work/release-matte` | `release_matte_work` | Worker | Internal worker protocol excluded from OpenAPI. [Run queue](run-queue.md#claims-and-reconciliation) and [media workers](media-jobs.md#claims-and-results). |
| `POST /internal/v1/work/resume` | `resume_work` | Worker | Internal worker protocol excluded from OpenAPI. [Run queue](run-queue.md#claims-and-reconciliation) and [media workers](media-jobs.md#claims-and-results). |
