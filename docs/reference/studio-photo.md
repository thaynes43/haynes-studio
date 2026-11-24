# Board reference photos

Story [407](https://work.haynesnetwork.com/work_packages/407) provides the Python
interface for versioned board photos. Whole-frame boards can generate a photo from a
prompt and ordered library stills or accept a D42 agent upload. Layered boards use the
[existing D51 compositor](layered-adapter.md). Each completed photo has an immutable
`studio.asset-version/v1` record with production, story and board scope.

## Plan and prepare

Use `plan_photo(story, board, library)` with canonical `Story` and `Board` models
and a library containing the referenced versions. The plan freezes the board ID, layer
method, target frame size, and ordered source version IDs and SHA-256 digests. A
whole-frame plan also freezes the NFC board prompt. A layered plan uses the compositor's
own signature for the set still, cast and draw order, layout, foreground and end-camera
framing. The plan holds the previously selected photo ID separately.

| Function | Operation |
|---|---|
| `generate_photo(plan, client=..., fetch=..., job=..., seed=..., licences=...)` | Uses the configured story 425 image client to render one Qwen-Image 2.1 prompt. No references uses text-to-image. With references, the pinned edit graph receives a single white canvas of contained stills, in input order from left to right and top to bottom. The canvas and text-to-image dimensions are 720×1280 for Short or 1280×720 for Video. |
| `compose_layered_photo(plan, fetch=...)` | Delegates to story 426's compositor with the plan's stills and framing. Photo prompts, photo reference picks, animation seeds and motion clips do not affect its signature. |
| `import_photo(plan, library, data=..., media_type=..., declared=..., by=...)` | Validates a whole-frame D42 upload. Its model, actual prompt and source versions are declared separately from the board inputs used to check freshness. |

`fetch(locator, sha256)` returns bytes or `None`. The package re-hashes bytes used
in generation or composition against their pins. For ComfyUI, record the actual
prompt, seed, filled workflow digest, job ID, timings and output digest. The adapter
does not report model weight digests. Supply the [model licence register](model-licences.md)
to record the known terms. Use the existing [shared queue rules](services.md#comfyui-images)
and the image client's in-flight handling.

## D42 upload

The transport supplies raw `image/png`, `image/jpeg` or `image/webp` bytes.
The limit is 20 MiB and 4096 pixels on either side. The source checks the header
dimensions before decoding and rejects malformed images, MIME mismatches and
animation. The stored photo is an opaque RGB PNG. It applies EXIF orientation,
composites transparency over white, and drops original metadata. The version content
hash covers the PNG. Provenance records the SHA-256 and MIME type of the original bytes.

Supply `ExternalProvenance` with a model, actual prompt, session, harness, an ordered
sequence of source version IDs (empty when no library assets were used), and
`paid_api=False`. The model, session and harness each take at most 200 characters.
The actual prompt takes at most 10,000 characters. An optional lowercase
`upload_sha256` must match the original bytes. Pass the authenticated
`Principal(kind="agent", key_id=...)` as `by`. The server derives the external
marker and agent key from this identity, resolves source hashes from the library and
keeps the declared model's licence unknown pending a check.

| Rule | Meaning |
|---|---|
| `photo.too_large` | Body or dimension limit exceeded, with status `too_large`. |
| `photo.image_invalid` | The byte stream does not identify and decode as a supported still with the declared type. |
| `photo.hash_mismatch` | A declared input, stored source or image-engine response digest disagrees with the bytes, or the supplied digest is malformed. |
| `prov.external_incomplete` | The declaration or agent identity fails D42 validation. |
| `ref.unknown`, `asset.scope_mismatch`, `asset.bytes_missing`, `asset.kind_mismatch` | A source is unknown, outside scope, missing content or of the wrong type. |
| `photo.method_invalid` | The operation does not apply to the board's layer method. |

## Record and select

1. Persist the original draft snapshot, selected photo ID, generation seed and job
   name when queueing. A resumed worker can rebuild the plan against the original
   pinned library versions and verify the saved `input_signature`. A running job reads
   its frozen plan.
2. Prepare the photo outside the board write transaction. Use
   `record_photo(prepared, latest_library, publish=..., by=..., now=...)` while
   serializing writes for that board's photo asset. The return value contains the
   new library and version. `publish(data, "image/png")` must write the private blob
   create-only and return its digest and canonical production locator. Identical bytes
   share a blob, while distinct completed actions get distinct version IDs and numbers.
3. With the latest story and board held under the write fence, call
   `can_select_photo(version, plan, story, board, updated_library)`. Record the
   version even when the result is stale or a competing photo changed the pointer.
   Select it only when the function returns true and the job's terminal update wins its
   compare-and-set. Keep `result_is_current` in that same write.
4. Merge `photo_facts(story, library)` into canonical facts for derived board reads
   and preflight. A selected photo with changed inputs or without a recorded signature
   is stale. Scope and generating facts carry through the caller's existing checks.

The upload transport in [story 430](https://work.haynesnetwork.com/work_packages/430)
owns request authentication and scope enforcement, streaming body limits, upload
schema parsing, `If-Match`, idempotency and atomic metadata/pointer writes. It should
take the plan from the matching draft, and retain the operation's idempotency
reservation across retries. The image worker must hold the appropriate queue claim
before submitting. A completed version by itself does not move the board pointer.

## Validation

Run `STUDIO_THREADS=2 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 uv run --no-sync pytest tests/photo`
with the locked environment. The tests use story 425's fake ComfyUI transport and
synthetic stills.

On 2026-11-24, one live edit prompt combined two synthetic reference assets after
the shared queue reported zero running and zero pending. The source prepared and
recorded a 768×1376 PNG in a private session job directory in 51.69 s, with 51.0 s
reported by ComfyUI and 0.0 s of queue wait. The stored PNG's SHA-256 was
`868df97c9c7da7e362ce823cc89337210dd384277eccd92bddde39254e13e9e9`.
