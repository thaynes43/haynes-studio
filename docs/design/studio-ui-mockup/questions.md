# Questions for Tom

**Answered 2026-11-04** (Tom). Rulings are D29 to D32 in `docs/proposals/0003-studio-plan.md`:

1. No script gate. The only approval is go-live; script and images iterate together (D29).
2. Superseded by D33 in the v4 work order: speaking-board timing comes from voice audio plus a short pad; silent boards use an editable hold. Platform caps are not implemented in this mockup.
3. Media lists use filters: unpublished, approved, or both (D31).
4. Yes. Tweak and queue a new run while one runs, then compare (D30).
5. Persist selections: the Editor's asset library opens scoped to the current production, with filters to widen (D32).

The historical questions and prototype defaults below are superseded by D29 to D44 and by
the v3 to v6 changes in [`review.md`](review.md). The current UI uses technical layer and
motion badges, drafts stay editable during builds, and there is no script or per-board
approval. The 0.25 s pad and 25 fps display are prototype defaults. R01 (see
[the backlog review](../../backlog/review-2026-11-05.md)) owns production timing; how a
format's length range is enforced remains a grooming choice.

The original questions follow.

Story: https://work.haynesnetwork.com/projects/haynes-studio/work_packages/401

These are design choices for the coordinator's review, not blockers for this mockup.
Recommendations below are the prototype defaults, not recorded owner decisions.

1. **Does the script need its own approval before reference photos?**
   Options: a separate text gate; review text and photo together on each board.
   **Recommend:** review them together for this already-approved PoC script. Retain
   the existing real-production gates until their replacement is explicitly approved.

2. **Should a format's length range block Build?**
   Options: hard limit; advisory range; no range in the editor.
   **Recommend:** an advisory range when formats are editable; omit it from this PoC
   mockup. Positive board lengths are totaled without a format blocker. Actual voice
   fit and cost need measured durations later.

3. **Where does an approved private cut belong before publication?**
   Options: In development with “Cut approved”; a fourth Ready status; Pending approval
   until release. **Recommend:** In development with the approval badge for now.
   Published stays empty; no publishing action is included.

4. **Can boards change while a build runs?**
   Options: lock editing; edit a new revision while the frozen build continues.
   **Recommend:** lock story editing for this first flow. Asset browsing and generation
   remain available. Later edits keep the prior build, mark it as an earlier cut, and
   require a new build before cut approval.

5. **Which assets should the library show first?**
   Options: the current production's label; all assets; assets already on the board.
   **Recommend:** default to Yellowbirds, with All productions available. Keep one
   shared store; promoting an asset labels it Yellowbirds, not a separate library.

## Prototype boundaries and mappings

| UI | Meaning / boundary |
|---|---|
| Production → media type → story | D28 hierarchy overrides the older proposal's “production = one video” terminology. |
| Talking / Reaction / Ambient | Layered speech-to-video / layered image-to-video / whole-frame. |
| Photo generation | Asset references plus prompt text; about 1.5 min in practice, accelerated SVG variation here. No model call. |
| Build | At least one board; no script or per-board approval gate (D29). About 1.5–2 h GPU for the 45 s example. Estimates are illustrative, not a scheduler cost model. |
| Build result / cut review | A frozen storyboard preview, not playable video, audio or a technical validation result. Separate simulated human approval. |
| Asset promotion | Creates a new in-memory library entry; does not replace existing assets. |
| Sound and motion | Editable annotations; simulated per-board voice generation/playback and derived timing (D33/D35). No real audio or camera editor. |
| User / admin settings | Theme is functional; identity and access are read-only placeholders. No login, permissions or service administration. |
| Persistence | Theme and view selections use guarded localStorage. Drafts, generated assets, created productions/stories and runs stay in memory. Reload resets content. |

No API routes are proposed: that contract belongs to E3/E6, after this flow is accepted.


## v4 questions

None. D33–D37 answer the new navigation, timing, annotation and layout questions.
The 0.25 s pad and 25 fps timecode display are prototype defaults, not additional
owner rulings. No new decision is needed to review this mockup.
