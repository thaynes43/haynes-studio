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

## Promotion and retention

| Action | Version state afterward | Normal picker | Private result |
|---|---|---|---|
| Record a successful candidate job | `candidate` | Hidden | Version and PNG retained |
| Decline the preview or generate again | `candidate` | Hidden | Previous version and PNG retained |
| Explicit human `library.promote(library, version_id, by=..., now=...)` | `promoted` | Visible in scope | Same version, pin, provenance and capabilities |
| Retry promotion | `promoted` | Visible in scope | Same record returned |

Declining a preview leaves its existing `candidate` state. Generate again starts a
new job and reserves a new asset ID. Promotion changes only the version's state. A
board still pins a version ID. For a whole-frame reference photo, add the promoted
version ID to `photo.input_asset_version_ids` and pass the draft to `plan_photo`.
[Board reference photos](studio-photo.md)

## API and UI integration

- The API persists the frozen request with `studio.job/v1` kind `asset_candidate`.
  Use the reserved asset ID as `target_id` and the plan signature as `input_signature`.
  Rebuild the plan from the saved input and verify the signature before rendering.
  Keep the HTTP idempotency reservation and serialize by job ID across workers.
  If the blob published before a metadata commit failed, retry with the same
  prepared output. Reconcile unknown ComfyUI work before any submission retry.
- Require a human with access to the generation scope for generation and promotion.
  Authorize previews through the private job, its result and the reader's scope
  before granting media access. Use normal library search for pickers and validate
  new board reference writes against eligible versions in scope.
  The library query's `include_candidates=True` option is for authorized private
  result views. [API story 430](https://work.haynesnetwork.com/work_packages/430)
- The UI polls the job for the preview ID and shows Promote as an explicit action.
  Decline or Generate again can leave the prior preview private. Use the returned
  promoted version ID when adding the still to a board. Show the capabilities and
  refresh the photo's freshness after changing its inputs.
  [Library UI story 456](https://work.haynesnetwork.com/work_packages/456)

## Validation

`STUDIO_THREADS=2 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 uv run --no-sync pytest tests/assets`
uses the fake ComfyUI transport and the create-only local store under `tmp_path`.
The integration test promotes a synthetic still and passes it through the
whole-frame board-photo edit path as a pinned reference.
