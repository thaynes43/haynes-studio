import { expect, test as base, type Page } from "@playwright/test";

import { treePath } from "../src/routes";
import { mockStudio, production, story } from "./studio-api";

const test = base.extend<{ api: Awaited<ReturnType<typeof mockStudio>>; empty: boolean }>({
  empty: [false, { option: true }],
  api: async ({ context, baseURL, empty }, use) => {
    const api = await mockStudio(context, baseURL!, { empty });
    await use(api);
    expect(api.violations).toEqual([]);
  },
});

const trail = (page: Page) => page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("button");
const addShort = (page: Page) => page.getByRole("button", { name: "+ Short · 9:16" });
const addVideo = (page: Page) => page.getByRole("button", { name: "+ Video · 16:9" });

async function expectNoOverflow(page: Page) {
  await expect.poll(() => page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  )).toBe(true);
}

test.describe("create from an empty Editor", () => {
  test.use({ empty: true });

  for (const viewport of [{ width: 400, height: 860 }, { width: 1280, height: 900 }]) {
    test(`persists production, media type and story at ${viewport.width}×${viewport.height}`, async ({ page, api }) => {
      await page.setViewportSize(viewport);
      await page.goto("/editor");
      await expect(page.getByRole("link", { name: /Asset library/ })).toHaveAttribute("href", "/editor/assets");
      await page.getByRole("link", { name: /Storyboard editor/ }).click();
      await expect(page.getByText("No productions yet.")).toBeVisible();
      await expect(trail(page)).toHaveText(["Editor", "Storyboard"]);

      await page.getByRole("textbox", { name: "Production name" }).fill("  Night Shift  ");
      await page.getByRole("button", { name: "Create production" }).click();
      await expect(trail(page)).toHaveText(["Editor", "Storyboard", "Night Shift"]);
      const mediaPicker = new URL(page.url()).pathname;
      await expect(page.getByText("No media types yet.")).toBeVisible();
      await expect(page.getByRole("link", { name: "Short 9:16" })).toHaveCount(0);
      await expect(addVideo(page)).toBeVisible();
      await expectNoOverflow(page);

      await addShort(page).click();
      await expect(page.getByRole("heading", { name: "Choose a story" })).toBeFocused();
      await expect(page.getByText("No stories yet.")).toBeVisible();
      const storyPicker = `${mediaPicker}/short`;
      await expect(page).toHaveURL((url) => url.pathname === storyPicker);
      await expectNoOverflow(page);

      const title = page.getByRole("textbox", { name: "Story title" });
      await title.fill("Closing Time");
      await title.press("Enter");
      await expect(page.getByRole("heading", { name: "Closing Time" })).toBeFocused();
      await expect(trail(page)).toHaveText(["Editor", "Storyboard", "Night Shift", "Short", "Closing Time"]);
      await expect(trail(page).last()).toHaveAttribute("aria-current", "page");
      await expect(page.getByText("No boards yet.")).toBeVisible();
      const storyboard = new URL(page.url()).pathname;
      const storyId = storyboard.split("/").at(-1)!;
      const beforeReload = api.calls.length;
      await page.reload();
      await expect(page.getByText("No boards yet.")).toBeVisible();
      expect(api.calls.slice(beforeReload)).toContain(`GET /v1/stories/${storyId}`);

      await page.goBack();
      await expect(page).toHaveURL((url) => url.pathname === storyPicker);
      await expect(page.getByRole("link", { name: "Closing Time" })).toBeVisible();
      await page.goBack();
      await expect(page).toHaveURL((url) => url.pathname === mediaPicker);
      await expect(page.getByRole("link", { name: "Short 9:16" })).toBeVisible();
      await expect(addShort(page)).toHaveCount(0);
      await expect(addVideo(page)).toBeVisible();
      await expect(page.getByRole("link", { name: "Video 16:9" })).toHaveCount(0);
      await expectNoOverflow(page);
      await page.goBack();
      await expect(page.getByRole("link", { name: "Night Shift" })).toBeVisible();
      await page.goForward();
      await expect(trail(page).last()).toHaveText("Night Shift");
      await page.goForward();
      await expect(trail(page).last()).toHaveText("Short");
      await page.goForward();
      await expect(page).toHaveURL((url) => url.pathname === storyboard);
      await expect(trail(page).last()).toHaveText("Closing Time");

      await trail(page).getByText("Night Shift", { exact: true }).click();
      await expect(page).toHaveURL((url) => url.pathname === mediaPicker && url.search === "");
      await expect(trail(page)).toHaveText(["Editor", "Storyboard", "Night Shift"]);
      await trail(page).getByText("Editor", { exact: true }).click();
      await expect(page.getByRole("heading", { name: "Editor" })).toBeFocused();
      await expect(trail(page)).toHaveText(["Editor"]);
      expect(api.calls.filter((call) => /^(POST|PUT) \/v1\/productions(?:\/|$)/.test(call))).toHaveLength(3);
    });
  }
});

test("validates current names from every page and surfaces API validation references", async ({ page, context, api }) => {
  await page.setViewportSize({ width: 400, height: 860 });
  await page.goto(treePath("board"));
  const name = page.getByRole("textbox", { name: "Production name" });
  const createProduction = page.getByRole("button", { name: "Create production" });
  await createProduction.click();
  await expect(name).toBeFocused();
  await expect(page.getByRole("alert")).toHaveText("Enter a production name.");
  await name.fill("  bluebirds  ");
  await createProduction.click();
  await expect(page.getByRole("alert")).toHaveText("A production with this name already exists.");
  expect(api.calls).not.toContain("POST /v1/productions");

  await page.getByRole("link", { name: production.name }).click();
  await page.getByRole("link", { name: "Short 9:16" }).click();
  const title = page.getByRole("textbox", { name: "Story title" });
  const createStory = page.getByRole("button", { name: "Create story" });
  const storyPath = `/v1/productions/${production.id}/media-types/short/stories`;
  await expect(title).toBeVisible();
  const secondTab = await context.newPage();
  await secondTab.goto(page.url());
  const otherTitle = secondTab.getByRole("textbox", { name: "Story title" });
  await expect(otherTitle).toBeVisible();
  await title.fill("The Second Shift");
  await createStory.click();
  await expect(page.getByText("No boards yet.")).toBeVisible();
  await otherTitle.fill("  THE SECOND SHIFT  ");
  await secondTab.getByRole("button", { name: "Create story" }).click();
  await expect(secondTab.getByRole("alert")).toHaveText("A story with this title already exists in this media type.");
  await expect(secondTab.getByRole("link", { name: "The Second Shift" })).toBeVisible();
  expect(api.calls.filter((call) => call === `POST ${storyPath}`)).toHaveLength(1);
  await secondTab.close();
  await page.goBack();
  await expect(page.getByRole("link", { name: story.title })).toBeVisible();
  await expect(page.getByRole("link", { name: "The Second Shift" })).toBeVisible();

  api.failNext({
    path: storyPath, method: "POST", status: 422,
    detail: {
      code: "schema.invalid", status: "invalid", http_status: 422, path: "/title",
      message: "Invalid title", request_id: "mock-story-title",
    },
  });
  await title.fill("Closing Time");
  await createStory.click();
  await expect(page.getByRole("alert")).toContainText("Studio rejected this story title. Enter 1–80 characters.");
  await expect(page.getByRole("alert")).toContainText("Request ID mock-story-title");
  await expect(title).toHaveValue("Closing Time");
  await expect(title).toHaveAttribute("aria-invalid", "true");
  await title.fill("Closing Credits");
  await createStory.click();
  await expect(page.getByRole("heading", { name: "Closing Credits" })).toBeFocused();
});

test("reloads the production on a revision conflict without replaying the write", async ({ page, api }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const path = treePath("board", { production: production.id });
  await page.goto(path);
  await expect(addVideo(page)).toBeVisible();
  api.enableMedia(production.id, "video");
  const before = api.calls.length;
  await addVideo(page).click();
  await expect(page.getByRole("alert")).toContainText("This production changed. Its media types are up to date.");
  await expect(page.getByRole("alert")).toContainText("Request ID mock-request-409");
  await expect(page).toHaveURL((url) => url.pathname === path);
  await expect(addVideo(page)).toHaveCount(0);
  await expect(addShort(page)).toHaveCount(0);
  expect(api.calls.slice(before).filter((call) => call.includes(`/v1/productions/${production.id}`))).toEqual([
    `PUT /v1/productions/${production.id}/media-types/video`,
    `GET /v1/productions/${production.id}`,
  ]);
  await page.getByRole("link", { name: "Video 16:9" }).click();
  await expect(page.getByText("No stories yet.")).toBeVisible();
});

test("requires a successful reload before another enable attempt can use a fresh revision", async ({ page, api }) => {
  await page.goto(treePath("board"));
  await page.getByRole("textbox", { name: "Production name" }).fill("Night Shift");
  await page.getByRole("button", { name: "Create production" }).click();
  await expect(addVideo(page)).toBeVisible();
  const id = new URL(page.url()).pathname.split("/").at(-1)!;
  const path = `/v1/productions/${id}`;
  api.enableMedia(id, "short");
  api.failNext({
    path, method: "GET", status: 503,
    detail: {
      code: "database.unavailable", status: "service_unavailable", http_status: 503,
      path: "", message: "Database unavailable", request_id: "mock-reload-503",
    },
  });
  await addVideo(page).click();
  await expect(page.getByRole("alert").filter({ hasText: "Reload its media types" })).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: "mock-reload-503" })).toBeVisible();
  await expect(addVideo(page)).toBeDisabled();
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByRole("link", { name: "Short 9:16" })).toBeVisible();
  await expect(addVideo(page)).toBeEnabled();
  await addVideo(page).click();
  await expect(page).toHaveURL((url) => url.pathname === treePath("board", { production: id, media: "video" }));
  await expect(page.getByText("No stories yet.")).toBeVisible();
  expect(api.calls.filter((call) => call === `PUT ${path}/media-types/video`)).toHaveLength(2);
});
