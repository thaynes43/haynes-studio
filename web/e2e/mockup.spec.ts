import { expect, test } from "@playwright/test";

// Keep the standalone storyboard prototype covered alongside the production shell.
const MOCKUP = new URL("../../docs/design/studio-ui-mockup/index.html", import.meta.url).href;

test("the committed storyboard mockup renders", async ({ page }) => {
  const errors: string[] = [];
  const external: string[] = [];
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  // The mockup is self-contained: any network request is a regression.
  await page.route(/^https?:/, (route) => {
    external.push(route.request().url());
    return route.abort();
  });

  await page.goto(MOCKUP);

  await expect(page).toHaveTitle("Haynes Studio Storyboard");
  await expect(page.locator("header.top .brand-name")).toHaveText("HAYNES STUDIO");
  await expect(page.locator("#main #page-title")).toBeVisible();
  await expect(page.locator("#main")).not.toBeEmpty();
  expect(errors).toEqual([]);
  expect(external).toEqual([]);
});
