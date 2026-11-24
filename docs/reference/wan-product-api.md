# Wan product job API v1

The Studio product client uses HTTP to stage immutable inputs, submit typed jobs
and fetch results. The Wan API owns the graphs and the Foley sidecar owns audio
inference. Both use the existing Wan compute lease.

## Availability

The product contract is version `1.0.0`. Use the `wan-video` Service in namespace
`ai` on port 8080 from an authorized client. The private viewing ingress keeps
the legacy `/videos` routes. The `/v1` routes and typed results use the Service.

- `GET /v1/profiles` returns `api_version` and the server's profile matrix. Require
  the expected version and profile before submitting.
- `GET /v1/ready` returns `ready: true` and `api_version` when Wan can read
  ComfyUI and the expected GPU pair, the render hold is clear, and the Foley
  product worker reports the expected version and model manifest. It also
  reports `active_video_job` and `active_foley_job`, each a job ID or null.
  Readiness is a health signal. Admission still checks the shared lease,
  the queue and the GPU conditions.
- `GET /openapi.json` publishes the request and response schemas.

**Installed baseline, 2026-11-24.** A read-only probe from the API container
returned `/health` with `accepting_jobs: true` and `active_job: null`,
`/ready` with `ready: true`, and OpenAPI `1.0.0` with only the legacy video
paths. `/v1/profiles` returned 404. The installed API SHA-256 was
`61fdb5314acd1db6a04f014d3b213f4215f14df52e9f1827cce68c216bc79c18`.
The Foley loopback worker reported models present and no active job. The Service
health check succeeded from inside the Wan workload. Direct Service access from
the task session timed out. The product interface has fake-engine source tests. A separate GitOps rollout and version
read-back are required before a live client switches to it. The E0 and story 842
paths remain historical proof for the profiles.
[Service reference](services.md) · [Story 458](https://work.haynesnetwork.com/work_packages/458)

## Submit and recover

1. For I2V and S2V, upload the input bytes to `PUT /v1/inputs/{sha256}.png` and,
   for S2V, `PUT /v1/inputs/{sha256}.wav`. Use the lowercase, 64-digit SHA-256
   of each body and a `Content-Length` of 1 to 19,999,999 bytes. PNG headers must
   have dimensions between 1 and 4096 pixels per side. WAV input must be PCM
   with all samples present. The API verifies the digest and publishes the file
   create-only. HTTP 201 means created and 200 means identical bytes already
   exist. HTTP 409 with `upload_busy` means an upload is active and can be retried.
2. Generate a new lowercase 32-digit hex UUID, without hyphens, for each
   intended attempt. Persist the job ID and request before sending
   `PUT /v1/jobs/{type}/{job_id}` with that JSON body and a `Content-Length`
   of at most 65,536 bytes. The server records the job before acknowledging
   it. HTTP 202 means accepted. An equivalent request at the same path gives
   200 with the existing status, including when the worker is busy or held.
   The same ID with a different request gives 409 `id_conflict`. I2V and S2V
   share a video ID namespace with legacy jobs. Foley has its own namespace.
3. Poll `GET /v1/jobs/{type}/{job_id}`. After a lost reply or transport
   timeout, use that path first. If it returns 404, the exact same PUT and ID
   can safely be repeated. HTTP 409 `worker_busy` refuses a new job while
   compute is reserved, the worker is busy, or a hold needs inspection. A
   retry of an existing job never starts a second generation. Allow delays
   on reads and honor the profile budget.
4. A status is `queued`, `running`, `succeeded` or `failed`. It includes
   `api_version`, `type`, `id`, `profile`, `status_url`,
   `request_sha256`, the story URL, and timestamps as the job progresses.
   Video jobs record the ComfyUI `prompt_id` and `graph_sha256` before the
   engine POST. A lost engine acknowledgment is reconciled with read-only
   queue and history polls for that UUID. Slow reads are retried within the
   watchdog window, up to 12 consecutive misses or 90 seconds since the first
   miss. Failure cleanup cancels confirmed owned prompts by ID. An unconfirmed submission or foreign work can hold the
   worker for inspection. Treat a reported `unexpected_work_seen` as a
   stop signal for the build even if its own clip finished. Restart recovery
   settles interrupted work without replaying it. A failed job keeps its ID
   and error for inspection.
5. On success, `result` gives `file_url`, `media_type`, `bytes` and
   `sha256`. Fetch the file with GET and verify both byte count and digest.
   Video results are MP4 and Foley results are WAV. The route supports a
   single byte range, with 206 for a satisfiable range and 416 for an
   unsatisfiable range. It returns 409 `result_unavailable` before success.
   The client validates decode, dimensions and duration for its build stage.

## Request fields and profiles

All job types require `profile`, `prompt`, `seed` and `story`. Use a full
`https://work.haynesnetwork.com/work_packages/<id>` URL in `story`. The API
rejects unknown fields and unsupported profiles with 400. Prompts are trimmed.
Video prompts and supplied negative prompts are nonblank and at most 4096
characters. Foley prompts are nonblank and at most 2048 characters. A supplied
Foley negative prompt may be empty and has a 2048-character cap.

| Type and profile | Additional fields | Engine and watchdog |
| --- | --- | --- |
| `i2v` · `wan2.2-ti2v-5b` | Required `image_sha256`. Optional `frames`, from 5 through 121 in steps of four, default 121. | E0 TI2V-5B, 24 fps, 20 steps, two-GPU CFG split. Video watchdog 1200 s. |
| `s2v` · `wan2.2-s2v-14b-lightning` | Required `image_sha256`, `audio_sha256` and integer `board_frames` from 1 through 342 at 24 fps. WAV samples must equal the floor or ceiling of `board_frames × sample_rate / 24`. | E0 S2V-14B fp8 and wav2vec2, four-step lightning LoRA, CFG 1, one GPU, 16 fps, at most three 77-frame chunks. Video watchdog 1200 s. |
| `foley` · `controlfoley-v1` | Required `source_job_id` of a successful Wan MP4, including legacy video records. Optional `start_seconds` from 0 to 300 (default 0) and `duration` from 0.7 to 8 seconds (default 8). The window must fit the source clip. | Pinned ControlFoley, 44.1 kHz WAV, one GPU. Inference watchdog 600 s after cooldown and preprocessing. |

Both video types accept optional `width` and `height` in multiples of 32 from
64 to 1280, defaulting to 576 × 1024. Their default negative prompt is the
E0 Studio prompt. Seeds are integers. I2V allows 0 through 2⁵³−1, S2V 0 through
2⁵³−3, and Foley 0 through 2³²−1. S2V reserves the next two seeds for Extend.
The S2V graph asks for `4 × ceil(board_frames / 6) + 1` source frames,
rounded up to whole 77-frame chunks above 77. Its delivered frames follow TIME-9.
[Studio time and adapter contract](../contracts/studio-contracts-v1.md#the-wan-clip-client-as-built-story-842)

The video worker requires the approved GPU pair below 62 °C with utilization
at most 5% and memory use at most 22,000 MiB on each card before it submits.
Foley keeps its idle, cooldown, memory and thermal watchdog checks. The product
paths accept typed job fields and media digests. Steps, model selection, arbitrary
graphs, URLs and filenames stay under server control.
