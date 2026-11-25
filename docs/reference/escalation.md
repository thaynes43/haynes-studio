# Studio escalation

[Story 445](https://work.haynesnetwork.com/work_packages/445) implements the
`studio.escalation/v1` contract, the HTTP lifecycle and a disposable test
transport. [Story 454](https://work.haynesnetwork.com/work_packages/454) owns
the shepherd's workflow. [Story 446](https://work.haynesnetwork.com/work_packages/446)
owns the authorized responder drill.

## Run evidence and the package

The fenced worker reports each completed technical evaluation to
`POST /internal/v1/work/escalation-check-failure`. It sends the run ID and claim
fence, a stable positive attempt ordinal for this run, check and board, the
run's technical error code, the frozen board ID or null for a run-wide check,
and the exact run-check result. Supply the failing artifact SHA-256 in
`result.artifact` and the recorded check input key in `result.key`. The latter
is the `sha256:` cache key committing to the check's inputs, version and
thresholds. Reuse the attempt ordinal on a request retry. The producer has a
bounded evaluation and retry budget and uses a new ordinal for each distinct
evaluation.

An accepted observation is a create-only run record. The digest covers its
canonical run ID, attempt, board ID, error code and complete check result. A package
requires two independent failed observations for the same check ID, board
ID, input key and artifact hash in one run. The technical error families
are `build.check_failed`, `mix.check_failed` and `layered.decal_weak` with
their corresponding check IDs. Admission refusals, a busy lane, held or
cancelled claims, retries of the same evaluation and overridden results
contribute no additional failure. A human decal override on the same run and
artifact suppresses further observations, authorization and request of the package. A request
already made can still file its callback while the package is current.

The deduplication ID is SHA-256 of the canonical JSON array
`["studio.escalation/v1", run_id, check_id, board_id, input_sha256, artifact_sha256]`.
The database uses it as the package ID. Once a package exists, later
observations of that failure add no package or observation row. The package
holds references to two recorded results, each with its own SHA-256, and
the immutable run's snapshot SHA-256. Its [schema](../../src/haynes_studio/schemas/studio.escalation.v1.schema.json)
allows typed IDs, hashes and closed vocabulary. API operation names and
parameters identify private evidence and artifacts. Studio's normal production
authorization applies to the evidence and media routes. The media operation
returns bytes only for a hash already covered by its private catalog. The
check evidence is independently available through its run record.

Studio stores the immutable bytes as UTF-8 JSON with sorted keys and no
insignificant whitespace. SHA-256 covers those exact bytes. The HTTP envelope
returns the object as `package`, its digest as `sha256`, and the lifecycle
beside it. The package expires 24 hours after proposal.

### Example package

This example uses synthetic IDs and digests. Formatting is expanded for
reading.

```json
{
  "schema": "studio.escalation/v1",
  "deduplication_id": "871b4e6fc6fb63b4f038ecd688039a820da66b4ce3f3891d89090cf1d330764a",
  "production_id": "prd_000000000A0000000000000001",
  "story_id": "sty_000000000A0000000000000002",
  "run_id": "run_000000000A0000000000000000",
  "snapshot_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "board_ids": [
    "brd_000000000A0000000000000003"
  ],
  "failure": {
    "check": "layered.decal_gate",
    "input_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "results": [
      {
        "operation": "get_escalation_check",
        "record_sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
      },
      {
        "operation": "get_escalation_check",
        "record_sha256": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
      }
    ]
  },
  "artifacts": [
    {
      "operation": "get_media",
      "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
  ],
  "allowed_actions": [
    "get_escalation_check",
    "get_media",
    "studio_get_story_summary",
    "studio_get_board",
    "studio_patch_board",
    "studio_queue_run"
  ],
  "patch_fields": [
    "layout",
    "seeds",
    "timing",
    "title"
  ],
  "forbidden_actions": [
    "go_live",
    "promotion",
    "deletion",
    "other_story",
    "other_production",
    "check_override",
    "cancel_run"
  ],
  "usage_cap": {
    "seconds": 900,
    "queued_runs": 1
  },
  "expires_at": "2026-11-26T00:00:00.000000Z",
  "responder_key": {
    "id": "key_0000000000GWDMWVY6ZDHV9W1R",
    "production_id": "prd_000000000A0000000000000001",
    "scopes": [
      "read",
      "draft:write",
      "runs:queue"
    ]
  },
  "callback": {
    "method": "POST",
    "operation": "report_escalation",
    "idempotency_header": "Idempotency-Key",
    "outcomes": [
      "done",
      "failed",
      "escalate"
    ]
  }
}
```

## Operator and responder operations

Here `P` is `/v1/productions/{production_id}/escalations` and `E` is
`P/{deduplication_id}`.

| HTTP operation | Identity and effect |
|---|---|
| `GET P`, `GET E` | Production `read`. Returns the package, digest, latest state, expiry flag and append-only events. The list accepts `limit` (1–20, default 10) and `cursor` from `next_cursor`. |
| `GET /v1/runs/{run_id}/escalation-checks/{record_sha256}` | Production `read`. Returns the recorded evaluation, time, worker and its digest. The responder can read only the two package references. |
| `POST E/authorize` | Signed-in person with CSRF. Authorizes a current proposal. An optional body `{"acknowledge_board_ids":[...]}` records a person's request to change that named board under CR-23. |
| `POST E/decline` | Signed-in person with CSRF. Closes a proposal. |
| `POST E/cancel` | Signed-in person with CSRF. Closes a proposed, authorized or requested package, including an expired one. |
| `POST E/callback` | Exact package responder bearer key. Accepts one report after request and before package expiry. |

A transport hands off an authorized package using its canonical bytes, SHA-256
and deduplication ID. It records the returned unique external request ID in
the `requested` event. Only the in-process test transport exercises this
transition in story 445. The running API has no dispatcher. Person and
automatic authorization only append a decision.

The callback takes `Idempotency-Key` and JSON with `outcome` (`done`, `failed`
or `escalate`), a short `summary`, `usage`, `changed_board_ids` and optional
`queued_run_ids`. Use an empty list for a set of identifiers with no changes.
`usage` is the literal `"unknown"` or an object with `elapsed_seconds` and
optional `input_tokens`, `output_tokens` and `cost_usd`. Null optional
measurements represent unknown values. Zero stays zero. The callback records
actual measured use, including an overrun. A replay of the same key and
normalized body returns the original recorded state while the package remains
current. A different key or body conflicts. Expiry and cancellation refuse
callbacks. Reporting records the result independently of Studio drafts or
run state.

## Authorization and budgets

`STUDIO_ESCALATION_AUTHORIZATION=person` is the default and the fallback for
an unrecognized value. `automatic` implements provisional CR-30. Each UTC
calendar day it authorizes up to
`STUDIO_ESCALATION_PER_PRODUCTION_PER_DAY` (default 1) for a production and
`STUDIO_ESCALATION_TOTAL_PER_DAY` (default 2) for Studio. Counts include every
authorization that day, even after cancellation. Both counts and the
authorization row are serialized under the same PostgreSQL transaction
lock. A package over either cap keeps its proposal and records the reason
and observed counts. A signed-in person can make the explicit decision on
it. Each authorization records its principal, the counts before the decision
and the configured limits. Enable automatic mode by configuration after the
drill passes.

A responder receives the existing `read`, `draft:write` and `runs:queue` scopes
on the named production only. Run-wide evidence with no board receives
`read` alone and a zero run budget. The package reserves an epoch-zero
`key_` ULID for its expected public identity, using the first 80 bits of the
deduplication digest as the ULID randomness, and states its exact expiry.
That identifier contains no key material. The API verifies the
registered identity, production, exact scopes and expiry. The existing
key-admin CLI assigns ordinary IDs. Provisioning the reserved identity through
a sanctioned path remains a prerequisite for story 446.

Through the existing MCP operations, a board-scoped responder can read the
named story summary and board, patch `layout`, `seeds`, `timing` or `title` on
that board and queue one run from the current revision of that story. The
normal draft revision and queue idempotency controls apply. Other boards,
other stories and productions, deletion, promotion, go-live, asset and
format writes, run cancellation and check overrides are prohibited. A
person-edited board still needs a fresh revision and responder-specific read
token under [CR-23](agent-drafting.md#re-drafts-and-receipts). The authorization
event must explicitly name the board for that acknowledgment. Automatic
authorization carries no such acknowledgment.

The execution window is up to 15 minutes from request, bounded by package
expiry. Studio serializes responder writes with cancellation, terminal
callback and the one-run limit. The external session needs the same time
and queue limits. A callback can still record a result after the
execution window ends and before the package expires.

## Database

Revision `0007_escalation_packages` follows `0006_format_recipes`. Alembic
grants the Studio runtime role `SELECT, INSERT` on
`escalation_check_failures`, `escalation_packages` and `escalation_events`.
The check and package documents live as canonical bytes. Each event has a
package ID, sequence, state, database time, principal and detail. Runtime
has no `UPDATE`, `DELETE` or `TRUNCATE` on these tables. Availability uses
the database source clock, and expiry is returned as a time-derived flag.

## dev-env v2 interface

**held: awaiting the dev-env coordinator's confirmation**

The work order identifies the sanctioned interface as a summoned session
under a CallerPolicy (dev-env DESIGN-064 section 5.6). A public copy of that
section was unavailable. The interface here is limited to the work order's
description. The immutable package becomes the caller-supplied contract.
The session acts within that contract and its usage limits. Its one
`done`, `failed` or `escalate` report maps to Studio's callback. D12 calls for dev-env to select provider and model
by capacity. Confirmation of the real interface is held for story 446.

Before story 446, the dev-env coordinator must confirm each of these items.

1. Which sanctioned request endpoint and version take the contract and
   deduplication ID, and how can Studio reconcile a lost reply to the
   request? How does cancellation interact with pending admission?
2. Which pre-authorized Studio caller identity and CallerPolicy are bound
   to that endpoint? How is the exact reserved Studio responder identity
   provisioned for the single drill and delivered to the session?
3. What network path permits Studio's namespace to reach the endpoint and
   the responder to reach scoped Studio MCP and the callback?
4. Which time, quota, and cost measurements does the session report,
   in what units, and when is an explicit unknown value returned?
5. What launch cap and per-session limits does dev-env enforce for the one
   drill, and how are their thresholds coordinated with Studio's cap?

The real transport remains held pending those answers. The fixture proves
package formation, lifecycle and authorization against disposable PostgreSQL.
Installation and usable responder execution require separate evidence.
