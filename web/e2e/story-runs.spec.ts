import { expect, test as base, type Page } from "@playwright/test";

import { treePath } from "../src/routes";
import { pollInterval } from "../src/run-polling";
import { mockStudio, story, storyContext } from "./studio-api";
import { generateReviewMedia, type ReviewMedia } from "./studio-review-media";

const test = base.extend<{
  api: Awaited<ReturnType<typeof mockStudio>>;
}, { media: ReviewMedia }>({
  media: [async ({ browser }, use) => { await use(await generateReviewMedia(browser)); }, { scope: "worker" }],
  api: async ({ context, baseURL, media }, use) => {
    const api = await mockStudio(context, baseURL!, { storyboardMedia: media, runMedia: media });
    await use(api);
    expect(api.violations).toEqual([]);
  },
});

const storyPath = treePath("board", storyContext);
const runsPath = `/v1/stories/${story.id}/runs`;
const firstBoardId = story.board_order[0];
const photoTwo = "asv_01M79V9FC00000000000000011";
const voiceTwo = "asv_01M79V9FC00000000000000012";
const build = (page: Page) => page.getByRole("button", { name: "Build", exact: true });
const run = (page: Page, number: number) => page.getByRole("article", { name: `Run ${number}`, exact: true });
const stage = (page: Page) => page.getByRole("region", { name: "Selected board stage" });
const activeBoard = (page: Page) => page.getByRole("list", { name: "Boards" }).locator('[aria-current="page"]');

async function openStory(page: Page) {
  await page.clock.install();
  await page.goto(storyPath);
  await expect(build(page)).toBeEnabled();
  await expect(page.getByText("No runs yet.")).toBeVisible();
}

async function poll(page: Page, delay = pollInterval) {
  await page.clock.runFor(delay + 100);
}

async function expectNoOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width);
}

for (const viewport of [{ width: 400, height: 860 }, { width: 1280, height: 900 }]) {
  test.describe(`${viewport.width} × ${viewport.height}`, () => {
    test.use({ viewport });

    test("builds two revisions in FIFO order, compares them, and approves only the older snapshot", async ({ page, api, media }) => {
      const queue = api.queue!;
      await openStory(page);
      await expect(build(page)).toBeInViewport();
      await expect(build(page)).toHaveAccessibleDescription(/past the format maximum/);
      const timeline = (await page.getByRole("region", { name: "Panel timeline" }).boundingBox())!;
      const list = (await page.getByRole("region", { name: "Runs", exact: true }).boundingBox())!;
      expect(list.y).toBeGreaterThanOrEqual(timeline.y + timeline.height);

      await build(page).click();
      await expect(run(page, 1)).toContainText("Queue position 1");
      const first = queue.runs[0];
      queue.advance(first.id, "running", "Worker started", { progress: { percent: 25, stage: "rendering_boards" } });
      await poll(page);
      await expect(run(page, 1)).toContainText("rendering boards 25%");
      await expect(run(page, 1)).toContainText("Uncertain estimate");

      await page.getByRole("link", { name: /^Board 02/ }).click();
      await page.getByRole("button", { name: "Remove board" }).click();
      await expect(activeBoard(page)).toContainText("Board 02");
      await page.getByRole("button", { name: "Move earlier" }).click();
      await expect(activeBoard(page)).toContainText("Board 01");
      await page.getByRole("button", { name: "Add board" }).click();
      await expect(activeBoard(page)).toContainText("Board 04");
      const addedId = (await stage(page).getByLabel("Board ID").textContent())!;
      const initial = structuredClone(queue.snapshots.get(first.id)!.story);
      const [initialBoard] = initial.boards;
      api.editDraftBoard(firstBoardId, {
        lines: [{ ...initialBoard.lines[0], text: "The soup demands a receipt." }],
        photo: { ...initialBoard.photo, current_version_id: photoTwo },
        voice: { ...initialBoard.voice, current_version_id: voiceTwo },
        method: { layer: "whole_frame", motion: "i2v" },
      });
      const location = page.url();
      await page.reload();
      await expect(run(page, 1)).toContainText("rendering boards 25%");
      await expect(page).toHaveURL(location);
      await expect(stage(page).getByLabel("Board ID")).toHaveText(addedId);
      await build(page).click();
      await expect(run(page, 2)).toContainText("Queue position 2");
      await expect(run(page, 2)).toContainText(/Wait .*uncertain/);
      await expect(page.getByRole("region", { name: "Runs", exact: true }).getByRole("heading", { level: 3 }))
        .toHaveText(["Run 2", "Run 1"]);

      const second = queue.runs[1];
      const revised = structuredClone(queue.snapshots.get(second.id)!.story);
      expect(first.snapshot.sha256).not.toBe(second.snapshot.sha256);
      expect(initial.board_order).toHaveLength(4);
      expect(revised.board_order).toEqual([initial.board_order[2], firstBoardId, initial.board_order[3], addedId]);
      expect(initialBoard.lines[0].text).toBe("The soup can hear you.");
      expect(revised.boards[1]).toMatchObject({
        id: firstBoardId, lines: [{ text: "The soup demands a receipt." }],
        photo: { current_version_id: photoTwo }, voice: { current_version_id: voiceTwo },
        method: { layer: "whole_frame", motion: "i2v" },
      });
      expect(initialBoard.photo.current_version_id).not.toBe(photoTwo);
      expect(initialBoard.voice.current_version_id).not.toBe(voiceTwo);
      expect(initialBoard.method).not.toEqual(revised.boards[1].method);

      const unsaved = page.getByRole("complementary", { name: "Board inspector" })
        .getByRole("textbox", { name: "New direction note" });
      await unsaved.fill("An unsubmitted edit");
      const callsAtLoss = api.calls.length;
      api.failNext({
        path: runsPath, method: "GET", status: 503,
        detail: {
          status: "service_unavailable", http_status: 503, path: "",
          code: "database.failed", message: "Metadata temporarily unavailable", request_id: "test-unavailable",
        },
      });
      await poll(page);
      await expect(page.getByText("Metadata temporarily unavailable")).toBeVisible();
      await expect(run(page, 2)).toContainText("Queue position 2");

      queue.advance(first.id, "succeeded", "Verified delivery");
      queue.advance(second.id, "running", "Worker started", { progress: { percent: 40, stage: "mix" } });
      await poll(page, 2 * pollInterval);
      await expect(page.getByText("Metadata temporarily unavailable")).toBeHidden();
      await expect(run(page, 1)).toContainText("Finished");
      await expect(run(page, 2)).toContainText("mix 40%");
      await expect(unsaved).toHaveValue("An unsubmitted edit");
      await expect(unsaved).toBeFocused();
      await expect(stage(page).getByLabel("Board ID")).toHaveText(addedId);
      expect(api.calls.slice(callsAtLoss)).not.toContain(`GET /v1/stories/${story.id}`);

      const proxyPath = `/v1/media/${media.proxy.hash}`;
      const fetched = page.waitForResponse((response) => new URL(response.url()).pathname === proxyPath);
      await run(page, 1).getByRole("button", { name: "View run" }).click();
      const video = run(page, 1).getByLabel("Phone proxy");
      await expect(video).toHaveAttribute("src", proxyPath);
      const response = await fetched;
      expect(response.request().headers().range).toBe("bytes=0-");
      expect(response.status()).toBe(206);
      expect(response.headers()["content-range"]).toBe(`bytes 0-${media.proxy.body.length - 1}/${media.proxy.body.length}`);
      await video.evaluate(async (el: HTMLVideoElement) => { el.muted = true; await el.play(); });
      await expect.poll(() => video.evaluate((el: HTMLVideoElement) => el.currentTime)).toBeGreaterThan(0);
      await expect(run(page, 1).getByRole("link", { name: "Review in Productions" }))
        .toHaveAttribute("href", treePath("productions", { ...storyContext, run: first.id }));
      await expect(run(page, 1)).toContainText("audio.loudness · Passed");
      await expect(page.getByRole("button", { name: "Approve for go-live" })).toHaveCount(0);

      queue.advance(second.id, "succeeded", "Verified delivery");
      await poll(page);
      await expect(run(page, 2)).toContainText("Finished");
      expect(second.started_at! >= first.finished_at!).toBe(true);
      expect(queue.snapshots.get(first.id)!.story).toEqual(initial);
      expect(queue.snapshots.get(second.id)!.story).toEqual(revised);
      const listReads = api.calls.filter((call) => call === `GET ${runsPath}`).length;
      await poll(page, 2 * pollInterval);
      expect(api.calls.filter((call) => call === `GET ${runsPath}`)).toHaveLength(listReads);
      await expectNoOverflow(page);

      await page.getByRole("link", { name: "Compare runs" }).click();
      await expect(page).toHaveURL(new RegExp(`${storyPath}/runs/compare$`));
      await expect(page.getByRole("combobox", { name: "Left run", exact: true })).toHaveValue(first.id);
      await expect(page.getByRole("combobox", { name: "Right run", exact: true })).toHaveValue(second.id);
      const comparison = page.getByRole("region", { name: "Board comparison" });
      await expect(comparison).toBeVisible();
      const row = (id: string) => comparison.getByRole("article").filter({ hasText: id });
      await expect(row(addedId)).toContainText("Added");
      await expect(row(initial.board_order[1])).toContainText("Removed");
      await expect(row(firstBoardId)).toContainText("Reordered");
      await expect(row(firstBoardId)).toContainText("Script · Photo version · Voice version · Method");
      await expect(row(firstBoardId)).toContainText(photoTwo);
      await expect(row(firstBoardId)).toContainText(voiceTwo);
      expect(api.calls).toContain(`GET /v1/runs/${first.id}/snapshot`);
      expect(api.calls).toContain(`GET /v1/runs/${second.id}/snapshot`);
      await expect(page.getByLabel("Phone proxy")).toHaveCount(2);
      const left = (await page.getByRole("region", { name: "Left run" }).boundingBox())!;
      const right = (await page.getByRole("region", { name: "Right run" }).boundingBox())!;
      if (viewport.width === 400) expect(right.y).toBeGreaterThanOrEqual(left.y + left.height);
      else {
        expect(right.y).toBe(left.y);
        expect(right.x).toBeGreaterThanOrEqual(left.x + left.width);
      }
      await expectNoOverflow(page);

      const firstSnapshot = queue.snapshots.get(first.id)!;
      queue.snapshots.delete(first.id);
      await page.reload();
      await expect(page.getByRole("region", { name: "Left run" })).toContainText("Snapshot not available.");
      await expect(page.getByLabel("Phone proxy")).toHaveCount(2);
      queue.snapshots.set(first.id, firstSnapshot);

      await page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("button", { name: "Runs", exact: true }).click();
      await run(page, 1).getByRole("button", { name: "View run" }).click();
      await run(page, 1).getByRole("link", { name: "Review in Productions" }).click();
      const firstReview = treePath("productions", { ...storyContext, run: first.id });
      await expect(page).toHaveURL(firstReview);
      const panel = page.getByRole("region", { name: "Go-live" });
      await expect(panel.locator("code")).toHaveText(media.olderMaster.hash);
      await page.getByRole("checkbox", { name: "Confirm the AI-generated platform setting" }).check();
      await panel.getByRole("button", { name: "Approve for go-live", exact: true }).click();
      await expect(panel.getByText("Go-live approval recorded.")).toBeVisible();
      expect(api.approvalWrites).toEqual([{
        run: first.id, body: { master_sha256: media.olderMaster.hash, platform_setting: true },
      }]);
      expect(queue.history(first.id)).toMatchObject([{
        run_snapshot_sha256: first.snapshot.sha256, delivery_id: first.delivery_id, derived: { state: "active" },
      }]);
      expect(queue.history(second.id)).toEqual([]);

      await page.reload();
      await expect(page).toHaveURL(firstReview);
      const links = page.getByRole("list", { name: "Story runs" });
      await expect(links.getByRole("link", { name: /Run 1.*Finished.*Approved/ })).toHaveAttribute("aria-current", "true");
      await links.getByRole("link", { name: /^Run 2 Finished$/ }).click();
      await expect(panel.locator("code")).toHaveText(media.master.hash);
      await expect(panel.getByRole("button", { name: "Approve for go-live", exact: true })).toBeDisabled();
      await expectNoOverflow(page);
    });

    test("reuses a lost press key after a draft edit and uses a new key for the next build", async ({ page, api }) => {
      const queue = api.queue!;
      await openStory(page);
      api.dropNextQueueReply(viewport.width === 400 ? "connection" : "server");
      await build(page).click();
      await expect(page.getByRole("button", { name: "Retry build" })).toBeEnabled();
      expect(queue.runs).toHaveLength(1);
      const first = queue.runs[0];
      await page.getByRole("button", { name: "Add board" }).click();
      await expect(activeBoard(page)).toContainText("Board 05");
      await page.getByRole("button", { name: "Retry build" }).click();
      await expect(build(page)).toBeEnabled();
      expect(queue.runs).toHaveLength(1);
      expect(queue.presses).toEqual([
        { key: first.idempotency_key, revision: '"1"' }, { key: first.idempotency_key, revision: '"1"' },
      ]);
      await build(page).click();
      await expect(run(page, 2)).toBeVisible();
      expect(queue.presses[2].key).not.toBe(first.idempotency_key);
      expect(queue.presses[2].revision).toBe('"2"');
    });

    test("shows stale and denied builds and reports preflight problems board by board", async ({ page, api }) => {
      const queue = api.queue!;
      const [first, second] = story.board_order;
      await openStory(page);
      api.setDraftOrder([second, first]);
      await build(page).click();
      await expect(page.getByRole("alert")).toContainText("The draft changed. Reload the draft before building.");
      await expect(build(page)).toBeDisabled();
      expect(queue.presses).toHaveLength(1);
      await page.getByRole("button", { name: "Reload draft" }).click();
      await expect(build(page)).toBeEnabled();
      await expect(stage(page).getByLabel("Board ID")).toHaveText(first);

      api.preflightProblems([
        { rule: "method.unavailable", status: "unavailable", path: "/boards/0/method", board_id: second,
          board_number: 7, field: "/method", message: "This method can’t be built." },
        { rule: "voice.absent", status: "invalid", path: "/boards/1/voice", board_id: first,
          board_number: 12, field: "/voice", message: "A current voice is required." },
      ]);
      await build(page).click();
      await expect(page.getByRole("alert")).toContainText("This method can’t be built.");
      await expect(page.getByText("A current voice is required.", { exact: false })).toBeVisible();
      const feedback = page.locator(".run-build-feedback");
      await expect(feedback.locator(".run-problems > p")).toHaveText([`Board 01 ${second}`, `Board 02 ${first}`]);
      expect(queue.runs).toHaveLength(0);
      expect(queue.presses.map(({ revision }) => revision)).toEqual(['"1"', '"2"']);

      api.preflightProblems([]);
      api.failNext({
        path: runsPath, method: "POST", status: 503, detail: {
          status: "service_unavailable", http_status: 503, code: "database.failed",
          message: "The metadata store could not complete the request", request_id: "mock-database", path: "",
        },
      });
      await build(page).click();
      await expect(page.getByRole("button", { name: "Retry build" })).toBeEnabled();
      await page.getByRole("button", { name: "Add board" }).click();
      await expect(activeBoard(page)).toContainText("Board 03");
      await page.getByRole("button", { name: "Retry build" }).click();
      await expect(page.getByRole("alert")).toContainText("The draft changed. Reload the draft before building.");
      await expect(build(page)).toBeDisabled();
      await page.getByRole("button", { name: "Reload draft" }).click();
      await expect(build(page)).toBeEnabled();

      api.failNext({
        path: runsPath, method: "POST", status: 403, detail: {
          status: "forbidden", http_status: 403, code: "auth.forbidden", message: "This credential cannot perform the operation",
          request_id: "mock-forbidden", path: "",
        },
      });
      await build(page).click();
      await expect(page.getByRole("alert")).toContainText("This credential cannot perform the operation");
      await expect(feedback.getByText("auth.forbidden")).toBeVisible();
      expect(queue.runs).toHaveLength(0);
    });

    test("reports a hold, pending cancellation and failure, and records only the visual check override", async ({ page, api }) => {
      const queue = api.queue!;
      await openStory(page);
      await build(page).click();
      await expect(run(page, 1)).toBeVisible();
      await build(page).click();
      await expect(run(page, 2)).toBeVisible();
      const [first, second] = queue.runs;
      queue.advance(first.id, "running", "Worker started", {
        progress: { percent: 18, stage: "wan" },
        wan_attempts: [{ attempt: 1, job_id: "1".repeat(32), kind: "i2v", state: "sent" }],
      });
      queue.advance(first.id, "held", "Waiting for the worker to reconcile the GPU job", {
        error: { code: "wan.ambiguous_submit", message: "Wan has no settled outcome.", stage: "wan", board_id: null, board_number: null },
        checks: [{ check: "layered.decal_gate", artifact: "b".repeat(64), result: "fail" }],
      });
      await poll(page);
      await expect(run(page, 1)).toContainText("Paused · Held");
      await expect(run(page, 1)).toContainText("Waiting for the worker to reconcile the GPU job");
      await run(page, 1).getByRole("button", { name: "Details" }).click();
      await expect(run(page, 1)).toContainText("layered.decal_gate");
      await expect(run(page, 1).getByRole("textbox")).toHaveCount(0);

      const revision = first.revision;
      await run(page, 1).getByRole("button", { name: "Cancel run" }).click();
      await expect(run(page, 1)).toContainText("Cancellation requested.");
      await expect(run(page, 1)).toContainText("Paused · Held");
      await expect(run(page, 1).getByRole("button", { name: "Cancel run" })).toHaveCount(0);
      expect(queue.cancelWrites).toEqual([{ id: first.id, revision: `"${revision}"` }]);

      queue.advance(first.id, "cancelled", "The GPU job settled", {
        progress: { percent: 100, stage: "cancelled" }, error: null,
      });
      queue.advance(second.id, "running", "Worker started");
      const artifact = "a".repeat(64);
      queue.advance(second.id, "failed", "Build check failed", {
        error: { code: "layered.decal_weak", message: "The decal track did not pass.", stage: "key_frames", board_id: firstBoardId, board_number: 12 },
        checks: [
          { check: "layered.decal_gate", result: "fail", artifact },
          { check: "audio.loudness", result: "fail", artifact: "c".repeat(64) },
        ],
      });
      await poll(page);
      await expect(run(page, 1)).toContainText("Cancelled");
      await expect(run(page, 1)).not.toContainText("Cancellation requested.");
      await expect(run(page, 2)).toContainText("Stage key frames");
      await expect(run(page, 2)).toContainText("layered.decal_weak");
      await expect(run(page, 2)).toContainText("The decal track did not pass.");

      await build(page).click();
      await expect(run(page, 3)).toBeVisible();
      await run(page, 2).getByRole("button", { name: "Details" }).click();
      const form = run(page, 2).getByRole("textbox", { name: "Reason for visual override" });
      const save = run(page, 2).getByRole("button", { name: "Record override" });
      await expect(form).toHaveCount(1);
      await expect(run(page, 2).getByText(artifact)).toBeVisible();
      await expect(save).toBeDisabled();
      await form.fill("The mark reads clearly on the phone.");
      queue.advance(queue.runs[2].id, "running", "Worker started", { progress: { percent: 10, stage: "plan" } });
      await poll(page);
      await expect(run(page, 3)).toContainText("plan 10%");
      await expect(form).toBeFocused();
      await expect(form).toHaveValue("The mark reads clearly on the phone.");
      const overrideRevision = second.revision;
      await save.click();
      await expect(run(page, 2)).toContainText("layered.decal_gate · Overridden");
      await expect(form).toHaveCount(0);
      expect(queue.overrideWrites).toEqual([{
        id: second.id, revision: `"${overrideRevision}"`, body: { artifact, reason: "The mark reads clearly on the phone." },
      }]);
      await expectNoOverflow(page);
    });

    test("shows visibility measurements and offers review only for uncertainty", async ({ page, api }) => {
      const queue = api.queue!;
      await openStory(page);
      await build(page).click();
      await expect(run(page, 1)).toContainText("Queued");
      const first = queue.runs[0];
      const artifact = "a".repeat(64);
      const thresholds = { visible_min_percent: 85, hidden_max_percent: 50 };
      const measured = { target: { key: "a" }, pose: { key: "still" }, total_pixels: 400 };
      queue.advance(first.id, "running", "Worker started");
      queue.advance(first.id, "failed", "Review the uncertain visibility check", {
        checks: [
          { check: "occlusion.visibility", result: "fail", artifact,
            actual: { result: "uncertain", measured: {
              ...measured, visible_lower_pixels: 0, visible_upper_pixels: 280,
              unknown_occluders: [{ key: "table" }],
            }, thresholds } },
          { check: "occlusion.visibility", result: "fail", artifact: "b".repeat(64),
            actual: { result: "fail", measured: {
              ...measured, visible_lower_pixels: 200, visible_upper_pixels: 200,
            }, thresholds } },
        ],
      });
      await poll(page);
      const card = run(page, 1);
      await card.getByRole("button", { name: "Details" }).click();
      await expect(card).toContainText("0–280 of 400 pixels visible · visible ≥ 85%, hidden ≤ 50%");
      await expect(card).toContainText("Unmeasured occluders · table");
      await expect(card).toContainText("200 of 400 pixels visible");
      await expect(card.getByRole("button", { name: "Record override" })).toHaveCount(1);
      await card.getByRole("textbox", { name: "Reason for visibility override" }).fill("The face is readable.");
      await card.getByRole("button", { name: "Record override" }).click();
      await expect(card).toContainText("occlusion.visibility · Overridden");
      await expect(card).toContainText("0–280 of 400 pixels visible");
      await expect(card.getByRole("button", { name: "Record override" })).toHaveCount(0);
    });
  });
}
