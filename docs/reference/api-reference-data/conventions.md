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
See [Studio API](../studio-api.md#browser-agent-and-worker-requests),
[Studio MCP](../studio-mcp.md), [formats](../formats.md#api-and-scopes),
[escalation](../escalation.md#authorization-and-budgets) and [go-live](../go-live.md).

A person with key-admin authority issues and revokes agent keys. An agent uses
only the key provisioned to its session. It never creates, copies or asks for
one. Present the secret only in the Authorization header to the configured
Studio API or MCP endpoint. Keep it out of URLs, query strings, tool arguments,
request bodies (including provenance), logs, source, examples and handoffs.
The public `key_` ID identifies a credential record. Use it for permitted
key administration and audit. [Agent key administration](../studio-mcp.md#agent-key-administration).

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
See the [identifier contract](../../contracts/studio-contracts-v1.md#identifiers-p-01)
and [staging archive](../staging-archive.md).

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
handler returns `409 conflict.revision`. See [agent drafting](../agent-drafting.md#re-drafts-and-receipts)
and [staging archive](../staging-archive.md).

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
check the board revision before resending. [Photo upload](../studio-api.md#d42-photo-upload).

## Asynchronous jobs and polling

Generation returns `202` with a job ID and `Location`, or `200` on replay. Poll
`GET /v1/jobs/{id}` or `studio_get_job` for board jobs. Check the terminal
status and `result_is_current` before using a version. A job can succeed and
retain its result without changing the board. A person can inspect a private
candidate result and promote it separately. Queueing a run freezes the story
revision and returns `201` with its `Location`. Poll `GET /v1/runs/{id}` or
`studio_get_run` for progress and terminal state. Cancel using the run's current
revision. A cancellation can stay pending while work settles. Use the
scoped HTTP media routes for byte ranges and the delivery endpoint or tool for
metadata. See [media jobs](../media-jobs.md), [asset candidates](../asset-candidates.md),
[reference photo composer](../photo-composer.md), [run queue](../run-queue.md),
[candidate feedback](../feedback.md) and [release packages](../release-package.md).

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
16 MiB. See [Studio MCP limits](../studio-mcp.md#tools-and-revisions) and
[archive limits](../staging-archive.md#operations).
