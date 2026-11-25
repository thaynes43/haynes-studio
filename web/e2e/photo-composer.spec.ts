import { expect, test as base, type Page } from "@playwright/test";

import { photoAssetReturn } from "../src/photo-composer-model";
import { assetsPath, treePath } from "../src/routes";
import { boardContext, mockStudio, story, storyContext } from "./studio-api";
import {
  castPin, generatePhotoMedia, photoVersionId, propPin, setPin, unavailablePin, uploadDigest, workflowDigest,
} from "./studio-photo-fixtures";

const test = base.extend<{ mock: { api: Awaited<ReturnType<typeof mockStudio>>; media: Awaited<ReturnType<typeof generatePhotoMedia>> } }>({
  mock: async ({ browser, context, baseURL }, use) => {
    const media = await generatePhotoMedia(browser);
    const api = await mockStudio(context, baseURL!, { photoMedia: media });
    await use({ api, media });
    expect(api.violations).toEqual([]);
  },
});
const boardRoute = treePath("board", boardContext);
const photoRoute = treePath("board", boardContext, "photo");
const composer = (page: Page) => page.locator(".photo-composer");
const stage = (page: Page) => page.getByRole("region", { name: "Selected board stage" });
const prompt = (page: Page) => composer(page).getByRole("textbox", { name: "Photo prompt" });
const button = (page: Page, name: string) => composer(page).getByRole("button", { name, exact: true });
const picker = (page: Page) => composer(page).getByRole("region", { name: "Photo versions" });
const resumePolling = (page: Page) => page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));

async function returnFromAssets(page: Page, versionId: string) {
  const { to, state } = photoAssetReturn(boardContext, versionId);
  // The future Assets page passes this state to React Router's Link or navigate.
  await page.evaluate(({ to, state }) => {
    const historyState = { usr: state, key: crypto.randomUUID(), idx: history.state.idx + 1 };
    history.pushState(historyState, "", to);
    dispatchEvent(new PopStateEvent("popstate", { state: historyState }));
  }, { to, state });
}

for (const viewport of [{ width: 400, height: 860 }, { width: 1280, height: 900 }]) {
  test.describe(`${viewport.width} × ${viewport.height}`, () => {
    test.use({ viewport });

    test("queues pinned assets and a prompt, preserves edits during a job and supports regeneration", async ({ page, mock }) => {
      const { api, media } = mock;
      const jobs = api.photos!;
      await page.clock.install();
      await page.goto(boardRoute);
      await expect(stage(page).getByRole("img")).toHaveAttribute("src", `/v1/media/${media[0].hash}`);
      await expect(composer(page)).not.toHaveAttribute("open");
      await composer(page).locator("summary").first().click();
      await expect(composer(page).getByRole("img", { name: "Selected reference photo" })).toHaveAttribute("src", `/v1/media/${media[0].hash}`);
      await expect.poll(() => api.calls.includes(`GET /v1/media/${media[0].hash}`)).toBe(true);
      await expect(composer(page).getByRole("button", { name: /Remove Ada portrait/ })).toBeVisible();

      const panelBox = (await composer(page).boundingBox())!;
      if (viewport.width === 400) {
        const filmstrip = (await page.getByRole("list", { name: "Boards" }).boundingBox())!;
        expect(panelBox.y).toBeGreaterThan(filmstrip.y + filmstrip.height);
      } else {
        const stageBox = (await stage(page).boundingBox())!;
        expect(panelBox.x).toBeGreaterThan(stageBox.x + stageBox.width);
      }

      await composer(page).getByRole("combobox", { name: "Add pinned asset" }).selectOption(setPin);
      await prompt(page).fill("Ada waits at the cabin table.");
      await button(page, "Regenerate photo").click();
      await expect(composer(page).getByText("Waiting in the shared household image queue")).toBeVisible();
      const firstJob = jobs.latest()!;
      expect(jobs.presses[0]).toMatchObject({ board: boardContext.board, saved: {
        prompt: "Ada waits at the cabin table.", input_asset_version_ids: [castPin, setPin],
      } });
      jobs.start(firstJob.id);
      await resumePolling(page);
      await expect(composer(page).getByText("Photo job running…")).toBeVisible();

      await composer(page).getByRole("combobox", { name: "Add pinned asset" }).selectOption(propPin);
      await prompt(page).fill("Ada inspects a bowl of soup.");
      await page.clock.runFor(450);
      await expect.poll(() => api.contentEdits.at(-1)?.body.photo).toMatchObject({
        prompt: "Ada inspects a bowl of soup.", input_asset_version_ids: [castPin, setPin, propPin],
        current_version_id: photoVersionId(100),
      });
      await expect(composer(page).getByText("Photo inputs unsaved.")).toHaveCount(0);
      const late = api.completePhoto(firstJob.id, boardContext.board);
      expect(late.current).toBe(false);
      await resumePolling(page);
      await expect(composer(page).getByText("Photo saved · not current")).toBeVisible();
      await expect(composer(page).getByText("Photo inputs changed.")).toBeVisible();
      await expect(prompt(page)).toHaveValue("Ada inspects a bowl of soup.");
      await expect(prompt(page)).toBeFocused();
      await expect(stage(page).getByRole("img")).toHaveAttribute("src", `/v1/media/${media[0].hash}`);
      await picker(page).getByText("v4 · Generated", { exact: true }).click();
      const historyUrl = `/v1/asset-versions/${late.result.id}/media/${late.file.hash}`;
      await expect(picker(page).getByRole("img", { name: "Reference photo v4" })).toHaveAttribute("src", historyUrl);
      await expect.poll(() => api.calls.includes(`GET ${historyUrl}`)).toBe(true);
      expect(api.calls).not.toContain(`GET /v1/media/${late.file.hash}`);

      await button(page, "Regenerate photo").click();
      await expect(composer(page).getByText("Waiting in the shared household image queue")).toBeVisible();
      const secondJob = jobs.latest()!;
      expect(jobs.presses[0].key).not.toBe(jobs.presses[1].key);
      jobs.start(secondJob.id);
      await resumePolling(page);
      await expect(composer(page).getByText("Photo job running…")).toBeVisible();
      const regenerated = api.completePhoto(secondJob.id, boardContext.board);
      expect(regenerated.current).toBe(true);
      await resumePolling(page);
      await expect(composer(page).getByText("Photo ready", { exact: true })).toBeVisible();
      await expect(stage(page).getByRole("img")).toHaveAttribute("src", `/v1/media/${regenerated.file.hash}`);
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
    });

    test("retries a paused request with the same key and reports an API job failure", async ({ page, mock }) => {
      const jobs = mock.api.photos!;
      jobs.pause(true);
      jobs.loseNextReply();
      await page.clock.install();
      await page.goto(photoRoute);
      await expect(composer(page).getByText("Image lane paused", { exact: true })).toBeVisible();
      await button(page, "Regenerate photo").click();
      await expect(composer(page).getByText("Queued · image lane paused")).toBeVisible();
      await button(page, "Retry photo request").click();
      await expect(button(page, "Regenerate photo")).toBeDisabled();
      expect(jobs.presses).toHaveLength(2);
      expect(jobs.presses[0]).toEqual(jobs.presses[1]);
      const { id } = jobs.latest()!;
      jobs.pause(false);
      jobs.start(id);
      await resumePolling(page);
      await expect(composer(page).getByText("Photo job running…")).toBeVisible();
      jobs.fail(id, "image.unavailable", "Image worker unavailable.");
      await resumePolling(page);
      await expect(composer(page).getByRole("alert")).toContainText("Image worker unavailable. (image.unavailable)");
      await expect(button(page, "Regenerate photo")).toBeEnabled();
    });

    test("retains a newer prompt when completion wins the race with its save", async ({ page, mock }) => {
      const { api } = mock;
      const jobs = api.photos!;
      api.editDraftBoard(boardContext.board, { photo: {
        current_version_id: null, input_asset_version_ids: [castPin], prompt: "Ada at the table.",
      } });
      await page.clock.install();
      await page.goto(photoRoute);
      await button(page, "Generate photo").click();
      await expect(composer(page).getByText("Waiting in the shared household image queue")).toBeVisible();
      const { id } = jobs.latest()!;
      jobs.start(id);
      await resumePolling(page);
      await expect(composer(page).getByText("Photo job running…")).toBeVisible();

      await prompt(page).fill("Ada at the door.");
      const result = api.completePhoto(id, boardContext.board);
      expect(result.current).toBe(true);
      await resumePolling(page);
      await expect(composer(page).getByText("Photo saved · not current")).toBeVisible();
      await expect(picker(page).getByText("v4 · Generated · Selected for saved inputs")).toBeVisible();
      await expect(prompt(page)).toHaveValue("Ada at the door.");
      await page.clock.runFor(450);
      await expect(composer(page).getByText("Photo inputs changed.")).toBeVisible();
      await expect(prompt(page)).toHaveValue("Ada at the door.");
      await expect(button(page, "Regenerate photo")).toBeEnabled();
    });

    test("lists immutable provenance and preserves the picker at a revision conflict", async ({ page, mock }) => {
      const { api, media } = mock;
      await page.clock.install();
      await page.goto(photoRoute);
      const versions = picker(page);
      await expect(versions.locator("summary")).toHaveText(["v3 · Imported", "v2 · Agent upload", "v1 · Generated · Selected"]);
      await expect(versions.getByText("Recorded without media. This version can’t be selected.")).toBeVisible();
      await expect(button(page, "Select v3")).toHaveCount(0);
      await versions.getByText("v3 · Imported").click();
      await expect(versions.getByRole("img", { name: "Reference photo v3" })).toHaveCount(0);
      await versions.getByText("v2 · Agent upload").click();
      await expect(versions.getByText("Fixture agent · photo-fixture")).toBeVisible();
      await expect(versions.getByText(uploadDigest)).toBeVisible();
      await expect(versions.getByText(/key_01M/)).toHaveCount(0);
      await versions.getByText("v1 · Generated · Selected").click();
      await expect(versions.getByText("ComfyUI · Fixture image model")).toBeVisible();
      await expect(versions.getByText("17", { exact: true })).toBeVisible();
      await expect(versions.getByText(workflowDigest)).toBeVisible();
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);

      api.editDraftBoard(boardContext.board, { title: "Revised closing panel" });
      const upload = button(page, "Select v2");
      await upload.focus();
      await page.keyboard.press("Enter");
      await expect(composer(page).getByText("Board changed. Latest photo selection loaded.")).toBeVisible();
      await expect(page).toHaveURL(photoRoute);
      await expect(upload).toBeFocused();
      expect(api.contentEdits.map(({ revision }) => revision)).toEqual(['"1"']);
      await upload.click();
      expect(api.contentEdits.at(-1)).toMatchObject({ revision: '"2"', body: { photo: { current_version_id: photoVersionId(101) } } });
      await expect(versions.getByText("v2 · Agent upload · Selected")).toBeVisible();
      await expect(stage(page).getByRole("img")).toHaveAttribute("src", `/v1/media/${media[1].hash}`);
      await page.reload();
      await expect(picker(page).getByText("v2 · Agent upload · Selected")).toBeVisible();
      await expect(stage(page).getByRole("img")).toHaveAttribute("src", `/v1/media/${media[1].hash}`);
    });

    test("returns a scoped asset selection and recomposites a layered board without a prompt", async ({ page, mock }) => {
      const { api } = mock;
      await page.clock.install();
      await page.goto(boardRoute);
      await page.getByRole("link", { name: "Reference photo", exact: true }).click();
      await expect(page).toHaveURL(photoRoute);
      await expect(composer(page).locator(":scope > summary")).toBeFocused();
      const browse = composer(page).getByRole("link", { name: "Browse Assets" });
      await expect(browse).toHaveAttribute("href", assetsPath(boardContext));
      await browse.click();
      await expect(page).toHaveURL(assetsPath(boardContext));
      await expect(page.getByText("Assets will appear here.")).toBeVisible();
      await returnFromAssets(page, unavailablePin);
      await expect(composer(page).getByText("This asset can’t be used on this board.")).toBeVisible();
      expect(api.contentEdits).toHaveLength(0);

      await browse.click();
      await expect(page.getByText("Assets will appear here.")).toBeVisible();
      await returnFromAssets(page, propPin);
      await expect(composer(page).getByRole("button", { name: /Remove Soup bowl/ })).toBeVisible();
      await page.clock.runFor(450);
      await expect(composer(page).getByText("Photo inputs changed.")).toBeVisible();
      expect(api.contentEdits).toHaveLength(1);
      expect(api.contentEdits[0].body.photo?.input_asset_version_ids).toEqual([castPin, propPin]);
      await page.reload();
      await expect(composer(page).getByRole("button", { name: /Remove Soup bowl/ })).toBeVisible();
      expect(api.contentEdits).toHaveLength(1);

      const layered = story.board_order[0];
      await page.goto(treePath("board", { ...storyContext, board: layered }, "photo"));
      await expect(composer(page).getByRole("region", { name: "Composite layers" })).toContainText("Cabin");
      await expect(composer(page).getByRole("region", { name: "Composite layers" })).toContainText("Ada");
      await expect(prompt(page)).toHaveCount(0);
      await expect(composer(page).getByRole("combobox")).toHaveCount(0);
      await button(page, "Recomposite").click();
      await expect(composer(page).getByText("Waiting in the shared household image queue")).toBeVisible();
      const job = api.photos!.latest()!;
      expect(api.photos!.presses.at(-1)).toMatchObject({ board: layered, seed: 0 });
      api.photos!.start(job.id);
      await resumePolling(page);
      await expect(composer(page).getByText("Compositing photo…")).toBeVisible();
      const result = api.completePhoto(job.id, layered);
      await resumePolling(page);
      await expect(picker(page).getByText("v1 · Composite · Selected")).toBeVisible();
      await expect(stage(page).getByRole("img")).toHaveAttribute("src", `/v1/media/${result.file.hash}`);
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
    });
  });
}
