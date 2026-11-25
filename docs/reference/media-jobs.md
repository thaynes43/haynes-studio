# Studio media workers

Voice, photo and candidate requests create durable `studio.job/v1` records.
Workers run beside the build lane using the same authenticated internal
protocol. The API owns PostgreSQL transactions and catalog writes.

| Worker entry point | Lane | Service-specific configuration |
|---|---|---|
| `studio-worker --lane voice` | One board voice at a time | `STUDIO_TTS_HOST` and optional `STUDIO_TTS_PORT` (10210) for Kokoro Wyoming TTS. |
| `studio-worker --lane image` | One photo or asset candidate at a time | `STUDIO_COMFYUI_URL` as an HTTP(S) origin for the shared image engine. Layered photos use the deterministic D51 compositor. |
| `studio-worker` | Build queue | See the [build worker configuration](run-queue.md#worker-configuration). |

Each media worker takes `STUDIO_API_URL`, `STUDIO_WORKER_TOKEN`,
`STUDIO_MODEL_REGISTER` and `STUDIO_STORE_ROOT`. Use a separate worker ID and
token per process and mount the canonical store read/write for media workers.
Blobs are written create-only by hash. A blob becomes readable through the API
after its reference is committed. Keep the internal API reachable only from
workers. `--once` processes at most one claim. Media workers have no Wan client
or compute lease and use no paid provider.

## Claims and results

POST paths share the prefix `/internal/v1/work` and require a worker token.

| Path | Media worker payload and effect |
|---|---|
| `/claim` | `{"lane":"image"}` or `{"lane":"voice"}`. Returns the lane's FIFO head, frozen inputs, fence and claim deadline, or 204. The existing empty request claims the run lane. |
| `/heartbeat` | `job_id` and `fence`. Extends the claim by 90 seconds on the database clock. |
| `/publish` | `job_id` and `fence`. Records entry to engine dispatch and renews the claim before submission. |
| `/complete` | `job_id`, `fence` and result evidence. The API verifies stored content and commits the version, terminal status and eligible draft selection together. |
| `/fail` | `job_id`, `fence`, bounded `code` and `message`. Preserves the request inputs and requester. |

Workers heartbeat every 15 seconds during blocking work. Expiry before
dispatch allows another worker to take the same job with a new fence.
Expiry after dispatch fails it with `work.dispatch_unconfirmed`. A replacement
can claim subsequent image jobs and waits until ComfyUI reports an empty
running and pending queue. Each submission checks the queue immediately
before sending. The worker lets existing work finish and never interrupts it.
An uncertain submission is never replayed under another worker fence.
There is no automatic purge.

The media lanes have no public cancel route in this story. Poll the
[job operations](studio-api.md#media-operations) for status and versions.
HTTP and MCP callers use the same production and credential checks.
