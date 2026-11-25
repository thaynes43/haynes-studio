# Asset candidates and library promotion

`haynes_studio.assets` plans, generates and records one cast, costume, set or prop
still per job. It produces standard library records. Generation runs through the
same Qwen-Image 2.1 client as board photos, with one text-to-image request at the
client's default 1104×1472 size. The shared image lane checks the queue before
submission. [Story 408](https://work.haynesnetwork.com/work_packages/408) ·
[Image lane](services.md#comfyui-images)

## Plan, generate and record

1. Reserve a `job_` ID and an `ast_` ID. Call `plan_candidate(job_id=..., asset_id=...,
   kind=..., name=..., production_id=..., prompt=..., seed=..., by=..., labels=...)`
   with the authenticated human principal. Use an explicit `production_id=None`
   for a global asset. The plan freezes the validated name, labels, scope, prompt,
   seed, requester and requested size. Its `input_signature` is scoped to the
   reserved asset ID.
2. Under the image queue claim, look up `candidate_result(library, plan)` before a
   submission. An already recorded job returns its version, even after promotion.
   A reused job ID with other inputs raises `idempotency.mismatch` with status
   `conflict`. Call `generate_candidate(plan, client=..., licences=...)` when the
   job has no recorded result and the claim allows submission. The function
   checks the engine's digests and decodes the output as a metadata-free RGB PNG.
3. Call `record_candidate(prepared, library, store=..., now=...)` from the latest
   library state under the completion fence. It validates the asset and version,
   publishes the PNG with `Store.publish` create-only, and returns the new library
   and version. The version has number 1 and source key `asset-candidate:<job_id>`.
   An exact retry returns the recorded version without another write. Different
   output under the same job ID raises `idempotency.mismatch`. Persist the returned
   metadata and the job's succeeded result together.

The version pins the stored PNG's digest and records its actual dimensions and byte
count. Its generator provenance records the engine and model, filled workflow hash,
normalized prompt, seed, engine job ID, original engine PNG hash, timing and input
signature. The licence comes from the supplied register or is unknown. Cast, costume
and prop PNGs have `opaque_photo`; a set PNG has `opaque_plate`. These describe the
opaque still and leave cutout, mask, keying and motion capability to their own stages.
[Model licence register](model-licences.md) · [Library records](studio-library.md)

## Cut out an existing still

[Story 965](https://work.haynesnetwork.com/work_packages/965) adds a matte
candidate job for a pinned library PNG or JPEG with the `opaque_photo`
capability. In the Assets page opened in a story, **Cut out** shows on
eligible versions, including image candidate results. The form shows the
story's pinned format version and offers the cast slots defined in its
`cast.matte_slots`. Update the story's format pin to a recipe with explicit
slot sizes to enable the action.

A press sends the source version ID, format version ID and selected slot.
An uncertain reply keeps the request and its key in the open Assets page.
If a retry is refused, keep using **Retry matte request** in that page to
recover the original job. Reloading before the job link appears clears the
saved key. A new press after reload can queue a second cutout because the
API can only look up a matte job by its ID. Once you have the job link,
reload it to read the queued, paused, running or terminal state.
An admitted source and the result stay in the same library scope, including
the shared library. A successful result opens the existing candidate review
and its explicit **Promote** action. The source stays pinned and the job
does not select a board asset. The matte lane and the image lane claim work
independently. [Matting adapter](matting-adapter.md) · [Worker protocol](media-jobs.md)

## Promotion and retention

| Action | Version state afterward | Normal picker | Private result |
|---|---|---|---|
| Record a successful candidate job | `candidate` | Hidden | Version and PNG retained |
| Choose Not now or generate again | `candidate` | Hidden | Previous version and PNG retained |
| Explicit human `library.promote(library, version_id, by=..., now=...)` | `promoted` | Visible in scope | Same version, pin, provenance and capabilities |
| Retry promotion | `promoted` | Visible in scope | Same record returned |

Choosing **Not now** hides the preview in the current tab and records no server
decision (CR-14, provisional CR-44). **Review again** reopens it in that tab.
Generate again starts a new job and reserves a new asset ID. Promotion changes
only the version's state. A board still pins a version ID. For a whole-frame
reference photo, add the promoted version ID to `photo.input_asset_version_ids`
and pass the draft to `plan_photo`.
[Board reference photos](studio-photo.md)

## API and UI integration

- The API reserves the asset ID and saves the plan signature and frozen request
  as a `studio.job/v1` candidate job. The worker checks for an existing result
  before submitting. The fenced completion writes the asset, version and job
  outcome together. If a dispatched claim expires, its job fails and the
  shared image lane checks for outstanding ComfyUI work before a new submission.
  [Worker protocol](media-jobs.md#claims-and-results)
- Signed-in people generate and promote candidates using the
  [media operations](studio-api.md#media-operations). Read the result version
  metadata before previewing its content through the
  [private playback routes](studio-api.md#private-playback). Normal library
  search and board pickers use eligible versions in scope.
- The Assets page opens on the references of the board in the
  [composer's handoff URL](photo-composer.md#assets-handoff). The `scope` parameter
  can widen the view to `story`, `production` or `library`. A story combines its
  direct pins and all its boards' references. `target` can select another board
  in that story. `q` and `kind` filter the versions returned for the scope.
  Removing a scope chip keeps the target. The saved Assets destination keeps scope,
  target and kind. Using a promoted still returns its exact version ID to the composer.
- Assets reads the image or matte lane and follows the job in the `job` URL
  parameter. Open a candidate's job link to review or promote its result. If the
  job read is refused, polling stops and a new request is available. Job IDs travel
  between the library and generation views after a successful read. The API exposes
  individual job results and has no candidate history listing.
  Promote sends a bodyless request keyed by the immutable version ID. Uploaded
  board photos are available through Board photo history and promote as a new
  reusable version.
- Candidate job previews use the job media route. Photo and board voice previews
  use the version route. Other promoted media uses the hash route, except a
  generated or matted global still can use its source job. Unreferenced global media without
  a source job may show an unavailable preview under the current media policy.
  Recorded-only versions show their metadata. All previews use the session cookie.
  [Library UI story 456](https://work.haynesnetwork.com/work_packages/456)

## Validation

`STUDIO_THREADS=2 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 uv run --no-sync pytest tests/assets`
uses the fake ComfyUI transport and the create-only local store under `tmp_path`.
The integration test promotes a synthetic still and passes it through the
whole-frame board-photo edit path as a pinned reference.
