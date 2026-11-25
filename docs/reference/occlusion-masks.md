# Set occlusion and focal-prop visibility

[Story 452](https://work.haynesnetwork.com/work_packages/452) supplies the Studio
worker adapter and the layered visibility check. The
[pinned CPU profile](segmentation-backend-profile.md#artifact-contract-for-story-452)
defines the request and receipt schemas. Source tests use the real Unix-socket
service with a fake graph and synthetic stills. They prove the artifact contract
and the pixel counts. Model quality remains open pending the private trial.

## Set and layout declarations

An opaque set version may carry an immutable `occlusion` object with two
arrays, `foreground` and `focal_props`. The version identity includes both the
plate hash and the declarations. Changing a role, depth or stored hint creates
a new version even when the plate bytes are identical.

| Entry | Fields |
|---|---|
| Foreground role | `key`, nullable `label`, positive `layer_order`, optional `hint`. Its mask identifies pixels of the set plate assigned to this depth for the source check. |
| Focal prop | `key`, `label`, `depth`, `layer_order` when depth is known, optional `hint`. A prop with `depth: "background"` has order 0 and uses the plate. A prop with `depth: "foreground"` uses the plate and names its `foreground_role` and that role's order. A prop with `depth: "separate"` pins a `source_asset_version_id` with `rgba_cutout` and uses the slot in the layout preset named by its own key. `depth: "unspecified"` requires review. |

Keys are unique across the two arrays and distinct from cast slots on the
board. Layer order increases toward the camera. The plate has order 0.
The cast occupy orders 10, 20 and so on in board draw order. Foreground
roles have distinct orders above the cast. Separate props use free orders.
Hints follow the backend's point, box or text shape in the normalized source
still's coordinates. The adapter defaults to a set target's stored label and
hint. A job observing a separate prop supplies the declaration from its
owning set. An explicit hint is frozen with the request.

A board layout opts in with `check_poses`, a list of
`{"key": "baseline", "frame": 0}` objects. Keys are unique and frames are
zero-based at the delivery rate, relative to the board. The renderer's
`foreground` flag controls the legacy edge and feather layer. It draws no
segmented role masks. Pre-build refuses boards that pin a set with foreground
roles as `occlusion.render_unsupported`, including with `foreground: false`.
Legacy boards keep the same rendering behavior.

## Worker and completion

Call `haynes_studio.assets.occlusion.run_segmentation_job` beside the
segmentation sidecar. The worker and sidecar can write to the shared
`/segmentation` scratch volume, which is reserved for those containers. A
symlink or non-regular lock at `.studio-segmentation.lock` yields
`lock_path_invalid`. The worker reads an authorized library version and owns
the store writes. The sidecar receives the normalized still through a private
attempt directory and the closed request over the local Unix socket. It needs
neither network access nor a store credential. The client compares readiness with the
explicitly frozen profile ID, profile-manifest hash and CPU device. The worker
must ship the same `haynes_studio.segmentation` source as the pinned serving
image. Different source changes the manifest hash and every call returns
`profile_unavailable`.

The job owns the current claim. It supplies a read-only authorized library
slice, a claim check, a current-ready lookup and atomic, fenced writers for
completion and failure. The lookup key is the authorized output scope,
source version ID, canonical request hash and frozen profile-manifest hash.
The worker verifies a hit by reading the receipt and mask back, checking
their hashes and descriptors and revalidating the mask dimensions and
pixels. The scratch lock serializes lookup and dispatch. A confirmed busy
reply permits up to thirteen waits of five seconds with a fresh attempt for
each dispatch. Transport timeout ends the attempt and defers scratch cleanup
until the service's deadline has passed.

On a matching reply, the worker verifies the closed result, request echoes,
profile provenance, on-disk receipt and exact binary PNG. It publishes the
mask by hash, then the canonical receipt by hash, and verifies both with
store read-back. The completion writer creates a `ready` record with
`identity`, `status`, `reason`, `result` and `mask` under the same live claim.
Only a current, completed `ready` is usable geometry. A lost claim or a
partial write can leave unreferenced blobs. The failure writer appends
verified `needs_hint` and `failed` receipts as diagnostics outside the ready
identity namespace, leaving the same frozen request eligible for a later
ready completion. `needs_hint` carries its stable reason to human review
with zero usable masks. The source version stays read-only.

## Visibility check

`evaluate_visibility` takes the pinned layout and library plus the worker's
frozen still inputs, resolved layer moves and completed observations for each
named pose. It resolves the camera from the board clock and checks every
cast face and declared focal prop. It uses the compositor's centred set fit,
slot crop origin, sprite size, placement, held pose and camera crop. For
buildable layers it measures coverage from cast alpha and the legacy edge
and feather foreground alpha in delivery framing. The standalone check can
measure separate props at their declared positions against those layers.
Those prop components do not supply occluder alpha. The standalone
source check can also fit segmented role masks with the plate's centred cover
and camera framing to test the declared depth arrangement. Those masks describe
proposed layers, so the build refuses the set until the renderer supports them.
Binary support is sampled at the centres of the framed output pixels. The
denominator extends that grid before slot and frame clipping. The check removes
clipped pixels and pixels with alpha of at least 128 in any measured layer strictly above it.
Shadows do not contribute. A baked-in foreground prop must be entirely within
its named role and unambiguous across the other roles. Its own layer and all
layers beneath it cannot occlude it. A baked background prop needs depth
geometry where the legacy foreground redraw intersects its projected support.
A mask spanning depth layers requires a person to supply a better hint or
layer assignment. A separate prop's setup failure affects its own check.

Each check records the target, pose, frame size, camera crop, evidence hashes,
integer visible and total pixel counts, status and thresholds. A measured
fraction of at least 85% is `visible`. A fraction of at most 50% is `hidden`
and produces a blocking pre-build violation. Only `uncertain` can be
overridden. The interval between the floors and missing or invalid geometry
yield `uncertain` with the existing technical check review action. Unmeasurable
cases record zero for both counts and a reason. The floors are proposed
technical defaults pending the private trial.

The worker stops an uncertain run for review before asking for any clip.
Run details show the measurement and floors. A signed-in person can record
a reason with the existing check override action. The override stores the
full measurement, floors and evidence hashes, including the supplied bytes'
digest when a mask fails validation. Selecting Build again can proceed when
all uncertain checks have approved evidence for the exact same frozen inputs.
The new snapshot pins the approved evidence hashes.

## Gaps

- The renderer needs to draw the declared role masks in the frame before a
  board that pins them can build.
- The product lacks the segmentation job and frozen pose provider. Opted-in
  boards get `uncertain` for missing geometry. A source check covers the
  stills supplied for that pose. Cast moves and camera changes require
  evidence at each declared pose. A moving set needs the exact source frame
  bound to each pose.

## Expected private quality trial

A person must authorize one private miniature set plate with a near table,
lectern or chair part, one named visible prop and at least one keyed doll
cutout. Supply unobscured reference stills for the prop and face where
needed. Pin the still hashes, trace the foreground and subjects in source
coordinates, and label one baseline pose and a variant hiding a face or
prop. Use the same inputs in both arrangements.

Once the sidecar is installed and its measuring smoke and storage evidence
are available, try each observation without a hint, then allow at most one
person-supplied point or box per unresolved target. Record model, profile and
image pins, private input/trace and output hashes, per-target mask IoU and
visible and total pixel counts for each pose, status, elapsed time, misses,
uncertainties and hand work in minutes. Require foreground IoU of at least
0.85 and face/prop IoU of at least 0.75, agreement with the person's
visible/hidden labels and zero false-visible verdicts on the hidden variant.
Stop after the fixture. A miss, failure or unresolved uncertainty keeps
quality acceptance open.
