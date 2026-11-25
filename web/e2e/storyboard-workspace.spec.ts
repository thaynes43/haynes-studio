import { expect, test as base, type Page } from "@playwright/test";

import { treePath } from "../src/routes";
import { mockStudio, otherStoryContext, story, storyContext } from "./studio-api";
import { generateReviewMedia, type ReviewMedia } from "./studio-review-media";

const test = base.extend<{
  api: Awaited<ReturnType<typeof mockStudio>>;
}, { media: ReviewMedia }>({
  media: [async ({ browser }, use) => { await use(await generateReviewMedia(browser)); }, { scope: "worker" }],
  api: async ({ context, baseURL, media }, use) => {
    const api = await mockStudio(context, baseURL!, { storyboardMedia: media });
    await use(api);
    expect(api.violations).toEqual([]);
  },
});

const storyPath = treePath("board", storyContext);
const boardPath = (board: string) => treePath("board", { ...storyContext, board });
const stage = (page: Page) => page.getByRole("region", { name: "Selected board stage" });
const timeline = (page: Page) => page.getByRole("region", { name: "Panel timeline" });
const strip = (page: Page) => page.getByRole("list", { name: "Boards" });
const activeBoard = (page: Page) => strip(page).locator('[aria-current="page"]');
const ids = () => [
  ...story.board_order, "brd_01M79V9FC00000000000000003", "brd_01M79V9FC00000000000000004",
];
const boardOrder = (page: Page) => strip(page).getByRole("link").evaluateAll((links) =>
  links.map((link) => link.getAttribute("href")!.split("/").at(-1)),
);

for (const viewport of [{ width: 400, height: 860 }, { width: 1280, height: 900 }]) {
  test.describe(`${viewport.width} × ${viewport.height}`, () => {
    test.use({ viewport });

    test("lays out the stage and persists add, keyboard reorder, and removal by ID", async ({ page, api, media }) => {
      const [first, second, third, fourth] = ids();
      await page.goto(storyPath);
      await expect(page).toHaveURL(boardPath(first));
      await expect(stage(page).locator("code")).toHaveText(first);
      await expect(stage(page)).toContainText("0.000–0.917 s");
      const photoPath = `/v1/media/${media.photo.hash}`;
      await expect(stage(page).getByRole("img")).toHaveAttribute("src", photoPath);
      await expect(strip(page).locator("img")).toHaveAttribute("src", photoPath);
      await expect(timeline(page)).toContainText("5.417 s");
      await expect(timeline(page)).toContainText("Target 3.5–5 s");
      await expect(timeline(page)).toContainText("past the format maximum");
      const stageBox = (await stage(page).boundingBox())!;
      const timelineBox = (await timeline(page).boundingBox())!;
      const inspector = page.getByRole("complementary", { name: "Board inspector" });
      expect(timelineBox.y).toBeGreaterThanOrEqual(stageBox.y + stageBox.height);
      if (viewport.width === 400) {
        expect(stageBox.x).toBe(16);
        expect(stageBox.width).toBe(368);
        expect(timelineBox.x).toBe(16);
        expect(await strip(page).evaluate((list) => list.scrollWidth > list.clientWidth)).toBe(true);
        const box = (await inspector.boundingBox())!;
        expect(box.y).toBeGreaterThanOrEqual(timelineBox.y + timelineBox.height);
      } else {
        const box = (await inspector.boundingBox())!;
        expect(box.y).toBe(stageBox.y);
        expect(box.x).toBeGreaterThanOrEqual(stageBox.x + stageBox.width);
        await expect(inspector.getByRole("heading", { name: "Board inspector" })).toBeVisible();
      }

      await page.getByRole("button", { name: "Add board" }).click();
      await expect(activeBoard(page)).toHaveAccessibleName("Board 05 1.000 s");
      const added = (await stage(page).locator("code").textContent())!;
      expect(ids()).not.toContain(added);
      await expect(page).toHaveURL(boardPath(added));
      await expect(timeline(page)).toContainText("6.417 s");
      await expect(activeBoard(page)).toBeFocused();

      await page.keyboard.press("Tab");
      await expect(page.getByRole("button", { name: "Add board" })).toBeFocused();
      await page.keyboard.press("Tab");
      await expect(page.getByRole("button", { name: "Move earlier" })).toBeFocused();
      await page.keyboard.press("Enter");
      await expect(timeline(page).getByRole("status")).toHaveText("Moved to board 04.");
      await expect(activeBoard(page)).toBeFocused();
      await expect(activeBoard(page)).toHaveAccessibleName("Board 04 1.000 s");
      expect(await boardOrder(page)).toEqual([first, second, third, added, fourth]);
      await expect(stage(page).locator("code")).toHaveText(added);
      await expect(stage(page)).toContainText("3.417–4.417 s");
      await page.reload();
      await expect(activeBoard(page)).toHaveAccessibleName("Board 04 1.000 s");
      expect(await boardOrder(page)).toEqual([first, second, third, added, fourth]);

      await page.getByRole("button", { name: "Remove board" }).click();
      await expect(timeline(page).getByRole("status")).toHaveText("Board removed.");
      await expect(page).toHaveURL(boardPath(fourth));
      await expect(stage(page).locator("code")).toHaveText(fourth);
      await expect(activeBoard(page)).toBeFocused();
      await page.reload();
      await expect(stage(page).locator("code")).toHaveText(fourth);
      expect(await boardOrder(page)).toEqual(ids());
      expect(api.boardWrites).toEqual([
        { method: "POST", path: `/v1/stories/${story.id}/boards`, revision: '"1"' },
        { method: "PUT", path: `/v1/stories/${story.id}/board-order`, revision: '"2"', order: [first, second, third, added, fourth] },
        { method: "DELETE", path: `/v1/boards/${added}`, revision: '"1"' },
      ]);
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    });

    test("reloads on reorder conflicts and preserves or recovers the selected position", async ({ page, api }) => {
      const [first, second, third, fourth] = ids();
      await page.goto(boardPath(second));
      await expect(activeBoard(page)).toContainText("Board 02");
      api.setDraftOrder([third, second, first, fourth]);
      await page.getByRole("button", { name: "Move earlier" }).click();
      await expect(timeline(page).getByRole("status")).toHaveText("The draft changed. Loaded the latest version.");
      await expect(activeBoard(page)).toBeFocused();
      await expect(page).toHaveURL(boardPath(second));
      expect(await boardOrder(page)).toEqual([third, second, first, fourth]);
      expect(api.boardWrites).toHaveLength(1);
      expect(api.boardWrites[0]).toMatchObject({ revision: '"1"', order: [second, first, third, fourth] });

      api.setDraftOrder([third, first, fourth]);
      await page.getByRole("button", { name: "Move later" }).click();
      await expect(timeline(page).getByRole("status")).toContainText("That board is no longer available.");
      await expect(page).toHaveURL(boardPath(first));
      await expect(stage(page).locator("code")).toHaveText(first);
      expect(await boardOrder(page)).toEqual([third, first, fourth]);
      expect(api.boardWrites).toHaveLength(2);
      expect(api.boardWrites[1]).toMatchObject({ revision: '"2"' });
    });

    test("plays the selected voice with a byte range and keeps equal panel numbers scoped to their story", async ({ page, api, media }) => {
      const [first] = ids();
      const unknown = "brd_01M79V9FC00000000000000099";
      await page.goto(boardPath(unknown));
      await expect(timeline(page).getByRole("status")).toHaveText("That board is no longer available.");
      await expect(page).toHaveURL(boardPath(first));
      await expect(activeBoard(page)).toContainText("Board 01");
      expect(api.calls).not.toContain(`GET /v1/boards/${unknown}`);

      const audio = stage(page).locator("audio");
      const voicePath = `/v1/media/${media.voice.hash}`;
      await expect(audio).toHaveAttribute("src", voicePath);
      await expect(stage(page).getByText("Voice 0.2 s", { exact: true })).toBeVisible();
      const fetched = page.waitForResponse((response) => new URL(response.url()).pathname === voicePath);
      await audio.evaluate(async (el: HTMLAudioElement) => { el.muted = true; await el.play(); });
      const response = await fetched;
      expect(response.request().headers().range).toBe("bytes=0-");
      expect(response.status()).toBe(206);
      expect(response.headers()["content-range"]).toBe(`bytes 0-${media.voice.body.length - 1}/${media.voice.body.length}`);
      await expect.poll(() => audio.evaluate((el: HTMLAudioElement) => el.currentTime)).toBeGreaterThan(0);

      const crumb = page.getByRole("navigation", { name: "Breadcrumb" });
      await crumb.getByRole("button", { name: "Short", exact: true }).click();
      await page.getByRole("link", { name: "The Other Menu" }).click();
      await expect(page).toHaveURL(new RegExp(`^.*${treePath("board", otherStoryContext)}/boards/brd_`));
      await expect(activeBoard(page)).toContainText("Board 01");
      await expect(stage(page).getByRole("heading", { name: "Board 01" })).toBeVisible();
      await expect(stage(page).locator("code")).not.toHaveText(first);
      await expect(stage(page)).toContainText("Whole-frame · Image-to-video");
      await expect(stage(page)).toContainText("0.000–2.625 s");
      await expect(stage(page).getByRole("img")).toHaveCount(0);
      await expect(audio).toHaveCount(0);
      await expect(timeline(page)).not.toContainText("Target");
      const secondStory = page.url();
      await page.goBack();
      await expect(page.getByRole("link", { name: story.title })).toBeVisible();
      await page.goForward();
      await expect(page).toHaveURL(secondStory);
      await expect(stage(page)).toContainText("0.000–2.625 s");
    });
  });
}
