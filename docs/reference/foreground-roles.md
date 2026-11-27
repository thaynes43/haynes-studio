# Foreground role masks

An opaque set still can declare parts such as a table or a lectern under
`occlusion.foreground` on its library version. Each role has a unique lowercase
key, a unique `layer_order` from 1 to 1024, and a `mask` with the mask's
`version_id` and `sha256`, the original set's `still_sha256`, and the original
`width` and `height` in pixels. A set version can declare up to 16 roles. A
different role assignment gets a new set version and can reuse the still.
Omit `occlusion` for a set with no roles.

Use a promoted PNG with the `mask` capability from the shared library or the
current production. The mask must be a single grayscale frame with only 0
and 255, with at least one pixel set to 255. It can be up to 20 MiB and
16,777,216 pixels. The set still supplies the colour and the mask selects which
pixels go in front of the cast. Photo and film apply the same centred cover fit
to the still and mask. Cast entries draw at depths 10, 20, 30 and so on in board
order. A role at depth 15 draws over the first cast entry and under the second.
A role at the same depth draws over that entry.

A new Build or photo generation request freezes exact mask versions and hashes
when the selected set is a static still on a layered board with
`layout.foreground` enabled. The masks take the place of the legacy edge and
feather for that composite. HTTP and MCP use the same admission checks.
Build checks both an explicit set loop and a set loop found by the planner.
Layered photo admission checks the explicitly selected set loop.

| Refusal | When it applies |
| --- | --- |
| `occlusion.unsupported` | A whole-frame board selects the declaring set, a whole-frame photo uses it as a direct reference, or a layered board uses a set loop alongside the declaring still. |
| `occlusion.unsupported` | A set loop used by the request records a source version that declares roles. CR-71 uses only `provenance.generator.source_asset_version_ids` on that loop. Other loops keep their existing behavior, including loops with missing provenance, absent still hashes, or same-byte siblings. |
| `occlusion.foreground_required` | The board has `layout.foreground` disabled. |
| `occlusion.mask_missing` | The mask version or bytes are missing, or the mask is outside the permitted scope. |
| `occlusion.mask_not_ready` | The version needs promotion or suitable PNG mask content. |
| `occlusion.mask_stale` | The mask or still differs from its pinned hash. |
| `occlusion.mask_size` | The mask dimensions differ from the declaration or the source still. |
| `occlusion.mask_invalid` | The mask exceeds a limit or fails the grayscale, binary or single-frame requirement. |

An idempotent replay keeps its original run or job ID and frozen inputs. Workers
use those inputs for queued runs and reclaimed photo jobs. A reclaimed job can
save a result that is no longer current with the draft. Historical archives
import their runs and media as recorded. A fresh request from an imported draft
is checked at admission. [Tom's ruling on story 968](https://work.haynesnetwork.com/work_packages/968/activity#comment-10598)
