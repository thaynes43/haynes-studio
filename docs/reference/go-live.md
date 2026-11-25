# Go-live approvals

A go-live approval records a verified person's decision on one finished Studio
run and one exact master under D29. The record includes the run ID, frozen
snapshot SHA-256, delivery ID, master SHA-256, the verified issuer and subject,
the signed-in display name when available, and the authentication and approval
times. Draft edits leave the run and its eligibility intact. Each run can have
one active approval. Withdrawing it appends a second record. A new approval
after withdrawal gets a new ID.

The approval is for manual release. See [release packages](release-package.md)
for preparation and recording a manual drop.
See [story 412](https://work.haynesnetwork.com/work_packages/412) for the approval
record and [decisions D29, D43, D44, D49 and D52](../proposals/0003-studio-plan.md#decisions-so-far)
for its rules.

## Identity and sign-in

Set `STUDIO_GO_LIVE_APPROVER_SUBJECTS` to a JSON array of verified OIDC subject
strings for the exact `STUDIO_OIDC_ISSUER`. It defaults to `[]` and the API
refuses every approver until a subject is configured. The approver must also be
able to sign in through the normal subject or group policy. Agent keys and
worker tokens are refused by the review and decision routes. The writes require
the session cookie and `X-Studio-CSRF`. The review needs only the session cookie.

The API records the ID token's verified `auth_time` when present and the
callback time otherwise. Provider timestamps ahead of the callback use the
configured OIDC clock leeway and are capped at the callback time. A session
migrated without that evidence requires another sign-in.
`STUDIO_GO_LIVE_FRESHNESS_SECONDS` accepts 1–3600 seconds and defaults to `900`. When
the API returns `approval.sign_in_again`, send the user to
`GET /auth/login?fresh=true&return_to=<encoded-path>`. This requests OIDC
reauthentication and records the return path on the one-use login attempt. A
failed callback redirects to `/?auth_error=<code>`.

## Read a run's review

`GET /v1/runs/{id}/go-live-approvals` uses the same production read scope and
`Cache-Control: private, no-store` as the run. Unknown and inaccessible runs
return the same 404. The response includes `run_id`, the delivered
`master_sha256` or null, newest-first `approvals` with their derived withdrawal
state, and `release_checks` previewed with the synthetic-content setting on.
The preview can be partial or null when checks fail. Signed-in readers see
approval display names and decision times. The go-live allowlist also grants
access to issuer, subject and sign-in time in approval and withdrawal records.
Fresh sign-in is checked independently for decisions.

`approve` and `withdraw` each have `allowed: true` or
`allowed: false` with the corresponding write's refusal `code`. An in-scope
reader still gets HTTP 200 and the available evidence when refused a decision.
With no active record, the review's withdrawal code is
`approval.already_withdrawn` for an otherwise eligible caller. The review reads
run, delivery and decision records in one PostgreSQL snapshot. Each write
checks current identity and eligibility again.

## Record a decision

- `POST /v1/runs/{id}/go-live-approvals` takes `master_sha256` from the
  reviewed delivery and `platform_setting: true` for the required
  synthetic-content setting. A successful request returns 201 and the
  approval with its evidence.
- `POST /v1/go-live-approvals/{id}/withdraw` returns 201 and the original
  approval with the appended withdrawal in `derived.withdrawal`.
  `derived.state` reads `active` or `withdrawn`.

| Recorded result | Evidence |
|---|---|
| `delivery` | Successful completion time, exact delivery ID and master hash, and the delivery's verification evidence. |
| `licences` | Each engine and each recorded model file, the matching register key and its terms. A pinned model file must also match its registered SHA-256. An `unknown` term appears as `unknown` and is eligible under D49. A missing row is a refusal with per-row evidence. |
| `ai_label` | The confirmed synthetic-content setting and generated description, beginning with “This video was AI-generated.” |
| `public_credits` | Video, voice and sound generator names from run provenance, with hardware when the engine recorded a public hardware label. |
| `external_inputs` | The externally generated asset-version IDs and kinds flagged privately under D42. |

The licence rows come from the [local model licence register](model-licences.md).
The API and all worker lanes read the register shipped in the installed Studio
package, independently of the working directory. `STUDIO_MODEL_REGISTER` can
override it with a local JSON path. Configure the same register on API and workers.
An unreadable override returns a service error.
The description omits script, board, check, image
and composite generators, external-photo metadata and private deployment
locations. Approval and withdrawal use the checked metadata in PostgreSQL.

| HTTP status | Refusal codes |
|---|---|
| 403 | `approval.approver_not_configured`, `approval.subject_not_permitted`, `approval.group_not_permitted`, `approval.approver_not_permitted` (agent), `approval.worker_not_permitted`, `approval.sign_in_again` |
| 409 | `approval.already_active`, `approval.already_withdrawn` |
| 422 | `approval.legacy_run`, `approval.run_unfinished`, `approval.delivery_unverified`, `approval.delivery_mismatch`, `approval.not_exact_run`, `approval.provenance_missing`, `approval.licence_missing`, `approval.ai_label_missing` |
| 503 | `approval.licence_register_unavailable` |

The API's decal override route rejects these release checks.

## Story and run status

Story lists and reads include `latest_finished_run` with the run ID, terminal
status, finish time and active approval ID if any. Its order is by completion
time. `approved` means some run of the story has an active approval, including
an older run when a newer one has finished. Individual run reads and lists
expose `active_approval_id`.

`published` is derived from the story's recorded drops and defaults to false. The
`publication=unpublished|published` and `approved=true|false` filters combine
before pagination. A manual drop can remain recorded after approval withdrawal.
