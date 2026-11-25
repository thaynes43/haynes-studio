# Studio API

The API stores canonical production, media type, story, board and asset records in
PostgreSQL 16. It also stores the run queue and its worker claims. It serves private media from the D39 content-addressed store. Any
API replica can read a draft or continue a browser session created by another
replica. Story [409](https://work.haynesnetwork.com/work_packages/409) covers
source and test evidence for metadata and playback. See the [run queue reference](run-queue.md)
for story [410](https://work.haynesnetwork.com/work_packages/410). The CNPG database,
roles, Authentik application and credential projections are installed as of 2026-11-24,
and so is the Studio API with its migration Job and table grants
(story [434](https://work.haynesnetwork.com/work_packages/434), from an image built
before the run queue). A person's live sign-in is not yet recorded.
[Install evidence](../contracts/studio-contracts-v1.md#installed-and-published-state).

## Commands

```sh
uv sync --locked
uv run --no-sync studio-api openapi > studio-api.openapi.json
STUDIO_RUNTIME_ROLE=studio_app uv run --no-sync studio-api-migrate upgrade head
uv run --no-sync studio-api serve --host 0.0.0.0 --port 8000
```

The OpenAPI command works without runtime configuration. Generate the web client
from its OpenAPI 3.1 output. Stable operation IDs follow section 12 of the
[Studio contracts](../contracts/studio-contracts-v1.md). The document links the
package's canonical schemas and also describes the partial write bodies.

Run `studio-api-migrate upgrade head` as a one-shot Job with the migration
identity before starting the API. The image must contain the installed Python
package and its Alembic scripts. The revisions and their runtime grants are transactional.
Concurrent Jobs serialize on a Postgres advisory lock. The CLI only exposes
`upgrade head`. The DB test fixture exercises the destructive reversal on
an empty disposable schema. Use a forward migration for production recovery,
or recover metadata to an isolated database for inspection.

## Environment

| Variable | Value |
|---|---|
| `STUDIO_DATABASE_URL` | Runtime libpq URL or connection string supplied by the app's secret. |
| `STUDIO_MIGRATION_DATABASE_URL` | DSN for the migration or key administration command. Mount the migration identity in the migration Job, and the chosen provisioning identity in the key administration Job. |
| `STUDIO_DATABASE_SCHEMA` | Precreated schema, default `studio`. Both commands must agree. |
| `STUDIO_RUNTIME_ROLE` | Existing runtime login, typically `studio_app`. Set on the migration Job. A lower-case PostgreSQL identifier. An unset variable skips grants. |
| `STUDIO_BUILD_REVISION` | Build revision pinned in new snapshots. Use the same `git:<commit>` on the API and render workers. The local default is `git:unknown`. |
| `STUDIO_BUILD_STAGE_ROOT` | Shared private build staging directory used by the API completion route and workers. Use a separate directory from the authoritative store. See the [worker configuration](run-queue.md#worker-configuration). |
| `STUDIO_STORE_ROOT` | Root of the shared D39 store. Mount the same directory at every replica. |
| `STUDIO_STORE_FRESHNESS_SECONDS` | Maximum age of a successful store readiness check, 5–300 seconds. Default 30. |
| `STUDIO_PUBLIC_ORIGIN` | Browser HTTPS origin, without a trailing slash or path. The UI and API share it. |
| `STUDIO_OIDC_ISSUER` | Exact HTTPS issuer from Authentik discovery, including any final slash. |
| `STUDIO_OIDC_CLIENT_ID` | Client ID of the confidential OIDC application. |
| `STUDIO_OIDC_CLIENT_SECRET` | Secret supplied to the API process. |
| `STUDIO_OIDC_ALLOWED_SUBJECTS` | JSON array of allowed OIDC `sub` values scoped to the configured issuer. Defaults to `[]`. |
| `STUDIO_OIDC_ALLOWED_GROUPS` | JSON array of exact, case-sensitive group names. Defaults to `[]`. |
| `STUDIO_OIDC_LEEWAY_SECONDS` | Clock skew allowance for ID-token timestamps, 0–300 seconds. Default 60. |
| `STUDIO_OIDC_CACHE_TTL_SECONDS` | Cache lifetime for OIDC discovery and signing keys, 1–3600 seconds. Default 300. |
| `STUDIO_OIDC_FAILURE_TTL_SECONDS` | Cooldown after a failed discovery or signing key fetch, 1–60 seconds. Default 10. |
| `STUDIO_SESSION_SECONDS` | Absolute lifetime of an API session, 60–86400 seconds. Default 28800. |
| `STUDIO_GO_LIVE_APPROVER_SUBJECTS` | JSON array of approver subjects scoped to the configured OIDC issuer. Default `[]`. |
| `STUDIO_GO_LIVE_FRESHNESS_SECONDS` | Maximum age of sign-in for approval and withdrawal, 1–86400 seconds. Default 900. |

Use TLS for browser requests. Configure Authentik with
`STUDIO_PUBLIC_ORIGIN + /auth/callback`, `client_secret_basic`, PKCE S256 and
an RS256 signing key. The discovery document must identify the configured
issuer and advertise HTTPS authorization, token and key endpoints. Route
`/auth/*` and `/v1/*` to the API and the remaining UI paths to the static app.
Each API process caches discovery and JWKS independently and refreshes the key
set once when it sees an unknown `kid`. Requests that need a fetch return 503
while another fetch for the same cache is in flight or its cooldown is active.
Rate limiting belongs to the ingress in story
[434](https://work.haynesnetwork.com/work_packages/434).
[OIDC Core](https://openid.net/specs/openid-connect-core-1_0.html)
[RFC 7636](https://www.rfc-editor.org/rfc/rfc7636)

For the [OP432](https://work.haynesnetwork.com/work_packages/432) provider, set
`STUDIO_PUBLIC_ORIGIN=https://studio.haynesops.com`,
`STUDIO_OIDC_CLIENT_ID=haynes-studio` and
`STUDIO_OIDC_ALLOWED_GROUPS='["authentik Admins"]'`. Use the exact
per-provider issuer from the `haynes-studio` discovery document. The Authentik
application requires membership of the existing `authentik Admins` group.
Authentik 2026.8.5 supplies the `groups` array through the managed `profile`
mapping and includes it in the ID token. The API gets
`STUDIO_OIDC_CLIENT_SECRET` from the identically named key in
`ai/studio-oidc-client`.

At least one API allowlist must be non-empty at startup. The API accepts a
verified ID token when its subject matches the subject allowlist or its
`groups` claim is an array of strings containing an exact group match.
Subjects on the allowlist may sign in regardless of the group claim. A verified
token that matches neither rule receives HTTP 403 `auth.subject_forbidden`.
Groups grant Studio sign-in only. Go-live approval uses its own issuer and
subject allowlist. See [Go-live approvals](go-live.md).

`GET /healthz` returns 204 independently of the database and store. `GET /readyz`
returns 204 when the session, run queue and approval tables are reachable and the last completed store
check succeeded within the freshness window. It returns 503 if there is no
completed check, the last check failed, or its success is stale. A readiness
request starts one background store check per process when there is no result
or its age exceeds half the window, and answers from the last completed result.
Both probes have empty bodies.

The API writes one JSON access log line per request with `method`, `path`,
`status`, `principal_kind`, `principal_id` and `request_id`. The path excludes
the query string, including on the OIDC callback. Principal IDs are verified
subject, agent key ID or worker ID. Anonymous requests have a null principal
ID. The API sends the same ID in `X-Request-ID` and `error.request_id`.

Under provisional coordinator ruling CR-13, `unavailable` means a method is
not buildable (HTTP 422). `service_unavailable` indicates a dependency outage
(HTTP 503), and `internal` indicates an unexpected failure (HTTP 500).

## Database privileges

Provide a dedicated migration identity that owns the Studio schema and its
objects. It needs `CONNECT` on the Studio database and schema DDL rights.
The database owner provisions both logins and database-level `CONNECT` in
story [431](https://work.haynesnetwork.com/work_packages/431). The migration Job
sets `STUDIO_RUNTIME_ROLE=studio_app` and runs one command. The schema owner
applies the schema and table privileges transactionally during Alembic upgrade.
Revision `0003_studio_run_queue` also applies the initial grants for a database
already migrated through `0002_active_agent_grants`. The declarations below use the
default names. The app uses no sequences.

```sql
-- Provisioned by the database owner in story 431.
GRANT CONNECT ON DATABASE studio TO studio_app, studio_migrator;

-- Applied by revisions 0001 and 0003 as the schema owner.
GRANT USAGE ON SCHEMA studio TO studio_app;
GRANT SELECT, INSERT ON studio.productions, studio.stories,
    studio.boards, studio.selections TO studio_app;
GRANT UPDATE (document) ON studio.productions, studio.stories TO studio_app;
GRANT UPDATE (document, tombstone) ON studio.boards TO studio_app;
GRANT UPDATE (document, revision) ON studio.selections TO studio_app;
GRANT SELECT, INSERT ON studio.media_types, studio.draft_ids, studio.assets,
    studio.asset_versions, studio.asset_sources, studio.asset_media,
    studio.deliveries, studio.delivery_media TO studio_app;
GRANT SELECT, INSERT, DELETE ON studio.login_attempts, studio.sessions,
    studio.story_asset_refs TO studio_app;
GRANT SELECT ON studio.agent_keys, studio.agent_grants, studio.worker_tokens TO studio_app;

-- Applied by revision 0003.
GRANT SELECT, UPDATE (next_position, worker_seen_at) ON studio.run_lane TO studio_app;
GRANT SELECT, INSERT ON studio.runs, studio.run_wan_attempts,
    studio.run_check_overrides TO studio_app;
GRANT UPDATE (document, revision, worker_id, fence, claim_until, retry_at,
    admission_refusals, cancel_requested, publishing) ON studio.runs TO studio_app;
GRANT UPDATE (state, outcome) ON studio.run_wan_attempts TO studio_app;

-- Applied by revision 0004.
GRANT SELECT, INSERT ON studio.go_live_approvals, studio.go_live_withdrawals TO studio_app;
```

Revision `0004_go_live_approvals` uses the PostgreSQL UTF-8 `und-x-icu`
collation to lower-case NFC names. The schema owner's trigger maintains the
name reservations. The runtime role has no direct grants on `draft_names`.
The migration prints the affected IDs for pre-existing collisions and keeps
every display name. A collided name remains reserved while any of those
records uses it.

Agent key provisioning supports the migration role and a dedicated, non-owner
`studio_key_admin` role. For a dedicated role, grant only the privileges below
after migrating to head. The command checks these privileges and refuses the
API runtime role.

```sql
GRANT CONNECT ON DATABASE studio TO studio_key_admin;
GRANT USAGE ON SCHEMA studio TO studio_key_admin;
GRANT SELECT (id) ON studio.productions TO studio_key_admin;
GRANT SELECT, INSERT (id, digest, expires_at), UPDATE (expires_at, revoked_at)
    ON studio.agent_keys TO studio_key_admin;
GRANT SELECT, INSERT (key_id, production_id, scope), UPDATE (active)
    ON studio.agent_grants TO studio_key_admin;
```

Agent keys have a canonical `key_` ID and one row per
`(key_id, production_id, scope)` grant. Migration `0002_active_agent_grants`
marks existing grants active. Run the upgraded API before replacing grants
with the CLI. Replacement disables omitted rows and enables the requested
ones in one transaction, with no DELETE privilege. Registration of a revoked
key returns `key_admin.key_revoked`.

Agent `create --out` writes the new `0600` file after the database commits.
Use `create` without `--out` only from an interactive `kubectl exec`. A pod's
main process output can be logged by Kubernetes even with a TTY. See
[agent key administration](studio-mcp.md#agent-key-administration).

### Worker token administration

Run the worker token command after migrating to head. Use the migration identity
or a dedicated non-owner role in `STUDIO_MIGRATION_DATABASE_URL`. The command
requires these grants and refuses the API runtime role. The worker process itself
uses the internal HTTP API and needs no database account.

```sql
GRANT CONNECT ON DATABASE studio TO studio_worker_token_admin;
GRANT USAGE ON SCHEMA studio TO studio_worker_token_admin;
GRANT SELECT (digest, worker_id, expires_at, revoked_at), INSERT (digest, worker_id),
    UPDATE (revoked_at) ON studio.worker_tokens TO studio_worker_token_admin;
```

Mount the External Secrets Password generator's value as a file. Use 48–121
ASCII alphanumeric characters and an optional final newline. Supply the same
generated value to the worker in `STUDIO_WORKER_TOKEN`. The worker prepends
`worker_` to the bearer it sends to `/internal/v1/work/*`, and administration
stores only the lowercase SHA-256 digest of that bearer and its worker ID.
Send the `worker_` prefix too when checking authentication directly over HTTP.
Agent keys use the agent-key table and public routes. The API and MCP accept
43-character unpadded base64url agent keys generated from 32 random bytes and
externally generated agent keys of 48–128 ASCII alphanumeric characters.

```sh
uv run --no-sync studio-api-admin worker-token register \
  --worker-id "$WORKER_ID" --token-file "$MOUNTED_TOKEN_FILE"
uv run --no-sync studio-api-admin worker-token list
uv run --no-sync studio-api-admin worker-token revoke "$WORKER_ID"
```

Use 1–63 ASCII letters, digits, dots, underscores or hyphens for the worker ID,
starting with a letter or digit. Registering the same token for the same worker
ID is idempotent. A new token for an existing ID requires `--replace`, which
revokes the old token in the same transaction. A token already associated with a
different worker ID or revoked cannot be reused. List reports worker IDs, expiry
and revocation dates, including prior rows after replacement. Revoke is idempotent
and disables all tokens for the ID. Command output and audit events contain no
token or digest.

## Browser, agent and worker requests

- `GET /auth/login` initiates the OIDC code flow. It accepts an optional
  2,048-character same-origin `return_to` path with an optional query and an
  optional `fresh=true` for OIDC reauthentication. The callback consumes one
  browser-bound attempt and verifies the issuer, signing key, audience, time,
  nonce and subject. It creates an API session with a Secure, HttpOnly,
  SameSite=Lax `__Host-studio-session` cookie and redirects to the recorded
  path, default `/`. A callback failure redirects to `/?auth_error=<code>`.
  The database holds the cookie digest. Discovery, token exchange and claim
  validation happen in the API process. Subject sessions require the subject
  to remain on the configured allowlist. Group-only sessions bind their
  cookie digest to the configured group allowlist at sign-in. The API
  checks Authentik membership again on the next sign-in, after logout or
  expiry. So a person removed from the group keeps a Studio
  session they already hold until it expires: at most `STUDIO_SESSION_SECONDS`
  (8 hours by default, 24 hours at most). To end it sooner, delete that
  person's rows from the session table by subject, or change
  `STUDIO_OIDC_ALLOWED_GROUPS`, which ends every group session. Authentik's
  binding counts membership through a parent group, while the `groups` claim
  lists direct memberships only, so a member of a child group of an allowed
  group passes Authentik and is refused here. The session table has no claims document, so group names from the
  token are discarded after the sign-in check.
- `GET /v1/me` returns the principal and, for a browser session, a CSRF token.
  Send it in `X-Studio-CSRF` for unsafe methods, including `POST /auth/logout`.
  Logout deletes the database session row. The next media request will require
  a valid session even if a previous request opened the same file.
- Agents send `Authorization: Bearer <key>`. Grants apply per production and
  per scope. An Authorization header takes precedence over a session cookie.
  Agent keys can read productions in their `read` grants and edit drafts in
  their `draft:write` grants. Keys with `runs:queue` may enqueue and cancel runs.
- The P-14 `WorkerRoute` authenticates a worker bearer token before reading
  the query or body of any `/internal/v1/work/*` route. A worker token provides
  a worker principal here. Public Studio routes accept agent keys or sessions.

Protected routes authenticate before reading metadata request bodies. Query
parameter names and values must be UTF-8 text without NUL characters.

## Records and revisions

Use the paths and shapes in the generated OpenAPI. Lists return `items` and
`next_cursor`. Pass the cursor back with the same filters. Entity revisions
are integers. A read or write response carrying a revision also returns a
quoted `ETag`. Send that value as `If-Match` on the next update. A stale
write returns HTTP 409 with `conflict.revision` and `current_revision`.

Productions start at revision 1. Enabling a media type takes the production's
revision and returns the updated production. Story creation begins with a
title and optional draft fields. Production names are unique. Story titles are
unique within a production and media type. Both comparisons trim whitespace,
apply NFC and lowercase the result. A collision returns HTTP 409 with
`production.name_duplicate` or `story.title_duplicate` and `existing_entity_id`.
A story response contains ordered board IDs.
Fetch each board by ID. Creating a board or reordering uses the story's
revision. Editing or tombstoning uses the board's revision. Changing a board
also advances the story revision. A tombstone preserves its board number,
which is never reissued.

PATCH replaces each supplied field as a whole, including arrays and nested
objects. Omit nested IDs to add lines, notes and cues. Preserve their returned
IDs on edit. Remove an item by leaving it out of the replacement array.
The server derives timing, counts and warnings on reads. A newly added board
defaults to whole-frame I2V when it has no cast. A cast and a placed speaker
default to layered S2V. Explicit methods are still validated.

Selections are a per-subject JSON object in a `values` envelope. The empty
selection has revision 0. PUT replaces the object and advances its revision.
Story lists and reads expose `latest_finished_run`, `approved` and `published`.
See [Story and run status](go-live.md#story-and-run-status).

The catalog serves visible canonical versions through `GET /v1/assets`.
Filter by kind, one or more labels, production or board. The board filter
returns versions referenced by that board. `GET /v1/assets/{id}` returns the
asset and a paginated set of its versions. Catalog metadata includes the shared
library when the caller can read a production. Media access has a separate
reference check.

Trusted server code can register canonical metadata through
`db.drafts.import_draft`, `db.catalog.record_asset_version` and
`db.catalog.record_delivery`. Import accepts the CLI's production, storyboard
exchange and matching version documents in one caller-owned transaction.
Re-import of the same source keeps the stored IDs and draft edits. The delivery
reader uses the registered story to scope access. For D42, the OpenAPI
`ExternalPhotoDeclaration` describes the agent's model, prompt, sources,
session and harness. The upload transport can register the canonical version
with the optional server-computed `received_sha256` alongside the hash of
the stored, stripped bytes. Raw upload, image validation and generation jobs
are story [430](https://work.haynesnetwork.com/work_packages/430).

## Private playback

Use the delivery's `proxy.sha256` for the phone player's source at
`/v1/media/{sha256}`. GET and HEAD support one byte range. The response carries
`Accept-Ranges: bytes`, the content type and length, and on 206 the exact
`Content-Range`. A range beyond EOF returns 416. A malformed or multiple
range falls back to the complete representation, including a bounded range
whose last byte precedes its first. If-Range may use the strong hash ETag.
Media responses use `Cache-Control: private, no-store`.
[RFC 9110 range requests](https://www.rfc-editor.org/rfc/rfc9110.html#name-range-requests)

The API opens a blob only after looking up a reference attached to a
production the caller can read. Production-scoped asset versions and delivery
records carry their own association. Shared library media needs a reference
from a current draft in an accessible production. An unknown or inaccessible
hash returns 404. The store permits only canonical content locators and opens
files without following symlinks. Legacy deliveries with only an external
ledger locator remain metadata-only in this API.

## Verification

```sh
STUDIO_THREADS=2 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 uv run --no-sync pytest
STUDIO_THREADS=2 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 uv run --no-sync pytest -m db --require-db
```

The DB suite reads `STUDIO_TEST_DATABASE_URL` for a disposable PostgreSQL 16
database. The fixture identity creates a schema and temporary roles. It
upgrades from revision `0002_active_agent_grants`, downgrades to base and
upgrades from an empty schema. API and store operations run with the executable
Alembic grants. The suite checks key administration with the dedicated role,
runtime-role refusal, and protection for ownership, snapshot and Wan attempt
identity columns. It exercises OIDC with a fake issuer, round-trips The Winter
Menu's public metadata, and builds and reads a generated proxy with fake Wan.
