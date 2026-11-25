# Use Haynes Studio

This guide follows the LAN app at Studio `80975a9` (third deployment pin,
database revision `0012_release_constraints`). **Proven on the installed app**
below names the checks that reached the live service. **Proven against the
mock only** means the browser steps ran with synthetic responses. The
signed-in installed journey is **Expected**. [Deployment evidence, comment
10061](https://work.haynesnetwork.com/work_packages/964) ·
[Browser behaviour matrix](../reference/web-behaviour-matrix.md)

## Sign in and find a film

1. On your home network, open [Haynes Studio](https://studio.haynesops.com).
   Press **Sign in** and use your existing Authentik account. Studio returns
   to the page you opened. If your session expires, press **Sign in** again.
   If Authentik or Studio refuses access, give the operator the error and any
   Request ID shown. **Proven on the installed app** through the sign-in
   redirect. **Proven against the mock only** for the completed browser
   sign-in and return to the same page. [LAN install, OP434](https://work.haynesnetwork.com/work_packages/434) ·
   [Sign-in tests](../../web/e2e/shell.spec.ts)
2. Open **Productions**, choose **One More Meeting** or **The Winter Menu**,
   then **Shorts 9:16**, the story title and its **Imported** run. If a story
   is missing, clear its publication and approval filters and check that you
   opened the intended production and media type. Both imports have a private
   proxy available when your session can read the production. **Proven against
   the mock only** for navigation and saved filters. **Proven on the installed app**
   for the two imported records and scoped reads of their exact proxies.
   [Productions tests](../../web/e2e/production-review.spec.ts) ·
   [Import and playback, comment 9914](https://work.haynesnetwork.com/work_packages/957) ·
   [Archive receipts for both films](../../titles/one-more-meeting/run-evidence.json)
3. On your phone, open that same run, tap Play on **Phone proxy**, turn up
   the volume and drag the scrubber past halfway. Check that picture and
   sound resume. If the player fails, sign in again, return to the same
   run and tell the operator the title and run number if it still fails.
   On a shared device, open the account menu and press **Sign out** when done.
   **Expected** on a signed-in browser and physical phone. The scoped
   byte-range proof above used keys. [Installed journey spec](../reference/web-behaviour-matrix.md#installed-playback--expected) ·
   [Phone evidence, OP944](https://work.haynesnetwork.com/work_packages/944)

## Make and edit a story

1. Open **Editor** → **Storyboard editor**. Choose a production, or enter a
   **Production name** and press **Create production**. Choose **Short 9:16**
   or **Video 16:9**. If the type is missing, use **+ Short · 9:16** or
   **+ Video · 16:9**. Enter a **Story title** and press **Create story**.
   Studio opens an empty storyboard. If a name is taken, open the existing
   item or choose a different name. If the production changed, wait for
   Studio to refresh the media types and choose from the updated list.
   **Proven against the mock only.** [Editor tests](../../web/e2e/editor-entry.spec.ts)
2. Press **Add board**, then use the **Boards** filmstrip to select a panel.
   The stage shows that board's photo and timing. In **Board inspector**,
   edit the lines, speakers, method or direction and press **Save board**.
   The inspector shows **Board saved.** Use **Move earlier** or **Move
   later** to change the selected board's position. The number changes and
   the same board stays selected. If the save conflicts, compare **Your
   unsaved version** with **Latest saved version**, then save the intended
   edits. For a reorder conflict, check the refreshed filmstrip before
   trying again. **Proven against the mock only.**
   [Storyboard tests](../../web/e2e/storyboard-workspace.spec.ts) ·
   [Inspector tests](../../web/e2e/board-inspector.spec.ts)
3. Use the breadcrumb to go up a level and clear deeper selections. Open
   **Assets** from a board to see that board's references. Remove scope
   chips to widen the view. Returning to **Board** or **Productions** can
   restore the last destination. If the selected board was removed, Studio
   opens a surviving board and shows a notice. On a phone, scroll the
   filmstrip sideways and look below it for tools. **Proven against the
   mock only.** [Navigation tests](../../web/e2e/shell.spec.ts) ·
   [Storyboard tests](../../web/e2e/storyboard-workspace.spec.ts) ·
   [Assets tests](../../web/e2e/asset-library.spec.ts)

## Get voice and pictures

1. On a speaking board with a stock voice configured for the speaker, save
   the dialogue and speaker in **Board inspector**. Under **Voice & timing**,
   press **Generate voice**. Studio shows **Queued in voice lane** and then
   **Generating voice…**. Play the completed track on the board and check
   the measured duration. For **Voice ready ·
   stale**, save the current inputs, then press **Regenerate voice**. If a
   request loses its reply, use the offered retry. If the lane is paused,
   leave the existing request queued. If the speaker has no voice, ask the
   operator to prepare the story's narrator or cast voice before retrying.
   **Proven against the mock only.** [Voice tests](../../web/e2e/board-inspector.spec.ts) ·
   [Installed worker evidence](https://work.haynesnetwork.com/work_packages/961)
2. On the board, open **Reference photo**. For a whole-frame board, enter a
   **Photo prompt** and choose inputs from **Add pinned asset** or
   **Browse Assets**. Press **Generate photo** or **Regenerate photo**,
   which saves the inputs for that request.
   For a layered board, check **Composite layers** and press **Recomposite**.
   The request waits in the image lane. **Photo ready** means the current
   result can appear on the stage. A result for earlier inputs stays in
   **Photo versions**. If inputs changed while it ran, check the current
   inputs and regenerate. If a version is recorded without media, choose
   one with a preview or make a new one. An externally supplied photo
   comes through a scoped upload and appears as **Agent upload** in
   history. Choose its **Select v…** action if it did not become the stage
   selection. **Proven against the mock only** for the composer and upload
   history. A real photo request and upload are **Expected**.
   [Photo tests](../../web/e2e/photo-composer.spec.ts) ·
   [Photo upload route](../reference/studio-api.md#d42-photo-upload)
3. In **Assets**, press **Generate asset**, fill **Name**, **Kind** and
   **Prompt**, then press **Request candidate**. Stay on its job to see
   **Candidate queued**, **Candidate running** and **Candidate ready** with
   a preview. If the lane is paused, wait for the operator. Use **Retry
   candidate request** after an uncertain reply. If Studio says the job
   was not found, return to the library and reopen **Generate asset**.
   If the job failed, read the error before making a new request.
   **Proven against the mock only.** [Candidate tests](../../web/e2e/asset-library.spec.ts) ·
   [Candidate reference](../reference/asset-candidates.md#api-and-ui-integration)
4. When the preview is right, press **Promote**. **Promoted to library**
   makes the version available in scope. From a compatible board, the
   **Use on board** returns that exact version to the composer.
   **Not now** hides the candidate in this tab and **Review again** brings
   it back. If promotion is refused, read the message and retry the read
   if offered before promoting again. **Proven against the mock only.**
   [Promotion tests](../../web/e2e/asset-library.spec.ts)

## Build and compare

1. From the storyboard, press **Build**. **Runs** opens with a numbered run,
   a queue position and any available estimate. A run freezes the saved
   board order and asset versions. **Paused · Held** means that run is
   waiting for the worker to reconcile it. A lane pause holds new claims
   while already claimed work can finish. Open **Details** to see the
   stage and reason, and give the operator the run ID if it stays held.
   For a preflight refusal, fix the listed boards or missing inputs. For
   a revision conflict, use **Reload draft** and check the latest edits.
   Use **Retry build** after a lost reply to the same press. **Proven
   against the mock only.** [Runs tests](../../web/e2e/story-runs.spec.ts) ·
   [Operator queue steps](studio-operator-runbook.md#paused-lane-stuck-run-or-failed-job)
2. When the run finishes, press **View run** → **Review in Productions** to
   play the finished delivery. To compare, edit the draft and queue a second
   build. In **Runs**, open **Compare runs** and choose **Left run** and
   **Right run**. The panes stack on a phone. Check both videos and **Board
   comparison** for changes to the frozen snapshots. If a snapshot is
   missing, use the available players. **Proven against the mock only.**
   [Runs and comparison tests](../../web/e2e/story-runs.spec.ts)

## Give feedback or review a release

- For an eligible finished run in **Productions**, open **Candidates and
  feedback**. Choose a **Target**, press **Present run**, enter a **Feedback
  note**, then press **Add feedback**. Use **Boards (optional)** to attach
  a reference from that run. If the target is refused, check the run's
  format target. If a draft iteration conflicts, reload and review the
  current draft before starting it again. **Proven against the mock only.**
  [Feedback tests](../../web/e2e/candidate-feedback.spec.ts)
- Review the run you intend to release in **Productions**. For an eligible
  target, use **Release package** → **Release target** → **Prepare package**.
  The panel shows the checks and a hold reason while release is held. The
  **Go-live** panel lets Tom, once on the approver list, confirm the
  AI-generated platform setting and press **Approve for go-live**. It
  records his decision for that exact run and master. If the format is
  missing or has no release target, ask the operator to check the format
  before building a replacement run. If Studio asks for fresh sign-in,
  return to the same run and confirm again. If it reports a failed check,
  address the reason before trying again. Imported runs are ineligible and the
  installed approver list is empty. **Proven against the mock only** for
  package preparation and approval. **Proven on the installed app** for
  the imports' legacy refusal in the deployment probe.
  [Approval tests](../../web/e2e/production-review.spec.ts) ·
  [Release package tests](../../web/e2e/release-package.spec.ts) ·
  [Format recipes](../reference/formats.md#drafts-and-queued-runs) ·
  [Third-pin evidence, comment 10061](https://work.haynesnetwork.com/work_packages/964)

## Privacy and go-live

Keep films, voice tracks, reference photos and release packages in private
Studio storage. Watch from the LAN with your own sign-in. Comparing, giving
feedback and choosing a run happen privately. Go-live is Tom's only formal
approval (D29). Even after Studio records it, the run stays **Unpublished**
until a separately authorized manual release is recorded. Studio has no
platform publishing integration. [Decisions D29, D43 and D52](../proposals/0003-studio-plan.md#decisions-so-far) ·
[Release package tests](../../web/e2e/release-package.spec.ts)

## Remaining gaps

| Step | Why it is open | What would prove it |
| --- | --- | --- |
| LAN sign-in, selection and phone playback | Installed evidence ends at the sign-in redirect and scoped range reads. The installed browser spec awaits a person's session. | Sign in, navigate to both imports, play with audible sound and seek on a phone, then verify access ends on sign-out or expiry. [Installed journey](../reference/web-behaviour-matrix.md#installed-playback--expected) · [OP944](https://work.haynesnetwork.com/work_packages/944) |
| Edit, generate, upload, promote, build and compare | Nobody has recorded a voice take, uploaded a photo, given feedback or built a release package on the installed app. Workers have proved reachability and idle claims. | Use a person's session for the first end-to-end private trial and record the actual versions, run IDs and private playback results. Use an authorized uploader for the external photo. [OP961](https://work.haynesnetwork.com/work_packages/961) · [OP964](https://work.haynesnetwork.com/work_packages/964) |
| Assets search and missing candidate job | The installed pin predates the fixes for fast typing in **Search** and keeping image-lane status current after a job link returns 404. | Verify both behaviours after a pin that includes OP438, in a signed-in session. [Browser behaviour matrix](../reference/web-behaviour-matrix.md) |
| Feedback, release package and go-live | A real eligible run and real feedback and package are still due. The go-live approver list is empty. | Record feedback and a private package for an eligible Studio-built run. Tom's explicit decision on an exact master proves go-live approval. [OP964](https://work.haynesnetwork.com/work_packages/964) · [Go-live](../reference/go-live.md) |
| Matte and occlusion on a real board | The backend smokes and weights are staged, and the third pin has no serving matting or segmentation sidecar or matte jobs. | Run a private cast-photo matte and a real staged occlusion check with installed backends, then inspect the results. [Matte jobs](https://work.haynesnetwork.com/work_packages/965) · [Occlusion](https://work.haynesnetwork.com/work_packages/452) |
