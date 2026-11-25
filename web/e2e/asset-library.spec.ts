import { expect, test as base, type Page } from "@playwright/test";

import { assetsPath, treePath } from "../src/routes";
import { boardContext, mockStudio, story } from "./studio-api";
import { knownHiddenCandidate, libraryRecorded, librarySound } from "./studio-asset-fixtures";
import { castPin, generatePhotoMedia, photoVersionId, propPin, uploadDigest } from "./studio-photo-fixtures";

type Mock = { api: Awaited<ReturnType<typeof mockStudio>>; media: Awaited<ReturnType<typeof generatePhotoMedia>> };
const test = base.extend<{ mock: Mock }>({
  mock: async ({ browser, context, baseURL }, use) => {
    const media = await generatePhotoMedia(browser);
    await context.addCookies([{
      name: "studio-test-session", value: "fixture", url: baseURL!, httpOnly: true, sameSite: "Lax",
    }]);
    const api = await mockStudio(context, baseURL!, { photoMedia: media, assetLibrary: true });
    await use({ api, media });
    expect(api.violations).toEqual([]);
  },
});

const photoRoute = treePath("board", boardContext, "photo");
const browseRoute = assetsPath(boardContext);
const productionRoute = assetsPath(boardContext, false, { scope: "production" });
const list = (page: Page) => page.getByRole("list", { name: "Assets", exact: true });
const card = (page: Page, name: string) => list(page).getByRole("article", { name, exact: true });
const chip = (page: Page, scope: string) => page.getByRole("button", { name: new RegExp(`^Remove ${scope} filter`) });
const searchBox = (page: Page) => page.getByRole("searchbox", { name: "Search" });
const kindBox = (page: Page) => page.getByRole("combobox", { name: "Kind" });
const targetBox = (page: Page) => page.getByRole("combobox", { name: "Target board" });
const composer = (page: Page) => page.locator(".photo-composer");
const showPoll = (page: Page) => page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));

async function press(page: Page, element: ReturnType<Page["getByRole"]>) {
  await element.focus();
  await page.keyboard.press("Enter");
}

async function openGenerate(page: Page) {
  await page.goto(browseRoute);
  await page.getByRole("link", { name: "Generate asset", exact: true }).click();
  await expect(page).toHaveURL(assetsPath(boardContext, true));
}

async function noOverflow(page: Page, width: number) {
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
}

async function probeRange(page: Page, path: string, size: number) {
  const answer = await page.evaluate(async (url) => {
    const response = await fetch(url, { headers: { Range: "bytes=0-7" } });
    return { status: response.status, range: response.headers.get("Content-Range"), bytes: (await response.arrayBuffer()).byteLength };
  }, path);
  expect(answer).toEqual({ status: 206, range: `bytes 0-7/${size}`, bytes: 8 });
}

for (const viewport of [{ width: 400, height: 860 }, { width: 1280, height: 900 }]) {
  test.describe(`Assets ${viewport.width} × ${viewport.height}`, () => {
    test.use({ viewport });

    test("opens from a board, widens by keyboard, restores URL and returns a promoted pin", async ({ page, mock }, info) => {
      await page.goto(photoRoute);
      await composer(page).getByRole("link", { name: "Browse Assets" }).click();
      await expect(page).toHaveURL(browseRoute);
      await expect(page.getByRole("heading", { name: "Asset library" })).toBeFocused();
      await expect(list(page).getByRole("heading")).toHaveText(["Ada portrait", "Board photo"]);
      await expect(card(page, "Ada portrait").locator("summary")).toHaveText(["v1 · Generated"]);
      await expect(targetBox(page)).toHaveValue(boardContext.board);
      await expect(card(page, "Ada portrait").getByText("Already on board")).toBeVisible();

      const filterRow = page.getByRole("group", { name: "Asset scope filters" });
      await expect(filterRow).toHaveCSS("overflow-x", "auto");
      await press(page, chip(page, "board"));
      await expect(chip(page, "story")).toBeFocused();
      await expect(page).toHaveURL(assetsPath(boardContext, false, { scope: "story" }));
      await expect(list(page).getByRole("heading")).toHaveText(["Ada portrait", "Board photo", "Cabin", "Dining bell"]);
      await expect(card(page, "Ada portrait").locator("summary")).toHaveText(["v2 · Generated", "v1 · Generated"]);
      await expect(card(page, "Ada portrait").getByText("rgba_cutout", { exact: true })).toBeVisible();

      await page.keyboard.press("Enter");
      await expect(chip(page, "production")).toBeFocused();
      await expect(page).toHaveURL(productionRoute);
      await expect(card(page, "Recorded spoon").getByText("Recorded without media")).toBeVisible();
      await expect(card(page, "Recorded spoon").getByRole("img")).toHaveCount(0);
      await expect(card(page, "Recorded spoon").getByRole("link", { name: /Use/ })).toHaveCount(0);
      await expect(card(page, "Other production prop")).toHaveCount(0);
      await expect(card(page, "Candidate prop")).toHaveCount(0);

      const ada = (await card(page, "Ada portrait").boundingBox())!;
      const photo = (await card(page, "Board photo").boundingBox())!;
      if (viewport.width === 400) {
        expect(photo.x).toBe(ada.x);
        expect(photo.y).toBeGreaterThan(ada.y + ada.height);
      } else {
        expect(photo.x).toBeGreaterThan(ada.x);
        expect(photo.y).toBe(ada.y);
      }
      await noOverflow(page, viewport.width);
      if (!process.env.CI) {
        await page.screenshot({ path: info.outputPath(`assets-${viewport.width}.png`), animations: "disabled" });
      }

      await page.keyboard.press("Enter");
      await expect(searchBox(page)).toBeFocused();
      await expect(page).toHaveURL(assetsPath(boardContext, false, { scope: "library" }));
      await expect(card(page, "Other production prop").getByText("Unavailable for this board’s photo")).toBeVisible();
      await expect(kindBox(page).getByRole("option", { name: "Character card" })).toHaveCount(1);
      await kindBox(page).selectOption("prop");
      await expect(card(page, "Dining bell")).toHaveCount(0);
      await searchBox(page).fill("sOuP");
      await expect(list(page).getByRole("heading")).toHaveText(["Soup bowl"]);
      await targetBox(page).selectOption(story.board_order[0]);
      await expect(card(page, "Soup bowl").getByText("Layered photos use board cast and set")).toBeVisible();
      const filtered = assetsPath(boardContext, false, {
        scope: "library", target: story.board_order[0], kind: "prop", search: "sOuP",
      });
      await expect(page).toHaveURL(filtered);
      await expect.poll(() => mock.api.selections.lena.values.web_shell).toMatchObject({ assets: filtered });
      await page.reload();
      await expect(searchBox(page)).toHaveValue("sOuP");
      await expect(kindBox(page)).toHaveValue("prop");
      await expect(targetBox(page)).toHaveValue(story.board_order[0]);
      await expect(page.getByRole("link", { name: "Return to board" })).toHaveAttribute("href",
        treePath("board", { ...boardContext, board: story.board_order[0] }, "photo"));
      await expect(list(page).getByRole("heading")).toHaveText(["Soup bowl"]);
      await targetBox(page).selectOption(boardContext.board);

      await press(page, card(page, "Soup bowl").getByRole("link", { name: "Use Soup bowl v1 on board" }));
      await expect(page).toHaveURL(photoRoute);
      await expect(composer(page).locator(":scope > summary")).toBeFocused();
      await expect(composer(page).getByRole("button", { name: /Remove Soup bowl/ })).toBeVisible();
      await expect(composer(page).getByText("Photo inputs changed.")).toBeVisible();
      await expect.poll(() => mock.api.contentEdits[0]?.body.photo?.input_asset_version_ids).toEqual([castPin, propPin]);
      await noOverflow(page, viewport.width);
    });

    test("shows upload and imported provenance and uses cookie-authenticated preview ranges", async ({ page, mock }) => {
      const sound = mock.api.assets!.versions.find((version) => version.id === librarySound)!;
      const audioPath = `/v1/media/${sound.content!.sha256}`;
      const rangeAnswer = page.waitForResponse((response) => new URL(response.url()).pathname === audioPath &&
        response.status() === 206);
      await page.goto(productionRoute);
      const player = card(page, "Dining bell").getByLabel("Dining bell v1 preview");
      await expect(player).toHaveAttribute("src", audioPath);
      const audio = await rangeAnswer;
      expect(audio.headers()["content-range"]).toMatch(/^bytes 0-/);
      expect(await audio.request().headerValue("range")).toMatch(/^bytes=0-/);
      expect(await audio.request().headerValue("cookie")).toContain("studio-test-session=fixture");
      expect(await audio.request().headerValue("authorization")).toBeNull();
      await expect(card(page, "Dining bell").getByText("fixture:dining-bell")).toBeVisible();

      await page.goto(browseRoute);
      await page.getByText("Board photo history", { exact: true }).click();
      const upload = page.getByText("Board photo · v2 · Agent upload", { exact: true });
      await press(page, upload);
      const review = page.getByRole("article", { name: "Board photo promotion" });
      await expect(review.getByText("Fixture agent · photo-fixture")).toBeVisible();
      await expect(review.getByText("Fixture upload model")).toBeVisible();
      await expect(review.getByText(uploadDigest)).toBeVisible();
      const metadata = mock.api.assets!.versions.find(({ id }) => id === photoVersionId(101))!;
      await expect(review).not.toContainText(metadata.provenance.external!.agent.key_id);
      await expect(review.getByRole("link", { name: /Use/ })).toHaveCount(0);
      const versionPath = `/v1/asset-versions/${metadata.id}/media/${mock.media[1].hash}`;
      await expect(review.getByRole("img")).toHaveAttribute("src", versionPath);
      await probeRange(page, versionPath, mock.media[1].body.length);
      await press(page, review.getByRole("button", { name: "Promote", exact: true }));
      await expect(review.getByText("Promoted to library")).toBeFocused();
      await expect(review.getByRole("link", { name: "Use Board photo v1 on board" })).toBeVisible();
      expect(metadata.state).toBe("board");
      expect(mock.api.assets!.versions.find(({ provenance }) => provenance.source_key === `promote:${metadata.id}`))
        .toMatchObject({ state: "promoted", scope: { production_id: boardContext.production } });
      const archived = mock.api.assets!.versions.find(({ id }) => id === libraryRecorded)!;
      expect(mock.api.calls).not.toContain(`GET /v1/asset-versions/${archived.id}/media/${archived.content!.sha256}`);
      await noOverflow(page, viewport.width);
    });

    test("replays one press, reads the lane and job, retains a declined candidate and promotes explicitly", async ({ page, mock }) => {
      const assets = mock.api.assets!;
      assets.pause(true);
      assets.loseReply();
      await page.clock.install();
      await openGenerate(page);
      const form = page.getByRole("form", { name: "Generate asset candidate" });
      await expect(form.getByText("Image lane paused", { exact: true })).toBeVisible();
      await form.getByLabel("Name").fill("Soup ladle");
      await form.getByLabel("Kind").selectOption("prop");
      await form.getByLabel("Prompt").fill("A wooden ladle for the soup pot.");
      await form.getByRole("button", { name: "Request candidate" }).click();
      await form.getByRole("button", { name: "Retry candidate request" }).click();
      await expect(page.getByText("Candidate queued · image lane paused")).toBeVisible();
      expect(assets.presses[1]).toEqual(assets.presses[0]);
      const id = assets.latestJob()!.id;
      const jobPath = assetsPath(boardContext, true, { job: id });
      await expect(page).toHaveURL(jobPath);

      assets.pause(false);
      assets.start(id);
      await showPoll(page);
      await expect(page.getByText("Candidate running", { exact: true })).toBeVisible();
      const version = assets.complete(id);
      await showPoll(page);
      await expect(page.getByText("Candidate ready", { exact: true })).toBeVisible();
      const candidate = page.getByRole("article", { name: "Soup ladle candidate review" });
      await expect(candidate.getByText(id, { exact: true })).toBeVisible();
      const previewPath = `/v1/jobs/${id}/media/${version.content!.sha256}`;
      await expect(candidate.getByRole("img")).toHaveAttribute("src", previewPath);
      await probeRange(page, previewPath, version.content!.bytes!);
      await expect(candidate.getByText("Promote before use", { exact: true })).toBeVisible();
      await expect(candidate.getByRole("link", { name: /Use/ })).toHaveCount(0);

      await press(page, candidate.getByRole("button", { name: "Decline" }));
      await expect(candidate.getByRole("button", { name: "Review again" })).toBeFocused();
      await expect(candidate.getByText("Declined candidate", { exact: true })).toBeVisible();
      expect(version.state).toBe("candidate");
      expect(assets.promotions).toEqual([]);
      await page.reload();
      await expect(candidate.getByText("Declined candidate", { exact: true })).toBeVisible();
      const libraryJob = assetsPath(boardContext, false, { scope: "production", job: id });
      await page.getByRole("link", { name: "Back to library" }).click();
      await press(page, chip(page, "story"));
      await expect(page).toHaveURL(libraryJob);
      await expect(card(page, "Recorded spoon")).toBeVisible();
      await expect(card(page, "Soup ladle")).toHaveCount(0);
      await expect(candidate.getByRole("link", { name: /Use/ })).toHaveCount(0);
      expect(assets.versions.find((version) => version.id === knownHiddenCandidate)?.state).toBe("candidate");

      const promotePath = `/v1/asset-versions/${version.id}/promote`;
      await candidate.getByRole("button", { name: "Review again" }).click();
      mock.api.failNext({ path: promotePath, method: "POST", status: 403, detail: {
        status: "forbidden", code: "auth.forbidden", path: "", http_status: 403, request_id: "mock-promote-403",
        message: "This credential cannot perform the operation",
      } });
      const promote = candidate.getByRole("button", { name: "Promote", exact: true });
      await press(page, promote);
      await expect(candidate.getByRole("alert")).toContainText("auth.forbidden");
      await expect(candidate.getByRole("link", { name: /Use/ })).toHaveCount(0);
      mock.api.failNext({ path: promotePath, method: "POST", status: 409, detail: {
        status: "conflict", code: "conflict.revision", path: "", http_status: 409, request_id: "mock-promote-409",
        message: "The result changed. Refresh it first.",
      } });
      await press(page, promote);
      await expect(candidate.getByRole("alert")).toContainText("conflict.revision");
      await candidate.getByRole("button", { name: "Retry" }).click();
      await expect(candidate.getByRole("alert")).toHaveCount(0);

      const resultPath = `GET /v1/jobs/${id}/result`;
      const resultReads = mock.api.calls.filter((call) => call === resultPath).length;
      const releasePromotion = assets.holdReply("promote");
      try {
        await press(page, promote);
        const promoting = candidate.getByRole("button", { name: "Promoting…", exact: true });
        await expect(promoting).toBeVisible();
        const jobRead = page.waitForResponse((response) => new URL(response.url()).pathname === `/v1/jobs/${id}`);
        await showPoll(page);
        await (await jobRead).finished();
        await expect(promoting).toBeVisible();
      } finally {
        releasePromotion();
      }
      await expect(candidate.getByText("Promoted to library")).toBeFocused();
      await expect(card(page, "Soup ladle").getByRole("link", { name: "Use Soup ladle v1 on board" })).toBeVisible();
      expect(mock.api.calls.filter((call) => call === resultPath)).toHaveLength(resultReads);
      expect(version.state).toBe("promoted");
      expect(assets.promotions).toEqual([version.id]);

      await page.getByRole("link", { name: "Generate asset", exact: true }).click();
      await form.getByLabel("Name").fill("Pot lid");
      await form.getByLabel("Prompt").fill("A round lid.");
      const releaseJob = assets.holdReply("submit");
      try {
        await form.getByRole("button", { name: "Request candidate" }).click();
        await expect(form.getByRole("button", { name: "Submitting…" })).toBeVisible();
        await targetBox(page).selectOption(story.board_order[0]);
        await expect(page).toHaveURL((url) => url.searchParams.get("target") === story.board_order[0]);
      } finally {
        releaseJob();
      }
      await expect(page.getByText("Candidate queued", { exact: true })).toBeVisible();
      await expect(targetBox(page)).toHaveValue(story.board_order[0]);
      expect(assets.presses[2].key).not.toBe(assets.presses[0].key);
      const second = assets.latestJob()!;
      assets.start(second.id);
      assets.fail(second.id, "image.unavailable", "Image worker unavailable.");
      await showPoll(page);
      await expect(page.getByText("Candidate failed", { exact: true })).toBeVisible();
      await expect(page.getByRole("alert")).toContainText("image.unavailable");
      await expect(page.getByRole("button", { name: "Promote", exact: true })).toHaveCount(0);
      await noOverflow(page, viewport.width);
    });
  });
}
