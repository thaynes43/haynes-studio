import { expect, test, type Page } from "@playwright/test";
import { treePath } from "../src/routes";
import { mockStudio, production, story, storyContext } from "./studio-api";
import { description, importedRun, latestRun, oldRun, runningRun } from "./studio-review-fixtures";
import { generateReviewMedia, type ReviewMedia } from "./studio-review-media";

const storyPath = treePath("productions", storyContext);
const mediaPath = treePath("productions", { production: production.id, media: "short" });
const runPath = (run: string) => treePath("productions", { ...storyContext, run });
const decisionPath = (run: string) => `/v1/runs/${run}/go-live-approvals`;
const mediaUrl = (hash: string) => `/v1/media/${hash}`;
const goLive = (page: Page) => page.getByRole("region", { name: "Go-live" });
const approve = (page: Page) => page.getByRole("button", { name: "Approve for go-live", exact: true });
const confirmSetting = (page: Page) => page.getByRole("checkbox", { name: "Confirm the AI-generated platform setting" });

let reviewMedia: ReviewMedia;
test.beforeAll(async ({ browser }) => { reviewMedia = await generateReviewMedia(browser); });

const reviewTest = test.extend<{ api: Awaited<ReturnType<typeof mockStudio>> }>({
  api: async ({ context, baseURL }, use) => {
    const api = await mockStudio(context, baseURL!, { reviewMedia });
    await use(api);
    expect(api.violations).toEqual([]);
  },
});

async function expectNoOverflow(page: Page) {
  await expect.poll(() => page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  )).toBe(true);
}

for (const viewport of [{ width: 400, height: 860 }, { width: 1280, height: 900 }]) {
  reviewTest.describe(`${viewport.width}×${viewport.height}`, () => {
    reviewTest.use({ viewport });

    reviewTest("production hierarchy and combinable saved filters", async ({ page, api }) => {
      await page.goto("/productions");
      const crumb = page.getByRole("navigation", { name: "Breadcrumb" });
      await page.getByRole("link", { name: "Empty production" }).click();
      await expect(page.getByText("No media types yet.")).toBeVisible();
      await crumb.getByRole("button", { name: "Productions", exact: true }).click();
      await page.getByRole("link", { name: production.name }).click();
      await expect(page.getByRole("link", { name: "Videos 16:9" })).toHaveCount(0);
      await page.getByRole("link", { name: "Shorts 9:16" }).click();
      const filters = page.getByRole("group", { name: "Media status" });
      const mediaRows = page.locator("main ul.tree").getByRole("link");
      const unpublished = filters.getByRole("button", { name: "Unpublished", exact: true });
      const approvedFilter = filters.getByRole("button", { name: "Approved", exact: true });
      const published = filters.getByRole("button", { name: "Published", exact: true });
      await expect(mediaRows).toHaveCount(4);
      await unpublished.click();
      await expect(mediaRows).toHaveText([/The Winter Menu/, /Ready for release/]);
      await unpublished.click();
      await approvedFilter.click();
      await expect(mediaRows).toHaveText([/Ready for release/, /Released and approved/]);
      await published.click();
      await expect(mediaRows).toHaveText([/Released and approved/]);
      await unpublished.click();
      await expect(published).toHaveAttribute("aria-pressed", "false");
      await expect(mediaRows).toHaveText([/Ready for release/]);
      await expect.poll(() => api.selections.lena.values.web_shell).toMatchObject({
        production_filters: { [mediaPath]: { publication: "unpublished", approved: true } },
      });
      await page.getByRole("link", { name: /Ready for release/ }).click();
      await crumb.getByRole("button", { name: "Short", exact: true }).click();
      await expect(mediaRows).toHaveText([/Ready for release/]);
      await page.reload();
      await expect(unpublished).toHaveAttribute("aria-pressed", "true");
      await expect(approvedFilter).toHaveAttribute("aria-pressed", "true");
      await expect(mediaRows).toHaveText([/Ready for release/]);
      await expectNoOverflow(page);
    });

    reviewTest("runs show in order and play the private phone proxy and master", async ({ page, api }) => {
      const proxyUrl = mediaUrl(reviewMedia.proxy.hash);
      const range = page.waitForResponse((response) =>
        new URL(response.url()).pathname === proxyUrl && response.status() === 206);
      await page.goto(storyPath);
      const response = await range;
      expect(response.request().resourceType()).toBe("media");
      expect(response.request().headers().range).toMatch(/^bytes=/);
      expect(response.headers()["content-range"]).toBe(`bytes 0-${reviewMedia.proxy.body.length - 1}/${reviewMedia.proxy.body.length}`);
      expect(api.calls).toContain(`GET ${proxyUrl}`);
      const video = page.locator("video");
      await expect(video).toHaveAttribute("src", proxyUrl);
      await expect.poll(() => video.evaluate((el: HTMLVideoElement) => el.videoHeight)).toBe(96);
      await video.evaluate(async (el: HTMLVideoElement) => { el.muted = true; await el.play(); });
      await expect.poll(() => video.evaluate((el: HTMLVideoElement) => el.currentTime)).toBeGreaterThan(0);
      await page.getByRole("button", { name: "Master", exact: true }).click();
      await expect(video).toHaveAttribute("src", mediaUrl(reviewMedia.master.hash));
      await expect.poll(() => video.evaluate((el: HTMLVideoElement) => el.videoHeight)).toBe(144);
      await expect(page.getByRole("list", { name: "Story runs" }).getByRole("link")).toHaveText([
        /Run 4.*Running/, /Run 3.*Imported/, /Run 2.*Finished/, /Run 1.*Finished/,
      ]);
      await expect(page.getByRole("region", { name: "Run checks" })).toContainText("audio.loudness");
      await expect(page.getByRole("region", { name: "Run checks" })).toContainText("B12 · layered.decal gate · A");
      await expect(page.getByRole("region", { name: "Run checks" })).toContainText("B07 · layered.decal gate · A");
      await expect(goLive(page)).toContainText("Publishing is done by hand outside Studio.");
      const boards = page.getByRole("region", { name: "Draft boards" });
      await expect(boards.getByRole("heading", { level: 3 })).toHaveText(["B12 · Opening panel", "B07 · Closing panel"]);
      await expect(boards).toContainText("The soup can hear you.");
      await expect(boards).toContainText("Layered");
      await expect(boards).toContainText("Speech-to-video");
      await expect(boards).toContainText("Offscreen crunch");
      await expect(boards.getByRole("img", { name: "Reference photo for Opening panel" }))
        .toHaveAttribute("src", mediaUrl(reviewMedia.photo.hash));
      await expect(boards.locator("audio")).toHaveAttribute("src", mediaUrl(reviewMedia.voice.hash));
      await expectNoOverflow(page);
      await page.getByRole("link", { name: /Run 4.*Running/ }).click();
      await expect(page).toHaveURL(new RegExp(runPath(runningRun) + "$"));
      await expect(video).toHaveCount(0);
      await expect(approve(page)).toHaveCount(0);
    });

    reviewTest("approval pins an older run after a draft edit and withdrawal stays in history", async ({ page, api }) => {
      api.editDraft();
      await page.goto(storyPath);
      await expect(page.getByText("New draft line.")).toBeVisible();
      await page.getByRole("link", { name: /Run 1.*Finished/ }).click();
      await expect(page).toHaveURL(new RegExp(runPath(oldRun) + "$"));
      const panel = goLive(page);
      await expect(panel.locator(".review-description")).toHaveJSProperty("textContent", description);
      await expect(panel.getByText("AI-generated", { exact: true })).toBeVisible();
      await expect(panel.getByText("Run 1 master SHA-256", { exact: true })).toBeVisible();
      await expect(panel.locator("code")).toHaveText(reviewMedia.olderMaster.hash);
      await expect(approve(page)).toBeDisabled();
      await confirmSetting(page).check();
      await approve(page).click();
      await expect(panel.getByText("Go-live approval recorded.")).toBeVisible();
      await expect(panel.getByText("Approved by Lena Park")).toBeVisible();
      expect(api.approvalWrites).toEqual([{
        run: oldRun,
        body: { master_sha256: reviewMedia.olderMaster.hash, platform_setting: true },
      }]);
      await expect(page.getByText("Unpublished", { exact: true })).toBeVisible();
      api.recordManualPublication();
      await page.reload();
      await expect(page.getByText("Published", { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Withdraw approval" }).click();
      await expect(panel.getByText("Go-live approval withdrawn.")).toBeVisible();
      await expect(panel.getByText("Withdrawn", { exact: true })).toBeVisible();
      await page.reload();
      await expect(panel.getByText("Withdrawn", { exact: true })).toBeVisible();
      await expect(page.getByText("Published", { exact: true })).toBeVisible();
      await expectNoOverflow(page);
    });

    reviewTest("expired approval session returns to the exact run for deliberate confirmation", async ({ page, api }) => {
      await page.goto(storyPath);
      const panel = goLive(page);
      await confirmSetting(page).check();
      // The session becomes stale after the successful preview, before the POST.
      api.requireFreshSignIn();
      const returned = page.waitForURL(new RegExp(runPath(latestRun) + "$"));
      await approve(page).click();
      await returned;
      await expect(approve(page)).toBeDisabled();
      await expect(panel.getByText("Go-live approval recorded.")).toHaveCount(0);
      expect(api.loginRequests).toHaveLength(1);
      expect(api.loginRequests[0].get("fresh")).toBe("true");
      expect(api.loginRequests[0].get("return_to")).toBe(runPath(latestRun));
      expect(api.approvalWrites).toHaveLength(1);
      await confirmSetting(page).check();
      await approve(page).click();
      await expect(panel.getByText("Go-live approval recorded.")).toBeVisible();
    });

    reviewTest("an already stale session offers sign-in for that run directly", async ({ page, api }) => {
      api.requireFreshSignIn();
      await page.goto(runPath(oldRun));
      await expect(goLive(page)).toContainText("Sign in again to make a go-live decision.");
      await expect(approve(page)).toHaveCount(0);
      await goLive(page).getByRole("link", { name: "Sign in again" }).click();
      await expect(approve(page)).toBeDisabled();
      expect(api.loginRequests[0].get("return_to")).toBe(runPath(oldRun));
      expect(api.approvalWrites).toHaveLength(0);
    });

    reviewTest("legacy runs and signed-in non-approvers have no write controls", async ({ page, api }) => {
      await page.goto(runPath(importedRun));
      await expect(goLive(page)).toContainText("Imported runs cannot be approved for go-live.");
      await expect(page.getByText("Playback is unavailable for this imported delivery.")).toBeVisible();
      await expect(page.locator("video")).toHaveCount(0);
      await expect(approve(page)).toHaveCount(0);
      await page.goto(runPath(oldRun));
      await confirmSetting(page).check();
      await approve(page).click();
      await expect(goLive(page)).toContainText("Go-live approval recorded.");
      api.signInAs("arden");
      await page.getByRole("button", { name: "Lena Park" }).click();
      await page.getByRole("button", { name: "Sign out" }).click();
      await page.getByRole("link", { name: "Sign in", exact: true }).click();
      await page.goto(runPath(latestRun));
      await expect(page.getByRole("button", { name: "Arden Rivera" })).toBeVisible();
      await expect(goLive(page)).toContainText("Your account does not have go-live approval access.");
      await expect(approve(page)).toHaveCount(0);
      await page.goto(runPath(oldRun));
      await expect(goLive(page)).toContainText("Approved by Lena Park");
      await expect(goLive(page)).toContainText("Your account does not have go-live approval access.");
      await expect(page.getByRole("button", { name: "Withdraw approval" })).toHaveCount(0);
      expect(api.approvalWrites).toHaveLength(1);
    });

    reviewTest("missing approver configuration and failed release checks show their API reasons", async ({ page, api }) => {
      await page.goto(runPath(latestRun));
      api.refuseRun("approval.licence_missing");
      await page.reload();
      await expect(goLive(page)).toContainText("An engine or model file is missing from the licence register.");
      await expect(goLive(page)).toContainText("Model licences Failed");
      await expect(approve(page)).toHaveCount(0);
      api.disableApprovals();
      await page.reload();
      await expect(goLive(page)).toContainText("No go-live approvers are configured.");
      await expect(approve(page)).toHaveCount(0);
      expect(api.approvalWrites).toHaveLength(0);
    });

    reviewTest("other documented refusals preserve their individual API reasons", async ({ page, api }) => {
      const cases = [
        [403, "forbidden", "approval.group_not_permitted", "Studio group access grants sign-in only."],
        [403, "forbidden", "approval.approver_not_permitted", "Go-live decisions require a signed-in approver."],
        [403, "forbidden", "approval.worker_not_permitted", "Worker credentials cannot approve go-live."],
        [409, "conflict", "approval.already_active", "This run already has an active approval."],
        [409, "conflict", "approval.already_withdrawn", "This approval has already been withdrawn."],
        [422, "invalid", "approval.run_unfinished", "Go-live requires a successful, finished run."],
        [422, "invalid", "approval.delivery_unverified", "The delivery could not be verified."],
        [422, "invalid", "approval.delivery_mismatch", "The delivery does not match this run’s recorded master."],
        [422, "invalid", "approval.not_exact_run", "The reviewed master does not match the delivered master."],
        [422, "invalid", "approval.provenance_missing", "The run is missing required provenance."],
        [422, "invalid", "approval.ai_label_missing", "Go-live requires the AI-generated label and synthetic-content setting."],
        [503, "service_unavailable", "approval.licence_register_unavailable", "The model licence register is unavailable."],
      ] as const;
      for (const [status, category, code, message] of cases) {
        api.failNext({
          path: decisionPath(latestRun), method: "GET", status,
          detail: { http_status: status, status: category, code, path: "", message: code, request_id: "mock-refusal" },
        });
        await page.goto(runPath(latestRun));
        await expect(goLive(page).getByRole("alert")).toContainText(message);
        await expect(approve(page)).toHaveCount(0);
        await expect(goLive(page).getByRole("button", { name: "Withdraw approval" })).toHaveCount(0);
      }
      expect(api.approvalWrites).toHaveLength(0);
    });
  });
}

reviewTest("a write refusal displays the returned code's reason without replaying the write", async ({ page, api }) => {
  await page.goto(runPath(oldRun));
  await confirmSetting(page).check();
  api.failNext({
    path: decisionPath(oldRun), method: "POST", status: 422,
    detail: {
      code: "approval.not_exact_run", status: "invalid", http_status: 422,
      path: "", message: "Refusal from the API", request_id: "mock-request-422",
    },
  });
  await approve(page).click();
  await expect(goLive(page).getByRole("alert")).toContainText("The reviewed master does not match the delivered master.");
  await expect(approve(page)).toHaveCount(0);
  expect(api.calls.filter((call) => call === `POST ${decisionPath(oldRun)}`)).toHaveLength(1);
});
