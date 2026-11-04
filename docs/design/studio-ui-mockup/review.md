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
