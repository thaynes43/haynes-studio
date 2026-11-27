# Cast visibility in rendered films

A board can declare one cast slot and up to 16 distinct board-frame indices.
Each index is zero-based on that board's 24 fps delivery clock. A pose means
one rendered frame, with the keyed cast frames, cast movement and camera
sampled at that frame. Two adjacent frames can share a body movement pose
and still show different keyed pixels.

```json
{"visibility": {"slot": "a", "frames": [0, 12]}}
```

A person can set or clear the field through the existing board create and
patch routes. An omitted field preserves the current value on PATCH. A
person can send `null` or `{}` to clear it. Stored boards omit the field when
empty. The board routes retain the production's `draft:write` scope. MCP
exposes the field on the same board tools and returns the same HTTP refusal
for agent writes, including clearing the field or removing a declaring board
(`visibility.person_required`).

## Admission

The Build route checks a declaration before creating a new run.

| Refusal | Condition |
| --- | --- |
| `visibility.method_unsupported` | The board uses the whole-frame method. |
| `visibility.slot_absent` | The declared slot is absent from the board's cast. |
| `visibility.timing_unavailable` | The board's delivery frame count is unresolved. |
| `visibility.frame_out_of_range` | An index reaches or exceeds the board's frame count. |

New Builds store admitted declarations by board ID in the signed snapshot at
`toolchain_request.cast_visibility`. Workers take their decision from that
pin. A same-key replay returns its original run and results. Queued runs
without the admission pin and historical archives keep their original
behavior. Photo requests use their existing composition and signature.

## Measurement and review

On each selected frame, the layered compositor tracks the opacity of the
cast body through its normal placement, motion, draw order and camera. Cast
bodies above the subject and foreground layers attenuate the contribution.
Shadows are lighting. The unoccluded count uses the subject alone in the same
rendered viewport. Both counts require at least 128 of 255 opacity. The
renderer commits frame hashes and counts with the encoded segment. The run
check reads that record and records its exact count as both bounds.

An upper bound of 50% or less of the unoccluded count is `hidden`. A lower
bound of 85% or more is `visible`. Intermediate results and frames with
zero unoccluded pixels are `uncertain`. The board is hidden if any declared
frame is hidden. A board is visible if every declared frame is visible.

Both `hidden` and `uncertain` block delivery. An uncertain result requests
person review. Read `layered.visibility` in the run's checks for the board,
slot, artifact digest, per-frame evidence and verdict. A signed-in person
can post that digest and a reason through
`POST /v1/runs/{id}/checks/layered.visibility/overrides` with the current
run revision in `If-Match`. A fresh Build with identical frozen inputs can
use the person override if the rendered evidence matches exactly. Its check
records `overridden` with the original measured verdict and the person's
reason. Earlier runs keep their recorded verdicts and delivery status.
