# Studio media workers

Voice, photo and candidate requests create durable `studio.job/v1` records.
Workers run beside the build lane using the same authenticated internal
protocol. The API owns PostgreSQL transactions and catalog writes.

| Worker entry point | Lane | Service-specific configuration |
|---|---|---|
| `studio-worker --lane voice` | One board voice at a time | `STUDIO_TTS_HOST` and optional `STUDIO_TTS_PORT` (10210) for Kokoro Wyoming TTS. |
| `studio-worker --lane image` | One photo or asset candidate at a time | `STUDIO_COMFYUI_URL` as an HTTP(S) origin for the shared image engine. Layered photos use the deterministic D51 compositor. |
| `studio-worker` | Build queue | See the [build worker configuration](run-queue.md#worker-configuration). |

Each media worker takes `STUDIO_API_URL`, `STUDIO_WORKER_TOKEN` and
`STUDIO_STORE_ROOT`. It reads the packaged model licence register by default;
`STUDIO_MODEL_REGISTER` optionally supplies the same override used by the API.
Use a separate worker ID and
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

## Upload memory

One MCP process and one API process each admit a single D42 upload. A
concurrent upload gets HTTP 503 `photo.upload_busy` before the process reads
its body. Ordinary MCP requests at `/mcp` keep their 256 KiB cap. Use
`/mcp/upload` for the upload tool.

A local test on CPython 3.11.2 used separate Uvicorn processes over loopback,
a disposable PostgreSQL 16 database, and an exactly 20 MiB synthetic
4096 × 4096 RGBA PNG with EXIF rotation. MCP forwarded the image, and the
API decoded it, stripped metadata, encoded RGB PNG, and selected the version.
Linux `VmHWM` measured the peak resident memory of each process.

| Process | Startup RSS high-water | Upload peak RSS | Configured container limit |
| --- | ---: | ---: | ---: |
| MCP | 59,492 KiB (58 MiB) | 177,472 KiB (173 MiB) | 192 MiB |
| API | 190,840 KiB (186 MiB) | 354,084 KiB (346 MiB) | 320 MiB |

The API peak exceeds 320 MiB. Size the API container above this measurement
with headroom for other requests and container overhead before enabling
maximum-size uploads. The numbers measure process RSS in the local setup.

## Worker progress probe

Set `STUDIO_WORKER_PROGRESS_FILE=/run/studio/worker-progress`, or pass
`--progress-file /run/studio/worker-progress`, on each run, image or voice worker.
Use a separate file per worker process in a writable runtime directory outside the
media store. Without either option, progress files are disabled. The main thread
touches the file on each claim poll and pipeline step, on every Wan poll, and on
image queue and ComfyUI history polls. Only the main thread writes the file.
A stuck main thread therefore ages out even if its claim heartbeats keep running.

Probe with the same file and an age budget in seconds:

```bash
studio-worker --progress-file /run/studio/worker-progress --check-progress 1500
```

This mode makes no service calls and needs no worker credentials. It exits zero
while the marker is at most that old, and nonzero when it is older, missing or
unreadable. The check reads the marker's timestamp. Allow startup time before probing.
A persistent marker write failure stops the worker.

A single Wan clip can legitimately take 20 minutes. Its synchronous polling keeps
the marker fresh throughout that wait. Choose a liveness budget with room for the
longest legitimate step that does not poll, such as local compositing, encoding or
voice synthesis. Start by evaluating the example `1500` seconds against that workload.
The haynes-ops deployment story owns probe configuration.
