import { expect, test } from "@playwright/test";
import { treePath } from "../src/routes";
import { mockStudio, storyContext } from "./studio-api";
import { description, latestRun, oldRun } from "./studio-review-fixtures";
import { generateReviewMedia, type ReviewMedia } from "./studio-review-media";

let reviewMedia: ReviewMedia;
test.beforeAll(async ({ browser }) => { reviewMedia = await generateReviewMedia(browser); });
const runPath = (run: string) => treePath("productions", { ...storyContext, run });
const location = "https://www.youtube.com/shorts/fixture";

for (const viewport of [{ width: 400, height: 860 }, { width: 1280, height: 900 }]) {
  test.describe(`release package at ${viewport.width}×${viewport.height}`, () => {
    test.use({ viewport });

    test("prepares, downloads, holds and records the manual drop for one run", async ({ page, context, baseURL }) => {
      await context.grantPermissions(["clipboard-read", "clipboard-write"]);
      const api = await mockStudio(context, baseURL!, { reviewMedia, releaseMaximum: 60_000 });
      await page.goto(runPath(oldRun));
      const release = page.getByRole("region", { name: "Release package", exact: true });
      await expect(release).toContainText("Publish by hand outside Studio.");
      await release.getByRole("combobox", { name: "Release target" }).selectOption("tom-shorts");
      await release.getByRole("button", { name: "Prepare package" }).click();
      await expect(release.getByText(/Package ready, release held/)).toBeVisible();
      await expect(release.getByRole("button", { name: "Record publication" })).toHaveCount(0);
      const master = release.getByRole("link", { name: "Download master" });
      const copyDescription = release.getByRole("button", { name: "Copy description" });
      const copyChecklist = release.getByRole("button", { name: "Copy checklist" });
      await expect(master).toHaveCount(0);
      await expect(copyDescription).toHaveCount(0);
      await expect(copyChecklist).toHaveCount(0);
      await release.getByText("Model licences · Passed", { exact: true }).click();
      await release.getByText("video-local · Local model terms · unknown", { exact: true }).click();
      await expect(release.getByText("Terms are pending verification.", { exact: true })).toBeVisible();
      await release.getByText("Platform maximum · Passed", { exact: true }).click();
      await expect(release.getByText(/"max_length_ms": 60000/)).toBeVisible();

      const approve = async () => {
        await page.getByRole("checkbox", { name: "Confirm the AI-generated platform setting" }).check();
        await page.getByRole("button", { name: "Approve for go-live", exact: true }).click();
        await expect(release.getByText(/Releasable. The exact run and master/)).toBeVisible();
      };
      await approve();
      await copyDescription.click();
      await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(description);
      await copyChecklist.click();
      await expect.poll(() => page.evaluate(() => navigator.clipboard.readText()))
        .toContain("Turn on the synthetic-content setting.");
      await expect(master).toHaveAttribute("href", `/v1/media/${reviewMedia.olderMaster.hash}`);
      const download = page.waitForEvent("download");
      await master.click();
      expect((await download).suggestedFilename()).toBe(`${oldRun}.mp4`);

      await page.getByRole("button", { name: "Withdraw approval" }).click();
      await expect(release.getByText(/Package ready, release held/)).toBeVisible();
      await expect(master).toHaveCount(0);
      await expect(copyDescription).toHaveCount(0);
      await expect(copyChecklist).toHaveCount(0);
      await approve();

      await page.getByRole("link", { name: /Run 2.*Finished/ }).click();
      await expect(page).toHaveURL(new RegExp(runPath(latestRun) + "$"));
      await expect(release.getByRole("button", { name: "Prepare package" })).toBeVisible();
      await expect(release.getByRole("button", { name: "Record publication" })).toHaveCount(0);
      await page.getByRole("link", { name: /Run 1.*Finished/ }).click();

      if (viewport.width === 400) {
        api.signInAs("arden");
        await page.goto("/auth/login?return_to=" + encodeURIComponent(runPath(oldRun)));
        await expect(release.getByText(/Releasable. The exact run and master/)).toBeVisible();
        await expect(release.getByRole("button", { name: "Record publication" })).toHaveCount(0);
        api.signInAs("lena");
        await page.goto("/auth/login?return_to=" + encodeURIComponent(runPath(oldRun)));
      }
      await release.getByRole("textbox", { name: "Public location" }).fill(location);
      const record = release.getByRole("button", { name: "Record publication" });
      const keys: (string | undefined)[] = [];
      if (viewport.width === 1280) {
        await page.route(`**/v1/runs/${oldRun}/publications`, async (route) => {
          keys.push(route.request().headers()["idempotency-key"]);
          if (keys.length === 1) await route.abort();
          else await route.fallback();
        });
        await record.click();
        await expect(release.getByRole("alert")).toBeVisible();
      }
      await record.click();
      await expect(release.getByRole("heading", { name: "Publication recorded" })).toBeVisible();
      if (viewport.width === 1280) {
        expect(keys[0]).toBeTruthy();
        expect(keys).toEqual([keys[0], keys[0]]);
      }
      await expect(release.getByText(location)).toBeVisible();
      await expect(release.getByRole("link", { name: location })).toHaveCount(0);
      await expect(page.getByText("Published", { exact: true })).toBeVisible();
      await expect(release.getByRole("button", { name: "Record publication" })).toHaveCount(0);
      expect(api.calls.filter((call) => call.endsWith("/publications"))).toEqual([
        `POST /v1/runs/${oldRun}/publications`,
      ]);
      expect(api.violations).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    });
  });
}

test("shows the refusal for a frozen target without a maximum", async ({ page, context, baseURL }) => {
  const api = await mockStudio(context, baseURL!, { reviewMedia });
  await page.goto(runPath(oldRun));
  const release = page.getByRole("region", { name: "Release package", exact: true });
  await release.getByRole("combobox", { name: "Release target" }).selectOption("tom-shorts");
  await release.getByRole("button", { name: "Prepare package" }).click();
  await expect(release.getByRole("alert")).toContainText("The frozen target must declare a platform maximum");
  await expect(release.getByRole("link", { name: "Download master" })).toHaveCount(0);
  expect(api.violations).toEqual([]);
});
