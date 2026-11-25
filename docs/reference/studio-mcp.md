# Studio MCP

`studio-mcp` serves the v1 draft, media job and run tools over stateless MCP Streamable HTTP at
`/mcp`. Each request presents the caller's agent key in
`Authorization: Bearer <key>`. The server checks the key with `GET /v1/me` and
forwards the authorization value unchanged to the matching
[Studio API](studio-api.md) operation. The API checks production and scope on
each operation. The MCP process needs only the API origin and its HTTP listener
configuration.

```sh
uv sync --locked
STUDIO_API_URL=http://127.0.0.1:8000 uv run --no-sync studio-mcp
```

The listener defaults to `127.0.0.1:8001`. For a private ingress, set
`--host` and use repeatable `--allowed-host` values for the Host header that
reaches MCP, including any port. Native clients can omit Origin. Set repeatable
`--allowed-origin` values to permit specific browser origins. Use TLS for the
agent transport outside loopback. The upstream `STUDIO_API_URL` must be a fixed
HTTPS origin, except that HTTP is allowed for loopback or Kubernetes Service DNS
(`service.namespace.svc.cluster.local`, with an optional trailing dot). Set
`STUDIO_API_CA_FILE` to a mounted PEM CA bundle when verifying an API certificate
issued by a private CA. The upstream client ignores proxy and trust environment
variables and disables redirects.

## Tools and revisions

Discover v1 input schemas with `tools/list`. The MCP server identifies itself
as `studio-mcp` version `1.0.0`.

| Tool | Key scope | Result |
|---|---|---|
| `studio_list_productions`, `studio_get_production` | `read` | Production ID, revision, name and enabled media types. Detail includes labels. |
| `studio_list_stories` | `read` | Story summaries for the named production and media kind. Accepts the API's publication and approval filters. |
| `studio_get_story_summary` | `read` | Story ID and revision, board count, timing totals and a page of ordered board IDs. Optional `fields` selects editable story fields. |
| `studio_get_story_timing` | `read` | Story revision, frame totals, warnings, build blocker count and a page of board timings. |
| `studio_create_story`, `studio_patch_story` | `draft:write` | Story summary and revision. Create takes `fields` with a title, and patch takes `patch` and the current story revision. |
| `studio_get_board` | `read` | Board ID, story ID, revision, timing metadata and editable fields. Optional `fields` narrows the selection. |
| `studio_add_board` | `draft:write` | Board summary and resulting story revision. Takes the current story revision and a `fields` object. Use `{}` for defaults. |
| `studio_patch_board` | `draft:write` | Board summary and resulting board revision. Takes the current board revision and a `patch` object. |
| `studio_reorder_boards` | `draft:write` | Story summary and resulting revision. Takes the current story revision and every active board ID in the desired order. |
| `studio_remove_board` | `draft:write` | Board ID, resulting revision and `tombstone: true`. Takes the current board revision. |
| `studio_search_assets`, `studio_get_asset` | `read` | Visible asset version summaries with their immutable version numbers. Asset detail includes the asset revision. |
| `studio_generate_voice`, `studio_generate_photo` | `assets:generate` | Compact job status for a saved board. Photo accepts an optional seed. |
| `studio_upload_photo` | `assets:upload` | Upload result with the version ID, selection flag and resulting board revision. Takes `board_id`, `revision`, `media_type`, `data_base64` and `provenance`. |
| `studio_get_job` | `read` | Compact voice or photo job status, input signature and result version ID. |
| `studio_estimate_run`, `studio_list_runs`, `studio_get_run` | `read` | Story estimate and blockers, a page of runs, or run status with progress, stages and checks. |
| `studio_queue_run`, `studio_cancel_run` | `runs:queue` | Run status and revision. Queue takes the current story revision. Cancel takes the current run revision. |
| `studio_get_delivery` | `read` | Immutable delivery metadata including hashes, sizes and frame counts. |

Patch replaces each supplied field. For `lines`, `cues` or `notes`, keep
unchanged entries and their IDs in a replacement array. Omit an ID when adding
an entry and leave an entry out to remove it. Re-read the board for IDs assigned
on write. Pin asset version IDs returned from the catalog in the corresponding
story or board fields. The API resolves the pins and their scopes on write.

Each board mutation advances its story's revision in the same API transaction.
After patch or remove, re-read the story before a story-level edit. MCP sends
revision arguments as quoted HTTP `If-Match` values. A stale write returns
`isError: true` with
`structuredContent.error = { code, status, http_status, request_id, path, message, current_revision }`.
Use `current_revision` with a fresh read to reconcile edits before trying
again. Other API errors preserve the envelope's status and detail fields up to
64 KiB. Invalid tool input reports `violations` with a JSON Pointer `path` and
validation `rule` for each failing field. Authentication and API
failures during the protocol request's key check return HTTP errors before tool
dispatch. `service_unavailable` is 503, `internal` is 500, and `unavailable` at
422 is a method capability error.

Lists and ordered board/timing pages default to 10 items with a maximum of 20.
Pass back `next_cursor` as `cursor` with the same filters until it is null.
Ordered board and timing cursors include the story revision and the last board
ID. When a story changes between pages, restart the read from the first page
after the revision conflict. Responses carry one compact JSON object in
`structuredContent` and in a text block for older clients. The tools cap
metadata arguments at 64 KiB and the encoded result object at 128 KiB.
The upload's base64 field represents at most 20 MiB of decoded image bytes.
The MCP HTTP request cap is the maximum base64 length plus 256 KiB for the
JSON-RPC envelope and metadata. Upstream JSON responses are capped at 8 MiB.
Query a smaller page or request fewer fields if a read reaches a limit.

Supply `idempotency_key` on the generation and run queue tools. Retry with
the same key and arguments to recover the existing job or run after a lost
reply. The API returns `idempotency.mismatch` if the request under that key
changes. Uploads forward the decoded bytes and strict D42 declaration to
the [API upload](studio-api.md#d42-photo-upload).

People use the API for playback, previews, library candidate generation and
promotion. The [transport map](studio-operation-parity.md) gives the planned
and implemented HTTP and MCP operations for the web flows. Usage is part of
run provenance.

## Agent key administration

Run `studio-api-admin` after migrating to head. Set
`STUDIO_MIGRATION_DATABASE_URL` to the DSN of the migration role or the
dedicated key-admin role specified in [Database privileges](studio-api.md#database-privileges).
Set `STUDIO_DATABASE_SCHEMA` to the provisioned schema (default `studio`).

For deployment, mount the External Secrets Password generator's value as a file
and use `register`. Configure the generator for 48–128 ASCII alphanumeric
characters (`A–Z`, `a–z`, `0–9`). The file holds the token with an optional
final newline. The CLI also accepts a file from `create --out`, which generates
a 43-character unpadded base64url key.

```sh
uv run --no-sync studio-api-admin register --key-file "$MOUNTED_KEY_FILE" \
  --production "$PRODUCTION_ID" --scope read --scope draft:write
uv run --no-sync studio-api-admin create --out "$NEW_KEY_FILE" \
  --production "$PRODUCTION_ID" --scope read --expires-at "$ISO8601_EXPIRY"
uv run --no-sync studio-api-admin list
uv run --no-sync studio-api-admin revoke "$KEY_ID"
```

Repeat flags to grant the specified scopes to each production ID. The
agent scopes are `read`, `draft:write`, `assets:generate`, `assets:upload`
and `runs:queue`. Go-live approval is reserved for people. Expiry is optional
and must include a timezone when supplied. Registering the same key with
the same productions, scopes and expiry returns its existing key ID.
Changed grants or expiry require `--replace-grants`, which replaces the full
set. Registration of a revoked key returns `key_admin.key_revoked`. The database
stores only the SHA-256 digest.

Register and `create --out` print the key ID. Create requires a new output
path and opens it exclusively with mode `0600` after the database commits.
Use `create` without `--out` only from an interactive `kubectl exec`. A pod's
main process output can be logged by Kubernetes even with a TTY. The command
refuses before connecting when stdout is redirected. List returns IDs, grants,
expiry and revocation dates.
Revoke is idempotent. Each command writes a secret-free JSON access log event
to stderr with the action, status and available database role and key ID.

## SDK example

Use a production-scoped agent key that grants `read` and `draft:write`. The
example reads a board's current revision and uses it to patch the title.

```python
import asyncio
import os

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    headers = {"Authorization": "Bearer " + os.environ["STUDIO_AGENT_KEY"]}
    async with httpx.AsyncClient(headers=headers) as http:
        async with streamable_http_client(os.environ["STUDIO_MCP_URL"], http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                board_id = os.environ["STUDIO_BOARD_ID"]
                read_result = await session.call_tool("studio_get_board", {"board_id": board_id, "fields": ["title"]})
                if read_result.isError:
                    raise RuntimeError(read_result.structuredContent["error"])
                write_result = await session.call_tool("studio_patch_board", {
                    "board_id": board_id,
                    "revision": read_result.structuredContent["revision"],
                    "patch": {"title": "Reaction"},
                })
                if write_result.isError:
                    raise RuntimeError(write_result.structuredContent["error"])


asyncio.run(main())
```

## Verification

```sh
STUDIO_THREADS=2 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 uv run --no-sync pytest tests/mcp
STUDIO_THREADS=2 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 uv run --no-sync pytest -m db --require-db tests/db/test_studio_mcp.py
```

The DB test uses the SDK's client over the HTTP transport and an in-process
Studio API connected to [disposable PostgreSQL 16](../process/testing.md#disposable-postgres-db).
It discovers tools, provisions synthetic keys with the test migration owner,
patches a board, verifies both revisions and exercises the scope boundary.
