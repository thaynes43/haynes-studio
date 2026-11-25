import { expect, test } from "@playwright/test";
import { treePath } from "../src/routes";

const baseURL = process.env.STUDIO_INSTALLED_BASE_URL;
const storageState = process.env.STUDIO_INSTALLED_STORAGE_STATE;
const enabled = !process.env.CI && !!baseURL && !!storageState;
test.skip(!enabled, "Local opt-in requires an installed HTTPS origin and a person-supplied storage state.");
test.use({ storageState: enabled ? storageState : undefined });

// Exact archive imports from story 957 and the proxy receipts in story 942.
const imports = [
  {
    title: "One More Meeting",
    production: "prd_01M7ZGYNHFET1GKR4304FVD4PE",
    story: "sty_01M7ZGYNHFET1GKR4304FVD4PF",
    run: "run_01M7ZHNZJ2PWA8XR8K7KKWP17V",
    proxy: "63dbb1e26287360ed6c4a0422dbdbfa250ad981c74e9719133d4dfe72d809d1b",
    bytes: 1_789_344,
  },
  {
    title: "The Winter Menu",
    production: "prd_01M79V9FC00000000000000001",
    story: "sty_01M79V9FC00000000000000001",
    run: "run_01M7C5CJA7XKBCRPM0ZRP2P5RS",
    proxy: "0212a7de9d6b7816c4c4d3c98bfd6d8e80fc112163944152e399b3e980a6748d",
    bytes: 12_986_556,
  },
];

for (const fixture of imports) {
  test(`plays the imported ${fixture.title} proxy with a signed-in browser session`, async ({ page, context }) => {
    expect(URL.canParse(baseURL!), "Supply the installed HTTPS origin").toBe(true);
    const base = new URL(baseURL!);
    expect(base.protocol === "https:" && base.href === base.origin + "/", "Supply the HTTPS origin only").toBe(true);

    const reviewPath = treePath("productions", { ...fixture, media: "short" });
    const proxyPath = `/v1/media/${fixture.proxy}`;
    const deliveryPath = `/v1/runs/${fixture.run}/delivery`;
    const reads = new Set([
      "/v1/me", "/v1/me/selections", `/v1/productions/${fixture.production}`,
      `/v1/stories/${fixture.story}`, `/v1/stories/${fixture.story}/runs`,
      `/v1/runs/${fixture.run}`, deliveryPath, proxyPath,
    ]);
    let unexpectedWrite = false;
    await context.route("**/*", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const method = request.method();
      if (url.origin === base.origin) {
        if (method === "GET" || method === "HEAD") {
          const staticAsset = url.pathname.startsWith("/assets/") &&
            ["script", "stylesheet"].includes(request.resourceType());
          if (reads.has(url.pathname) || url.pathname === reviewPath || staticAsset) {
            return route.continue();
          }
        } else if (!(method === "PUT" && url.pathname === "/v1/me/selections")) {
          unexpectedWrite = true;
        }
      }
      // The shell normally remembers the current selection. Keep that write
      // and ancillary draft, feedback and release requests off the installed API.
      return route.abort();
    });

    const identity = page.waitForResponse((response) => new URL(response.url()).pathname === "/v1/me");
    await page.goto(new URL(reviewPath, base).href);
    expect((await identity).status(), "The supplied session must be signed in").toBe(200);
    await expect(page.getByRole("heading", { name: fixture.title, exact: true })).toBeVisible();
    const video = page.getByLabel("Phone proxy", { exact: true });
    await expect(video).toHaveAttribute("src", proxyPath);

    const range = "bytes=0-255";
    const response = page.waitForResponse((reply) => new URL(reply.url()).pathname === proxyPath &&
      reply.request().resourceType() === "fetch");
    const result = await page.evaluate(async ({ path, range }) => {
      const reply = await fetch(path, { headers: { Range: range }, credentials: "same-origin" });
      return { status: reply.status, range: reply.headers.get("content-range"), bytes: (await reply.arrayBuffer()).byteLength };
    }, { path: proxyPath, range });
    expect(result).toEqual({ status: 206, range: `bytes 0-255/${fixture.bytes}`, bytes: 256 });
    const request = (await response).request();
    expect((await request.headerValue("cookie") ?? "").split(/;\s*/).some((cookie) =>
      cookie.startsWith("__Host-studio-session=")), "The range request used the session cookie").toBe(true);
    expect(await request.headerValue("authorization") === null, "The range request sent no bearer credential").toBe(true);

    await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.videoHeight)).toBeGreaterThan(0);
    await video.evaluate(async (element: HTMLVideoElement) => { element.muted = true; await element.play(); });
    await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThan(0);
    expect(unexpectedWrite).toBe(false);
  });
}
