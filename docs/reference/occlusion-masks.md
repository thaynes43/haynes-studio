# Set occlusion declarations and segmentation adapter

[Story 452](https://work.haynesnetwork.com/work_packages/452) defines the set and
board declarations and supplies the Studio adapter for the pinned CPU segmentation
service. [Service request and result schemas](segmentation-backend-profile.md#artifact-contract-for-story-452)

## Set and layout declarations

An `opaque_plate` set version may carry an immutable `occlusion` object with
`foreground` and `focal_props` arrays. Each array holds up to 16 entries and at
least one must be nonempty. The set version pin includes the plate's content hash
and these declarations, so editing a role, depth or stored hint creates a new
version. [Library version identity](studio-library.md#what-a-version-is)

| Entry | Fields |
|---|---|
| Foreground role | `key`, nullable `label`, positive `layer_order`, optional `hint`. The role identifies plate pixels for a foreground layer. |
| Focal prop | `key`, `label`, `depth`, optional `hint`, and the fields required by its depth. |

Keys are unique across both arrays. Foreground roles and separate props use unique
positive layer orders up to 1024, increasing toward the camera. Labels and text
hints use trimmed NFC text without control characters. Point and box hints use
normalized source still coordinates.

| Focal prop depth | Associated fields |
|---|---|
| `background` | Order 0. The prop uses the base plate. |
| `foreground` | `foreground_role` names a declared role and `layer_order` matches that role's order. |
| `separate` | Positive `layer_order` and a `source_asset_version_id` for the separate prop still. |
| `unspecified` | Omit `layer_order`, `foreground_role` and `source_asset_version_id`. |

A board can add `layout.check_poses` with 1–16 `{key, frame}` objects, for example
`{"key": "baseline", "frame": 0}`. Keys are unique within the board. Frame indices
are non-negative integers, zero-based at the delivery rate and relative to the
board. The existing `layout.foreground` flag controls the legacy edge and feather
redraw.

## Segmentation adapter

`haynes_studio.assets.occlusion.run_segmentation_job` takes an authorized library
slice, a source version, a target, a current-claim check and fenced writers. It
reads the pinned still, checks its hash, format, dimensions and alpha, and sends a
closed request over the local Unix socket. An attempt directory on the shared
`/segmentation` volume carries the still and the service's output. The worker and
pinned serving image need matching segmentation source manifests. The client
checks the profile ID, manifest hash and CPU device before dispatch.

The adapter uses the stored label or hint for a declared plate target when the
caller omits it. A separate prop job uses the prop's own cutout and supplies its
label and hint. The ready lookup binds output scope, source version ID, canonical
request hash and pinned profile hash. A regular-file scratch lock serializes
lookup and dispatch. A confirmed busy response allows up to thirteen waits of
five seconds. A transport timeout leaves the attempt staged until the service
deadline passes.

Fresh and cached ready results pass the same verification. The adapter reads
the canonical receipt and PNG back from the store, checks their scope, media type,
length and hash against the completion, and checks the receipt's request and
profile identities. It binds the PNG to the receipt's mask descriptor and checks
its dimensions, binary pixels, bounding box and support on the source. Only that
verification can construct a `VerifiedObservation` with usable mask data.

The worker publishes the mask and receipt create-only and commits the ready
record under its current claim after read-back verification. Non-ready receipts
go to the failure writer as diagnostics, keeping the same request eligible for a
later ready completion. The source version stays read-only. Source tests use the
real Unix socket with a fake graph and synthetic stills.

## Pre-build refusal

A story with a set that declares a foreground role or focal prop, or a board
that declares check poses, is refused before build with
`occlusion.check_unavailable` and the message “The visibility check is not
installed”. This applies even with `layout.foreground` disabled. People and
agent keys receive the same refusal. The refusal carries no verdict and has no
override. Legacy documents without these declarations keep their existing
build behavior and serialization.

## The visibility check

The visibility check is not installed. The independent reviews found differences
between the measured geometry and the production photo, including resampled
alpha, cast placement and camera framing. The renderer and check will be built
together so the check can be tested against unmodified rendered frames.
[Story 968](https://work.haynesnetwork.com/work_packages/968) ·
[Review 1](https://github.com/thaynes43/haynes-studio/pull/140#issuecomment-7164312521) ·
[Review 2](https://github.com/thaynes43/haynes-studio/pull/140#issuecomment-7165771236) ·
[Review 3](https://github.com/thaynes43/haynes-studio/pull/140#issuecomment-7167251194) ·
[Review 4](https://github.com/thaynes43/haynes-studio/pull/140#issuecomment-7169445196)
