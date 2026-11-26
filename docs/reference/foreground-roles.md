# Foreground role masks and reference-photo visibility

A set version can declare foreground parts such as a table or lectern. Each role
pins a promoted library version with the `mask` capability and `image/png`
content. Use a single-frame binary grayscale PNG with the same dimensions as
the original set still. The set supplies the colour and the mask supplies the
alpha. The set version binds the still's hash and the declaration. Updating the
assignment creates a new set version, even when the plate bytes stay the same.

```json
{
  "occlusion": {
    "foreground": [
      {
        "key": "table",
        "label": "table",
        "layer_order": 15,
        "mask": {
          "version_id": "asv_01M79V9FC00000000000000007",
          "sha256": "13579bdf13579bdf13579bdf13579bdf13579bdf13579bdf13579bdf13579bdf",
          "still_sha256": "2468ace02468ace02468ace02468ace02468ace02468ace02468ace02468ace0"
        },
        "hint": { "kind": "point", "xy": [20, 30] }
      }
    ]
  }
}
```

Cast entries draw at depths 10, 20, 30 and so on in board order. The table at
15 draws over the first cast entry and under the second. A role at the same
depth as a cast entry draws after it. The photo and film use the same centred
Lanczos cover fit for the still and mask. `layout.foreground` enables the roles.
When enabled on a role-declared set, the roles supply the foreground in place
of the legacy edge and feather.

The run snapshot keeps the set's content hash and `occlusion_signature` and
the exact mask version IDs and content hashes. Preflight verifies readiness,
scope, hashes and image size. `occlusion.mask_missing`,
`occlusion.mask_stale`, `occlusion.mask_not_ready`, `occlusion.mask_size`
and `occlusion.mask_invalid` identify the failed condition. An enabled role with
a set loop, a whole-frame board with an active declaration, or a set with focal
prop targets refuses with `occlusion.unsupported`. Masks are inputs from the
library. Story 971 owns how they are made.
[Story 968](https://work.haynesnetwork.com/work_packages/968)
· [Story 971](https://work.haynesnetwork.com/work_packages/971)

## Reference-photo check

Every layered board using a role-declared set has a visibility check. The
default checks each cast cutout. A layered board can also opt in or narrow its
check with `layout.check_poses`. The supported frame value `0` means the
layered reference photo. It uses stationary cast and the last camera cue's
end framing. A target can name a whole cast slot or a half-open source-still
rectangle. For example, this board checks slot `a`'s face:

```json
{
  "layout": {
    "preset": "pair",
    "foreground": true,
    "check_poses": [
      { "key": "face", "frame": 0, "targets": [{ "slot": "a", "box_xyxy": [10, 10, 30, 30] }] }
    ]
  }
}
```

The compositor traces the target colour through its normal layer draw with
the full source alpha, including shadows, foreground masks and camera.
It counts eligible target pixels at half intensity or greater. The support
render uses the target alone with its authored nonzero alpha pixels made
opaque, through the same framing. For supported scenes all occluders are known
and the lower and upper counts agree. The check captures the reference image's
RGB hash, the photo input signature and the target evidence.

| Verdict | Action |
|---|---|
| Upper bound at or below 50%, or no target pixels in the reference photo | `occlusion.hidden` stops the build. |
| Lower bound at or above 85% | Build may proceed. |
| Between the thresholds | `occlusion.review_required` leaves the measured check on the failed run. A person can review and approve its artifact. |

A person records an uncertain check override on
`POST /v1/runs/{id}/checks/layered.visibility/overrides` with the failed run's
current ETag and the measured artifact digest. The next Build reuses it only
for the same frozen inputs and matching evidence. A changed draft, mask or
measurement requires fresh review. The CLI records the refusal and its
evidence when it has no matching approval.

## Writes and hints

An ordinary board patch that sends a layout without `check_poses` preserves
the existing declaration. A person can remove the declaration explicitly with
`check_poses: null` or `[]`. Canonical board and set version serializations
omit absent or empty declarations, including run snapshots and archived
storyboard board fields. An archive import that normalizes a snapshot stores
the original verified bytes under their source pin and exposes the normalized
snapshot on the run.

Point hints name one source pixel. Box hints are ordered half-open source
rectangles. Each known axis bounds the corresponding coordinates, even if the
other dimension is unavailable. Batch imports check dimensions regardless of
input order, including the version ID found by an idempotent import. Focal prop
declarations use their pinned prop still's dimensions for a separate prop and
the set still's dimensions for a prop baked into the plate.
