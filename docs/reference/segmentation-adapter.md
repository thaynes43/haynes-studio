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
alpha and include any supplied point hint. Fresh and cached ready results both
read the receipt and PNG back from the store and verify the locator scope,
media type, length and digest before returning a `VerifiedObservation`.

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
