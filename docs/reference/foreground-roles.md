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
grayscale PNG of at most 16,777,216 pixels and 20 MiB. Its declared width and
height match the original set still and the PNG. The two hashes pin the exact
mask and the set still it was made for. Omit `occlusion` when there are no roles.

Cast entries draw at depths 10, 20, 30 and so on in board order. The table at 15
draws over the first cast entry and under the second. A role at the same depth
as a cast entry draws after that entry. The photo and film apply the same
centred Lanczos cover fit to the set still and the masks.

For a layered board with a static role-declared set, `layout.foreground` must
be true. The roles supply the foreground in place of the legacy edge and
feather. Photo and film admission return `occlusion.foreground_required` when
the flag is false. On legacy sets, the flag controls the edge and feather.

On a whole-frame board, photo generation, external photo upload and Build
refuse a role-declared set with `occlusion.unsupported`. The same code applies
to a standalone reference to a role-declared set in photo generation or upload.

CR-71 is provisional for Tom's review. A foreground declaration belongs to the
set version that carries it. A set loop is a separate asset version. A board that
plays a loop gets `occlusion.unsupported` if its selected still declares roles or
if any of the loop's recorded `provenance.generator.source_asset_version_ids`
names a set version with roles. The provenance check also applies when the still
selection is empty or points to an unmasked sibling.

Build uses the source version IDs as recorded. Legacy loops keep their existing
admission, planning and snapshot bytes when neither the selected still nor a
recorded source declares roles. This includes loops without provenance pins and
loops with absent, unmatched or shared still hashes. Copying a loop and registering
it with different provenance creates a separate asset. Build uses the copy's own
record and cannot tell whether its video bytes came from a loop pinned to a masked
set. Catalogue rules for copies and conflicting provenance are outside story 968.

Under CR-70.2, photo jobs render the asset versions frozen at admission. If an undispatched
claim expires and the draft switches to a masked set before the worker reclaims
it, a job admitted with the earlier unmasked version still renders that version.
It saves a non-current result and leaves the draft's selected photo in place.
Fresh admission checks the draft's current set version.

Pre-build checks the mask scope, readiness, hash, dimensions and PNG pixels.
The run snapshot records the exact mask version IDs and content hashes.
Archive import checks the pins and the metadata limits.
[Story 968](https://work.haynesnetwork.com/work_packages/968)

| Code | What to check |
|---|---|
| `occlusion.mask_missing` | The mask version and its PNG are available to the production. |
| `occlusion.mask_not_ready` | The mask version is promoted and has PNG content and the `mask` capability. |
| `occlusion.mask_stale` | The declaration hashes match the set still and mask. |
| `occlusion.mask_size` | The mask dimensions match the source still and PNG. |
| `occlusion.mask_invalid` | The PNG fits both limits, has one grayscale frame and uses only 0 and 255, with some 255 pixels. |
| `occlusion.noncanonical` | Omit an empty declaration and use integers for the role depth and dimensions. |
