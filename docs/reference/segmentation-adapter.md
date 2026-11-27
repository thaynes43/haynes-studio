# Studio segmentation adapter

`haynes_studio.assets.occlusion.run_segmentation_job` observes one authorized,
stored still with the pinned CPU service. The job caller supplies the library
slice, source version ID, production scope (`None` for the shared library),
target `kind` and `key`, a `label` (required for props), and an optional `hint`.
Use a set's opaque plate for a foreground or plate prop target, a prop cutout
for a standalone prop, or a cast cutout for a face. Point and box hints use
coordinates in the source still.
[Segmentation request and result contracts](segmentation-backend-profile.md#artifact-contract-for-story-452)

The adapter reads the pinned still and verifies its hash, media type, dimensions
and alpha before hashing the canonical request. Labels and text hints are
trimmed and normalized to NFC. The ready lookup uses the production scope,
source version ID, request hash and profile manifest hash. The adapter keeps
its own copy of the comparison key and checks the returned record against it.

## Dispatch and verification

The client serializes work with a regular-file lock on the shared
`/segmentation` volume. Before dispatch it compares HTTP 200 and the entire
readiness body with the pinned profile ID, manifest hash and CPU device. Each
dispatch stages the still under a fresh attempt ID and uses the local Unix
socket. Lock contention and a confirmed service `busy` each allow up to 13
waits of five seconds, with a claim check before each retry. A transport failure
keeps the attempt staged until the service deadline and cleanup grace pass.
[Unix socket protocol](segmentation-backend-profile.md#backend-source)

The adapter verifies the reply envelope, canonical receipt bytes, request
binding and pinned provenance. A ready mask must agree with the receipt's PNG
descriptor and tight bounding box, meet the profile's score floor, and have
binary source-sized pixels. Its support must stay within the available cutout
alpha and include any supplied point hint. Grounded foreground masks must meet
the backend's bottom-row coverage prior, which point and box hints bypass.
Fresh and cached ready results both read the receipt and PNG back from the
store and verify the locator scope, media type, length and digest before
returning a `VerifiedObservation`.

## Publication and claim fence

On a fresh ready response, the adapter publishes the mask, then the receipt,
using create-only content-addressed storage. It verifies both stored artifacts
before asking the caller to commit a ready record. `needs_hint` and failed
receipts go to the diagnostic writer, leaving the ready key available. The
caller provides a current-only ready lookup and writers that enforce the claim
fence atomically. The adapter rechecks the claim before dispatch, publication
and writes, and after reading a cached completion.

Source tests exercise the production socket handler and inference flow with a
fake graph and synthetic stills. Private model-quality evidence is pending.
[Story 452](https://work.haynesnetwork.com/work_packages/452)

[Story 968](https://work.haynesnetwork.com/work_packages/968) defines the stored
role pins. [Story 975](https://work.haynesnetwork.com/work_packages/975) owns the
[film visibility check](film-visibility.md).

## Occlusion jobs

A signed-in person submits `POST /v1/asset-jobs/occlusion` with a session CSRF
header and `Idempotency-Key`. The body names one `source_version_id`, target
`kind` (`foreground`, `prop` or `face`), `key`, and optional `label` and `hint`.
A standalone prop or a prop on an opaque plate needs a label. A face uses a
cast cutout. Point coordinates are zero-based. Box right and bottom edges are
exclusive.

When `kind` is `prop` and the named set has a `focal_props` entry matching
`key`, the job uses the stored label and hint. Omit both fields in the request
for that target. A `separate` prop uses its declared source version. Other
focal props use the set still. A separate source must be a prop cutout from
the set's production or the shared library. The mask and receipt use the set's
scope when a set anchors the job. Direct requests use the source's scope.

The queue signs the frozen source version, decoded still dimensions, target,
profile manifest and output scope. The same key and body return the original
job, even when new admissions are disabled. A different body under that key
fails. A replacement claim gets a new fence and retains the frozen inputs,
including after an interrupted dispatch. The worker serializes segmentation
attempts through the shared scratch lock. Completion re-reads the still,
receipt and mask and commits the library version with the job transition in
one transaction. Attempt blobs are content-addressed and create-only.

`GET /v1/jobs/{id}` adds the request and provenance under `occlusion`.
Production-scoped `studio_get_job` returns the same metadata. A verified
`needs_hint` or `failed` reply ends the job with the receipt hash and reply
status in `error.diagnostic`. An adapter failure without a verified stored
receipt records only an error code and message. Only a verified ready reply
produces a mask version. A person can submit a corrected target with a new key.
For a stored focal prop, put the corrected hint in a new set version first.

A successful `GET /v1/jobs/{id}/result` returns a promoted library version
with only the `mask` capability. Its `segmentation` field binds the source
version and still hash to the request hash, profile hash and receipt hash.
A set author can pin it in a new set version using the
[foreground role contract](foreground-roles.md). The job leaves the draft's
selection untouched.

## Activation dependencies

**Expected.** A separate activation story applies Alembic `0014_occlusion_jobs`
and pins Studio API and worker images containing this source. The migration
adds a lane row and expands the existing check constraints. It takes the
same bounded prelocks as `0013_matte_jobs` and creates no worker identity.

1. Run `studio-segmentation serve` with the independently approved CPU image
   pinned by digest and set `STUDIO_SEGMENTATION_IMAGE` to that image reference.
   Mount the verified model bundle read-only at `/opt/studio-models` and use
   the [profile's resource limits](segmentation-backend-profile.md). The
   sidecar serves `/segmentation/segment.sock` and advertises the exact profile
   hash and CPU device. Use the raw `profile.json` bytes and digest from the
   verified bundle for the API and worker mounts.
2. Start `studio-worker --lane occlusion` beside the sidecar. Share a writable
   `/segmentation` volume with matching group permissions for the socket and
   staged attempts. Mount the Studio store read/write in the Studio worker.
   Give the sidecar only its scratch and read-only model mounts. The worker
   needs `STUDIO_API_URL`, `STUDIO_STORE_ROOT`, `STUDIO_WORKER_TOKEN`,
   `STUDIO_SEGMENTATION_MANIFEST` (path to read-only `profile.json`) and
   `STUDIO_SEGMENTATION_PROFILE_SHA256`. Verify TLS or listener network scope
   and the worker-only API route. Any new workload identity, credential,
   grant or ingress peer requires Tom's decision. The worker token needs the
   `occlusion` lane grant and belongs only in the Studio worker.
3. Confirm the worker and sidecar match the exact readiness tuple. To enable
   new admissions, put the same manifest and digest in the two
   `STUDIO_SEGMENTATION_*` settings on every API replica. API readiness and
   the existing lanes have no sidecar dependency. Before changing profiles,
   disable new admissions, drain the FIFO with the pinned worker, then pause
   the lane for the switch. Resume after the replacement passes readiness.
4. Record installation and the private functional smoke in the activation
   story. Tom owns acceptance.

[Story 971](https://work.haynesnetwork.com/work_packages/971) ·
[CPU serving contract and OP460 smoke](segmentation-backend-profile.md)
