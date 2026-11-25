# Matting and cast size matching

[OP451](https://work.haynesnetwork.com/work_packages/451) adds a Studio worker
adapter for the pinned BiRefNet Lite CPU service. It derives a private asset
candidate from one library `opaque_photo` version. The aligned cutout and
mask and the complete backend receipt retain the source's pixel coordinates.
The source version and its capabilities stay immutable.

## Job and candidate

[OP965](https://work.haynesnetwork.com/work_packages/965) wires
`haynes_studio.assets.matte.run_matte_job` into the `matte` media lane.
The function checks that the source is a library-level asset in the job's
scope and its pinned version has the `opaque_photo` capability.
[Request and job status](studio-api.md#media-operations) ·
[Deployment pin](media-jobs.md#matte-worker-deployment-pin)

The function takes an authorized job ID, scope, pinned source version and
pinned format recipe version. The
[service profile](matting-backend-profile.md#artifact-contract-for-story-451)
defines the request, supported source media and response. The caller uses
the job's own scope for both read and write. Cast, costume and prop keep
their kinds. An opaque library photo selected for a cast slot derives a
cast candidate. Use a chroma colour only when its uniform backing and sRGB
provenance are known.

The adapter is the worker-side operation. The sidecar shares
`/matting` with the matte lane worker, where the admitted claim supplies
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
directory. A timeout or ambiguous response ends the job. After a client
timeout, the adapter allows the backend's request deadline to pass and
waits for the pinned readiness response before removing its scratch files.
The wait is bounded. Before dispatch, the adapter also clears its expired,
unlocked scratch attempts from earlier runs.

Publish the verified straight RGBA8 cutout, L8 mask and canonical receipt
create-only by hash, in the source scope. The API or job owner commits the
returned `Outcome` under the same claim once all three blobs are
authoritative. A failed write may leave unreferenced blobs. Only the
committed outcome is an asset candidate. The job operation records
failures, including pin mismatch, missing service, exhausted busy retries,
timeout, invalid response and invalid shape. The timeout record mentions
the next sweep because the attempt can outlive the job. The existing
promotion operation remains a person's action.

The `matting:` source key and candidate asset/version IDs derive from the
pinned source descriptor, backend profile hash, optional chroma colour and
the format/slot normalization record. They exclude the job and scratch
attempt IDs. A replay in the same library verifies the three committed blobs
and returns the existing version and receipt. If media is missing, the
adapter replays the original job ID, checks all regenerated descriptors against
the recorded pins and recreates the missing blobs create-only. The worker copies
any staged files even when the adapter returns `created=False` and uses the existing
candidate ID. Different
bytes at a recorded locator fail with `store.hash_mismatch`. Independent
dispatches keep the same PNGs and candidate IDs. Each dispatch's receipt
signature includes its job ID.

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
slot crop conflicts with the measured silhouette and fails. A recipe
target taller than the frame fails with `matting.target_exceeds_frame`
and reports both heights. Motion clips
keep their separate, timed `keyed_layer` path. A target that fits the frame but not the space above its slot's bottom
line is refused with the same code, when the photo is planned (target height against
the slot's bottom line) and again when it is composed (with the sprite's fringe
included), so a doll is never cut at the top of the frame without an error. The
adapter's sweep of its own finished attempts skips any name in the shared scratch
that is not a regular marker file it wrote.

## Evidence

The source and database suites exercise the real socket server and its
subprocess with a synthetic fake graph. The pinned image and weights passed the earlier
[OP459 smoke](https://work.haynesnetwork.com/work_packages/459), comment
10004. The serving sidecar and matte worker still need a deployment pin.
The [private quality trial](https://work.haynesnetwork.com/work_packages/451)
stays pending Tom's verdict under CR-46.
