# Studio run queue

A run freezes one draft revision and its ordered boards, resolved asset versions,
and eligible motion alternatives. The API writes the canonical
`studio.run-snapshot/v1` JSON to the private production store and records its
SHA-256, its frozen library and a FIFO position in PostgreSQL. The worker uses
these records for the build. Draft and library edits after enqueue affect only
later runs. The build re-hashes referenced bytes before it asks Wan for a clip.

## Public HTTP

| Method and path | Behavior |
| --- | --- |
| `GET /v1/stories/{id}/estimate` | With `read`, see potential preflight problems, a cold-cache range and the current queue wait. |
| `POST /v1/stories/{id}/runs` | With `runs:queue`, send `If-Match` with the draft revision and a visible-ASCII `Idempotency-Key` of 1–255 characters. The response is 201 and carries the run location and its ETag. |
| `GET /v1/stories/{id}/runs` | With `read`, list runs in enqueue order. Pass the last page's `next_cursor` with the same story. |
| `GET /v1/runs/{id}` | With `read`, see progress, completed stages, checks, Wan attempt IDs and check overrides. The ETag is the run's own revision. |
| `POST /v1/runs/{id}/cancel` | With `runs:queue`, send the run ETag as `If-Match`. The response shows the new state or a pending `cancel_requested` flag. |
| `POST /v1/runs/{id}/checks/{check}/overrides` | A signed-in person sends the run ETag and `{"artifact": "<sha256>", "reason": "..."}`. The only supported check is a failed `layered.decal_gate`. |
| `GET /v1/runs/{id}/delivery` | With `read`, fetch a finished delivery. Stream its proxy through the authenticated [media route](studio-api.md#private-playback). |

A repeated enqueue with the same story, actor, key and revision returns 200 and
the same run ID, including after a draft edit. Reusing that key with a different
revision returns 422 `idempotency.mismatch`. A new key with a stale draft or run
ETag returns 409 `conflict.revision`. Preflight reports unavailable methods as
422. Draft CRUD and enqueue stay available during worker outages. Build preflight
checks pending voice and photo jobs and requires current whole-frame I2V
photos. The [media workers](media-jobs.md) claim the voice and image lanes
independently.

The estimate reports GPU and CPU wall-time ranges in seconds. Method rows name
the method, the number of I2V jobs or S2V chunks and that method's GPU range.
Layered I2V reuses pinned motion loops, so it estimates zero GPU jobs. The
baseline comes from The Winter Menu's E0 clips and layered CPU measurements.
These cold-cache estimates carry uncertainty from outside lease occupancy,
thermal delays, reuse and retries. Waiting time sums ahead-of-run
Studio work in this serial lane. An active run may be nearly done. A held or
unavailable queue can give a null wait range. The API shows `gpu_unavailable`
when no worker has checked in or renewed a claim within 90 seconds. Every estimate has
`uncertain: true` and a basis.

Cancellation clears any admission cooldown. If Wan may have received a job,
the worker checks its recorded ID. It drains an active job under the existing
lease and settles a refused or terminal job immediately. If Wan returns
`404 job_not_found` for a `sent` ID, the worker holds the run and records the
first absence. A second clean absence must be at least one claim lease plus the
Wan PUT timeout later (90 + 20 seconds) before cancellation releases the FIFO
lane. Inconclusive or active status reads restart the absence check. The original
claim can cancel immediately when it catches cancellation before its first PUT.
A PUT whose final fence check passed before cancellation can still reach Wan
afterward. Wan controls admission and deduplicates that ID. The fenced delivery
publication step is the cancellation cutoff. Terminal canonical documents are immutable.
A check override is a separate immutable record with a person, reason and
timestamp. The release checks are outside the override route's scope.

## Worker configuration

Run `studio-worker` or `python -m haynes_studio.queue.worker`. Each process uses
one claim at a time and the serial build pipeline. Use `--once` to process at
most one claim.

| Environment | Value |
| --- | --- |
| `STUDIO_API_URL` | Internal origin of studio-api. Keep `/internal/v1/work/*` reachable by workers. |
| `STUDIO_WORKER_TOKEN` | The same generated secret registered from a file in [worker token administration](studio-api.md#worker-token-administration). Use distinct IDs and secrets for separate workers. |
| `STUDIO_WAN_URL` | Internal origin of the [Wan product API](wan-product-api.md). |
| `STUDIO_WAN_STORY_URL` | Full OpenProject work package URL recorded in Wan's job ledger. |
| `STUDIO_STORE_ROOT` | The canonical Studio store. Mount read-only on the worker. |
| `STUDIO_BUILD_STAGE_ROOT` | A separate, shared private directory. API and workers see the same per-run staging files. The worker needs write access here. |
| `STUDIO_BUILD_REVISION` | Match the API's `git:<commit>` so the worker serves the snapshot's build revision. |
| `STUDIO_BUILD_IMAGE_DIGEST` | Optional immutable image digest recorded in run provenance. |
| `STUDIO_MODEL_REGISTER` | Path to the image's pinned [model licence register](model-licences.json). |
| `STUDIO_ASR_HOST`, `STUDIO_ASR_PORT` | Host and port of the configured Wyoming ASR service. The default port is 10300. |
| `STUDIO_THREADS` | Set to 2. The worker uses one orchestrator and the existing two-thread media settings. |

The worker writes intermediate artifacts, cache entries and the candidate
delivery create-only in the staging directory. A replacement worker can use the
same staged artifacts. The API verifies and publishes only the delivery stage
and its blobs into the canonical store, then records the delivery, playback
index and run success in one transaction. After an interrupted transaction or
lost completion reply, a replacement verifies the same create-only files.
A definite verification refusal fails the run and releases the head.
Staging is retained for inspection.

## Claims and reconciliation

PostgreSQL chooses one global FIFO head. Enqueue order is assigned inside the
acceptance transaction. A singleton lane and `FOR UPDATE SKIP LOCKED` serialize
claims without letting a later run pass a locked, held or occupied head.
Worker requests carry a per-run increasing fence and the service principal
that claimed it. Claims expire after 90 seconds on the database clock. Workers
heartbeat after 15 seconds during blocking work and at side-effect boundaries.
An expired claim can reconcile, but only its replacement can mutate the run.
Both the API and worker can restart without moving the head or erasing attempts.

```mermaid
stateDiagram-v2
    [*] --> queued: commit frozen snapshot and FIFO position
    queued --> running: worker claims
    queued --> cancelled: cancel before sending a job
    running --> queued: dependency unavailable or admission refused
    running --> held: reconcile a pending Wan attempt or an expired claim
    held --> running: new fence and reconciled Wan state
    held --> queued: known lease or service wait
    held --> cancelled: cancel after settling any sent job
    held --> failed: settled job or preflight failed
    running --> cancelled: cancel after settling any sent job
    running --> failed: toolchain changed, Wan rejected or build failed
    running --> succeeded: API publishes and records verified delivery
    cancelled --> [*]
    failed --> [*]
    succeeded --> [*]
```

The internal routes are POSTs under `/internal/v1/work`. All authenticate the
worker before reading a request body or query. The worker begins with
`/claim` (204 if there is no claimable head), renews with `/heartbeat` and
uses `/resume` only after checking a held claim. `/attempts` reserves a job
and `/attempts/{job_id}` records the fenced send marker or a proven outcome. `/publish`
fences publication. `/complete` verifies and registers the resulting delivery,
and `/fail` records failure, cancellation, a hold or a wait. Losing a lease
or a fence causes subsequent mutating operations to return 409.

```mermaid
flowchart TD
    A[Claim the FIFO head] --> B{Pending Wan attempt?}
    B -- No --> C[Check snapshot revision and Wan readiness]
    C --> R[Reserve ID and stage inputs]
    R --> S[Record fenced sent marker]
    S --> P[Recheck readiness, fence and cancellation before PUT]
    B -- Yes --> D[GET the persisted ID]
    P -->|Job PUT or ambiguous reply| D
    P -->|Preconnection failure or worker busy| W[Wait and keep the same ID]
    W --> A
    D -->|Absent, sent marker and no cancel| P
    D -->|Absent, reserved and no cancel| C
    D -->|Queued or running| D
    D -->|Terminal with cancel pending| X[Settle attempt and cancel run]
    D -->|Absent with cancel pending| H[Hold until a second clean absence after lease plus PUT timeout]
    H --> X
    D -->|Terminal pre-admission refusal| Y[Mark busy and defer the head]
    Y --> A
    D -->|Definite restart failure| C
    D -->|Succeeded| V[Verify graph, bytes and decoded clip]
    V -->|Verified| Z[Record result and continue build]
    V -->|Mismatch| F[Settle attempt and fail run]
    D -->|Other terminal failure| F
    P -->|Definite client rejection| F
```

Provisional coordinator ruling CR-19 resolves Q-410-01. Wan's product API owns
the compute lease and deduplicates by caller-selected job ID and request body.
After a lost reply the worker reads the recorded ID. If Wan reports it absent,
the worker can replay the exact same PUT with the original ID and stored body,
including when an earlier worker's request arrives late. The worker makes at
most one absent-ID replay per claim. A connection failure before any bytes were
sent gets its own code. A replacement still reads the durable ID before any PUT.
A lost reply to the Studio `sent` write triggers the same read on takeover. A
lost reply to a `busy` write is resolved from the persisted outcome or Wan's
terminal job record.

The worker checks `GET /v1/ready` for readiness and active video or Foley work
before every PUT. When Wan records a terminal refusal with `admission_code`
`gpu_busy`, `gpu_warm`, `engine_busy`, `lease_held`, `local_model_handover`
or `local_model_unavailable`, Studio marks the attempt `busy` and queues the
same run at the head. The next attempt gets a new ID because the refused
request did not reach the engine. Older job records use the exact legacy
messages for foreign ComfyUI work, busy GPUs and warm GPUs when the code
field is absent. `pre_admission_failed` and unfamiliar codes keep the run
and its recorded attempt held for inspection. A `worker_busy` HTTP response without a job record keeps
the same ID. Admission refusals back off for 60, 120 and at most 240 seconds on
the database clock. Success resets the refusal count. Other ordinary waits
use 15 seconds. A reported render hold or unexpected work observed during
inference can pause the build until Wan reports readiness. An explicit Wan
restart failure allows one fresh attempt per claim before yielding.

| Code | Queue behavior |
| --- | --- |
| `wan.submit_not_sent` | The connection failed before the PUT could be written. Recheck the saved ID and readiness after the wait. |
| `wan.ambiguous_submit` | Reconciliation still found no record after a same-ID replay. Keep the head and retry reconciliation. |
| `wan.cancel_waiting_for_absence` | Cancellation is pending for a sent ID. Hold the FIFO head and check the same ID for a second absence after the safety window. |
| `wan.foreign_engine_queue`, `wan.busy` | Honor the admission cooldown. Use a new ID only after a recorded terminal refusal. |
| `wan.pre_admission_failed`, `wan.admission_unknown` | Hold the run and retain its sent attempt for inspection. |
| `wan.id_conflict`, `wan.submit_rejected` | Fail the attempt and run on a conflicting ID or another definite PUT client error. |
| `wan.graph_mismatch`, `wan.result_invalid`, `wan.clip_invalid` | Fail the attempt and run with expected and actual evidence for the terminal result. Verification covers the graph pin, byte count, SHA-256, decode, dimensions, frame count and rate. |
| `work.revision_mismatch` | Fail the run if its frozen Studio revision differs from the worker. Queue a new run to capture the current immutable snapshot. Earlier verified clips in the same production are reused through the cache when their input and profile keys still match. |

The pinned I2V or S2V graph associates the recorded graph SHA-256 with the model
file hashes in the licence register.

## Installed proof for story 437

[Story 437](https://work.haynesnetwork.com/work_packages/437) records installed
evidence separately from source test results and creative acceptance.

- Run the migration Job with the preprovisioned roles, and show the head
  revision and effective runtime grants. Confirm the runtime user cannot
  mutate a snapshot, attempt ID or credential table. Confirm claims use HTTP
  with a worker token and refuse anonymous, browser and agent credentials
  before parsing a malformed body or query.
- Through two API replicas, enqueue two revisions and retry an idempotency key.
  Edit the draft and verify both SHA-256 values, FIFO order and scoped reads.
- Verify two worker identities compete for one head, an expired fence is
  rejected, and an API or worker restart leaves every accepted run recoverable.
- With an approved bounded fixture, observe lost submit acknowledgement, slow
  poll, expiry and Wan restart. Show recorded IDs, reads before any new
  submission, and digests. Verify the head retries after foreign work clears, and observe that a lease
  refusal or loss of talosw01 pauses builds while draft CRUD stays up.
- Verify a completed private delivery through the authenticated phone proxy,
  including a Range read, and verify access is refused outside the production.
  Verify cancelled work stops submissions and only a person can override a
  permitted visual check.
- Record image digests, revision and timing together with the private artifact
  locations and hashes. Keep installed, usable and Tom's verdict separate.
