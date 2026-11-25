# Private release package

In **Productions**, open a successful Studio-built run, choose its frozen
YouTube Shorts target under **Release package**, and select **Prepare package**.
Review the licence evidence and confirm the target account privately. An active
go-live approval for the exact run and master makes an eligible package
**releasable** and permits a go-live approver to record publication. The package
then shows **Download master**, **Copy description** and **Copy checklist** for a
manual upload outside Studio. A **held** package shows why those actions are
unavailable. Withdrawal returns the package to **held**. Signed-in readers can
continue to read their private media through the existing session and media route.

After uploading, a go-live approver can use **Record publication** with the public
location and, if known, the publication time. The time must be at or after
approval and within five minutes of the database clock if it is in the future.
Studio records the signed-in actor
and the server's recording time. The location appears as text and is never
fetched. A recorded drop remains in the history after withdrawal.

## Contents and checks

- The canonical JSON pins the run, snapshot hash, format version and recipe hash,
  target, delivery, and the master hash, byte count and media type. Studio uses
  the existing authenticated media route to download the master.
- The delivery's verification and exact-master binding, model licence rows,
  provenance, disclosure and canonical-run check are shared with go-live. The
  package description starts with `This video was AI-generated.` and credits
  only the video, voice and sound generators. Hardware appears when recorded as
  public provenance. Each approval checks current eligibility and requires a
  person to confirm the synthetic-content setting. A failed check marks the
  package stale. Resolve the failure and prepare again. If the checks still pass
  with changed evidence, the approval records the current evidence and reports
  `package_evidence_older: true` in its response.
- Each licence result displays the applicable engine and file rows and their
  recorded terms, notes and source evidence. A matching row is required (including
  its hash when the register pins the file). Non-commercial, conditional and
  unknown terms appear as recorded under D49. See the
  [local model licence register](model-licences.md).
- Package preparation compares the delivered frames and frame rate directly
  with the target's frozen millisecond maximum. The final frame counts toward
  the maximum. The checklist requires the synthetic-content setting and shows
  the aspect and maximum. A configured aspect must match the master. An unset
  aspect uses the master's aspect. The AI disclosure applies to every target.

## API

| Method and path | Access | Result |
| --- | --- | --- |
| `GET /v1/runs/{id}/release-packages` | Production `read` | Frozen YouTube Shorts targets and one view per prepared target. The view prefers current evidence and otherwise displays the newest package. Agent keys see status and hashes. Approver identity fields are reserved for signed-in people. |
| `POST /v1/runs/{id}/release-packages` | Production `runs:queue` | Send `{target_id}`. Returns the hash and size with 201 for new package bytes or 200 for identical bytes. Add `package_sha256` to rebuild a specific existing copy. |
| `GET /v1/runs/{id}/release-packages/{digest}/download` | Production `read` | Verified JSON attachment for a specific package hash, including earlier versions. |
| `POST /v1/runs/{id}/publications` | Go-live approver with fresh sign-in and CSRF | Send `Idempotency-Key` and `{package_sha256, location, published_at?}`. `published_at` accepts an ISO date and time with an offset. Returns 201 for a new drop and 200 for a replay with the same run, actor, key and body, including after withdrawal. |
| `GET /v1/media/{sha256}` | Production `read` | Verified delivery master through the existing authenticated, ranged media route. |

Out-of-scope package requests return 404. The
[go-live approvals reference](go-live.md) lists shared refusal codes.

| HTTP | Code | Meaning |
| --- | --- | --- |
| 422 | `release.format_missing`, `release.target_unknown` | Choose a YouTube Shorts target from the run's frozen recipe. |
| 422 | `release.maximum_unset` | The target must declare a platform maximum in the frozen recipe. |
| 422 | `release.over_length`, `release.aspect_mismatch` | The delivered master exceeds the maximum or differs from the declared aspect. |
| 422 | `release.location_invalid`, `release.publication_before_approval`, `release.publication_in_future` | Enter a single public location without credentials and a publication time within the approval and clock bounds if known. |
| 422 | `idempotency.mismatch` | The key already recorded a different publication body for this run and actor. |
| 409 | `release.approval_required` | An active approval must match the exact run, snapshot, delivery and master. |
| 409 | `release.already_published` | This run and target already have an immutable drop record. |
| 503 | `release.store_unavailable` | The download copy is missing or the store could not complete the request. |
| 503 | `release.package_changed` | The download copy has a different length or hash. |
| 503 | `release.package_record_changed` | The database package failed its integrity check and cannot serve as approval evidence. |

PostgreSQL holds the exact canonical JSON bytes, SHA-256 and byte count in one insert-only
row. Approval and listing verify that row and work independently of the download
copy. The response derives state and publication outside the hashed record.
Changed evidence produces a new package hash, with earlier versions retained.
Approve, withdraw, prepare and record all serialize on the run row.

Migration `0012_release_constraints` checks the stored byte count against the
canonical document and enforces one publication per run and target across all
package versions. It backfills each publication's target from the package it
names and requires the run and target to match that package. If duplicate
publications already exist for a run and target, the migration aborts and
preserves the publication history.

The private store holds a download copy at the content-addressed path. A missing
copy returns `503 release.store_unavailable`. Repeat preparation with identical
evidence or specify the package hash to rebuild the copy from the database
using create-only publication at the same path. A different copy returns
`503 release.package_changed` and requires
operator review of the occupied path. If a blob write succeeds before a database
failure, preparation can reuse those same bytes on retry.

Story `published` and approval `publication_ids` come from the appended drop.
The **legacy publication column cleanup** is a follow-up after the rollback
window for installed build `393fe1d`. That build reads `stories.published` for
story status and list filters and relies on its insert default. Migration 0009
retains the column for those readers.

Fixture runs cover preparation, permissions, withdrawal and publication. The
installed app has two imported legacy runs, which are ineligible under D52.
The first real package awaits the first finished run built by the new engine.
