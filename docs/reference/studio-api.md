# Studio API

The API stores canonical production, media type, story, board and asset records in
PostgreSQL 16. It serves private media from the D39 content-addressed store. Any
API replica can read a draft or continue a browser session created by another
replica. Story [409](https://work.haynesnetwork.com/work_packages/409) covers
source and test evidence. Installation and live verification are separate.

## Commands

```sh
uv sync --locked
uv run --no-sync studio-api openapi > studio-api.openapi.json
uv run --no-sync studio-api-migrate upgrade head
uv run --no-sync studio-api serve --host 0.0.0.0 --port 8000
```

The OpenAPI command works without runtime configuration. Generate the web client
from its OpenAPI 3.1 output. Stable operation IDs follow section 12 of the
[Studio contracts](../contracts/studio-contracts-v1.md). The document links the
package's canonical schemas and also describes the partial write bodies.

Run `studio-api-migrate upgrade head` as a one-shot Job with the migration
identity before starting the API. The image must contain the installed Python
package and its Alembic scripts. The initial migration is transactional, and
concurrent Jobs serialize on a Postgres advisory lock. On an empty disposable
database, test reversal with `studio-api-migrate downgrade base`. That command
drops the API tables and their contents. Use a forward migration for production
recovery, or recover metadata to an isolated database for inspection.

## Environment

| Variable | Value |
|---|---|
| `STUDIO_DATABASE_URL` | Runtime libpq URL or connection string supplied by the app's secret. |
| `STUDIO_MIGRATION_DATABASE_URL` | Migration identity's equivalent, mounted only in the migration Job. |
| `STUDIO_DATABASE_SCHEMA` | Precreated schema, default `studio`. Both commands must agree. |
| `STUDIO_STORE_ROOT` | Root of the shared D39 store. Mount the same directory at every replica. |
| `STUDIO_PUBLIC_ORIGIN` | Browser HTTPS origin, without a trailing slash or path. The UI and API share it. |
| `STUDIO_OIDC_ISSUER` | Exact HTTPS issuer from Authentik discovery, including any final slash. |
| `STUDIO_OIDC_CLIENT_ID` | Client ID of the confidential OIDC application. |
| `STUDIO_OIDC_CLIENT_SECRET` | Secret supplied to the API process. |
| `STUDIO_OIDC_ALLOWED_SUBJECTS` | JSON array of allowed OIDC `sub` values scoped to the configured issuer. |
| `STUDIO_SESSION_SECONDS` | Absolute lifetime of an API session, 60–86400 seconds. Default 28800. |

Use TLS for browser requests. Configure Authentik with
`STUDIO_PUBLIC_ORIGIN + /auth/callback`, `client_secret_basic`, PKCE S256 and
an RS256 signing key. The discovery document must identify the configured
issuer and advertise HTTPS authorization, token and key endpoints. Route
`/auth/*` and `/v1/*` to the API and the remaining UI paths to the static app.
Access logging excludes the OIDC callback query string. [OIDC Core](https://openid.net/specs/openid-connect-core-1_0.html)
[RFC 7636](https://www.rfc-editor.org/rfc/rfc7636)

`GET /healthz` returns 204. `GET /readyz` checks the metadata database and
store root, then returns 204 or 503. Both probes have empty bodies.

## Database privileges

Provide a dedicated migration identity that owns the Studio schema and its
objects. It needs `CONNECT` on the Studio database and schema DDL rights.
Grant the runtime identity `CONNECT` on the database, `USAGE` on the schema
and the grants below. Substitute the configured schema and the runtime role.
The app uses no sequences.

```sql
GRANT SELECT, INSERT, UPDATE ON studio.productions, studio.stories,
    studio.boards, studio.selections TO studio_app;
GRANT SELECT, INSERT ON studio.media_types, studio.draft_ids, studio.assets,
    studio.asset_versions, studio.asset_sources, studio.asset_media,
    studio.deliveries, studio.delivery_media TO studio_app;
GRANT SELECT, INSERT, DELETE ON studio.login_attempts, studio.sessions,
    studio.story_asset_refs TO studio_app;
GRANT SELECT ON studio.agent_keys, studio.agent_grants, studio.worker_tokens TO studio_app;
```

Credential provisioning uses a separate owner-managed identity. Agent keys
have a canonical `key_` ID and grants represented by
`(key_id, production_id, scope)` rows. Worker credentials have a
`worker_id`. Both store a lowercase SHA-256 digest of a unique, random
base64url bearer secret with at least 32 random bytes. Use `revoked_at` or
`expires_at` to disable a credential. Runtime grants do not include DDL,
schema ownership or credential-table writes. Workers call the internal API
through the story 410 transport and need no database account.

## Browser, agent and worker requests

- `GET /auth/login` initiates the OIDC code flow. The callback consumes one
  browser-bound attempt and verifies the issuer, signing key, audience, time,
  nonce and subject. It creates an API session with a Secure, HttpOnly,
  SameSite=Lax `__Host-studio-session` cookie and redirects to `/`.
  The database holds the cookie digest. Discovery, token exchange and claim
  validation happen in the API process.
- `GET /v1/me` returns the principal and, for a browser session, a CSRF token.
  Send it in `X-Studio-CSRF` for unsafe methods, including `POST /auth/logout`.
  Logout deletes the database session row. The next media request will require
  a valid session even if a previous request opened the same file.
- Agents send `Authorization: Bearer <key>`. Grants apply per production and
  per scope. An Authorization header takes precedence over a session cookie.
  Agent keys can read productions in their `read` grants and edit drafts in
  their `draft:write` grants.
- The P-14 `worker_access` dependency is for internal routes. Worker tokens
  provide a worker principal and cannot act as a browser or agent.

## Records and revisions

Use the paths and shapes in the generated OpenAPI. Lists return `items` and
`next_cursor`. Pass the cursor back with the same filters. Entity revisions
are integers. A read or write response carrying a revision also returns a
quoted `ETag`. Send that value as `If-Match` on the next update. A stale
write returns HTTP 409 with `conflict.revision` and `current_revision`.

Productions start at revision 1. Enabling a media type takes the production's
revision and returns the updated production. Story creation begins with a
title and optional draft fields. A story response contains ordered board IDs.
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
For the initial API, all draft stories are unpublished and unapproved.

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
range falls back to the complete representation. If-Range may use the strong
hash ETag. Media responses use `Cache-Control: private, no-store`.
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
database. It upgrades, reverses and reapplies the migration in the fixture
schema, exercises OIDC using a fake issuer and random signing key, round-trips
The Winter Menu's public metadata, and tests playback using a generated proxy.
