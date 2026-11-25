import { expect, test as base, type Page } from "@playwright/test";
import { assetsPath, treePath } from "../src/routes";
import { boardContext, mockStudio, production, story, storyContext } from "./studio-api";

const test = base.extend<{ api: Awaited<ReturnType<typeof mockStudio>> }>({
  api: async ({ context, baseURL }, use) => {
    const api = await mockStudio(context, baseURL!);
    await use(api);
    expect(api.violations).toEqual([]);
  },
});

const mainNav = (page: Page) => page.getByRole("navigation", { name: "Main", exact: true });
const crumbs = (page: Page) => page.getByRole("navigation", { name: "Breadcrumb" });
const editorNav = (page: Page) => page.getByRole("navigation", { name: "Editor", exact: true });
const boardRoute = treePath("board", boardContext);

async function expectNoOverflow(page: Page) {
  await expect.poll(() => page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  )).toBe(true);
}

for (const viewport of [{ width: 400, height: 860 }, { width: 1280, height: 900 }]) {
  test(`hierarchy and contextual history at ${viewport.width}×${viewport.height}`, async ({ page, api }) => {
    await page.setViewportSize(viewport);
    await page.goto("/");
    await expect(page).toHaveURL(/\/productions$/);
    await expect(mainNav(page).getByRole("link")).toHaveText(["Productions", "Editor"]);
    await expect(page.getByRole("link", { name: "Bluebirds" })).toBeVisible(); // second API page
    await page.getByRole("link", { name: production.name }).click();
    await page.getByRole("link", { name: "Shorts 9:16" }).click();
    await page.getByRole("link", { name: story.title }).click();
    const review = treePath("productions", storyContext);
    await expect.poll(() => api.selections.lena.values.web_shell).toMatchObject({ productions: review });

    await mainNav(page).getByRole("link", { name: "Editor" }).click();
    await expect(page.getByRole("heading", { name: "Editor" })).toBeFocused();
    const storyboard = page.getByRole("link", { name: /Storyboard editor/ });
    const library = page.getByRole("link", { name: /Asset library/ });
    const first = await storyboard.boundingBox();
    const second = await library.boundingBox();
    expect(first).not.toBeNull();
    expect(second).not.toBeNull();
    if (viewport.width === 400) {
      expect(second!.y).toBeGreaterThan(first!.y);
      expect(first!.x).toBe(16);
    } else {
      expect(second!.y).toBe(first!.y);
      expect(second!.x).toBeGreaterThan(first!.x);
      expect(first!.x).toBe(32);
    }
    await expectNoOverflow(page);

    await storyboard.click();
    await expect(page.getByRole("heading", { name: "Choose a production" })).toBeFocused();
    await page.getByRole("link", { name: production.name }).click();
    await page.getByRole("link", { name: "Short 9:16" }).click();
    await page.getByRole("link", { name: story.title }).click();
    const secondBoard = page.getByRole("link", { name: /^Board 02/ });
    await secondBoard.click();
    await expect(crumbs(page).getByRole("button")).toHaveText([
      "Editor", "Storyboard", "Yellowbirds", "Short", "The Winter Menu", "Board 02",
    ]);
    await expect(crumbs(page).getByRole("button", { name: "Board 02" })).toHaveAttribute("aria-current", "page");
    await expect(secondBoard).toBeFocused();
    await expect(page.getByRole("link", { name: "Runs", exact: true })).toHaveAttribute("href", treePath("board", storyContext, "runs"));
    await expect(page.getByRole("link", { name: "Reference photo", exact: true })).toHaveAttribute("href", treePath("board", boardContext, "photo"));
    await expectNoOverflow(page);

    await editorNav(page).getByRole("link", { name: "Assets" }).click();
    await expect(page).toHaveURL((url) => url.pathname + url.search === assetsPath(boardContext));
    await expect(crumbs(page).getByRole("button")).toHaveText(["Editor", "Assets", "Yellowbirds", story.title, "Board 02"]);
    await expect(page.getByRole("heading", { name: "Asset library" })).toBeFocused();

    const productionCrumb = crumbs(page).getByRole("button", { name: production.name });
    await productionCrumb.focus();
    await page.keyboard.press("Enter");
    const productionScope = assetsPath(boardContext, false, { scope: "production" });
    await expect(page).toHaveURL((url) => url.pathname + url.search === productionScope);
    await expect(crumbs(page).getByRole("button", { name: "Board 02" })).toHaveCount(0);
    await page.goBack();
    await expect(crumbs(page).getByRole("button", { name: "Board 02" })).toBeVisible();
    await page.goForward();
    await expect(crumbs(page).getByRole("button", { name: production.name })).toHaveAttribute("aria-current", "page");

    await editorNav(page).getByRole("link", { name: "Board" }).click();
    await expect(page).toHaveURL((url) => url.pathname === boardRoute);
    await expect(page.getByRole("heading", { name: story.title })).toBeFocused();
    await mainNav(page).getByRole("link", { name: "Productions" }).click();
    await expect(page).toHaveURL((url) => url.pathname === review);
    await expect.poll(() => api.selections.lena.values.web_shell).toEqual({
      productions: review,
      board: boardRoute,
      assets: productionScope,
    });

    await page.reload();
    await expect(page.getByRole("heading", { name: story.title })).toBeVisible();
    await mainNav(page).getByRole("link", { name: "Editor" }).click();
    await page.getByRole("link", { name: /Asset library/ }).click();
    await expect(page).toHaveURL((url) => url.pathname + url.search === productionScope);
    const account = page.getByRole("button", { name: "Lena Park" });
    await account.click();
    await page.getByRole("button", { name: "Light", exact: true }).click();
    await expect(page.locator("html")).toHaveCSS("color-scheme", "light");
    await expectNoOverflow(page);
    await page.keyboard.press("Escape");
    await expect(account).toBeFocused();
  });

  test(`reloads saved destinations with local and session storage blocked at ${viewport.width}×${viewport.height}`, async ({ page, api }) => {
    await page.setViewportSize(viewport);
    await page.addInitScript(() => {
      for (const storage of ["localStorage", "sessionStorage"]) {
        Object.defineProperty(window, storage, {
          get() { throw new DOMException("Storage blocked", "SecurityError"); },
        });
      }
    });
    const review = treePath("productions", storyContext);
    await page.goto(review);
    await expect.poll(() => api.selections.lena.values.web_shell).toMatchObject({ productions: review });
    await page.goto(boardRoute);
    await expect.poll(() => api.selections.lena.values.web_shell).toMatchObject({ productions: review, board: boardRoute });

    const account = page.getByRole("button", { name: "Lena Park" });
    await account.click();
    await page.getByRole("button", { name: "Light", exact: true }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(page).toHaveURL(boardRoute);
    await expect(crumbs(page).getByRole("button", { name: "Board 02" })).toHaveAttribute("aria-current", "page");
    const productions = mainNav(page).getByRole("link", { name: "Productions" });
    await expect(productions).toHaveAttribute("href", review);
    await expect(editorNav(page).getByRole("link", { name: "Board" })).toHaveAttribute("href", boardRoute);
    await expectNoOverflow(page);

    // With tab storage blocked, the fake callback lands at the Productions root.
    api.expire();
    await page.reload();
    await expect(page.getByRole("heading", { name: "Sign in to Haynes Studio" })).toBeFocused();
    await page.getByRole("link", { name: "Sign in", exact: true }).click();
    await expect(page).toHaveURL("/productions");
    await expect(page.getByRole("heading", { name: "Productions", exact: true })).toBeFocused();
    await expect.poll(() => api.selections.lena.values.web_shell).toMatchObject({
      productions: "/productions", board: boardRoute,
    });
  });
}

test("theme controls and settings preserve keyboard focus", async ({ page, api }) => {
  await page.setViewportSize({ width: 400, height: 860 });
  await page.emulateMedia({ colorScheme: "light" });
  await page.addInitScript(() => {
    if (!localStorage.getItem("haynes-studio-theme")) {
      localStorage.setItem("haynes-studio-theme", '{"bad":true}');
    }
  });
  await page.goto("/");
  const root = page.locator("html");
  await expect(root).toHaveAttribute("data-theme", "dark");
  await expect(root).toHaveCSS("color-scheme", "dark");

  const account = page.getByRole("button", { name: "Lena Park" });
  await account.focus();
  await page.keyboard.press("Enter");
  await expect(account).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Dark", exact: true })).toBeFocused();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Space");
  await expect(root).toHaveAttribute("data-theme", "light");
  await expect(page.getByRole("button", { name: "Light", exact: true })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(account).toBeFocused();
  await expect(account).toHaveAttribute("aria-expanded", "false");

  await account.click();
  await page.getByRole("link", { name: "User settings" }).click();
  await expect(page.getByRole("heading", { name: "User settings" })).toBeFocused();
  await page.getByRole("button", { name: "System", exact: true }).click();
  await expect(root).toHaveCSS("color-scheme", "light");
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(root).toHaveCSS("color-scheme", "dark");
  await expect(page.getByRole("button", { name: "System", exact: true })).toBeFocused();
  await page.reload();
  await expect(page.getByRole("button", { name: "System", exact: true })).toHaveAttribute("aria-pressed", "true");

  const boundary = api.calls.length;
  await account.click();
  await page.getByRole("link", { name: "Admin settings" }).click();
  await expect(page.getByRole("heading", { name: "Admin settings" })).toBeFocused();
  await expect(page.getByText("No admin settings yet.")).toBeVisible();
  expect(api.calls.slice(boundary)).toEqual([]);
  await expectNoOverflow(page);
});

test("expiry retains the route with blocked localStorage and rechecks the API identity", async ({ page, api }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", {
      get() { throw new DOMException("Storage blocked", "SecurityError"); },
    });
  });
  await page.goto(boardRoute);
  const root = page.locator("html");
  await expect(root).toHaveAttribute("data-theme", "dark");
  await expect.poll(() => api.selections.lena.values.web_shell).toMatchObject({ board: boardRoute });

  const account = page.getByRole("button", { name: "Lena Park" });
  await account.click();
  await page.getByRole("button", { name: "Light", exact: true }).click();
  await expect(root).toHaveAttribute("data-theme", "light");
  await page.keyboard.press("Escape");

  api.expire();
  const scope = assetsPath(boardContext);
  await editorNav(page).getByRole("link", { name: "Assets" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to Haynes Studio" })).toBeFocused();
  await expect(page.getByText("Your session expired.")).toBeVisible();
  await expect(account).toHaveCount(0);
  await expect(page).toHaveURL((url) => url.pathname + url.search === scope);
  await page.getByRole("link", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Asset library" })).toBeFocused();
  await expect(page).toHaveURL((url) => url.pathname + url.search === scope);
  await expect(crumbs(page).getByRole("button", { name: "Board 02" })).toBeVisible();
  await expect(root).toHaveAttribute("data-theme", "dark");

  api.signInAs("arden");
  await account.click();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to Haynes Studio" })).toBeFocused();
  await page.getByRole("link", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("button", { name: "Arden Rivera" })).toBeVisible();
  await expect(page.getByText("This item is no longer available.")).toBeVisible();
  await expect(crumbs(page).getByRole("button", { name: production.name })).toHaveCount(0);
  await expect(editorNav(page).getByRole("link", { name: "Board" })).toHaveAttribute("href", "/editor/board");
  await mainNav(page).getByRole("link", { name: "Productions" }).click();
  await expect(page.getByRole("heading", { name: "Bluebirds" })).toBeVisible();
  expect(api.writes.filter(({ user }) => user === "arden")).toEqual([]);
});

test("an API outage reports a reference and retry keeps the route", async ({ page, api }) => {
  api.failNext({
    path: "/v1/productions",
    status: 503,
    detail: {
      code: "database.unavailable", status: "service_unavailable", http_status: 503,
      path: "", message: "Database unavailable",
      request_id: "mock-request-503",
    },
  });
  await page.goto("/productions");
  await expect(page.getByRole("alert")).toContainText("Studio is temporarily unavailable.");
  await expect(page.getByRole("alert")).toContainText("Request ID mock-request-503");
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByRole("link", { name: production.name })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Productions" })).toBeFocused();
  await expect(page).toHaveURL(/\/productions$/);
});
