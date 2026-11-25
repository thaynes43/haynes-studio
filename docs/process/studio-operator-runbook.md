# Operate Haynes Studio

As of 2026-11-25, the third release pin is Studio `80975a9` with database
revision `0012_release_constraints`. The release record binds the full Studio
revision to both image digests. **Proven** deployment and postflight. **Changed**
during postflight, the recovered Winter Menu was found to retain the snapshot
reference, while the stored snapshot is absent. The corrected probe passed.
[Third release](https://github.com/thaynes43/haynes-ops/blob/main/docs/reference/studio-deployment.md#op964-third-release) ·
[Install evidence, comment 10061](https://work.haynesnetwork.com/work_packages/964)

The earlier app pins are recorded with the import and first upgrade
postflights. [First pin, OP957](https://work.haynesnetwork.com/work_packages/957) ·
[Second pin, OP959](https://github.com/thaynes43/haynes-ops/blob/main/docs/reference/studio-deployment.md#op959-release)

| Where | What runs there |
| --- | --- |
| `ai` | Two replicas each of `studio-api`, `studio-web` and `studio-mcp`, spread across nodes within each deployment. The LAN ingress serves the web, `/v1/` and `/auth/`. Authentik supplies LAN identity. MCP and the worker listener stay in-cluster. |
| `ai`, on `talosw01` | One serial `studio-worker` for the run lane, the offline `studio-render` worker and the Wan/Foley service on the two Studio 3090s. |
| `ai`, off `talosw01` | One `studio-voice-worker` for Kokoro and one `studio-image-worker` for photos and candidates. Shared ComfyUI runs on `talosm03`. |
| `database/postgres16` and gasha01 | Postgres holds the Studio catalog and queues. NFS holds the canonical `api-store-v1` and shared `build-stage-v1`. The API publishes verified outputs. The run worker reads the store and writes staging. |

[Deployment and mounts](https://github.com/thaynes43/haynes-ops/blob/main/docs/reference/studio-deployment.md) ·
[Services and placement](../reference/services.md) ·
[Worker lanes](../reference/media-jobs.md)

## Health reads

From an operator shell with existing cluster access, check Flux readiness,
pod placement, running image pins, disruption budgets, endpoints and database
health. Compare pod image digests to the [GitOps release record](https://github.com/thaynes43/haynes-ops/blob/main/kubernetes/main/apps/ai/studio/release.yaml).
Expect the six serving pods ready across distinct nodes in each pair, one
worker per lane and `postgres16` at three ready instances with successful
backup and continuous archiving.

```sh
flux get kustomizations -n ai | awk 'NR==1 || $1 ~ /^studio($|-)/'
kubectl -n ai get deploy studio-api studio-web studio-mcp studio-worker studio-voice-worker studio-image-worker
kubectl -n ai get pods -l 'app.kubernetes.io/name in (studio-api,studio-web,studio-mcp,studio-worker,studio-voice-worker,studio-image-worker)' \
  -o 'custom-columns=NAME:.metadata.name,NODE:.spec.nodeName,READY:.status.containerStatuses[*].ready,RESTARTS:.status.containerStatuses[*].restartCount,IMAGE:.status.containerStatuses[*].imageID'
kubectl -n ai get pdb studio-api studio-web studio-mcp
kubectl -n ai get endpointslice -l 'kubernetes.io/service-name in (studio-api,studio-web,studio-mcp)' \
  -o 'custom-columns=SERVICE:.metadata.labels.kubernetes\.io/service-name,READY:.endpoints[*].conditions.ready,PORT:.ports[*].port'
kubectl -n ai get job studio-migrate-08ac310f246c \
  -o 'custom-columns=JOB:.metadata.name,SUCCEEDED:.status.succeeded'
kubectl -n database get cluster.postgresql.cnpg.io postgres16 \
  -o 'custom-columns=NAME:.metadata.name,READY:.status.readyInstances,LAST:.status.lastSuccessfulBackup,CONDITIONS:.status.conditions[*].type,STATUS:.status.conditions[*].status'
kubectl -n ai get configmap studio-gatus-ep -o 'jsonpath={.data.config\.yaml}'
```

Check an API pod locally. `/healthz` checks the process and `/readyz` checks
the database and the current store probe. Check both pod endpoints again by
pod name if their readiness differs. Check progress markers and count recent
idle claim responses. A zero count during active work calls for a run or job
read. A failed marker check calls for inspecting that worker and its lane.

```sh
kubectl -n ai exec -i deploy/studio-api -c api -- python -I -B - <<'PY'
from urllib.request import urlopen

for route in ("/healthz", "/readyz"):
    with urlopen("http://127.0.0.1:8000" + route, timeout=5) as response:
        print(route, response.status, len(response.read()))
PY

for spec in worker:1500 voice-worker:120 image-worker:300; do
  worker="studio-${spec%:*}"
  if kubectl -n ai exec "deploy/$worker" -c worker -- studio-worker --check-progress "${spec#*:}"; then
    printf '%s progress OK\n' "$worker"
  fi
  kubectl -n ai logs "deploy/$worker" -c worker --since=2m |
    awk -v worker="$worker" '/\/work\/claim "HTTP\/1.1 204/ {n++} END {printf "%s claim 204: %d\n", worker, n}'
done
```

In Gatus, look for a passing `internal/studio` result within the last two
one-minute intervals. Its status read is
`GET /api/v1/endpoints/internal_studio/statuses` on the Gatus origin.
From the LAN, expect 200 at `/`, 401 at `/v1/me` and 404 on the private
routes below. A healthy Gatus probe with a failing LAN check narrows the
problem to the LAN path. The full rollout checks also verify worker engine
reachability and scoped media. [Gatus check](https://github.com/thaynes43/haynes-ops/blob/main/docs/reference/studio-deployment.md#gatus-and-backup-coverage) ·
[Anonymous ingress commands](https://github.com/thaynes43/haynes-ops/blob/main/docs/reference/studio-deployment.md#anonymous-ingress-and-mcp)

```sh
for route in / /v1/me /healthz /readyz /mcp /internal/v1/work/claim; do
  printf '%s ' "$route"
  curl -q -sS --max-time 5 -o /dev/null -w '%{http_code}\n' "https://studio.haynesops.com$route"
done
```

**Proven** in the OP440 read-only samples at 12:28–12:37 UTC on 2026-11-25.
The Flux stages showed `Ready=True`, `Suspended=False` at `main@sha1:7529f89e`.
The API, web and MCP pairs were all `2/2`. Each worker was `1/1`, with zero
restarts across all nine pods. The Python and web digest prefixes were
`08ac310f246c` and `497e020b8846`. Gatus config specified `internal/studio`
every minute.

```text
NAME                         NODE       READY       RESTARTS
studio-api-5ccf9956c6-lvs8h   talosw01   true,true   0,0
SERVICE      READY       PORT
studio-api   true,true   8000,8002
studio-mcp   true,true   8001
studio-web   true,true   8080
JOB                           SUCCEEDED
studio-migrate-08ac310f246c   1
postgres16  READY=3  LAST=2026-11-25T00:01:37Z  ContinuousArchiving=True  LastBackupSucceeded=True
/healthz 204 0
/readyz 204 0
studio-worker progress OK
studio-worker claim 204: 24
studio-voice-worker progress OK
studio-voice-worker claim 204: 24
studio-image-worker progress OK
studio-image-worker claim 204: 24
Gatus internal/studio HTTP 200
{'timestamp': '2026-11-25T12:36:12.515486936Z', 'success': True, 'status': 401}
```

**Changed** for the ingress sample. The GETs ran from inside the cluster
through internal Traefik with the Studio hostname and TLS certificate verified.
The output was `/ 200`, `/v1/me 401` and `404` on the four private paths
above. A LAN-client sample remains **Expected** for this walkthrough.
[Installed postflight](https://work.haynesnetwork.com/work_packages/964) ·
[Backup result](#backup-and-recovery)

## Start, stop or roll back

- **Start or update.** Use the reviewed haynes-ops change. Check Postgres,
  OIDC and NFS first, then the migration Job, API/MCP/web, worker registration
  and worker stages. Confirm the immutable pins and postflight before
  taking submissions. **Proven** for the third pin. [Preflight](https://github.com/thaynes43/haynes-ops/blob/main/docs/reference/studio-deployment.md#preflight) ·
  [Migration and rollout](https://github.com/thaynes43/haynes-ops/blob/main/docs/reference/studio-deployment.md#migration-and-rollout) ·
  [Postflight](https://github.com/thaynes43/haynes-ops/blob/main/docs/reference/studio-deployment.md#postflight-1)
- **Stop for maintenance.** Ask people to stop submissions, pause new claims
  on the affected lanes and drain running work. Investigate held work before
  stopping a consumer. Use GitOps for a sustained cluster change. Resume
  claims only after the health gates pass and pending jobs are reconciled.
  **Expected** for a person operating the installed pause controls.
  [Lane controls](../reference/studio-api.md#queue-controls) ·
  [Worker rotation](https://github.com/thaynes43/haynes-ops/blob/main/docs/reference/studio-deployment.md#rotation-and-rollback)
- **Roll back the third pin.** Follow the corrective GitOps procedure to
  restore the `393fe1d` workload pair and its matching build revision while
  retaining the `0012_release_constraints` schema and completed Jobs. Count
  newer writes first. If newer state needs third-pin semantics, prefer a
  forward fix. The rollback procedure preserves the database and media, and
  holds writes where the old build lacks lane enforcement. **Expected** for a
  third-pin rollback. [Rollback checks and restrictions](https://github.com/thaynes43/haynes-ops/blob/main/docs/reference/studio-deployment.md#roll-back-while-keeping-the-third-schema)
- **One API pod lost.** **Proven** once on this pin on 2026-11-25. The surviving
  API served ingress throughout replacement, both imported proxies remained
  unchanged and all workers continued claiming. The run used the cluster-side
  ingress path (**Changed**) and had zero saved selections or queued snapshots.
  [Recovery procedure](https://github.com/thaynes43/haynes-ops/blob/main/docs/reference/studio-deployment.md#op437-one-api-pod-recovery) ·
  [Results and corrected count, comments 10077 and 10078](https://work.haynesnetwork.com/work_packages/437)

## Paused lane, stuck run or failed job

1. A signed-in person reads `GET /v1/queue/lanes` for `paused`, `changed_by`
   and `changed_at`. To change it, send `PUT /v1/queue/lanes/{lane}` for
   `run`, `voice` or `image`, with `X-Studio-CSRF` from the current
   `GET /v1/me` and `Content-Type: application/json`. Use
   `{"paused":true}` to pause or `{"paused":false}` to resume.
   Read the same lane back. Paused lanes take submissions and
   return 204 to new claim polls. In-flight claims can finish. A 204 alone
   cannot distinguish idle from paused. Preserve the request ID on a refusal.
   **Expected** for an installed person's pause/resume. [Queue controls](../reference/studio-api.md#queue-controls) ·
   [Generated API reference](../reference/api-reference.md) ·
   [Installed worker and lane evidence](https://github.com/thaynes43/haynes-ops/blob/main/docs/reference/studio-deployment.md#worker-lane-grants)
2. In **Editor → Board → Runs**, open the run's **Details**. The scoped HTTP
   reads are `GET /v1/stories/{id}/runs` and `GET /v1/runs/{id}`. Check queue
   position, stage, status, reason, error and Wan attempt ID. For voice or
   image jobs, use `GET /v1/boards/{id}/jobs` or `GET /v1/jobs/{id}`.
   A signed-in person can also read candidate jobs. `gpu_unavailable` means
   the run worker has gone at least 90 seconds without a check-in or renewal. **Paused ·
   Held** is a run reconciliation state. The FIFO head stays in place until
   the worker settles it. Check the saved Wan job ID through the Wan API
   and preserve it after an ambiguous reply. A terminal `failed` run
   retains its evidence. Correct the cause and queue a new snapshot if a
   replacement is needed. [Run queue](../reference/run-queue.md#public-http) ·
   [Media jobs](../reference/studio-api.md#media-operations)
3. On worker restart, the 90-second claim deadline and fence survive in
   Postgres. The replacement gets a fresh fence and reconciles the same
   run and recorded Wan ID before dispatch. The old fence can no longer
   write. A media job may be reclaimed if it had yet to dispatch. After
   a recorded dispatch, expiry fails it with `work.dispatch_unconfirmed`.
   Before any fresh image request, verify the engine is idle. These
   recovery cases are **Proven in source tests**. An installed restart of
   a worker with a claimed job is **Expected**. [Run reconciliation](../reference/run-queue.md#claims-and-reconciliation) ·
   [Media claim recovery](../reference/media-jobs.md#claims-and-results)

The voice, image and run workers have **Proven** installed progress, idle
claims and engine reachability. The installed tokens passed wrong-lane denial
checks, and schema `0012` adds release and archive integrity constraints.
**Changed** after the first image worker rollout, the shared ComfyUI policy
selector needed repair before the image worker reached the engine.
[Lane installation and repair, comments 9993 and 10002](https://work.haynesnetwork.com/work_packages/961) ·
[Lane grants](https://work.haynesnetwork.com/work_packages/962) ·
[Schema constraints](https://work.haynesnetwork.com/work_packages/963) ·
[Installed token probes](https://work.haynesnetwork.com/work_packages/964)

## Capacity and private media

- Household jobs come first on shared ComfyUI. Read `GET /queue` and confirm
  both running and pending lists are empty before a Studio image submission.
  Keep one prompt in flight. Leave other work and loaded models alone.
  [Shared image service](../reference/services.md#comfyui-images)
- For heavy work on the 3090s, read Wan `GET /v1/ready`, check video and Foley
  activity, and let Wan verify the engine queue, GPU conditions, render hold
  and compute lease. Wan/Foley and any local model use that one lease, one
  job at a time. Busy, unreadable or unknown work stops admission. Check a
  saved job ID after a lost reply. [Wan API and readiness](../reference/wan-product-api.md#availability) ·
  [Admission refusals](../reference/wan-product-api.md#admission-refusals)
- On `talosw01`, offline render has 20 low-priority vCPUs with up to 18
  offline workers and the serial queue worker has four vCPUs. Keep two
  media threads in a session pod. Check store and staging headroom before
  heavy work. [Render limits](../reference/services.md#studio-render-cpu-work)
- Keep masters, phone proxies, uploads, voice, staging and packages in
  private cluster storage. Use authenticated playback on the LAN. Preserve
  every finished archive. A new attempt uses a new run or private job
  directory and create-only output. Keep receipts, hashes and operational
  notes in git. Keep all media and credentials out of git.
  [Private playback](../reference/studio-api.md#private-playback) ·
  [Store layout](../reference/studio-recovery.md#share-contents-and-regeneration)

**Proven** read-only at 12:40 UTC on 2026-11-25. Shared ComfyUI returned
zero running and zero pending entries. Wan reported `ready: true` with
`active_video_job: null` and `active_foley_job: null`. Check again before
submission. [Service read paths](../reference/services.md)

## Access

| Caller | What it may do |
| --- | --- |
| Signed-in person | Read and edit in scope, queue and cancel builds, request media jobs, promote, leave feedback, prepare a private package, set lane pause and record the supported visual override. |
| Tom | Go-live for the exact eligible run and master through `go_live:approve` and fresh sign-in. The installed allowlist is empty. Studio has no platform publishing integration. |
| Agent key | Only active grants for `read`, `draft:write`, `assets:generate`, `assets:upload`, `runs:queue`, `archive:read` and `archive:write` in scope. An explicit `formats:write` grant allows catalog authoring. The temporary import-proof keys were revoked. |
| Worker token | One internal lane grant per worker ID (`run`, `voice` or `image`). The matching worker authenticates to claim, heartbeat and settle work under its fence. |

[API identity and scopes](../reference/studio-api.md#browser-agent-and-worker-requests) ·
[Worker grants](../reference/studio-api.md#worker-token-administration) ·
[Go-live](../reference/go-live.md#identity-and-sign-in)

## Backup and recovery

**Proven** backup status covers Studio metadata in the shared CNPG daily
base backup and continuous WAL, with a 30-day recovery window. VolSync is
the policy for small PVCs. Studio has no such claim. D47 excludes the gasha01
NFS media store, staging and archived media. Uploaded and hand-made originals
need surviving bytes. A receipt alone gives the expected hash.
[Coverage and exact reads](../reference/studio-recovery.md#coverage) ·
[Archive receipts](../../titles/one-more-meeting/run-evidence.json)

1. For a lost database, stop writes and record the last good UTC target and
   known engine jobs. Have the database owner restore the base and WAL into a
   new isolated cluster, then extract Studio to a separately named database.
   Verify schema, scoped access and changes in authorization since the target.
   [Lost database procedure](../reference/studio-recovery.md#lost-database)
2. For lost media with Postgres intact, keep the database, hold build consumers
   and confirm the mount. In either case, inventory the matching database and
   store against expected locators, hashes and sizes. Keep unreferenced files
   for reconciliation. Use the bounded manual catalog and store check until
   the dedicated audit command exists. [Lost media procedure](../reference/studio-recovery.md#lost-media-database-intact) ·
   [Detect missing media](../reference/studio-recovery.md#detect-missing-media)
3. Reconcile held and in-flight work with the surviving Wan ledger and stage
   records before resuming workers. Check post-target approvals and withdrawals
   with Tom. Use an exact copy only after size and hash verification. Rebuilt
   outputs with changed bytes get a new run and approval applies only to
   its recorded run and master. [Recovery order](../reference/studio-recovery.md#recover-in-order)

The isolated restore drill is **Expected**. It stopped at Tom's decision on
archive credential scope before a restore ran.
[Drill procedure](../reference/studio-recovery.md#isolated-restore-drill-for-op436) ·
[Credential decision, comment 10072](https://work.haynesnetwork.com/work_packages/436)

## Remaining gaps

| Step | Why it is open | What would prove it |
| --- | --- | --- |
| LAN playback, new work and lane pause/resume | Installed reads cover signed-out ingress, scoped imports and worker readiness. Person-only controls and first real jobs await a session. | A person's session plays both phone proxies, pauses and resumes lanes without losing queued work, and completes a real private run, voice take and photo. [User journey](studio-user-journey.md) · [OP961](https://work.haynesnetwork.com/work_packages/961) |
| Worker restart and API replacement with saved work | The API pod drill had no saved selections or queued snapshots. Claimed-job worker recovery has source evidence. | Observe a bounded, authorized recovery with real saved work, including preserved IDs and no duplicate dispatch. [OP437](https://work.haynesnetwork.com/work_packages/437) |
| Isolated database restore | OP436 awaits Tom's archive credential decision. | Run the authorized isolated drill and compare catalog and media references before teardown. [OP436](https://work.haynesnetwork.com/work_packages/436) |
| Local model on Wan | The first activation was reverted. The model is dormant and activation two is held. | Tom's authorization, then the activation and bounded leased handover smoke. [OP442, comment 10010](https://work.haynesnetwork.com/work_packages/442) |
| Matting, segmentation, matte jobs and occlusion | Verified matting and segmentation weights and passing smokes exist. No sidecar serves in the third pin and matte job wiring is separate. | Install the approved backends and matte job consumer, then inspect a real private cast-photo matte and occlusion trial. [Matting](https://work.haynesnetwork.com/work_packages/459) · [Segmentation](https://work.haynesnetwork.com/work_packages/460) · [Matte jobs](https://work.haynesnetwork.com/work_packages/965) · [Occlusion](https://work.haynesnetwork.com/work_packages/452) |
| Upscaling | The upscaling backend is outside the installed pin. Delivery uses Lanczos. | Verify approved service installation and compare real private output against the delivery baseline. [OP461](https://work.haynesnetwork.com/work_packages/461) |
