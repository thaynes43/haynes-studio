# Questions for Tom

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
| Build | All current boards approved; about 1.5–2 h GPU for the 45 s example. Duration-scaled estimates after edits are illustrative, not a scheduler cost model. |
| Build result / cut review | A frozen storyboard preview, not playable video, audio or a technical validation result. Separate simulated human approval. |
| Asset promotion | Creates a new in-memory library entry; does not replace existing assets. |
| Sound and motion | Existing PoC cues are shown as short board notes. Audio editing, voice previews and camera controls are deferred. |
| User / admin settings | Theme is functional; identity and access are read-only placeholders. No login, permissions or service administration. |
| Persistence | In-memory story, library and build state; only theme uses guarded localStorage. Reload resets the example. |

No API routes are proposed: that contract belongs to E3/E6, after this flow is accepted.
