import { expect, test as base, type Locator, type Page } from "@playwright/test";

import { pollInterval } from "../src/run-polling";
import { storyFormatId, treePath } from "../src/routes";
import { mockStudio, production } from "./studio-api";
import { castVoice, narratorVoice, shortFormat } from "./studio-format-fixtures";
import { generateReviewMedia, type ReviewMedia } from "./studio-review-media";

type Api = Awaited<ReturnType<typeof mockStudio>>;
const test = base.extend<{ api: Api }, { media: ReviewMedia }>({
  media: [async ({ browser }, use) => { await use(await generateReviewMedia(browser)); }, { scope: "worker" }],
  api: async ({ context, baseURL, media }, use) => {
    const api = await mockStudio(context, baseURL!, { formatPin: true, runMedia: media });
    await use(api);
    expect(api.violations).toEqual([]);
  },
});

const format = (page: Page) => page.locator(".story-format");
const summary = (page: Page) => format(page).locator("summary");
const version = (page: Page) => format(page).getByRole("combobox", { name: "Format version" });
const save = (page: Page) => format(page).getByRole("button", { name: "Save format" });
const build = (page: Page) => page.getByRole("button", { name: "Build", exact: true });

async function createStory(page: Page) {
  const picker = treePath("board", { production: production.id, media: "short" });
  await page.goto(picker);
  const title = page.getByRole("textbox", { name: "Story title" });
  await title.fill("Closing Time");
  await title.press("Enter");
  await expect(page.getByText("No boards yet.")).toBeVisible();
  return new URL(page.url()).pathname.split("/").at(-1)!;
}

async function openFormat(page: Page) {
  await summary(page).click();
  await expect(version(page)).toBeVisible();
}

async function setShortFormat(page: Page) {
  await openFormat(page);
  await version(page).selectOption(shortFormat);
}

async function tabTo(page: Page, next: Locator) {
  await page.keyboard.press("Tab");
  await expect(next).toBeFocused();
}

async function expectNoOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width);
}

async function finishRun(page: Page, api: Api, number: number) {
  const list = page.getByRole("article", { name: `Run ${number}`, exact: true });
  await build(page).click();
  await expect(list).toContainText("Queue position 1");
  const run = api.queue!.runs.at(-1)!;
  api.queue!.advance(run.id, "running", "Fixture worker started");
  api.queue!.advance(run.id, "succeeded", "Fixture delivery is ready");
  await page.clock.runFor(pollInterval + 100);
  await list.getByRole("button", { name: "View run" }).click();
  await list.getByRole("link", { name: "Review in Productions" }).click();
  return run;
}

for (const viewport of [{ width: 400, height: 860 }, { width: 1280, height: 900 }]) {
  test.describe(`${viewport.width} × ${viewport.height}`, () => {
    test.use({ viewport });

    test("pins a newly created draft by keyboard and sees the next run’s frozen targets", async ({ page, api }) => {
      await page.clock.install();
      const storyId = await createStory(page);
      await expect(summary(page)).toContainText("No format pinned");
      await expectNoOverflow(page);
      await page.getByRole("button", { name: "Add board" }).click();
      await expect(page.getByRole("list", { name: "Boards" })).toBeVisible();

      const first = await finishRun(page, api, 1);
      await expect(page.getByText(/This run has no pinned targets\./)).toBeVisible();
      await expect(page.getByRole("button", { name: "Present run" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Prepare package" })).toHaveCount(0);
      const pinLink = page.getByRole("link", { name: "Pin a format in the story editor" });
      const editor = treePath("board", { production: production.id, media: "short", story: storyId });
      await expect(pinLink).toHaveAttribute("href", `${editor}#${storyFormatId}`);
      await pinLink.press("Enter");
      await expect(summary(page)).toBeFocused();
      await expect(version(page).locator("option")).toHaveText(["Choose a format", "Doll Short · v2", "Doll Short · v1"]);
      await tabTo(page, version(page));
      expect(await version(page).evaluate((el) => getComputedStyle(el).outlineStyle)).toBe("solid");
      await page.keyboard.press("ArrowDown");
      await expect(version(page)).toHaveValue(shortFormat);
      const narrator = format(page).getByRole("combobox", { name: "Narrator voice" });
      await tabTo(page, narrator);
      await page.keyboard.press("End");
      await expect(narrator).toHaveValue(narratorVoice);
      await tabTo(page, format(page).getByRole("button", { name: "Add cast member" }));
      await page.keyboard.press("Enter");
      await page.keyboard.press("Shift+Tab");
      await expect(format(page).getByRole("button", { name: "Remove cast a" })).toBeFocused();
      await page.keyboard.press("Shift+Tab");
      const actorVoice = format(page).getByRole("combobox", { name: "Cast A voice" });
      await expect(actorVoice).toBeFocused();
      await page.keyboard.press("ArrowDown");
      await expect(actorVoice).toHaveValue(castVoice);
      await page.keyboard.press("Shift+Tab");
      await expect(format(page).getByRole("textbox", { name: "Cast A name" })).toBeFocused();
      await page.keyboard.type("Ada");
      await expectNoOverflow(page);
      await page.keyboard.press("Enter");
      await expect(format(page).getByText("Format settings saved.")).toBeVisible();
      await expect(summary(page)).toHaveText("Format Format pinned");
      expect(api.formatWrites).toEqual([{ story: storyId, revision: '"2"', body: {
        format_version_id: shortFormat, cast: [{ slot: "a", name: "Ada", voice_version_id: castVoice }],
        narrator_voice_version_id: narratorVoice,
      } }]);

      const next = await finishRun(page, api, 2);
      expect(api.queue!.snapshots.get(first.id)?.format_version).toBeUndefined();
      expect(api.queue!.snapshots.get(next.id)).toMatchObject({
        story: { revision: 3, ...api.formatWrites[0].body }, format_version: { id: shortFormat },
      });
      const target = page.getByRole("combobox", { name: "Target", exact: true });
      await expect(target.locator("option")).toHaveText(["Choose a target", "Private feedback", "Shorts release"]);
      await expect(page.getByRole("button", { name: "Present run" })).toBeEnabled();
      await page.getByRole("combobox", { name: "Release target" }).selectOption("shorts");
      await expect(page.getByRole("button", { name: "Prepare package" })).toBeEnabled();
      await expectNoOverflow(page);
    });

    test("shows the saving and refused states without claiming the draft is pinned", async ({ page, api }) => {
      const id = await createStory(page);
      await setShortFormat(page);
      const path = `/v1/stories/${id}`;
      let release!: () => void;
      const held = new Promise<void>((resolve) => { release = resolve; });
      await page.route(`**${path}`, async (route) => {
        if (route.request().method() === "PATCH") await held;
        await route.fallback();
      });
      api.failNext({ path, method: "PATCH", status: 422, detail: {
        status: "invalid", http_status: 422, path: "/format_version_id", code: "ref.unknown",
        message: "That format version does not exist", request_id: "test-format-refusal",
      } });
      try {
        await save(page).click();
        await expect(summary(page)).toContainText("Saving format…");
        await expect(build(page)).toBeDisabled();
      } finally {
        release();
      }
      await expect(format(page).getByRole("alert")).toContainText("That format version does not exist");
      await expect(summary(page)).toContainText("No format pinned");
      await expect(version(page)).toHaveValue(shortFormat);
      await expect(save(page)).toBeEnabled();
      await expectNoOverflow(page);
    });
  });
}

test("shows both versions after a revision conflict and saves only after explicit confirmation", async ({ page, api }) => {
  const id = await createStory(page);
  await setShortFormat(page);
  api.editStory(id, { narrator_voice_version_id: narratorVoice });
  await save(page).click();
  await expect(format(page).getByRole("heading", { name: "Latest saved version" })).toBeVisible();
  await expect(format(page).getByRole("heading", { name: "Your unsaved version" })).toBeVisible();
  await expect(save(page)).toBeDisabled();
  expect(api.formatWrites).toHaveLength(1);
  await format(page).getByRole("button", { name: "Keep my edited fields" }).click();
  await save(page).click();
  await expect(summary(page)).toContainText("Format pinned");
  expect(api.formatWrites).toEqual([{
    story: id, revision: '"1"', body: { format_version_id: shortFormat },
  }, {
    story: id, revision: '"2"', body: { format_version_id: shortFormat },
  }]);
  await expect(format(page).getByRole("combobox", { name: "Narrator voice" })).toHaveValue(narratorVoice);
});

test("recovers an uncertain save by reading the draft before another write or build", async ({ page, api }) => {
  await createStory(page);
  await setShortFormat(page);
  api.dropNextFormatReply();
  await save(page).click();
  await expect(format(page).getByRole("alert")).toContainText("Studio could not be reached");
  await expect(save(page)).toBeDisabled();
  await expect(build(page)).toBeDisabled();
  await format(page).getByRole("button", { name: "Reload draft" }).click();
  await expect(summary(page)).toHaveText("Format Format pinned");
  await expect(save(page)).toBeDisabled();
  await expect(build(page)).toBeEnabled();
  expect(api.formatWrites).toHaveLength(1);
});
