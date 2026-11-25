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
| Foreground role | `key`, nullable `label`, positive `layer_order`, optional `hint`. Its mask identifies pixels of the set plate that draw at this depth. |
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
zero-based at the delivery rate, relative to the board. The layout's existing
`foreground` flag controls whether the table or other roles draw in front.
Legacy boards continue to use the existing edge and feather fields.

## Worker and completion

Call `haynes_studio.assets.occlusion.run_segmentation_job` beside the
segmentation sidecar. They share the `/segmentation` scratch volume. The
worker reads an authorized library version and owns the store writes. The
sidecar receives the normalized still through a private attempt directory
and the closed request over the local Unix socket. It needs neither network
access nor a store credential. The client compares readiness with the
explicitly frozen profile ID, profile-manifest hash and CPU device.

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
mask by hash, then the canonical receipt by hash, and finally calls the
completion writer to commit `identity`, `status`, `reason`, `result` and
`mask`. The last step is create-only under the same live claim. The worker
rechecks store read-back before it asks for completion. A lost claim or a
partial write can leave unreferenced blobs. Only a current, completed
`ready` is usable geometry. A `needs_hint` completion carries the receipt
and reason and goes to human review. It offers no mask and changes no
thresholds. A failed receipt may be kept as a diagnostic. The source
version remains read-only throughout.

## Visibility check

`evaluate_visibility` takes the pinned layout and library plus the worker's
frozen still inputs, resolved layer moves and completed observations for each
named pose. It resolves the camera from the board clock and checks every
cast face and declared focal prop. It uses the compositor's centred set fit, slot crop origin,
sprite size, placement, held pose and camera crop. It applies the same set
fit and framing to the foreground alpha. Binary support is sampled at the
centres of the framed output pixels. The denominator extends that grid
before slot and frame clipping. From that support it removes clipped pixels
and pixels with rendered alpha of at least 128 in any strictly higher layer.
Shadows do not contribute. A baked-in foreground prop must be entirely within
its named role and unambiguous across the other roles. Its own layer and all
layers beneath it cannot occlude it. A mask spanning depth layers requires
a person to supply a better hint or layer assignment.

Each check records the target, pose, frame size, camera crop, evidence hashes,
integer visible and total pixel counts, status and thresholds. A measured
fraction of at least 85% is `visible`. A fraction of at most 50% is `hidden`
and produces a blocking pre-build violation. The interval between them and
missing or invalid geometry yield `uncertain` with the existing technical
check review action. Unmeasurable cases record zero for both counts and a
reason. The floors are proposed technical defaults pending the private trial.

The product preflight requires review for opted-in boards while the job and
frozen pose provider are pending. A source check covers the stills supplied
for that pose. Cast moves and camera changes require evidence at each
declared check pose. A moving set needs an exact source frame bound to
each pose before it can be certified.

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
