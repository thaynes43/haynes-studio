# Foreground role masks

A set version can declare a foreground part such as a table or lectern. The set
still supplies the colour. The role mask supplies the alpha and a layer order
sets its depth among the cast. A change to the assignment creates a new set
version and can reuse the same still.

```json
{
  "occlusion": {
    "foreground": [
      {
        "key": "table",
        "layer_order": 15,
        "mask": {
          "version_id": "asv_01M79V9FC00000000000000007",
          "sha256": "13579bdf13579bdf13579bdf13579bdf13579bdf13579bdf13579bdf13579bdf",
          "still_sha256": "2468ace02468ace02468ace02468ace02468ace02468ace02468ace02468ace0",
          "width": 1080,
          "height": 1920
        }
      }
    ]
  }
}
```

Use a promoted asset version with the `mask` capability from the shared library
or the current production. The mask must be a nonempty, single-frame binary
grayscale PNG. Its declared width and height match the original set still and
the PNG. The two hashes pin the exact mask and the set still it was made for.

Cast entries draw at depths 10, 20, 30 and so on in board order. The table at 15
draws over the first cast entry and under the second. A role at the same depth
as a cast entry draws after that entry. The photo and film apply the same
centred Lanczos cover fit to the set still and the masks.

On sets with role masks, `layout.foreground` must be true on every board using
the set. The roles supply the foreground in place of the legacy edge and
feather. If the flag is false, Build returns `occlusion.foreground_required`.
Enable foreground on the board or choose a set version without role masks.
On legacy sets, the flag continues to control the edge and feather.

Build requires a layered board and static set still for role masks. A
whole-frame board or a set loop returns `occlusion.unsupported`. Pre-build
also checks the mask scope, readiness, hash, dimensions and PNG pixels.
The run snapshot records the exact mask version IDs and content hashes.
[Story 968](https://work.haynesnetwork.com/work_packages/968)

| Code | What to check |
|---|---|
| `occlusion.mask_missing` | The mask version and its PNG are available to the production. |
| `occlusion.mask_not_ready` | The mask version is promoted and has PNG content and the `mask` capability. |
| `occlusion.mask_stale` | The declaration hashes match the set still and mask. |
| `occlusion.mask_size` | The mask dimensions match the source still and PNG. |
| `occlusion.mask_invalid` | The PNG has one grayscale frame and uses only 0 and 255, with some 255 pixels. |
