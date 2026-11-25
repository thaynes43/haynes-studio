# Matting and cast size matching

[OP451](https://work.haynesnetwork.com/work_packages/451) adds a Studio worker
adapter for the pinned BiRefNet Lite CPU service. It derives a private asset
candidate from one library `opaque_photo` version. The aligned cutout and
mask and the complete backend receipt retain the source's pixel coordinates.
The source version and its capabilities stay immutable.

## Job and candidate

Call `haynes_studio.assets.matte.run_matte_job` with an authorized job ID,
scope, pinned source version and pinned format recipe version. The
[service profile](matting-backend-profile.md#artifact-contract-for-story-451)
defines the request, supported source media and response. The caller uses
the job's own scope for both read and write. Cast, costume and prop keep
their kinds. An opaque library photo selected for a cast slot derives a
cast candidate. Use a chroma colour only when its uniform backing and sRGB
provenance are known.

The adapter is the worker-side operation. The staged sidecar shares
`/matting` with the Studio run worker, where the admitted claim supplies
the filename-free request. The worker holds store reads and its job
fence. Pass a separate output store when the worker stages for an API-owned
commit. Pass the claim's fence/progress check and failure writer
(`code`, `message`). Compare the ready reply to an explicitly configured profile
ID, manifest hash and CPU provider. The `MattingClient` takes that expected
hash and a `Profile` constructed with the installed backend image digest and
its build SHA, from the release record. It validates the frozen request and
uses the backend's verifier to check every artifact, the response and the
receipt's measured alpha geometry. A valid busy reply waits 5 s before
another attempt, up to seven waits. Each dispatch uses a fresh attempt
directory. A timeout or ambiguous response ends the job.

Publish the verified straight RGBA8 cutout, L8 mask and canonical receipt
create-only by hash, in the source scope. The API or job owner commits the
returned `Outcome` under the same claim once all three blobs are
authoritative. A failed write may leave unreferenced blobs. Only the
committed outcome is an asset candidate. The job operation records
failures, including pin mismatch, missing service, exhausted busy retries,
timeout, invalid response and invalid shape. The existing promotion
operation remains a person's action.

The `matting:` source key and candidate asset/version IDs derive from the
pinned source descriptor, backend profile hash, optional chroma colour and
the format/slot normalization record. They exclude the job and scratch
attempt IDs. A replay in the same library verifies the three committed blobs
and returns the existing version and receipt. The first receipt carries its
actual job ID and full request signature. In independent dispatches, the PNGs
and candidate IDs match. Receipt signatures track their individual job IDs.

The derived candidate has capabilities `rgba_cutout` and `mask`. Its
`content` is the cutout. Its `provenance.generator` has role `composite`,
engine `studio-matting`, the profile ID as model, weight hashes and
`source_asset_version_ids`. The generator parameters carry `profile_sha256`,
`image_digest`, `input_signature`, the verified `receipt`, the normal
`Content` descriptors `mask` and `receipt_blob`, and the `normalization` record
(policy, format version ID and hash, slot and target height). The asset
licence comes from the Studio model register's matting entry.

## Size and placement

An optional `cast.matte_slots` map on the format recipe gives each enabled
cast slot (`a` through `z`) a `target_height_px` integer from 1 through 2048. Missing size data
refuses a matte job. The format pin and choice of slot are part of the result.

`studio.cast-matte-size/v1` measures the half-open box and foreground area
at alpha 128. It refuses a box touching an input edge, height below 64 px,
upscale greater than 4×, width-to-height outside 1:4 through 2:1, or
foreground coverage below one quarter of the box. These are conservative
pilot bounds for a single cast silhouette. The result records the exact
ratio as target height over measured height, alongside the box, area and
alpha threshold.

Layered board photos consume a promoted candidate when the board uses the
same format version and cast slot. The photo signature includes its size
and measurement. Placement centers the silhouette at the layout slot's
horizontal center and aligns its bottom to the slot. The recipe gives the
figure height. Placement trims fully transparent padding and resizes once,
keeping the fractional-alpha support beyond the measured silhouette. A
slot crop conflicts with the measured silhouette and fails. Motion clips
keep their separate, timed `keyed_layer` path.

## Evidence

The source suite exercises the real socket server and its subprocess with a
synthetic fake graph. The pinned image and weights passed the earlier
[OP459 smoke](https://work.haynesnetwork.com/work_packages/459), comment
10004. The serving sidecar and product matting job admission still need a
deployment pin. The [private quality trial](https://work.haynesnetwork.com/work_packages/451)
stays pending Tom's verdict under CR-46.
