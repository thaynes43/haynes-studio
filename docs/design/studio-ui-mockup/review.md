# V1 adversarial UX review

Story: https://work.haynesnetwork.com/projects/haynes-studio/work_packages/401

Reviewed the v1 source at `8cd3e80` and clicked through Stories → Story → Board,
Library, Formats, Candidates and Render before replacing it. Browser: 400 × 860.

- **Navigation has no hierarchy.** Stories, Story and Board are peers alongside four
  other tabs. A newcomer must learn the data model to navigate. **Fix:** Productions
  → Yellowbirds → Shorts → The Winter Menu; Editor is the only other top-level section.
- **The work starts two screens down.** At 400 px the first board begins at y=1,674;
  the sticky header is 131 px tall. **Fix:** compact header, short metadata, immediate
  review action, then the boards.
- **Mobile hides destinations.** The navigation needs 526 px inside a 352 px viewport.
  **Fix:** two visible top-level links; compact breadcrumbs with an ancestor menu that
  still exposes every level.
- **The mockup is presenting a design meeting.** Decision tags, epic labels, repeated
  example notices, questions and implementation notes dominate. **Fix:** one small
  example tag; move uncertainties and implementation assumptions to supporting docs.
- **The video disappears into different sections.** Build leaves the story for Render;
  completion sends the user to Candidates and platform accounts. **Fix:** build and
  progress on the story; review its finished cut in the production tree.
- **Approval can happen without seeing the punchline.** The vote card truncates its
  dialogue to three lines but offers Approve. **Fix:** show all lines in the storyboard;
  approve in the focused board view alongside the reference photo and method.
- **Every board feels like a control room.** Seeds, chunks, voice identifiers, cue
  timing, model explanations and technical checks compete with script and photo.
  **Fix:** lead with photo, script, method and duration; disclose the photo composer
  only when editing it. Keep the PoC's sound/motion notes concise.
- **Terminology changes with the screen.** Production, story, candidate, drop and
  revision overlap; “Whole-frame” sits beside user-facing shot types. **Fix:** production
  means theme, story means video, board means clip; methods are Talking, Reaction,
  Ambient. Keep their technical mappings off-screen.
- **The library has everything except a clear creation path.** Eight categories,
  provenance and version management obscure choosing an input; generation-to-library
  promotion is missing. **Fix:** Cast, Costumes, Sets and Props; a Generate asset page,
  explicit promotion, and a named target board for adding an asset.
- **Scope runs ahead of the pilot.** Editable format recipes, actor-role switches,
  platform accounts and publishing gates belong to later work. **Fix:** one production,
  one real sample story, honest empty Videos/Published views, no publishing action.
- **Preferences have no home.** Implementation notes get header space; a user menu
  and explicit theme choice do not. **Fix:** a placeholder user-name dropdown with
  working Light/Dark/System and small User settings/Admin settings destinations.
- **Editing must make the approval consequence obvious.** V1 resets approvals, but
  buries why among technical checks. **Fix:** edits immediately mark a board Needs
  review; changed photo inputs require regeneration. A running build uses a frozen
  snapshot; an older completed build cannot approve a changed story.

## V2 scope

An interactive, in-memory design prototype, not an installed studio. The nine-board
r4 script and 45.3 s timing are sample content; the displayed approvals are fictional.
CSS/SVG drawings stand in for private photos. Generation and build progress are
explicitly simulated. Only the theme preference survives reload.

V2 browser check at 400 × 860: header 61 px; first board y=671; no horizontal page
overflow. Checked the interaction flow, themes and desktop at 1280 px. One extracted
script syntax check passed. Independent native review found a stale-photo race and
keyboard-focus loss; both were fixed and checked. Not tested inside claude.ai.

## v3 changes

Applied Tom's 2026-11-04 answers (D29–D32). These replace the v2 approval and
persistence defaults above and in the historical `questions.md` boundaries.

- Build needs only a board. Script and photos stay editable during runs; Agent draft
  is informational. A finished run has one **Approve for go-live** action, followed
  by disabled **Publish / Not connected**. Length shows the running total only.
- Runs snapshot boards when queued, execute serially, and show number, status,
  estimate/progress and timestamp. Two finished runs compare by board ID, including
  additions, removals and reordering. Older runs remain approvable after edits.
- Production, Shorts and Videos use combinable status chips. Assets default to
  Yellowbirds, with an All productions chip. Filters, selected board, photo panels
  and each top-level tab's location persist; guarded localStorage saves those
  preferences. Drafts, generated assets and runs remain in memory.

Validation: one extracted-script `node --check`; serial Chromium checks at
400 × 860 and 1280 × 900. Checked queue snapshots, comparisons, approval, filters,
navigation/reload persistence, blocked/malformed storage and all three themes.
No horizontal page overflow, script errors or external requests; mobile gutters
remain 16 px. Independent native source review: no findings. Comparison image widths
were equalized after visual inspection.

Still a placeholder prototype, not deployed or creatively accepted. No new questions;
not tested inside claude.ai. The coordinating session reviews and merges this PR.

## v4 research

Researched 2026-11-04, before implementing v4:

- **Stage, filmstrip, inspector.** [PanelForge's workspace and timeline screenshots](https://www.panel-forge.com/features.html)
  use a neutral working surface, a large image area and surrounding controls. Its
  [Panel Timeline documentation](https://docs.panel-forge.com/v9/Panel_Timeline)
  describes the bottom strip, panel identifiers and per-panel timing (that page is
  explicitly a draft). Adopt the spatial arrangement and readable IDs; replace the
  drawing properties with text forms, as Tom requested.
- **Metadata belongs to the selected panel.** [Storyboard Pro's Panel view](https://docs.toonboom.com/help/storyboard-pro-24/storyboard/reference/views/panel-view.html)
  groups panel/scene information, duration, dialogue, action and timing notes.
  [Wonder Unit Storyboarder](https://wonderunit.com/storyboarder/) likewise puts
  dialogue, action, timing and shot type on the right. Adopt stacked Script,
  Voice & timing, Reference photo and Annotations sections. Camera directions and
  sound cues stay editable notes; the PoC does not need separate camera controls.
- **Keep text beside the visual iteration.** [Boords' storyboard guide](https://assets.boords.com/docs/creating-storyboards)
  combines generated or supplied frames with label, sound and action fields, also
  accessible from its editor sidebar. Adopt nearby prompt, speaker and note fields
  without adding a separate script approval or another editor mode.
- **Make timing visible.** PanelForge's [timeline features](https://www.panel-forge.com/features.html)
  combine panel timing and audio tracks. Adopt a simple waveform strip, duration on
  each thumbnail, and a selected-board timecode range. D33 determines our timing:
  voice audio plus a short pad, or a user-set silent hold; no multitrack editor.
- **Palette is a design choice, informed by the references.** Use graphite and
  neutral gray surfaces, a darker stage, blue selection/audio and amber changed-input
  cues. Status always has text. The lighter Productions view shares these tokens.
  Default to Dark, retaining Light/System. Exact colors and the responsive stacking
  are our adaptation, not claims about a vendor's design standard.

## v4 changes

Implements the D33–D37 work order and retains D29–D32. Base: freshly fetched main
`caab3e2`; the D33–D37 proposal was still in [PR 23](https://github.com/thaynes43/haynes-studio/pull/23)
when checked. Only this mockup and its two companion documents are in scope.

- The editor is a stage, narrow tool rail, panel filmstrip and text inspector. At
  400 px, stage → horizontal filmstrip → collapsible inspector sections. The stage
  shows `S01-B08`-style stable IDs, reference version and a timecode range.
- Each speaking board has Generate/Regenerate voice, a version and simulated
  Play/Stop. Duration uses the last generated voice plus a **0.25 s prototype pad**.
  Silent boards expose a hold field. Editing dialogue/voice marks the prior track
  stale; new dialogue without a track is untimed until generation. Photo and voice
  inputs can change during generation without falsely marking the result current.
- Annotations can be added, edited and removed. The asset library includes reference
  and voice placeholders as well as reusable inputs. Opening it from a board applies
  that board and production; removable chips widen to the production, then all assets.
- Editor opens a landing with Storyboard editor and Asset library. Storyboarding
  offers choose/create production → Short/Video → choose/create story. Creations are
  in memory. Breadcrumbs are buttons and clear deeper filters; there is no duplicate
  path eyebrow. URL context distinguishes stories with the same board number, and
  the Productions tab remembers its own context.
- Runs still snapshot at queue time, execute serially and compare by stable board ID.
  Script, photo and voice versions remain visible in comparisons. Go-live is the only
  approval; Publish stays disconnected. Status chips and guarded selection/theme
  persistence remain. Drafts, new productions/stories, assets and runs reset on reload.

Validation (one syntax check and light, serial Chromium; 2-CPU session):

- One extracted-script `node --check` passed with raw output discarded. Static page
  contract and `git diff --check` passed; only the three requested text files changed.

- 1280 × 900: stage beside inspector, filmstrip beneath the stage; visual inspection.
  400 × 860: no horizontal page overflow, 16 px shell gutters; a 342 px filmstrip
  viewport contains 1,042 px of thumbnails, and the inspector follows it vertically.
  The Video stage also retains 16:9 at 400 px without page overflow.
- Clicked the landing and selection paths; created a production and a Video story,
  added its first board, then used Back/Forward to restore the original story and
  picker context. Checked the remembered Productions destination and combined
  Unpublished + Approved filters.
- Changed silent hold to 2.4 s; edited, added and removed annotations. Changed dialogue
  during voice generation and prompt during photo generation: both retained their
  changed-input state. Regenerated voice: 4.79 s audio + 0.25 s = 5.04 s board.
  Simulated Play/Stop updates both controls.
- Queued two runs while editing. Verified Running/Queued, eventual completion,
  different frozen dialogue/photo/voice versions in comparison, and approval of the
  older run after edits. Publish remained disabled.
- Board asset filter: 7 assets → 25 production assets → All productions. Selected
  board, inspector disclosure, asset type/search/scope survived reload. Malformed
  and blocked localStorage remained usable. Light, Dark and both System schemes
  used the intended tokens. No script errors or external resource loads in these
  checks. The local static server's initial favicon request returned 404.
- Initial browser checks exposed a focus-restoration error and duplicate Assets
  control IDs; both were fixed before the passing checks above.
- Independent native source review found missing entity context in history and
  remembered navigation. Fixed with contextual hashes and a saved review context;
  the targeted Back/Forward and cross-production checks above passed.

This remains an interactive placeholder, not a renderer or installed studio. The
waveform is decorative; regenerated voice durations are illustrative estimates from
sample text, not measured audio. Timecode uses a 25 fps display assumption. No media,
model calls, publishing or deployment. Tom's creative acceptance is pending; not
verified inside claude.ai. No OpenProject writes. The ready PR is intentionally left
unmerged for coordinating session `a1-haynes-ops-1103-141902`.

## v5 changes (2026-11-04, Tom's notes on v4)

- **One Build button.** The editor header holds Build (or Queue run). The Runs panel under the workspace lists runs and the estimate only. The story review page keeps its Build, since it has no header button.
- **Only the media types a production has.** The editor's media picker and the production page list the types that production already uses (Yellowbirds: Short). The missing types appear as small "+ Video · 16:9" buttons that add the type and open it.
- **Backstage palette.** Dark: near-black page, charcoal cards with thin borders, green primary actions with dark text, pill-shaped buttons. Light keeps the same structure, with a deeper green (`#13823d`) so links and button text stay legible on white.
