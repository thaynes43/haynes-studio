# Studio recovery

[OP435](https://work.haynesnetwork.com/work_packages/435) records coverage and
recovery steps. The isolated restore drill belongs to
[OP436](https://work.haynesnetwork.com/work_packages/436).

## Coverage

| Data | Protection | Read-only evidence on 2026-11-25 |
| --- | --- | --- |
| Studio metadata | The `studio` database is on CNPG `database/postgres16`. The `postgres` ScheduledBackup uses `@daily`. Barman writes cluster-wide physical base backups and continuous WAL to S3 at `s3://cnpg-haynesops/`, under `postgres16-v6`, with a 30-day recovery window. | The first completed base containing Studio and both imports is `postgres-20261125000000`, Barman ID `20261125T000000`, created by Kubernetes at 2026-11-25 05:00Z. The previous base predates Studio and needs WAL replay past its creation. [Story 435](https://work.haynesnetwork.com/work_packages/435), comments 9887 and 9948. |
| Small Studio PVCs | VolSync is the policy for any future small Studio claim. | No Studio PVC exists in `ai`. No claim is mounted by `studio-api`, `studio-web`, `studio-mcp`, `studio-worker` or `studio-render`. The API, worker and render mounts use raw NFS. |
| Media | **NFS media is not backed up (D47).** | The share holds the canonical store, build staging, old job directories and finished archives listed below. |

The Backup's Barman start and stop fields read 00:00:00Z to 00:01:37Z.
Use the Kubernetes creation timestamp to identify the daily trigger.
The first base containing Studio was taken after the 03:42Z imports.
The tracker records three Ready instances and continuous archiving.
The isolated restore remains due in story 436.

WAL archiving was healthy at the check. CNPG reported `ContinuousArchiving=True`,
`LastBackupSucceeded=True` and 3 ready instances. The primary's
`pg_stat_archiver` reported WAL `000000580000034C0000008D` archived at
`2026-11-25T01:58:08Z`, after Studio provisioning, with no failure recorded
in that statistics view. These are status and freshness checks. Select a
recovery target using the cluster owner's archive continuity checks.
[D39 and D47](../proposals/0003-studio-plan.md#decisions-so-far) ·
[CNPG backup scope](https://cloudnative-pg.io/docs/1.30/backup/#main-concepts)

To refresh the evidence, run the following and select the `postgres16`
cluster, `postgres` schedule and latest completed Backup for that cluster.
Record only backup identifiers, times, status and archiving evidence.
Use the tracker record above for the first completed base after provisioning.

```sh
kubectl -n database get backups,scheduledbackups
kubectl -n database get backup "$backup_name" \
  -o 'custom-columns=CLUSTER:.spec.cluster.name,OWNER:.metadata.ownerReferences[*].name,CREATED:.metadata.creationTimestamp,ID:.status.backupId,PHASE:.status.phase,START:.status.startedAt,COMPLETE:.status.stoppedAt'
kubectl -n database get cluster.postgresql.cnpg.io postgres16 \
  -o 'custom-columns=READY:.status.readyInstances,LAST:.status.lastSuccessfulBackup,CONDITIONS:.status.conditions[*].type,STATUS:.status.conditions[*].status'
```

## Share contents and regeneration

Paths are relative to the Studio NFS root, which `studio-render` mounts at
`/studio`. The API mounts `api-store-v1/` as its `/studio`. The worker reads
that store and shares `build-stage-v1/` with the API at `/build-stage`.
[Deployment and mounts](https://github.com/thaynes43/haynes-ops/blob/main/docs/reference/studio-deployment.md)

| Path | Contents |
| --- | --- |
| `api-store-v1/library/sha256/` | Shared library blobs, including cast and set stills, reference photos, cutouts, motion loops and source sound. |
| `api-store-v1/productions/<production_id>/sha256/` | Production input assets, board photos and voice takes/tracks, canonical run snapshots, and delivery masters, proxies and JSON records. |
| `api-store-v1/productions/<production_id>/records/`, `api-store-v1/.staging/`, `api-store-v1/.probe/` | Delivery stage records from the store adapter, temporary publication parts and startup probe files. |
| `build-stage-v1/<run_id>/` | Worker build tree. It holds staging inputs, clips and their engine records, keyed frames, composites, segments, picture, mix and checks, cache/stage records and the candidate delivery. PostgreSQL records run progress and the final delivery. Much of the intermediate data stays on this filesystem. |
| `jobs/` | Older manual jobs with hand-prepared layers/decals, source material, voice, sound, clips, keyed frames, renders, checks and local receipts. |
| `productions/` | The finished E1 archives, with the exact cuts and private run, delivery and provenance sidecars. |
| `code/`, `.venv/` | Render tooling and environment. Recreate from the pinned source, lock and installed toolchain. |

For each missing file, look for surviving bytes at the recorded hash first.
The [legacy input recovery map](legacy-recovery-map.md) records known sources
for older inputs. Use that source only after size and SHA-256 verification.

- **From Postgres alone.** The restore recovers metadata committed by the
  chosen target. The product `runs.snapshot` holds the frozen story, boards and
  input pins by value, with the frozen library in `runs.frozen_library`.
  Serialize the snapshot through `snapshot_bytes()` and verify its recorded hash
  and locator to recover the JSON blob byte for byte. Derive its expected size
  from those canonical bytes. A canonical delivery JSON blob can be recovered
  in the same way from `deliveries.document`. Check any document hash recorded
  in the stage record. Private stage, cache, archive and engine sidecars need
  their own records or inputs.
- **Generated inputs and clips.** Asset `provenance.generator` can name the
  prompt or prompt reference, seed, source IDs/hashes, workflow and model-file
  digests, parameters and engine job ID. Read the run snapshot and provenance in
  `runs.document` for the engine profile, model-file digests, hardware and
  toolchain. Check the saved Wan attempt requests and outcomes. A missing pin,
  external workflow, unavailable model or missing source limits reconstruction.
  The ComfyUI photo adapter records its filled workflow digest and has no
  engine-reported weight digests. Wan, image and generated sound outputs can
  differ on another execution. Voice synthesis needs the exact text, voice,
  engine and settings. Treat a voice take as new bytes unless its hash matches.
  Approximate generations get new hashes and new asset versions or a new run
  delivery. The catalog preserves old versions and pins. Select or promote a
  replacement version explicitly.
- **Derived outputs.** With the input bytes and pinned settings and toolchain,
  rebuild layered reference composites, assembled voice tracks, keyed frames,
  segment and film renders, deterministic checks, mix, master and proxy. The mix
  needs the same takes or tracks, sound and placement. The master also needs the
  original picture packets. The proxy needs the master and pinned encoder.
  Accept an exact reconstruction only when the hash and byte count match. The
  Winter Menu exact rebuild had surviving audio and picture inputs and matched
  mix, master and proxy. ASR and other engine checks can be rerun with their
  inputs and service, subject to engine reproducibility.
  [Winter Menu exact rebuild](../../titles/the-winter-menu/e1-build/recovery-20261121/README.md)
- **Scratch and caches.** New runs recreate build scratch and cache entries from
  verified inputs. The API recreates probe data. Postgres records run progress
  and output references. Recovering the original staging parts, cache records,
  local ASR results or legacy Wan journal requires surviving files. A lost
  journal requires reconciliation with the engine before reusing that lane.

See [board photos](studio-photo.md), [mix](studio-mix.md),
[delivery](studio-delivery.md) and the [run queue](run-queue.md) for the
recorded fields and build boundaries.

### Open loss risk for Tom

Original uploaded or imported reference photos and other hand-made source
bytes require a surviving original or an exact copy. A prompt, received hash
or provenance declaration cannot reconstruct a photo. The D42 uploader
keeps the normalized PNG and records the received digest. These are separate
bytes. Likewise, legacy hands-on edits and the exact E1 archives cannot be
recreated from Postgres alone. A new cut from the same brief remains a new run.

| Exposure | Measured file bytes on 2026-11-25 |
| --- | ---: |
| Product catalog uploaded/imported content | 0 cataloged blobs, 0 bytes at the check. This does not count uncataloged originals in legacy input directories or outside the share. |
| Old manual job `jobs/winter-menu-video-v2/` | 1,834,465,321 across 2,751 files. This counts the whole job, including hand-prepared inputs, intermediates and outputs. The unique hand-made subset is unmeasured. |
| The Winter Menu, quieter-gavel archive | 73,638,915 across 5 files. |
| One More Meeting archive | 10,102,482 across 10 files. |

The measurements count logical regular-file bytes. The
[archive receipt](../../titles/one-more-meeting/run-evidence.json) records both
archive totals and hashes. An imported catalog entry preserves the metadata
for these archives. The exact cut and sidecars still require surviving bytes.

## Detect missing media

Use the restored database and the matching store root. Compare each canonical
locator, its expected SHA-256 and its size where known. Checks of the public
metadata alone do not establish presence.

| Catalog data | Expected file evidence |
| --- | --- |
| `deliveries.document` and `delivery_media` | Canonical master/proxy locators, hashes and byte sizes. Derive the canonical delivery JSON hash, locator and size from the product delivery document as above. Legacy ledger locators are external and need the separate legacy audit. |
| `asset_versions.document` and `asset_media` | Content and board voice track locators, hashes and sizes. Take hashes have derived WAV locators and sometimes no size. Definition-only voices require no file. Include candidates and historical versions. |
| `runs.document.snapshot`, `runs.snapshot` and `runs.frozen_library` | The recorded snapshot hash and locator, with canonical size computed from `runs.snapshot` and a check that the row itself hashes to the pin. Include frozen input pins that may differ from the current draft. |
| Canonical stage records | Include their blob locators, SHA-256s and sizes. Track staging files, temporary parts and unexpected paths separately from unreferenced canonical blobs. |

For a known locator, `LocalStore.verify()` opens the file safely and re-hashes
it. Compare the file's size on the same descriptor when the catalog provides
one. `LocalStore.doctor()` already inventories and hashes the local store and
checks stage references. It takes externally referenced locators but does not
check all DB rows. A media GET or HEAD checks the locator and recorded size
after authorization and can detect absence of that item. It does not re-hash
served bytes. The worker's pre-build checks re-hash input pins.
[Store checks](store-and-stages.md) · [Playback](studio-api.md#private-playback)

**OP436 requirement.** Expose a read-only operator command
`studio-api-admin audit-media --store-root <absolute-path> --format json`,
using a read-only Postgres DSN in `STUDIO_DATABASE_URL` and schema in
`STUDIO_DATABASE_SCHEMA`. Open a read-only repeatable-read catalog snapshot
and traverse the store without following links. Run against a quiesced store so an in-flight
publication cannot appear unreferenced. Produce one private JSON report with
counts and lists of `missing`, `mismatched`, `unreferenced`, `unreadable` and
external references. Give the affected IDs, relative locators, expected hashes
and sizes, actual values on mismatch, and error codes. Report unknown sizes as
null. Label missing items with their known prerequisites or unknown recovery
status. Return `0` for a complete clean scan, `1` for a complete scan with
missing, mismatched or unreferenced content, or `2` for invalid inputs or an
incomplete scan such as a database, mount or read error. It deletes, repairs
and rewrites nothing. [OP436](https://work.haynesnetwork.com/work_packages/436)
owns this requirement and the isolated fixture used to exercise it. The command
is a specification. Today an operator can combine the read-only catalog
inventory with `LocalStore.verify()` and `doctor()` for a bounded manual check.

## Recover in order

### Lost database

1. Have the service owner pause the Studio worker and other write paths before
   reconnecting anything. Record the last known good UTC target and current
   engine jobs. Ask the CNPG owner to select a base whose end is at or before
   the target, verify the full archived WAL span to that time and follow the
   existing owner procedure. Restore into a new isolated physical cluster.
   Extract only the Studio database into a separately named replacement
   through the approved database-owner process. Verify the schema, scoped
   grants, references, and any authorization or revocation changes after
   the target before allowing clients to reconnect. Preserve the originals.
   [CNPG owner playbook](https://github.com/thaynes43/haynes-ops/blob/main/.agents/runbooks/tier4-component-playbooks.md#cnpg)
2. With workers still paused, run the detection check against the selected
   database and matching store. Investigate unreadable paths and size/hash
   mismatches first. Bytes written after the database target may show up as
   unreferenced. Keep them and the report for reconciliation.
3. Reconcile nonterminal runs before reenabling any build consumer. The queue
   keeps the FIFO head, fenced claim, reserved job ID, exact request, send
   marker and outcome in Postgres. For a retained attempt, it reads that same
   Wan job first. With confirmed absence it can replay the same ID and body
   under the documented fence, readiness and lease rules, which deduplicate
   a delayed or lost reply. A point-in-time rollback can hide intent, job IDs
   or terminal outcomes written later, and the engine or staging store can
   outlive the database. The worker cannot deduplicate a job whose attempt ID
   has vanished. Reconcile each affected head with Wan's job history and
   surviving staging/run records, including completed jobs. Keep the lane
   paused if any job or finalization is ambiguous. A clear live engine queue
   alone does not reconcile completed work.
   [Queue reconciliation](run-queue.md#claims-and-reconciliation)
4. Restore Studio's metadata reads once the owner has checked database access
   and store readiness. A finished run with deleted canonical media still
   shows its recorded status, checks and delivery metadata. Authenticated
   media fetch returns 404 for absent bytes (503 on certain store I/O
   failures). The metadata remains readable when the store is mounted and
   ready. In the OP414 web source, the Productions player reports “This
   video could not be played.” Imported external ledger deliveries have their
   own unavailable message. The source has no persistent missing-media badge.
5. Check surviving copies and deterministic recovery against the original
   hash. If the exact bytes are unavailable, create or import replacement
   inputs as new versions, select them on a current draft and queue a new
   run with a new idempotency key. This creates a new delivery. For a manual
   production use a new private job directory and production ID. Preserve
   the old run, delivery, hashes and finished archive. Approval binds to
   the old run, delivery and master SHA-256. Recovery creates or transfers
   no approval. After a database rollback, have Tom and the service owner
   reconcile approvals and withdrawals after the target before treating a
   restored approval as active for release. A withdrawal written after the
   target can be absent from the restored database. Keep release on hold for
   any approval whose later history cannot be established. A rebuilt master
   with a different hash requires a new approval, and a distinct run never
   inherits the original decision even when its bytes match.
   [Go-live approvals](go-live.md)

### Lost media, database intact

1. Keep the database and put build consumption on hold. Confirm the actual
   NFS mount or replacement root before treating empty paths as missing.
2. Run the same inventory against the intact catalog and available media.
   Reconstruct exact snapshot JSON from Postgres where needed. Reconcile
   queued/held runs and in-flight engine or publication state before resuming
   workers. The worker verifies the snapshot blob before rendering and fails
   pre-build with `run.snapshot_changed` if it cannot match it.
3. Apply the readback, replacement and approval rules above. Reuse verified
   bytes by hash. Rebuild unavailable outputs as a new run. Leave the exact
   archive losses open if their original inputs or records are gone.

## Isolated restore drill for OP436

Proposed targets for the coordinator and CNPG owner to authorize and check
for collisions. Use the existing owner path for the selected source backup.

- Restore one temporary, single-instance CNPG clone named
  `postgres16-op436-restore` in the `database` namespace, isolated from Studio
  and other clients. Use the existing Barman source in read-only mode with a
  fresh target lineage name and no archive writes from the clone. A physical
  backup restores the whole source cluster, including other databases and
  role metadata. Keep the clone private even to Studio. Extract only
  `studio` into a new database named `studio_op436` with one drill-only role
  `studio_op436_drill`. The owner provides its isolated connection. Limit
  the role to the new database and drill schema. Reconnect a disposable API
  read path using a drill-only test identity, with no worker or Wan access,
  no production ingress, no live credential projections and no production NFS
  mounts.
- Use a new private folder `/studio/recovery-drills/op436-01/`, mode `0700`,
  with a private store and staging subfolder. Use at most one synthetic
  missing-media fixture with one present blob and one intentionally absent
  reference. Check snapshot serialization, delivery and approval links,
  metadata views and absent-media reporting, and that no engine submission
  occurs. Use the read-only scan before and after fixture setup as appropriate.
- At preflight, `studio` occupied 8,696,291 bytes and the sum of connectable
  databases was about 1.52 GB. Logical sizes do not bound physical restore
  or WAL bytes. Proposed hard caps are **8 GiB** of temporary cluster storage,
  **4 GiB** of total selected archive reads including WAL, **64 MiB** for
  the Studio logical transfer and **1 MiB/16 files** for the private fixture.
  Require at least **2 GiB and 100,000 inodes** in reserve after budgeting.
  Require the owner to measure archive, WAL and destination headroom and
  verify the caps can be enforced before starting. Stop on unknown size,
  exceeded cap or target collision. Allow **90 minutes** for the restore and
  data transfer within OP436's three-hour cap, with time reserved for
  verification and cleanup. One attempt, two local CPU threads, zero GPU.
- The owner removes the disposable API, drill database/role, clone/PVCs and
  only the drill-created folder after recording evidence. On failure record
  the stage, elapsed time and objects left for that owner. Verify production
  targets and backup retention stayed intact. Keep only redacted output,
  counts, timestamps, hashes and checks in the evidence PR.
