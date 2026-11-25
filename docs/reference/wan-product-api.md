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

**Pre-rollout baseline, 2026-11-24.** A read-only probe from the API container
returned `/health` with `accepting_jobs: true` and `active_job: null`,
`/ready` with `ready: true`, and OpenAPI `1.0.0` with only the legacy video
paths. `/v1/profiles` returned 404. The installed `/config/video/api.py` SHA-256 was
`61fdb5314acd1db6a04f014d3b213f4215f14df52e9f1827cce68c216bc79c18`.
It matches the November 24 source baseline with OP917's queue client-ID check.
The services page records the earlier deployment read on November 18 and gives
the loopback command used for current agent access. The Foley loopback worker reported models present and no active job. The Service
health check succeeded from inside the Wan workload. Direct Service access from
the task session timed out. The product interface has fake-engine source tests.
The E0 and story 842 paths remain historical proof for the profiles.
[Service reference](services.md#wan-api-storage-and-delivery) ·
[OP917 source](https://github.com/thaynes43/haynes-ops/commit/2ab6a5550dc908a757c32a9b22878a14fda60319) · [Story 458](https://work.haynesnetwork.com/work_packages/458)

**Installed later on 2026-11-24.** Flux applied haynes-ops `1a5d2e08`. Seven files
matched the merged SHA-256s. In-pod `/v1/ready` and `/v1/profiles` returned 200 for
`1.0.0` and the three job types with no active job. The legacy file route still
served bounded, suffix and open-ended ranges with 206. The ingress rule excludes
`/v1`. The coordinator read the rule from the session, which had no LAN route. A live product GPU job and the post-S2V admission check remain open.
[Story 458](https://work.haynesnetwork.com/work_packages/458), comment 9749.

## Submit and recover

1. For I2V and S2V, upload the input bytes to `PUT /v1/inputs/{sha256}.png` and,
   for S2V, `PUT /v1/inputs/{sha256}.wav`. Use the lowercase, 64-digit SHA-256
   of each body and a `Content-Length` of 1 to 19,999,999 bytes. Each PNG side
   must be 1 to 4096 pixels. The file must contain `IDAT` and end at `IEND`
   within 4,096 chunks after `IHDR`. An `acTL` chunk returns HTTP 400
   `animated_png`. WAV input must have one `data` chunk of 16-bit PCM, mono or
   stereo, at 16000, 22050, 24000, 44100 or 48000 Hz. The API accepts `LIST` and
   `fact` chunks before or after `data` and ignores bytes after the declared
   RIFF boundary. A second `data` chunk returns HTTP 400 `invalid_input`.
   Other WAV formats return HTTP 400 `unsupported_wav_format`. Incomplete inputs
   return HTTP 400 `invalid_input`.
   The Studio voice drive track is 24 kHz mono 16-bit PCM. [Studio voice](studio-voice.md)
   The API verifies the digest and publishes the file create-only. HTTP 201 means
   created and 200 means identical bytes already
   exist. HTTP 409 with `upload_busy` means an upload is active and can be retried.
   Send the body within 30 seconds plus one second per 131,072 declared bytes
   (just under 183 seconds at the maximum size) and avoid stalls of 15 seconds.
   A timeout returns HTTP 408 `upload_timeout` and removes any temporary file.
   The staging directory is limited to 4 GiB and 4,096 entries, including
   abandoned temporary files. New content also requires 5 GiB free on the Wan
   volume after upload. HTTP 507 `input_storage_full` means a quota or reserve
   has been reached. An identical upload can still return 200. Staged inputs
   are retained without automatic deletion.
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
   engine POST. The API polls the queue and history for that UUID when the
   engine acknowledgment is lost. The job can fail with `PromptSubmissionLost`
   and release the lease without a hold after 120 seconds if the prompt remains
   unacknowledged, all queue and history polls are well formed and show it
   absent, the hold stays clear, and every GPU sample meets the admission limits
   of 5% utilization and 22,000 MiB of memory use per card. A busy or unreadable
   GPU sample, or a failed or malformed poll, disables that shortcut.
   Slow reads are retried within the watchdog window, up to 12 consecutive
   misses or 90 seconds since the first miss.
   Failure cleanup cancels confirmed owned prompts by ID. An unconfirmed
   submission or foreign work can hold the worker for inspection. Treat a
   reported `unexpected_work_seen` as a stop signal for the build even if its
   own clip finished.

   On API startup, recovery verifies queue ownership and holds the worker if it
   sees foreign work. It interrupts owned running prompts, deletes owned pending
   prompts and marks queued and running video jobs failed.
   Recovery skips history lookup, so a render that finished while the API
   container was down is discarded as a job result. A failed job keeps its
   ID and error for inspection. Use a new job ID for a new attempt.
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

## Admission refusals

A job refused before engine submission can include `admission_code` beside its
existing `error` text. The engine did not start the refused job. Older records
can omit the field. An HTTP refusal before a job is recorded still uses the
existing HTTP error body. The legacy Wan route retains its response shape when
the local-model profile is absent.

| `admission_code` | Meaning | Client action |
| --- | --- | --- |
| `gpu_busy` | GPU utilization or memory exceeded the admission limits. | Back off and use a new ID when compute is available. |
| `gpu_warm` | The required cooldown or idle conditions were unmet. | Back off and retry with a new ID after cooldown. |
| `engine_busy` | The engine queue showed work or could not be verified. | Wait for a verified idle queue, then retry with a new ID. |
| `lease_held` | Another lane owns compute or an existing render hold blocks admission. | Retry with a new ID after the lease or render hold clears. |
| `local_model_handover` | The API could not verify that local-model residency was safe. | Retry with a new ID after verification. A durable hold requires operator inspection. |
| `local_model_unavailable` | A local-model status needed for admission was unavailable. | Retry with a new ID after the sidecar can supply status. |
| `pre_admission_failed` | A different error occurred before the engine started, such as an invalid inference budget. | Inspect the error and resolve the cause before making a new request. |

Continue to poll the same ID after an ambiguous reply. The installed
`f30445f` queue and the command-line client classify refusals from the
`error` text:

- The run queue (`src/haynes_studio/queue/wan.py`) treats the ComfyUI
  foreign-queue text and the two Rack GPU texts (busy, and above the
  temperature limit) as an admission refusal in which nothing ran. It records
  the attempt as busy and waits for the lane. Mounted-profile sidecar and
  handover refusals use the same Rack GPU busy text, so the queue waits on
  those too.
- The command-line clip client (`src/haynes_studio/adapters/wan.py`) treats
  only the lease text, `Compute is reserved by another video/audio job`, as
  `adapter.busy`. Any other refusal, the Rack GPU texts included, ends as
  `adapter.job_failed` with "inspect before any further render". It does not
  back off by itself.

Merged story [430](https://work.haynesnetwork.com/work_packages/430) moves
the queue to `admission_code` with a legacy text fallback when no code is
present. It awaits the next app pin. A Wan or Foley admission check that
sees foreign engine work preserves it and refuses that attempt without
latching a new hold.

## Legacy cleanup

The installed legacy worker raises a JSON parse error and latches the hold
when ComfyUI returns an empty HTTP 200 response to `/interrupt` or `/queue`
deletion. After the companion Wan rollout, the shared engine client accepts
those replies. When cleanup confirms the running queue has drained, the
lease can be released and the next legacy job can proceed.
[Wan rollout PR](https://github.com/thaynes43/haynes-ops/pull/5020)

## Local-model requests

Story 441 defines the additive v1 operations. Story 442 installed their code
dormant at haynes-ops `79fa01b5`, published the sidecar image and verified
both pilot files. The local-model routes return HTTP 503
`local_model_not_installed` until the sidecar and profile are activated.
Use the same internal Service as for the video and Foley product jobs.
[Story 441](https://work.haynesnetwork.com/work_packages/441) · [Story 442](https://work.haynesnetwork.com/work_packages/442)

| Operation | Request |
| --- | --- |
| `GET /v1/local-model/profile` | Discover the configured model name, GPU UUID, context and output token limits, operation deadlines and memory bands. This reads configuration. Admission verifies the sidecar separately. |
| `PUT /v1/local-model/requests/{request_id}` | Submit one `load`, `infer` or `unload` request under the Wan compute lease. |
| `GET /v1/local-model/requests/{request_id}` | Read the request and, when compute is available, reconcile a lost reply. |

Generate and persist a fresh lowercase 32-digit hex UUID and the typed request
before sending it. Use a JSON body of 1 to 65,536 bytes with a
`Content-Length`. All operations require `operation` and `profile`, where
`profile` is the configured model name. Load and unload take only those fields.
Inference requires `prompt` (1 to 4,096 characters, trimmed and nonblank).
Optional fields are `mode`, `max_output_tokens` and one of `image_sha256`
or `image_sha256s`. The singular digest keeps its existing upload bounds.
The plural field accepts one to four PNGs in input order, each up to 8 MiB and
up to 1080×1920 or 1920×1080. Stage every PNG through
`PUT /v1/inputs/{sha256}.png` first. The API and the model child both check each
staged digest and its PNG bounds. Omit both image fields for text-only work.
The complete input includes the model template and image tokens. The backend
counts it on CPU and caps each image at 1,024 visual tokens. If that input plus
the requested output budget cannot fit the configured context, the worker
returns `context_limit` before image encoding. The profile's output ceiling
applies by default.

| Mode | Inputs and `result.text` |
| --- | --- |
| `text` | Free text with optional images. Omission and explicit `text` produce the same request fingerprint as the original text request. |
| `frame_check_v1` | Requires an image. Returns a JSON object with `frames`, one entry per input image in order. Each entry has `face` (`visible`, `hidden`, `uncertain`), `code` (one to 64 characters or `null` for unreadable evidence) and `wardrobe` (`match`, `mismatch`, `uncertain`). |
| `plan_v1` | Returns a JSON object with `scene_id` (one to 64 characters) and `shots` (one to 12 objects, each containing a `technical_direction` of one to 512 characters). |
| `plan_tool_v1` | Returns one JSON object with `name` equal to `record_plan_v1` and an `arguments` object. Arguments are `scene_id` (one to 64 characters), integer `shot_count` (one to 12) and `technical_direction` (one to 512 characters). The call is returned as data. |

Structured results and tool arguments are validated against server-owned
versioned definitions. Incomplete output or a schema mismatch within the
resource bounds fails with `invalid_result`. A token or byte limit violation
fails with `backend_failed` and records a residency hold. The request accepts
only its typed fields. Schemas,
grammars, tool definitions and image URLs are controlled by the server.
An explicit structured mode and the order of its image digests are part of
the immutable request.

```json
{"operation":"infer","profile":"configured-model","prompt":"Describe this panel.","max_output_tokens":128}
```

Load the profile before issuing inference. A load of a verified resident
profile and an unload of a verified empty profile succeed without an engine
call. HTTP 202 acknowledges a recorded request. HTTP 200 on an equivalent PUT
returns the existing status. Changing a valid request at the same ID gives
HTTP 409 `id_conflict`. A new request gets HTTP 409 `worker_busy` while
another job owns compute or a render hold is active. A durable residency hold
returns HTTP 503 `local_model_held`.

Poll the original ID after a transport error. If GET returns
`request_not_found`, repeat the identical PUT with that ID. The status is
`queued`, `running`, `succeeded` or `failed`. A successful inference
includes `result.text`, `input_tokens` and `output_tokens`. The result
text is limited to 32 KiB UTF-8 and is returned in one response. A failed
request retains the ID and its error. Use a new ID for an intentional new
attempt after inspecting the failure.

Wan admission still samples both GPUs against the existing utilization, memory
and temperature limits for product video. S2V's placement determines whether
handover needs to unload a model. An idle resident model on the other GPU can
stay loaded while both cards meet the admission limits.

| Situation | Lease behavior |
| --- | --- |
| A one-card S2V job uses the other card | A verified idle model stays resident. Operators can declare the S2V GPU UUID after verifying fixed engine placement. With placement unverified, S2V reserves both cards for handover. |
| A job needs the resident card | The Wan lease stays held across unload, memory verification and engine submission. Both-card jobs and Foley on the model card use this handover. Wan's `queued` acknowledgment records the request. ComfyUI submission waits for the configured card to reach the unloaded memory ceiling. |
| Wan or Foley owns compute | The local request receives `worker_busy`. A replay or status read can still return its existing record. |
| The API loses a sidecar reply or restarts | The sidecar keeps a copy of the same lease until work ends. Once the lease is available, the API matches the original request ID to the sidecar receipt and checks residency. A recorded request proved absent fails with `submission_lost`. |
| A profile is mounted and residency needs checking | A live child with no residency journal latches a hold. Without either, ordinary idle engine cache is allowed. An unavailable sidecar refuses work needing residency evidence without adding a hold. |
| A model operation exceeds its deadline or the child dies | The supervisor kills a timed-out child and reaps it before recording the receipt or releasing its copy of the lease. The request reports `operation_timeout` or `backend_exited` after the card passes its unloaded memory check. |
| The supervisor dies | A replacement starts unloaded. A fresh idle card sample at or below the unloaded ceiling verifies that the card is clear. A pending request then fails with `sidecar_restarted`. Unavailable status blocks new GPU work while residency is uncertain. |
| Unload ends the model process | The supervisor reaps the process group. A fresh idle sample at or below the configured ceiling and no more than 4 MiB above the recorded baseline proves release. Otherwise a residency hold survives API restarts. |
| Engine work is unknown or the render hold is set | Existing engine work is preserved. Wan and Foley refuse their admission attempt. A well-formed foreign queue returns `engine_busy` and keeps the prior reservation. Malformed queue responses fail closed. A transient queue read failure refuses the attempt. |
