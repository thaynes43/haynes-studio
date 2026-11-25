import { expect, test as base, type Page } from "@playwright/test";

import type { components } from "../src/api/schema";
import { assetsPath, treePath } from "../src/routes";
import { pollInterval } from "../src/run-polling";
import { boardContext, mockStudio, story } from "./studio-api";
import { knownHiddenCandidate, libraryRecorded, librarySound } from "./studio-asset-fixtures";
import { formatFixture } from "./studio-inspector-fixtures";
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
const generationForm = (page: Page) => page.getByRole("form", { name: "Generate asset candidate" });
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

function refuseStalePromotion(api: Mock["api"], versionId: string) {
  api.failNext({ path: `/v1/asset-versions/${versionId}/promote`, method: "POST", status: 409, detail: {
    status: "conflict", code: "conflict.revision", path: "", http_status: 409, request_id: "mock-promote-409",
    message: "The result changed. Refresh it first.",
  } });
}

for (const viewport of [{ width: 400, height: 860 }, { width: 1280, height: 900 }]) {
  test.describe(`Assets ${viewport.width} × ${viewport.height}`, () => {
    test.use({ viewport });

    test("keeps rapid search keys in the input and URL, including through history", async ({ page, mock }) => {
      await page.goto(productionRoute);
      await expect(card(page, "Soup bowl")).toBeVisible();
      const search = searchBox(page);
      const term = "Soup bowl";
      // Send individual keys with no delay or assertion between them.
      await search.pressSequentially(term);
      await expect(search).toHaveValue(term);
      await expect(page).toHaveURL((url) => url.searchParams.get("q") === term);
      await expect(list(page).getByRole("heading")).toHaveText([term]);

      await kindBox(page).selectOption("prop");
      await expect(page).toHaveURL(assetsPath(boardContext, false, { scope: "production", kind: "prop", search: term }));
      await expect.poll(() => mock.api.selections.lena.values.web_shell).toMatchObject({
        assets: assetsPath(boardContext, false, { scope: "production", kind: "prop" }),
      });
      await search.fill("Recorded spoon");
      await expect(list(page).getByRole("heading")).toHaveText(["Recorded spoon"]);
      await page.goBack();
      await expect(page).toHaveURL(assetsPath(boardContext, false, { scope: "production", search: term }));
      await expect(search).toHaveValue(term);
      await page.goForward();
      await expect(search).toHaveValue("Recorded spoon");
      await expect(list(page).getByRole("heading")).toHaveText(["Recorded spoon"]);
    });

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
      const selectionsWrites = () => mock.api.calls.filter((call) => call === "PUT /v1/me/selections").length;
      await expect.poll(() => mock.api.selections.lena.values.web_shell).toMatchObject({
        assets: assetsPath(boardContext, false, { scope: "library", kind: "prop" }),
      });
      const beforeSearch = selectionsWrites();
      await searchBox(page).fill("sOu");
      await expect(page).toHaveURL((url) => url.searchParams.get("q") === "sOu");
      await expect(searchBox(page)).toHaveValue("sOu");
      await searchBox(page).press("End");
      await searchBox(page).press("P");
      await expect(list(page).getByRole("heading")).toHaveText(["Soup bowl"]);
      await expect(page).toHaveURL((url) => url.searchParams.get("q") === "sOuP");
      expect(selectionsWrites()).toBe(beforeSearch);
      await targetBox(page).selectOption(story.board_order[0]);
      await expect(card(page, "Soup bowl").getByText("Layered photos use board cast and set")).toBeVisible();
      const filtered = assetsPath(boardContext, false, {
        scope: "library", target: story.board_order[0], kind: "prop", search: "sOuP",
      });
      await expect(page).toHaveURL(filtered);
      await expect.poll(() => mock.api.selections.lena.values.web_shell).toMatchObject({
        assets: assetsPath(boardContext, false, { scope: "library", target: story.board_order[0], kind: "prop" }),
      });
      expect(selectionsWrites()).toBe(beforeSearch + 1);
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

    test("withholds board checks and actions while the newly selected target loads", async ({ page, mock }) => {
      const layered = story.board_order[0];
      await page.goto(productionRoute);
      const ada = card(page, "Ada portrait");
      await ada.getByText("v1 · Generated", { exact: true }).click();
      const alreadyOnBoard = ada.getByText("Already on board", { exact: true });
      await expect(alreadyOnBoard).toBeVisible();
      const soup = card(page, "Soup bowl");
      const useSoup = soup.getByRole("link", { name: "Use Soup bowl v1 on board" });
      const oldLink = await useSoup.elementHandle();
      const originalHref = await oldLink.getAttribute("href");
      const boardPath = `/v1/boards/${layered}`;
      let release = () => {};
      const held = new Promise<void>((resolve) => { release = resolve; });
      await page.route(boardPath, async (route) => {
        await held;
        await route.fallback();
      });
      const reading = page.waitForRequest((request) => new URL(request.url()).pathname === boardPath);
      try {
        await targetBox(page).selectOption(layered);
        await reading;
        await expect(page).toHaveURL((url) => url.searchParams.get("target") === layered);
        expect(mock.api.calls).not.toContain(`GET ${boardPath}`);
        await expect(alreadyOnBoard).toHaveCount(0);
        await expect(useSoup).toHaveCount(0);
        // A detached element keeps its last href, so this checks the render
        // between selecting the target and the request's loading state.
        expect(await oldLink.getAttribute("href")).toBe(originalHref);
      } finally {
        release();
      }
      await expect(soup.getByText("Layered photos use board cast and set")).toBeVisible();
      await expect(alreadyOnBoard).toHaveCount(0);
      await expect(useSoup).toHaveCount(0);
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
      const history = page.getByText("Board photo history", { exact: true });
      await history.click();
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
      const promote = review.getByRole("button", { name: "Promote", exact: true });
      refuseStalePromotion(mock.api, metadata.id);
      await press(page, promote);
      await expect(review.getByRole("alert")).toContainText("conflict.revision");
      let release = () => {};
      const held = new Promise<void>((resolve) => { release = resolve; });
      await page.route(`/v1/boards/${boardContext.board}/photo-versions`, async (route) => {
        await held;
        await route.fallback();
      });
      try {
        await press(page, review.getByRole("button", { name: "Retry" }));
        await expect(page.getByText("Loading board photos…", { exact: true })).toBeVisible();
        await expect(history).toBeFocused();
      } finally {
        release();
      }
      await expect(upload).toBeVisible();
      await expect(history).toBeFocused();
      await press(page, upload);
      await press(page, promote);
      await expect(review.getByText("Promoted to library")).toBeFocused();
      await expect(review.getByRole("link", { name: "Use Board photo v1 on board" })).toBeVisible();
      expect(metadata.state).toBe("board");
      expect(mock.api.assets!.versions.find(({ provenance }) => provenance.source_key === `promote:${metadata.id}`))
        .toMatchObject({ state: "promoted", scope: { production_id: boardContext.production } });
      const archived = mock.api.assets!.versions.find(({ id }) => id === libraryRecorded)!;
      expect(mock.api.calls).not.toContain(`GET /v1/asset-versions/${archived.id}/media/${archived.content!.sha256}`);
      await noOverflow(page, viewport.width);
    });

    test("replays one press, prevents promotion after Not now and promotes explicitly after Review again", async ({ page, mock }) => {
      const assets = mock.api.assets!;
      assets.pause(true);
      assets.loseReply();
      await page.clock.install();
      await openGenerate(page);
      const form = generationForm(page);
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

      const notNow = candidate.getByRole("button", { name: "Not now" });
      await expect(notNow).toHaveAccessibleDescription("Hides this candidate in this tab. Records nothing.");
      await press(page, notNow);
      await expect(candidate.getByRole("button", { name: "Review again" })).toBeFocused();
      await expect(candidate.getByText("Hidden in this tab", { exact: true })).toBeVisible();
      const promote = candidate.getByRole("button", { name: "Promote", exact: true });
      await expect(promote).toHaveCount(0);
      await expect(candidate.getByRole("img")).toHaveCount(0);
      expect(version.state).toBe("candidate");
      expect(assets.promotions).toEqual([]);
      await page.reload();
      await expect(candidate.getByText("Hidden in this tab", { exact: true })).toBeVisible();
      await expect(promote).toHaveCount(0);
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
      await press(page, promote);
      await expect(candidate.getByRole("alert")).toContainText("auth.forbidden");
      await expect(candidate.getByRole("link", { name: /Use/ })).toHaveCount(0);
      refuseStalePromotion(mock.api, version.id);
      await press(page, promote);
      await expect(candidate.getByRole("alert")).toContainText("conflict.revision");
      await press(page, candidate.getByRole("button", { name: "Retry" }));
      await expect(candidate.getByRole("alert")).toHaveCount(0);
      await expect(page.getByRole("heading", { name: "Candidates", exact: true })).toBeFocused();

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

    test("stops polling a missing job but keeps the generate lane live and drops the job on filter change", async ({ page, mock }) => {
      const job = "job_01M79V9FC00000000000000001";
      let jobReads = 0;
      await page.route(`/v1/jobs/${job}`, (route) => {
        jobReads++;
        return route.fulfill({ status: 404 });
      });
      await page.clock.install();
      await page.goto(assetsPath(boardContext, false, { job }));
      await expect(page.getByRole("alert")).toHaveText("Candidate job not found.");
      await expect(page.getByText("Reading candidate job…", { exact: true })).toHaveCount(0);
      await expect(page.getByRole("link", { name: "Generate asset", exact: true })).toHaveAttribute("href", assetsPath(boardContext, true));
      await expect(page.getByRole("navigation", { name: "Editor" }).getByRole("link", { name: "Assets" }))
        .toHaveAttribute("href", browseRoute);
      await expect.poll(() => mock.api.selections.lena.values.web_shell).toMatchObject({ assets: browseRoute });

      await page.goto(assetsPath(boardContext, true, { job }));
      await expect(page.getByRole("alert")).toHaveText("Candidate job not found.");
      await expect(page.getByRole("link", { name: "Back to library" })).toHaveAttribute("href", browseRoute);
      const form = generationForm(page);
      await expect(form.getByRole("status")).toHaveText("Shared image lane open");
      mock.api.assets!.pause(true);
      const laneResponse = page.waitForResponse((response) => new URL(response.url()).pathname === "/v1/queue/lanes");
      await page.clock.runFor(pollInterval);
      expect((await laneResponse).status()).toBe(200);
      await expect(form.getByRole("status")).toHaveText("Image lane paused");
      expect(jobReads).toBe(2);

      const target = story.board_order[0];
      await targetBox(page).selectOption(target);
      await expect(page).toHaveURL(assetsPath(boardContext, true, { target }));
      await expect(page.getByText("Candidate job not found.")).toHaveCount(0);
      expect(jobReads).toBe(2);

      await form.getByLabel("Name").fill("Soup ladle");
      await form.getByLabel("Prompt").fill("A wooden ladle for the soup pot.");
      const request = form.getByRole("button", { name: "Request candidate" });
      await expect(request).toBeEnabled();
      await request.click();
      await expect(page.getByText("Candidate queued · image lane paused", { exact: true })).toBeVisible();
      await expect(page).toHaveURL(assetsPath(boardContext, true, { target, job: mock.api.assets!.latestJob()!.id }));
      await expect.poll(() => mock.api.selections.lena.values.web_shell).toMatchObject({
        assets: assetsPath(boardContext, false, { target }),
      });
    });

    for (const status of [404, 403]) {
      test(`uses cutout wording while reading a job and handles a ${status} reply`, async ({ page, mock }) => {
        const job = "job_01M79V9FC00000000000000001";
        const path = `/v1/jobs/${job}`;
        expect(mock.api.assets).toBeDefined();
        let respond!: () => void;
        const held = new Promise<void>((resolve) => { respond = resolve; });
        await page.route(path, async (route) => {
          await held;
          await route.fulfill({ status, json: { error: {
            status: status === 404 ? "not_found" : "forbidden",
            code: status === 404 ? "not_found" : "auth.forbidden",
            message: "Cutout job access was refused.", path: "", http_status: status, request_id: "mock-job-read",
          } } });
        });
        const requested = page.waitForRequest((request) => new URL(request.url()).pathname === path);
        const replied = page.waitForResponse((response) => new URL(response.url()).pathname === path);
        try {
          await page.goto(assetsPath(boardContext, false, { job, jobKind: "matte" }));
          await requested;
          await expect(page.getByText("Reading cutout job…", { exact: true })).toBeVisible();
        } finally {
          respond();
        }
        expect((await replied).status()).toBe(status);
        if (status === 404) await expect(page.getByRole("alert")).toHaveText("Cutout job not found.");
        else await expect(page.getByRole("alert")).toContainText("auth.forbidden");
        await expect(page.getByText("Reading cutout job…", { exact: true })).toHaveCount(0);
      });
    }

    test("explains a missing format pin and a pinned recipe with no sized slots", async ({ page, mock }) => {
      expect(mock.api.assets).toBeDefined();
      let pin: string | null = null;
      await page.route(`/v1/stories/${story.id}`, (route) =>
        route.fulfill({ json: { ...story, format_version_id: pin } }));
      await page.route(`/v1/format-versions/${formatFixture.id}`, (route) =>
        route.fulfill({ json: { ...formatFixture, recipe: {
          ...formatFixture.recipe, cast: { ...formatFixture.recipe.cast, matte_slots: {} },
        } } }));
      const cutout = card(page, "Soup bowl").getByRole("button", { name: "Cut out" });
      await page.goto(productionRoute);
      await expect(page.getByText("This story needs a pinned format to request cutouts.")).toBeVisible();
      await expect(card(page, "Soup bowl")).toBeVisible();
      await expect(cutout).toHaveCount(0);

      pin = formatFixture.id;
      const loaded = page.waitForResponse((response) => new URL(response.url()).pathname === `/v1/format-versions/${pin}`);
      await page.reload();
      expect((await loaded).status()).toBe(200);
      await expect(page.getByText("The pinned format has no sized cast slots for cutouts.")).toBeVisible();
      await expect(card(page, "Soup bowl")).toBeVisible();
      await expect(cutout).toHaveCount(0);
    });

    test("keeps cutout presses by slot, focuses job status and results, and promotes", async ({ page, mock }) => {
      type Job = components["schemas"]["JobView"];
      type MatteRequest = components["schemas"]["MatteRequest"];
      const assets = mock.api.assets!;
      const source = assets.versions.find(({ id }) => id === propPin)!;
      const otherProduction = "prd_01M79V9FC00000000000000002";
      for (const [number, name, production_id] of [
        [555, "Shared bowl", null], [556, "Another production’s bowl", otherProduction],
      ] as const) assets.versions.push({
        ...source, id: photoVersionId(number), name, scope: { production_id },
        asset_id: photoVersionId(number).replace("asv_", "ast_"),
      });
      const recipe = {
        ...formatFixture.recipe, cast: { ...formatFixture.recipe.cast,
          matte_slots: { a: { target_height_px: 160 }, c: { target_height_px: 220 } } },
      };
      const format = { ...formatFixture, recipe };
      await page.route(`/v1/stories/${story.id}`, (route) =>
        route.fulfill({ json: { ...story, format_version_id: format.id } }));
      await page.route(`/v1/format-versions/${format.id}`, (route) => route.fulfill({ json: format }));
      let paused = true;
      await page.route("/v1/queue/lanes", (route) => route.fulfill({ json: { items: [
        { lane: "matte", paused, changed_at: null, changed_by: null },
        { lane: "image", paused: false, changed_at: null, changed_by: null },
      ] } }));

      const [lostC, lostA, implausible, oversize, ready] = [550, 551, 552, 557, 558]
        .map((number) => photoVersionId(number).replace("asv_", "job_"));
      const ids = [lostC, lostA, implausible, oversize, ready];
      const failures = new Map([
        [implausible, { code: "matting.shape_invalid", message: "The shape is implausible." }],
        [oversize, { code: "matting.target_exceeds_frame", message: "The target exceeds the frame." }],
      ]);
      const jobs = new Map<string, Job>();
      const presses: { key: string; body: MatteRequest }[] = [];
      const keys = new Map<string, string>();
      const mattePath = "/v1/asset-jobs/matte";
      await page.route(mattePath, (route) => {
        const key = route.request().headers()["idempotency-key"];
        const body = route.request().postDataJSON() as MatteRequest;
        presses.push({ key, body });
        const prior = keys.get(key);
        if (prior === lostC && presses.length === 3) {
          return route.fulfill({ status: 403, json: { error: { code: "forbidden", message: "Request refused" } } });
        }
        if (prior) return route.fulfill({ status: 200, json: jobs.get(prior) });
        const id = ids[keys.size];
        keys.set(key, id);
        const job: Job = {
          schema: "studio.job/v1", id, target_id: source.id, kind: "matte",
          status: id === ready ? "succeeded" : failures.has(id) ? "failed" : "queued",
          input_signature: "sha256:" + "a".repeat(64), created_at: source.provenance.created_at,
          updated_at: source.provenance.created_at, created_by: source.provenance.created_by,
          result_version_id: id === ready ? output.id : null,
          result_is_current: id === ready ? false : null, error: failures.get(id) ?? null,
          matte: { ...body, source_sha256: source.content!.sha256, format_sha256: format.sha256, kind: "prop",
            production_id: source.scope.production_id, target_height_px: 220 },
        };
        jobs.set(id, job);
        return id === lostC || id === lostA ? route.abort("failed") : route.fulfill({ status: 202, json: job });
      });
      const outputFile = mock.media[5];
      const output = {
        ...source, id: photoVersionId(553), asset_id: photoVersionId(554).replace("asv_", "ast_"),
        state: "candidate" as const, capabilities: ["rgba_cutout", "mask"] as ("rgba_cutout" | "mask")[],
        content: { ...source.content!, sha256: outputFile.hash, bytes: outputFile.body.length },
        provenance: { ...source.provenance, origin: "derived" as const, source_key: "matting:" + "a".repeat(64),
          generator: { role: "composite" as const, engine: "studio-matting", source_asset_version_ids: [source.id] } },
      };
      Object.assign(output.provenance.generator, { params: { receipt: { job_id: ready } } });
      for (const id of ids) {
        const path = `/v1/jobs/${id}`;
        await page.route(path, (route) => route.fulfill({ json: jobs.get(id) }));
        await page.route(`${path}/result`, (route) => route.fulfill({ json: output }));
        await page.route(`${path}/media/${outputFile.hash}`, (route) =>
          route.fulfill({ body: outputFile.body, contentType: "image/png" }));
      }
      const state = (label: string) => page.getByRole("status").filter({ hasText: label });
      const cutout = card(page, "Soup bowl").getByRole("button", { name: "Cut out", exact: true });
      const form = page.getByRole("form", { name: "Request matte" });
      const promotions = () => page.getByRole("button", { name: "Promote", exact: true });
      async function selectSlot(value: "a" | "c") {
        await cutout.click();
        const slot = form.getByRole("combobox", { name: "Cast slot" });
        await expect(slot).toBeFocused();
        await noOverflow(page, viewport.width);
        await expect(slot.getByRole("option")).toHaveText(["Choose a slot", "A", "C"]);
        await expect(form).toContainText(`Format ${format.format_id} · v${format.number}`);
        await slot.selectOption(value);
      }
      async function loseReply() {
        const failed = page.waitForEvent("requestfailed", (request) => new URL(request.url()).pathname === mattePath);
        await form.getByRole("button", { name: "Request matte", exact: true }).click();
        await failed;
        await expect(form.getByRole("button", { name: "Retry matte request" })).toBeVisible();
        await form.getByRole("button", { name: "Close cutout" }).click();
        await expect(form).toHaveCount(0);
      }

      await page.goto(assetsPath(boardContext, false, { scope: "library" }));
      await expect(card(page, "Shared bowl").getByRole("button", { name: "Cut out" })).toBeVisible();
      await expect(card(page, "Another production’s bowl")).toBeVisible();
      await expect(card(page, "Another production’s bowl").getByRole("button", { name: "Cut out" })).toHaveCount(0);
      await expect(card(page, "Recorded spoon").getByRole("button", { name: "Cut out" })).toHaveCount(0);
      await selectSlot("c");
      await loseReply();
      await selectSlot("a");
      await loseReply();
      expect(presses[1].key).not.toBe(presses[0].key);
      expect(presses[1].body.slot).toBe("a");
      await selectSlot("c");
      await form.getByRole("button", { name: "Retry matte request" }).click();
      await expect(form.getByRole("alert")).toContainText("Request refused");
      await form.getByRole("button", { name: "Retry matte request" }).click();
      await expect(state("Cutout queued · matte lane paused")).toBeFocused();
      await expect(page.getByText("A signed-in Studio user can resume the matte lane.")).toBeVisible();
      await expect(page).toHaveURL((url) => url.searchParams.get("job") === lostC &&
        url.searchParams.get("job_kind") === "matte");
      expect(presses[0].key).toMatch(/^[0-9a-f-]{36}$/);
      expect(presses[0].body).toEqual({ slot: "c", format_version_id: format.id, source_version_id: source.id });
      expect(presses[2]).toEqual(presses[0]);
      expect(presses[3]).toEqual(presses[0]);
      expect(jobs.size).toBe(2);
      await expect(promotions()).toHaveCount(0);
      paused = false;
      await showPoll(page);
      await expect(page.getByText("Cutout queued", { exact: true })).toBeVisible();
      jobs.get(lostC)!.status = "running";
      await showPoll(page);
      await expect(state("Cutout running")).toBeVisible();
      await expect(promotions()).toHaveCount(0);
      Object.assign(jobs.get(lostC)!, { status: "failed", error: { code: "adapter.timeout", message: "Matting timed out." } });
      await showPoll(page);
      await expect(state("Cutout failed")).toBeVisible();
      await expect(page.getByRole("alert")).toContainText("adapter.timeout");
      await expect(page.getByRole("alert")).toContainText("Try requesting the cutout again later.");
      await expect(promotions()).toHaveCount(0);

      await selectSlot("a");
      await form.getByRole("button", { name: "Retry matte request" }).click();
      await expect(page.getByText("Cutout queued", { exact: true })).toBeFocused();
      expect(presses[4]).toEqual(presses[1]);
      jobs.get(lostA)!.status = "cancelled";
      await showPoll(page);
      await expect(state("Cutout cancelled")).toBeVisible();
      await expect(promotions()).toHaveCount(0);

      for (const [id, failure] of failures) {
        await selectSlot("c");
        await form.getByRole("button", { name: "Request matte", exact: true }).click();
        await expect(state("Cutout failed")).toBeFocused();
        await expect(page).toHaveURL((url) => url.searchParams.get("job") === id);
        await expect(page.getByRole("alert")).toContainText(failure.code);
        await expect(page.getByRole("alert")).toContainText("Try another cast slot or another photo.");
      }
      expect(presses[5].key).not.toBe(presses[0].key);

      assets.versions.push(output);
      await selectSlot("c");
      await form.getByRole("button", { name: "Request matte", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Candidates" })).toBeFocused();
      await page.reload();
      await expect(state("Cutout ready")).toBeVisible();
      const review = page.getByRole("article", { name: "Soup bowl candidate review" });
      await expect(review.getByRole("img")).toHaveAttribute("src", `/v1/jobs/${ready}/media/${outputFile.hash}`);
      await expect(review.getByText("Promote before use")).toBeVisible();
      await review.getByRole("button", { name: "Promote", exact: true }).click();
      await expect(review.getByText("Promoted to library")).toBeFocused();
      expect(assets.promotions).toEqual([output.id]);
      await noOverflow(page, viewport.width);
    });

    test("releases the press after a 422 and submits a new key and corrected body", async ({ page, mock }) => {
      const path = "/v1/asset-jobs";
      await openGenerate(page);
      const form = generationForm(page);
      const prompt = form.getByLabel("Prompt");
      await form.getByLabel("Name").fill("Soup ladle");
      await prompt.fill("The rejected prompt");
      mock.api.failNext({ path, method: "POST", status: 500, detail: {
        status: "internal", code: "request.failed", path: "", http_status: 500,
        request_id: "mock-submit-500", message: "Reply failed",
      } });
      await form.getByRole("button", { name: "Request candidate" }).click();
      const retry = form.getByRole("button", { name: "Retry candidate request" });
      await expect(retry).toBeVisible();
      mock.api.failNext({ path, method: "POST", status: 422, detail: {
        status: "invalid", code: "schema.invalid", path: "prompt", http_status: 422,
        request_id: "mock-submit-422", message: "Invalid prompt",
      } });
      const refused = page.waitForResponse((response) => new URL(response.url()).pathname === path && response.status() === 422);
      await retry.click();
      const rejected = (await refused).request();
      await expect(form.getByRole("alert")).toContainText("schema.invalid");
      await expect(prompt).toBeEditable();
      await prompt.fill("A wooden ladle for the soup pot.");
      await form.getByRole("button", { name: "Request candidate" }).click();
      await expect(page.getByText("Candidate queued", { exact: true })).toBeVisible();
      const [accepted] = mock.api.assets!.presses;
      expect(mock.api.assets!.presses).toHaveLength(1);
      expect(accepted.key).not.toBe(await rejected.headerValue("idempotency-key"));
      expect(rejected.postDataJSON()).toMatchObject({ prompt: "The rejected prompt" });
      expect(accepted.body).toMatchObject({ prompt: "A wooden ladle for the soup pot." });
    });
  });
}
