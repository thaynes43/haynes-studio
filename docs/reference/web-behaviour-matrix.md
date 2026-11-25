# Studio web behaviour matrix

[Story 438](https://work.haynesnetwork.com/work_packages/438) covers the app's
implementation of the [v6 interactions](../design/studio-ui-mockup/implementation-backlog.md#mockup-surface-to-story).
Run `pnpm --dir web test:e2e --workers=1` with Playwright Chromium installed.
The suite builds the app and serves it on loopback. The
[contract mock](../../web/e2e/studio-api.ts) supplies metadata, an OIDC return,
revision fences, queue transitions and synthetic media generated at test time.
It rejects external requests. The standalone [mockup smoke](../../web/e2e/mockup.spec.ts)
checks rendering and network isolation. Layout checks use geometry and focus,
with no image comparisons.

The main cases below run at 400 × 860 and 1280 × 900. The dedicated theme/settings,
expiry, outage and write-refusal cases add focused checks at one viewport each.
“Missing at base” identifies coverage added by this story.

| Behaviour | Playwright spec and test | What it asserts |
| --- | --- | --- |
| Routes, breadcrumbs and Back/Forward | [shell](../../web/e2e/shell.spec.ts) · “hierarchy and contextual history”; [editor entry](../../web/e2e/editor-entry.spec.ts) · “persists production, media type and story” | Production → media → story → board, correctly scoped photo and runs links, scope changes and browser history. |
| Dark, Light and System themes | [shell](../../web/e2e/shell.spec.ts) · “theme controls and settings preserve keyboard focus”; “hierarchy and contextual history” | Invalid preference falls back to Dark. Keyboard switches to Light. System follows the OS and survives reload. |
| Saved destinations and identity | [shell](../../web/e2e/shell.spec.ts) · “hierarchy and contextual history”; “expiry retains the route with blocked localStorage and rechecks the API identity” | API records Productions, Board and Assets paths. Reload and returning navigation use them. Session expiry requests sign-in and another user cannot restore inaccessible context. |
| Reload with blocked local and session storage | **Missing at base.** [shell](../../web/e2e/shell.spec.ts) · “reloads saved destinations with local and session storage blocked” | Waits for selection writes, reloads the same board, checks the saved API destinations and Dark fallback. After expiry, waits for the focused Productions root and confirms the saved Board destination survives. |
| Create a production, enable a media type and create a story | [editor entry](../../web/e2e/editor-entry.spec.ts) · “persists production, media type and story”; “validates current names from every page and surfaces API validation references”; “reloads the production on a revision conflict without replaying the write” | Reads all relevant name pages, persists creates, restores the story after reload and reports conflicting or invalid writes without replay. |
| Edit lines, notes, voice, timing, methods and cues | [board inspector](../../web/e2e/board-inspector.spec.ts) · “persists script, speakers, timing, method, and direction through the API”; “keeps edits on refusal and presents both versions after a conflict”; “shows the API refusal if a silent S2V request bypasses the control” | Checks the patch and revision, existing child IDs, saved values, keyboard line edits, silent S2V rejection and explicit conflict recovery. |
| Add, remove and reorder boards by keyboard | [storyboard workspace](../../web/e2e/storyboard-workspace.spec.ts) · “lays out the stage and persists add, keyboard reorder, and removal by ID”; “reloads on reorder conflicts and preserves or recovers the selected position” | Tabs to the move control, applies the edit with the correct revision and order, keeps focus on the moved board and reloads persisted order. Removal and conflicts pick the correct surviving board. |
| Keyboard focus across navigation, dialog-free actions and edits | [shell](../../web/e2e/shell.spec.ts) · “hierarchy and contextual history”; “theme controls and settings preserve keyboard focus”; [asset library](../../web/e2e/asset-library.spec.ts) · “opens from a board, widens by keyboard, restores URL and returns a promoted pin”; [board inspector](../../web/e2e/board-inspector.spec.ts) · “keeps focused input through polling and reload, then regenerates with measured timing and ranged playback” | Headings, active board, menu close and scope chips return focus to their destinations. A late voice result leaves focus on the typed line. |
| No page overflow | [shell](../../web/e2e/shell.spec.ts) · “hierarchy and contextual history”; [production review](../../web/e2e/production-review.spec.ts) · “runs show in order and play the private phone proxy and master”; [storyboard workspace](../../web/e2e/storyboard-workspace.spec.ts) · “lays out the stage and persists add, keyboard reorder, and removal by ID”; [story runs](../../web/e2e/story-runs.spec.ts) · “builds two revisions in FIFO order, compares them, and approves only the older snapshot”; [photo composer](../../web/e2e/photo-composer.spec.ts) · “queues pinned assets and a prompt, preserves edits during a job and supports regeneration”; [asset library](../../web/e2e/asset-library.spec.ts) · “opens from a board, widens by keyboard, restores URL and returns a promoted pin” | Compares document width to viewport width. The phone filmstrip scrolls inside the page and compare panes stack. |
| Two stories share the same board numbers | [storyboard workspace](../../web/e2e/storyboard-workspace.spec.ts) · “plays the selected voice with a byte range and keeps equal panel numbers scoped to their story” | Both are Board 01 with distinct IDs and timing. Photo and voice from the first story stay out of the second. |
| Stale voice results | [board inspector](../../web/e2e/board-inspector.spec.ts) · “keeps focused input through polling and reload, then regenerates with measured timing and ranged playback”; “tracks the paused lane, retries a single press, and reports worker failure and a stale saved result” | A late result stays stale for newer unsaved or saved lines. Playback and measured timing appear only for the current regenerated voice. |
| Stale photo results and saved pins | [photo composer](../../web/e2e/photo-composer.spec.ts) · “queues pinned assets and a prompt, preserves edits during a job and supports regeneration”; “retains a newer prompt when completion wins the race with its save”; “returns a scoped asset selection and recomposites a layered board without a prompt” | Covers both orders of completion and save, historical preview versus the current stage pin, ordered inputs, and layered recomposition. |
| Uploaded and imported versions | [photo composer](../../web/e2e/photo-composer.spec.ts) · “lists immutable provenance and preserves the picker at a revision conflict”; [asset library](../../web/e2e/asset-library.spec.ts) · “shows upload and imported provenance and uses cookie-authenticated preview ranges” | Shows recorded upload provenance, ranges a restricted preview, selects the upload with an ETag and keeps it on reload. Promotion creates a separate version. Recorded-only history has no preview or select action. |
| Combined publication/approval filters and combined Assets filters | [production review](../../web/e2e/production-review.spec.ts) · “production hierarchy and combinable saved filters”; [asset library](../../web/e2e/asset-library.spec.ts) · “opens from a board, widens by keyboard, restores URL and returns a promoted pin” | Waits for the story-list response carrying both query parameters, then checks the intersection, persisted filters and reload. Assets keeps scope, target, kind and query in the URL while remembering only the durable selection. |
| Rapid Assets search | **Missing at base.** [asset library](../../web/e2e/asset-library.spec.ts) · “keeps rapid search keys in the input and URL, including through history” | Waits for the loaded catalog, sends individual keys without a delay, then checks the whole input, query and matching result. Kind changes and Back/Forward restore the correct search. |
| Generate lane and missing candidate link | **Missing at base.** [asset library](../../web/e2e/asset-library.spec.ts) · “stops polling a missing job but keeps the generate lane live and drops the job on filter change” | Waits for the 404 message and initial lane read. Advances the fake clock to the next poll and waits for the lane response and changed status. A target change drops the missing job from the URL and the next candidate still queues. |
| Candidate jobs and promotion | [asset library](../../web/e2e/asset-library.spec.ts) · “replays one press, prevents promotion after Not now and promotes explicitly after Review again”; “releases the press after a 422 and submits a new key and corrected body” | Retries an ambiguous press with the same key, records the explicit promotion and uses a new key after a definitive refusal. |
| Two queued snapshots, comparison and exact older-run approval | Comparison existed. **Queue-to-approval link missing at base.** [story runs](../../web/e2e/story-runs.spec.ts) · “builds two revisions in FIFO order, compares them, and approves only the older snapshot” | Waits for queue and terminal states after fake-clock polls. Compares frozen IDs and edits, tests missing snapshot fallback, then follows the run review link. Waits for the approval receipt, checks its snapshot and master, reloads and confirms the newer run is still unapproved. |
| Go-live approval negatives and withdrawal | [production review](../../web/e2e/production-review.spec.ts) · “legacy runs and signed-in non-approvers have no write controls”; “expired approval session returns to the exact run for deliberate confirmation”; “missing approver configuration and failed release checks show their API reasons”; “other documented refusals preserve their individual API reasons”; “a write refusal displays the returned code's reason without replaying the write”; “approval pins an older run after a draft edit and withdrawal stays in history” | Checks legacy and identity gates, exact-run and release refusals, deliberate confirmation after fresh sign-in, and withdrawal history after reload. |
| Disconnected Publish | Manual release existed. **Explicit no-publish assertion missing at base.** [release package](../../web/e2e/release-package.spec.ts) · “prepares, downloads, holds and records the manual drop for one run” | Waits for the package, exact-run approval, download and return to that run. Checks that the story is still Unpublished, no Publish action is available, and no publication request occurred before “Record publication”. The mock records only the explicit Studio request and rejects external traffic. |
| Feedback and iteration on a candidate | [candidate feedback](../../web/e2e/candidate-feedback.spec.ts) · “presents a run and walks from frozen feedback to an answering run” | Checks frozen board labels, a corrected note, no blind replay on revision conflict and links between runs. |

## Installed playback · Expected

The [installed spec](../../web/e2e/installed-playback.spec.ts) uses the exact two
[imported archives](studio-import.md), including the quieter-gavel cut from
[story 428](https://work.haynesnetwork.com/work_packages/428). The archive
IDs are recorded on [story 957](https://work.haynesnetwork.com/work_packages/957)
and proxy hashes and sizes come from the [archive receipt](../../titles/one-more-meeting/run-evidence.json).
The journey awaits a person-supplied authenticated session.

From a machine on the Studio LAN, a person must provide the installed HTTPS
origin and an absolute path to a Playwright storage-state JSON file for an
existing identity allowed to read both imports. Sign in through Authentik in
a Playwright browser context, then save that context with
`await context.storageState({ path: "/absolute/private/path/studio-state.json" })`.
Store the file outside the checkout with access restricted to the operator.

```sh
STUDIO_THREADS=2 \
STUDIO_INSTALLED_BASE_URL=https://studio.haynesops.com \
STUDIO_INSTALLED_STORAGE_STATE=/absolute/private/path/studio-state.json \
  pnpm --dir web exec playwright test --config playwright.installed.config.ts --workers=1
```

This is a separate local runner. Both cases skip without the two inputs and
always skip in CI. On success, the real shell accepts the existing session,
loads each exact run's delivery and plays its private H.264 proxy at a phone
viewport. The test checks the session cookie on a browser request, HTTP 206,
the exact content range and byte count, and advancing playback time. The
runner allows only the read requests for identity, selections, the two
production/story/run records and their proxies, plus app scripts and styles.
It intercepts the shell's automatic selection write and ancillary draft,
feedback and release reads. It collects no screenshots, traces or videos.
The person performs OIDC sign-in before the run. Human sign-in, physical phone
playback and seek, new builds, uploads, approvals and creative acceptance
remain outside this evidence. [Human playback story](https://work.haynesnetwork.com/work_packages/944)
