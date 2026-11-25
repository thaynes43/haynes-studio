# Studio media workers

Voice, photo and candidate requests create durable `studio.job/v1` records.
Workers run beside the build lane using the same authenticated internal
protocol. The API owns PostgreSQL transactions and catalog writes.

| Worker entry point | Lane | Service-specific configuration |
|---|---|---|
| `studio-worker --lane voice` | One board voice at a time | `STUDIO_TTS_HOST` and optional `STUDIO_TTS_PORT` (10210) for Kokoro Wyoming TTS. |
| `studio-worker --lane image` | One photo or asset candidate at a time | `STUDIO_COMFYUI_URL` as an HTTP(S) origin for the shared image engine. Layered photos use the deterministic D51 compositor. |
| `studio-worker --lane matte` | One matte candidate at a time | Pinned CPU sidecar over `/matting/matte.sock`. See the deployment pin below. |
| `studio-worker` | Build queue | See the [build worker configuration](run-queue.md#worker-configuration). |

Each media worker takes `STUDIO_API_URL`, `STUDIO_WORKER_TOKEN` and
`STUDIO_STORE_ROOT`. It reads the packaged model licence register by default;
`STUDIO_MODEL_REGISTER` optionally supplies the same override used by the API.
Use a separate worker ID and token per process with its
[lane grant](studio-api.md#worker-token-administration). Mount the canonical
store read/write for media workers.
Blobs are written create-only by hash. A blob becomes readable through the API
after its reference is committed. Keep the internal API reachable only from
workers. `--once` processes at most one claim. Media workers have no Wan client
or compute lease and use no paid provider.

## Claims and results

POST paths share the prefix `/internal/v1/work` and require a worker token.

| Path | Media worker payload and effect |
|---|---|
| `/claim` | `{"lane":"image"}`, `{"lane":"voice"}` or `{"lane":"matte"}`. Returns the lane's FIFO head, frozen inputs, fence and claim deadline, or 204. An empty body selects `run`. A matte poll can settle an expired dispatch at the head even on a paused lane. `{"lane":"matte","settle_only":true}` always returns 204 without taking a claim. |
| `/heartbeat` | `job_id` and `fence`. Extends the claim by 90 seconds on the database clock. |
| `/publish` | `job_id` and `fence`. Records entry to engine dispatch and renews the claim before submission. |
| `/complete` | `job_id`, `fence` and result evidence. The API verifies stored content and commits the version, terminal status and eligible draft selection together. |
| `/release-matte` | `job_id` and `fence` from a matte worker. If dispatch was recorded, also send `reason: "connect"` for a failed socket connection, `reason: "busy"` for a confirmed lock refusal, or `reason: "readiness"` for a confirmed pre-inference loading reply. Requeues the same FIFO job and revokes its claim. The release counter stops at three. A further busy reply still requeues. A further connection or readiness outage fails the job with `matting.sidecar_unavailable`. |
| `/fail` | `job_id`, `fence`, bounded `code` and `message`. Preserves the request inputs and requester. |

For shared routes (`/claim`, `/heartbeat`, `/publish`, `/complete`, and
`/fail`), the API authenticates the token and checks that it has a lane grant,
enforces the 2 MiB body limit, checks the lane identified by the request,
validates the body, then looks up the claim or job in the authorized lane.
For `/claim`, strict JSON must identify a supported lane before the lane
check can precede field validation. An empty body, JSON null, or an object without
`lane` selects the run lane. For the other shared routes, an object with
`job_id` and no `run_id` selects the media lanes. Other shapes follow the
run-lane default, including invalid JSON. A token outside the selected lane
or lane group receives 403 `work.lane_forbidden` before field validation.
Among media lanes, field validation precedes the lane-scoped job lookup.
A malformed media body can return 422, and a well-formed request for a job
in another media lane returns 404. Within the lane, the worker ID, fence
and claim deadline must still match. The dedicated `/resume` (run) and
`/release-matte` (matte) routes check their lane grant before reading the body.

Workers heartbeat every 15 seconds during blocking work. Expiry before
dispatch allows another worker to take the same job with a new fence.
Expiry after dispatch fails it with `work.dispatch_unconfirmed`. A replacement
can claim subsequent image jobs and waits until ComfyUI reports an empty
running and pending queue. Each submission checks the queue immediately
before sending. The worker lets existing work finish and never interrupts it.
An uncertain submission is never replayed under another worker fence.
There is no automatic purge.

Poll the
[job operations](studio-api.md#media-operations) for status and versions.
HTTP and MCP callers use the same production and credential checks.

## Matte worker deployment pin

The GitOps pin for [story 965](https://work.haynesnetwork.com/work_packages/965)
needs the pinned sidecar, the API schema upgrade through `0013_matte_jobs`,
and the worker's dedicated token and grant. Set `STUDIO_RUNTIME_ROLE` to the
existing API runtime login when applying the migration so it grants access
to update the release counter. The migration sets a PostgreSQL lock timeout
of 500 ms per acquisition. It can queue for the grant table and takes the
other three table prelocks with `NOWAIT`. A reader queued behind it can
wait for the grant lock budget plus DDL and commit, measured at about
10 ms at the installed table sizes. End-to-end readiness also includes
the remaining readiness queries. A lock timeout rolls the upgrade back to
`0012_release_constraints` and the Job retries within its configured budget.

The sidecar and worker can start in either order. Before each claim the
worker checks the exact CPU profile
at `GET /v1/ready` and waits for any tracked attempt to clear. While the socket
is unavailable, the model is loading, the profile differs, or a previous
attempt is active, the worker reports the reason in its log and progress marker
and polls again at its usual five-second interval. While waiting, it settles an
expired dispatched head without claiming the next job. The API records the
dispatch fence before the worker opens the socket. A failed connection can
release the job once fenced. The confirmed pre-inference `POST /v1/matte`
replies eligible for release are:

| Exact reply | Release reason |
| --- | --- |
| `409 {"code":"adapter.busy"}` | `busy`. The engine has the inference lock. |
| `503 {"code":"adapter.not_found"}` | `readiness`. The engine is unavailable before inference, for example while loading a replacement. |

Other error replies follow the dispatched failure path. A sent request whose
outcome is uncertain stays fenced. If the API fails to confirm a release, the
worker logs a generic warning and keeps polling. A claim that the API did not
release still appears as **Cutout running** while its lease is live. If dispatch
was recorded, expiry settles it as **Cutout failed** with
`work.dispatch_unconfirmed`, including while the lane is paused or the sidecar
is unavailable. A claim without a dispatch can be reclaimed once the lane
is open and the sidecar is ready. Use `studio-matting ready` to verify the
deployed sidecar.
Use the migration identity for the initial registration.

```sh
studio-api-admin worker-token register --worker-id studio-matte-worker \
  --lane matte --token-file "$MOUNTED_TOKEN_FILE"
studio-worker --lane matte
```

Set `STUDIO_API_URL`, `STUDIO_WORKER_TOKEN`, `STUDIO_STORE_ROOT`,
`STUDIO_MATTING_IMAGE`, `STUDIO_MATTING_REVISION`, and
`STUDIO_MATTING_PROFILE_SHA256`. Use the same generated token for
registration and the worker environment. The backend image and revision
refer to the pinned sidecar. The profile digest comes from its release record.
Set `STUDIO_WORKER_PROGRESS_FILE=/run/studio/worker-progress` for liveness.
Use `studio-worker --progress-file /run/studio/worker-progress --check-progress 300`
as the probe and allow the worker time to write its first marker. Its Unix
request can block for 35 seconds. Unconfirmed requests can add 33 seconds of
quiescence and up to 121 seconds of readiness recovery before the main thread
touches the marker again. The 300-second budget also leaves room for fenced API
calls and local staging. The probe reads the marker timestamp.

Move the staged matting sidecar and its scratch volume from the run worker
activation to the matte worker pod in
[deployment pin 967](https://work.haynesnetwork.com/work_packages/967).
Mount the same writable scratch volume at `/matting` in the sidecar and
matte worker. Give them the shared group that can use the mode-0660
socket and read and write the attempt files. Mount the canonical store
read/write in the worker at its configured store root. The API uses the
same store. The sidecar alone mounts the read-only weights. The worker
reaches the matting service through the shared Unix socket. In haynes-ops,
add the matte worker's pod label to the API's port-8002 ingress rule alongside
the voice and image labels. Allow the matte worker network egress for DNS
and the API's port-8002 listener only. The Unix socket needs no network rule.
Admit exactly `POST /internal/v1/work/release-matte` in the listener's
allowlist. As a postflight check, use the matte token and a current fenced
claim on a disposable cutout. Send `POST /internal/v1/work/release-matte` with
its `job_id` and `fence` through port 8002. Verify HTTP 204 and confirm the
same job is queued again through its scoped status read. If the worker has
already reclaimed it, verify a higher fence for the same job.

The worker writes verified output into private per-claim staging on scratch.
Under the fence it copies every staged blob into the canonical store,
including files rebuilt for an existing candidate. The API verifies all three
hashes and commits the candidate and terminal job in one transaction.
A confirmed busy reply requeues the worker's claim for the next poll.
A timeout waiting for a reply after submission fails the job and can leave
the attempt for the next adapter sweep.
[File and receipt contract](matting-adapter.md)

## Upload memory

A replacement upload can target a board whose selected photo is recorded
without media. Versions used as actual image sources still require their
bytes. On a protected board the new photo is saved unselected.

One MCP process and one API process each admit a single D42 upload. A
concurrent upload gets HTTP 503 `photo.upload_busy` before the process reads
its body. Requests at `/mcp` have a 256 KiB cap, with a 2 MiB cap for the two
[archive text write tools](studio-mcp.md#tools-and-revisions). Use
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
`--progress-file /run/studio/worker-progress`, on each run, image, voice or matte worker.
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
