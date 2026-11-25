# Set occlusion and focal-prop visibility

[Story 452](https://work.haynesnetwork.com/work_packages/452) supplies the Studio
worker adapter and the layered visibility check. The
[pinned CPU profile](segmentation-backend-profile.md#artifact-contract-for-story-452)
defines the request and receipt schemas. Source tests use the real Unix-socket
service with a fake graph and synthetic stills. A generated test compares
visibility bounds with frames from `compose_photo`. Model quality remains
open pending the private trial.

## Set and layout declarations

An opaque set version may carry an immutable `occlusion` object with two
arrays, `foreground` and `focal_props`. The version identity includes both the
plate hash and the declarations. Changing a role, depth or stored hint creates
a new version even when the plate bytes are identical.

| Entry | Fields |
|---|---|
| Foreground role | `key`, nullable `label`, positive `layer_order`, optional `hint`. The declaration identifies plate pixels intended for a future foreground layer. |
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
zero-based at the delivery rate, relative to the board. The `foreground`
flag controls the legacy edge and feather redraw. Legacy boards keep the
same rendering behavior.

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

Fresh and cached ready results go through the same adapter verification before
the adapter constructs a `VerifiedObservation`. Verification binds the
canonical receipt to the request's input and target, the frozen profile and the
exact mask bytes. The visibility check accepts these observations and matches
their identity to the production, source version, target, hint and profile for
the pose. An unverified record supplies no geometry.

## Visibility check

`evaluate_visibility` takes the pinned layout and library plus frozen stills,
resolved cast moves and verified observations for each named delivery frame.
It measures cast faces and props baked into the base plate. It follows
`compose_photo` through the centred plate fit, cropped and resized cast
sprites in board draw order, the enabled legacy edge and feather redraw,
and finally the camera crop. At a named pose it uses the supplied cast moves
and resolves the camera on the board clock.

The check traces the binary target mask through the compositor's pixel
operations. A cast trace retains the source cutout alpha inside that mask.
Higher cast layers attenuate the trace by their rendered alpha. Shadows
change lighting and leave the trace's surface coverage alone. The legacy
foreground can cover a face or restore pixels of the same baked-in prop
from the plate. A disabled foreground uses no observation. A pixel counts
when the target's unoccluded rendered support and its composited contribution
both reach 128 on the delivery grid. The denominator adds support lost to
the slot and frame clips, sampled by extending the same grid with nearest
pixel centres.

An invalid or missing higher cast or foreground input is unknown. Before
camera resampling, an unknown cast can leave the contribution unchanged or
cover it completely. An unknown legacy foreground can leave the current
contribution unchanged or replace it with the corresponding plate value.
Known layers still apply in order. Bicubic camera resampling has negative
weights, so a framed pixel that may sample an unknown contribution gets a
conservative range. Pixels outside that footprint retain their exact value.
With all inputs known, the two counts are equal to the rendered trace count.
The renderer test generates cast order, translation, rotation, slot and frame
clipping, camera pushes and legacy foreground states. It renders absent,
fully covering and intermediate completions for each unknown layer and
checks that every count lies within the reported bounds.

Declared foreground roles cause `occlusion.render_unsupported` even
with `foreground: false`. A separate prop and targets at or below its
declared order cause `occlusion.separate_prop_unsupported`. An opted-in
whole-frame layout causes `occlusion.layout_unsupported`. Affected targets
return `unsupported` and pre-build refuses the board. These refusals have no
override. Rendering and measuring the declared layers belongs to
[story 968](https://work.haynesnetwork.com/work_packages/968).

Each check records the target, pose, frame size, camera crop, evidence hashes,
integer lower and upper visible pixel counts, total support, unknown occluders
and thresholds. An upper bound of at most 50%
is `hidden` and produces a blocking pre-build violation. A lower bound of at
least 85% is `visible`. All other intervals are `uncertain` and can go to
human review. If the target's own mask or pose is unavailable, the check
records zero counts and the target's reason. The floors are proposed
technical defaults pending the private trial.

The worker stops an uncertain run for review before asking for any clip.
Run details show the measurement and floors. A signed-in person can record
a reason with the existing check override action. The override stores the
full measurement, floors and evidence hashes. Selecting Build again can
proceed when all uncertain checks
have approved evidence for the same frozen inputs. The lookup excludes the
previous snapshot's approval list. The new snapshot pins only the approved
hashes matching the current checks.

### Supplied-input equivalence

The input pin hashes the layout, profile, frame size, supplied pose records
and their observations, stills, moves and hints before applying geometry or
request validation. Rejected input contributes to the pin. The result hash
also binds the library pin, measurement and thresholds.

- Mappings compare by the ordered sequence of typed keys and values supplied
  by iteration. Two implementations with the same entries in the same order
  are equivalent. Reordering hint keys changes the pin even when the normalized
  service request would have the same digest.
- Strings compare by Unicode code point sequence. The encoding preserves each
  sequence, including its normalization form and any surrogate code points,
  for evidence. U+1F600 and the literal pair U+D83D U+DE00 have different pins.
  The normalized request still needs valid UTF-8 before it can name a verified
  observation.
- Bytes compare by their content hash. Null, a missing entry and empty bytes
  are distinct. Lists and tuples have separate tags and compare elementwise.
  Dataclass records compare by qualified class and field values in declaration
  order.
- Booleans, Python integers and Python floats have distinct encodings. Integer
  magnitude and sign and all binary64 float bits, including signed zero and
  NaN payload, contribute. NumPy scalars compare by dtype and stored value
  bytes. Arrays additionally bind shape and the element sequence in row-major
  order. Object dtype values recursively use the same encoding.

## Gaps

- The product lacks the segmentation job and frozen pose provider. Opted-in
  supported boards get `uncertain` for missing geometry. A source check covers the
  stills supplied for that pose. Cast moves and camera changes require
  evidence at each declared pose. A moving set needs the exact source frame
  bound to each pose.

## Expected private quality trial

A person must authorize one private miniature set plate with a near table,
lectern or chair part, one named visible prop baked into the plate and at
least one keyed doll cutout. Use the legacy edge and feather if the prop or
face needs a foreground redraw. Supply unobscured reference stills for the
prop and face where needed. Pin the still hashes, trace the foreground and
subjects in source coordinates, and label one baseline pose and a variant
hiding a face or prop. Use the same inputs in both arrangements.

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
