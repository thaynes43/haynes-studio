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

Under CR-72, a new Build stores admitted declarations by board ID at
`visibility_admission.boards` in the signed snapshot. The top-level snapshot
schema reserves this field, and `visibility_admission.schema` identifies the
record as `studio.visibility-admission/v1`. Workers use those frozen declarations.
A same-key replay returns its original run and results. Queued runs without the
admission record and historical archives keep their recorded behavior. Photo
requests use their existing composition and signature.

## Measurement and review

On each selected frame, the layered compositor tracks the opacity of the
cast body through its normal placement, motion, draw order and camera. Cast
bodies above the subject and foreground layers attenuate the contribution.
Shadows are lighting. The unoccluded count uses the subject alone in the same
rendered viewport. Both counts require at least 128 of 255 opacity. The
renderer commits frame hashes and counts with the encoded segment. The run
check reads that record and records its exact count as both bounds.
`measured.measurement_stage` is `composed_pre_encode`.

Under CR-73, this check finds a cast member covered by other layers in the
composed frame handed to the encoder. It does not detect a picture that the
encoder renders unreadable. In the striped-target regression, the check passes
with 4,096 visible pixels at each selected frame. The stripes have the same
luma as the gray background, and the decoded 4:2:0 master and phone proxy show
zero pixels with the target's strong color contrast.

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
carry the decision in `visibility_admission.overrides`. Completion follows
the staged master and splice records to the segment for the board. A pass and
a carried override both require exact evidence from that segment for all
frozen poses. A matching override records `overridden` with the original
measured verdict and the person's reason. Earlier runs keep their recorded
verdicts and delivery status.
