import { expect, test as base, type Locator, type Page } from "@playwright/test";

import { pollInterval } from "../src/run-polling";
import { storyFormatId, treePath } from "../src/routes";
import { mockStudio, production } from "./studio-api";
import { castVoice, formatVersions, narratorVoice, oldShortFormat, shortFormat, wideFormat } from "./studio-format-fixtures";
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
const formatSection = (page: Page) => page.locator(".story-format-section");
const summary = (page: Page) => format(page).locator("summary");
const version = (page: Page) => format(page).getByRole("combobox", { name: "Format version" });
const save = (page: Page) => format(page).getByRole("button", { name: "Save format" });
const build = (page: Page) => page.getByRole("button", { name: "Build", exact: true });
const pinLink = (page: Page) => page.getByRole("link", { name: "Pin a format in the story editor" });
const castName = (page: Page) => format(page).getByRole("textbox", { name: "Cast A name" });
const castVoiceChoice = (page: Page) => format(page).getByRole("combobox", { name: "Cast A voice" });
const narrator = (page: Page) => format(page).getByRole("combobox", { name: "Narrator voice" });
const addCast = (page: Page) => format(page).getByRole("button", { name: "Add cast member" });
const removeCast = (page: Page) => format(page).getByRole("button", { name: "Remove cast a" });
const reloadDraft = (page: Page) => formatSection(page).getByRole("button", { name: "Reload draft" });
const latestSaved = (page: Page) => format(page).getByRole("heading", { name: "Latest saved version" });
const missingFormat = "fmv_01M79V9FC00000000000000099";
const missingVoice = "asv_01M79V9FC00000000000000099";
const packageWarning = "No platform maximum. A package can’t be prepared.";

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

async function addBuildableBoard(page: Page, api: Api, storyId: string) {
  await page.getByRole("button", { name: "Add board" }).click();
  await expect(page.getByRole("list", { name: "Boards" })).toBeVisible();
  const fixture = api.attachFormatBoardPhoto(storyId);
  await page.reload();
  await expect(page.getByRole("list", { name: "Boards" })).toBeVisible();
  return fixture;
}

function requestGate() {
  let release!: () => void;
  let started!: () => void;
  const held = new Promise<void>((resolve) => { release = resolve; });
  const reached = new Promise<void>((resolve) => { started = resolve; });
  return { held, release, reached, started };
}

async function requestApi(page: Page, path: string, body?: Record<string, unknown>, match?: string) {
  return page.evaluate(async ({ path, body, match }) => {
    const response = await fetch(path, body === undefined ? undefined : {
      method: "PATCH",
      headers: { "content-type": "application/json", "x-studio-csrf": "test-csrf-lena",
        ...(match !== undefined && { "If-Match": match }) },
      body: JSON.stringify(body),
    });
    return { status: response.status, etag: response.headers.get("etag"), json: await response.json() };
  }, { path, body, match });
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
      const { board, photo } = await addBuildableBoard(page, api, storyId);

      const first = await finishRun(page, api, 1);
      await expect(page.getByText(/This run has no pinned targets\./)).toBeVisible();
      await expect(page.getByRole("button", { name: "Present run" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Prepare package" })).toHaveCount(0);
      const editor = treePath("board", { production: production.id, media: "short", story: storyId });
      await expect(pinLink(page)).toHaveAttribute("href", `${editor}#${storyFormatId}`);
      await pinLink(page).press("Enter");
      await expect(summary(page)).toBeFocused();
      await expect(version(page).locator("option")).toHaveText(["Choose a format", "Doll Short · v2", "Doll Short · v1"]);
      await tabTo(page, version(page));
      expect(await version(page).evaluate((el) => getComputedStyle(el).outlineStyle)).toBe("solid");
      await page.keyboard.press("ArrowDown");
      await expect(version(page)).toHaveValue(shortFormat);
      await expect(format(page).getByRole("listitem").filter({ hasText: "Private feedback" })).toContainText(packageWarning);
      await expect(format(page).getByRole("listitem").filter({ hasText: "Shorts release" })).toHaveText("Shorts release");
      await page.keyboard.press("End");
      await expect(version(page)).toHaveValue(oldShortFormat);
      await expect(format(page).getByRole("listitem").filter({ hasText: "Shorts release" })).toContainText(packageWarning);
      await page.keyboard.press("Home");
      await expect(version(page)).toHaveValue(shortFormat);
      await tabTo(page, narrator(page));
      await page.keyboard.press("End");
      await expect(narrator(page)).toHaveValue(narratorVoice);
      await tabTo(page, addCast(page));
      await page.keyboard.press("Enter");
      await page.keyboard.press("Shift+Tab");
      await expect(removeCast(page)).toBeFocused();
      await page.keyboard.press("Shift+Tab");
      const actorVoice = castVoiceChoice(page);
      await expect(actorVoice).toBeFocused();
      await page.keyboard.press("ArrowDown");
      await expect(actorVoice).toHaveValue(castVoice);
      await page.keyboard.press("Shift+Tab");
      await expect(castName(page)).toBeFocused();
      await page.keyboard.type("Ada");
      await expectNoOverflow(page);
      await page.keyboard.press("Enter");
      await expect(format(page).getByText("Format settings saved.")).toBeVisible();
      await expect(summary(page)).toHaveText("Format Format pinned");
      expect(api.formatWrites).toEqual([{ story: storyId, revision: '"3"', body: {
        format_version_id: shortFormat, cast: [{ slot: "a", name: "Ada", voice_version_id: castVoice }],
        narrator_voice_version_id: narratorVoice,
      } }]);

      const next = await finishRun(page, api, 2);
      expect(api.queue!.snapshots.get(first.id)).toMatchObject({
        story: { boards: [{ id: board.id, photo: { current_version_id: photo.id }, timing: { hold_ms: 4000 } }] },
      });
      expect(api.queue!.snapshots.get(first.id)?.format_version).toBeUndefined();
      expect(api.queue!.snapshots.get(next.id)).toMatchObject({
        story: { revision: 4, ...api.formatWrites[0].body, boards: [{ photo: { current_version_id: photo.id } }] },
        format_version: { id: shortFormat, sha256: formatVersions.find(({ id }) => id === shortFormat)!.sha256 },
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
      await addCast(page).click();
      await castName(page).fill("Ada");
      await castVoiceChoice(page).selectOption(castVoice);
      const path = `/v1/stories/${id}`;
      const patch = requestGate();
      await page.route(`**${path}`, async (route) => {
        if (route.request().method() !== "PATCH") return route.fallback();
        patch.started();
        await patch.held;
        await route.fallback({ postData: { ...route.request().postDataJSON(), format_version_id: missingFormat } });
      });
      try {
        await castName(page).press("Enter");
        await patch.reached;
        await expect(summary(page)).toBeFocused();
        await expect(summary(page)).toHaveCSS("outline-style", "solid");
        await expect(summary(page)).toContainText("Saving format…");
        await expect(save(page)).toHaveJSProperty("disabled", true);
        for (const control of [version, narrator, castName, castVoiceChoice, addCast, removeCast]) {
          await expect(control(page)).toBeDisabled();
        }
        await expect(build(page)).toBeDisabled();
      } finally {
        patch.release();
      }
      await expect(formatSection(page).getByRole("alert")).toContainText("That format version does not exist");
      await expect(summary(page)).toContainText("Format save failed");
      await expect(version(page)).toHaveValue(shortFormat);
      await expect(save(page)).toBeEnabled();
      await summary(page).press("Enter");
      await expect(version(page)).toBeHidden();
      await expect(formatSection(page).getByRole("alert")).toContainText("That format version does not exist");
      expect(api.formatWrites).toHaveLength(1);
      await expectNoOverflow(page);
    });

    test("shows a collapsed format conflict and blocks Build until the conflict is resolved", async ({ page, api }) => {
      const id = await createStory(page);
      await addBuildableBoard(page, api, id);
      await setShortFormat(page);
      await save(page).click();
      await expect(format(page).getByText("Format settings saved.")).toBeVisible();
      await version(page).selectOption(oldShortFormat);

      const path = `/v1/stories/${id}`;
      const patch = requestGate();
      await page.route(`**${path}`, async (route) => {
        if (route.request().method() === "PATCH") {
          patch.started();
          await patch.held;
        }
        await route.fallback();
      });
      const response = page.waitForResponse((reply) => new URL(reply.url()).pathname === path && reply.request().method() === "PATCH");
      try {
        await save(page).click();
        await patch.reached;
        api.editStory(id, { title: "Closing Time, Revised" });
        await summary(page).click();
        await expect(version(page)).toBeHidden();
        await expect(summary(page)).toContainText("Saving format…");
      } finally {
        patch.release();
      }
      expect((await response).status()).toBe(409);
      await expect(page.getByRole("heading", { name: "Closing Time, Revised" })).toBeVisible();
      await expect(summary(page)).toHaveText("Format Format change needs review");
      await expect(latestSaved(page)).toBeHidden();
      await expect(build(page)).toBeDisabled();
      const reason = "Review your unsaved format settings before building.";
      await expect(page.getByText(reason)).toBeVisible();
      await expect(build(page)).toHaveAccessibleDescription(reason);
      await build(page).click({ force: true });
      expect(api.queue!.presses).toHaveLength(0);
      await expectNoOverflow(page);

      const keyboard = viewport.width === 400;
      if (keyboard) {
        await summary(page).focus();
        await page.keyboard.press("Enter");
      } else {
        await summary(page).click();
      }
      await expect(latestSaved(page).locator("..")).toContainText("Doll Short · v2");
      await expect(format(page).getByRole("heading", { name: "Your unsaved version" }).locator(".."))
        .toContainText("Doll Short · v1");
      await expect(build(page)).toBeDisabled();
      await expectNoOverflow(page);

      if (keyboard) {
        const keep = format(page).getByRole("button", { name: "Keep my edited fields" });
        await tabTo(page, keep);
        await page.keyboard.press("Enter");
        await save(page).click();
        await expect(format(page).getByText("Format settings saved.")).toBeVisible();
      } else {
        await format(page).getByRole("button", { name: "Use latest saved version" }).click();
      }
      await expect(page.getByText(reason)).toHaveCount(0);
      await build(page).click();
      await expect(page.getByRole("article", { name: "Run 1", exact: true })).toContainText("Queue position 1");
      const [run] = api.queue!.runs;
      const chosen = keyboard ? oldShortFormat : shortFormat;
      expect(api.queue!.snapshots.get(run.id)).toMatchObject({ story: { format_version_id: chosen }, format_version: { id: chosen } });
      expect(api.queue!.presses).toHaveLength(1);
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

for (const { mode, message } of [
  { mode: "connection", message: "Studio could not be reached" },
  { mode: "server", message: "The request could not be completed" },
] as const) {
  test(`keeps recovery visible and locks writes after a ${mode} error`, async ({ page, api }) => {
    await createStory(page);
    await setShortFormat(page);
    api.dropNextFormatReply(mode);
    await save(page).click();
    await expect(formatSection(page).getByRole("alert")).toContainText(message);
    await expect(save(page)).toBeDisabled();
    await expect(version(page)).toBeDisabled();
    await expect(build(page)).toBeDisabled();
    await expect(page.getByRole("button", { name: "Add board" })).toBeDisabled();
    await summary(page).press("Enter");
    await expect(version(page)).toBeHidden();
    await expect(summary(page)).toContainText("Check format save");
    await expect(formatSection(page).getByRole("alert")).toContainText(message);
    await reloadDraft(page).click();
    await expect(summary(page)).toHaveText("Format Format pinned");
    await expect(reloadDraft(page)).toHaveCount(0);
    await expect(build(page)).toBeEnabled();
    expect(api.formatWrites).toHaveLength(1);
  });
}

test("recovers after a successful PATCH returns revision 6 with ETag 4", async ({ page, api }) => {
  const id = await createStory(page);
  await addBuildableBoard(page, api, id);
  await setShortFormat(page);
  const path = `/v1/stories/${id}`;
  api.alterNextFormatReplyRevision();
  const patch = page.waitForResponse((reply) => new URL(reply.url()).pathname === path && reply.request().method() === "PATCH");
  await save(page).click();
  const response = await patch;
  expect(response.status()).toBe(200);
  expect(response.headers().etag).toBe('"4"');
  expect(await response.json()).toMatchObject({ revision: 6 });
  expect(api.formatWrites[0].revision).toBe('"3"');
  await expect(summary(page)).toHaveText("Format Check format save");
  await expect(build(page)).toBeDisabled();
  await expect(reloadDraft(page)).toBeVisible();

  await reloadDraft(page).click();
  await expect(summary(page)).toHaveText("Format Format pinned");
  await expect(build(page)).toBeEnabled();
  await expect(reloadDraft(page)).toHaveCount(0);
  await build(page).click();
  await expect(page.getByRole("article", { name: "Run 1", exact: true })).toContainText("Queue position 1");
  const [run] = api.queue!.runs;
  expect(api.queue!.snapshots.get(run.id)).toMatchObject({ story: { revision: 4 }, format_version: { id: shortFormat } });
  expect(api.formatWrites).toHaveLength(1);
});

for (const write of ["conflict", "success"] as const) {
  test(`rejects a coherent old draft after a PATCH ${write} until reload reaches the known revision`, async ({ page, api }) => {
    const id = await createStory(page);
    await setShortFormat(page);
    const storyPath = `/v1/stories/${id}`;
    const timingPath = `${storyPath}/timing`;
    const readDraft = async () => ({ story: await requestApi(page, storyPath), timing: await requestApi(page, timingPath) });
    let stale = await readDraft();
    let intermediate: typeof stale | undefined;
    if (write === "conflict") {
      api.editStory(id, { narrator_voice_version_id: narratorVoice });
      intermediate = await readDraft();
      api.editStory(id, { format_version_id: oldShortFormat });
    }
    let replay = true;
    let replayedTiming = 0;
    await page.route(({ pathname }) => pathname === storyPath || pathname === timingPath, async (route) => {
      if (!replay || route.request().method() !== "GET") return route.fallback();
      if (new URL(route.request().url()).pathname === timingPath) {
        replayedTiming += 1;
        return route.fulfill({ json: stale.timing.json });
      }
      return route.fulfill({ headers: { etag: stale.story.etag! }, json: stale.story.json });
    });
    await save(page).click();
    await expect(reloadDraft(page)).toBeVisible();
    await expect(build(page)).toBeDisabled();
    await expect(latestSaved(page)).toHaveCount(0);

    // In the conflict case, revision 2 is newer than the sent revision and still below the server's revision 3.
    stale = intermediate ?? stale;
    await reloadDraft(page).click();
    await expect.poll(() => replayedTiming).toBe(2);
    await expect(summary(page)).toHaveText(write === "conflict" ? "Format Format change needs review" : "Format Check format save");
    await expect(reloadDraft(page)).toBeEnabled();
    await expect(build(page)).toBeDisabled();
    await expect(latestSaved(page)).toHaveCount(0);

    replay = false;
    await reloadDraft(page).click();
    if (write === "conflict") {
      await expect(summary(page)).toHaveText("Format Format change needs review");
      await expect(latestSaved(page).locator("..")).toContainText("Doll Short · v1");
      await expect(save(page)).toBeDisabled();
      await expect(build(page)).toBeDisabled();
      await format(page).getByRole("button", { name: "Use latest saved version" }).click();
    } else {
      await expect(version(page)).toHaveValue(shortFormat);
      await expect(save(page)).toBeDisabled();
    }
    await expect(summary(page)).toHaveText("Format Format pinned");
    await expect(build(page)).toBeEnabled();
    expect(api.formatWrites).toHaveLength(1);
  });
}

for (const missing of ["name", "voice"] as const) {
  test(`requires a cast ${missing} before writing`, async ({ page, api }) => {
    await createStory(page);
    await setShortFormat(page);
    await addCast(page).click();
    if (missing === "name") await castVoiceChoice(page).selectOption(castVoice);
    else await castName(page).fill("Ada");
    const required = missing === "name" ? castName(page) : castVoiceChoice(page);
    await save(page).click();
    await expect(required).toBeFocused();
    expect(await required.evaluate((input: HTMLInputElement | HTMLSelectElement) => input.validity.valueMissing)).toBe(true);
    expect(api.formatWrites).toHaveLength(0);
  });
}

test("refuses a whitespace-only cast name before writing", async ({ page, api }) => {
  await createStory(page);
  await setShortFormat(page);
  await addCast(page).click();
  await castName(page).fill("   ");
  await castVoiceChoice(page).selectOption(castVoice);
  await castName(page).press("Enter");
  await expect(format(page).getByText("Enter a name for each cast member.")).toBeVisible();
  expect(api.formatWrites).toHaveLength(0);
});

test("answers format requests with API-shaped refusals and read-back", async ({ page, api }) => {
  const id = await createStory(page);
  const path = `/v1/stories/${id}`;
  const { board, photo } = await addBuildableBoard(page, api, id);
  const response = await requestApi(page, path);
  expect(response).toMatchObject({ status: 200, etag: '"3"', json: {
    revision: 3, format_version_id: null, created_at: expect.any(String), updated_at: expect.any(String),
    created_by: { kind: "human" }, derived: { board_count: 1, frames: 96, duration_ms: 4000, warnings: [] },
  } });
  const invalid = [
    [{ format_version_id: missingFormat }, "ref.unknown", "/format_version_id", "That format version does not exist"],
    [{ format_version_id: wideFormat }, "format.frame_mismatch", "/format_version_id",
      "That format's frame size does not match the story's media kind"],
    [{ cast: [{ slot: "a", name: "Ada", voice_version_id: missingVoice }] }, "ref.unknown", "/cast/0/voice_version_id",
      `the library has no asset version ${missingVoice}`],
    [{ narrator_voice_version_id: missingVoice }, "ref.unknown", "/narrator_voice_version_id",
      `the library has no asset version ${missingVoice}`],
    [{ published: true }, "schema.unknown_field", "/published", "The field is not writable"],
  ] as const;
  for (const [body, code, fieldPath, message] of invalid) {
    expect(await requestApi(page, path, body, '"3"')).toMatchObject({ status: 422, etag: null, json: { error: {
      status: "invalid", http_status: 422, code, path: fieldPath, message, request_id: expect.any(String),
    } } });
  }
  expect(await requestApi(page, path, { format_version_id: shortFormat })).toMatchObject({
    status: 422, etag: null, json: { error: {
      status: "invalid", http_status: 422, code: "schema.invalid", path: "/header/If-Match", message: "Field required",
    } },
  });
  expect(await requestApi(page, path, { format_version_id: shortFormat }, '"2"')).toMatchObject({
    status: 409, etag: '"3"', json: { error: {
      status: "conflict", http_status: 409, code: "conflict.revision", path: "/revision", message: "The record has changed",
      current_revision: 3, request_id: expect.any(String),
    } },
  });
  expect(await requestApi(page, path)).toEqual(response);
  for (const unknown of ["/v1/formats/unknown/versions", `/v1/format-versions/${missingFormat}`]) {
    expect(await requestApi(page, unknown)).toMatchObject({ status: 404, json: { error: {
      status: "not_found", http_status: 404, code: "not_found", path: "", message: "The requested resource is unavailable",
    } } });
  }
  for (const catalog of ["/v1/formats", "/v1/formats/doll-short/versions"]) {
    expect(await requestApi(page, catalog)).toMatchObject({
      status: 200, json: { items: [expect.any(Object), expect.any(Object)], next_cursor: null },
    });
  }
  expect(await requestApi(page, `/v1/format-versions/${shortFormat}`)).toMatchObject({
    status: 200, json: { id: shortFormat, format_id: "doll-short", recipe: { length: { min_ms: 3500, max_ms: 5000 } } },
  });
  expect(await requestApi(page, `/v1/assets?kind=voice&production=${production.id}`)).toMatchObject({
    status: 200, json: { items: [castVoice, narratorVoice].map((voiceId) => ({
      id: voiceId, licence: expect.any(Object), attributes: { stock: true, voice_id: expect.any(String) },
      capabilities: ["tts_voice"], provenance: {
        origin: "declared", external: null, source_key: null, generator: { role: "voice", model: expect.any(String) },
      },
    })), next_cursor: null },
  });
  const saved = await requestApi(page, path, { format_version_id: shortFormat }, '"3"');
  expect(saved).toMatchObject({ status: 200, etag: '"4"', json: {
    id, revision: 4, format_version_id: shortFormat, derived: { board_count: 1 },
    created_at: expect.any(String), updated_at: expect.any(String), created_by: { kind: "human" },
  } });
  expect(await requestApi(page, path)).toEqual(saved);
  expect(await requestApi(page, `${path}/timing`)).toMatchObject({ status: 200, json: {
    story_id: id, story_revision: 4, format_length: { format_version_id: shortFormat, min_ms: 3500, max_ms: 5000 },
    build_allowed: true, build_blockers: [],
  } });
  expect(await requestApi(page, `/v1/boards/${board.id}`)).toMatchObject({ status: 200, etag: '"2"', json: {
    created_at: expect.any(String), updated_at: expect.any(String), created_by: { kind: "human" },
    person_edit: "content", person_edit_revision: 2, photo: { current_version_id: photo.id },
  } });
  expect(await requestApi(page, `/v1/assets?production=${production.id}&board=${board.id}`)).toMatchObject({
    status: 200, json: { items: [{
      id: photo.id, licence: expect.any(Object), capabilities: ["opaque_photo"],
      content: { locator: expect.stringMatching(/^productions\/prd_[A-Z0-9]+\/sha256\/[0-9a-f]{2}\/[0-9a-f]{64}\.png$/) },
      provenance: {
        origin: "uploaded", external: { paid_api: false, server_computed_sha256: true },
        generator: { role: "image", model: expect.any(String), params: { input_signature: expect.stringMatching(/^sha256:/) } },
      },
    }], next_cursor: null },
  });
});

test("waits for the run snapshot before offering the Format link, then restores it through sign-in", async ({ page, api }) => {
  await page.clock.install();
  const id = await createStory(page);
  const { board } = await addBuildableBoard(page, api, id);
  const snapshot = requestGate();
  await page.route("**/v1/runs/*/snapshot", async (route) => {
    snapshot.started();
    await snapshot.held;
    await route.fallback();
  });
  try {
    await finishRun(page, api, 1);
    await snapshot.reached;
    await expect(pinLink(page)).toHaveCount(0);
  } finally {
    snapshot.release();
  }
  const destination = treePath("board", { production: production.id, media: "short", story: id }) + `#${storyFormatId}`;
  await expect(pinLink(page)).toHaveAttribute("href", destination);
  api.expire();
  await page.goto((await pinLink(page).getAttribute("href"))!);
  await page.getByRole("link", { name: "Sign in", exact: true }).press("Enter");
  expect(api.loginRequests.at(-1)?.has("return_to")).toBe(false);
  await expect(page).toHaveURL(treePath("board", { production: production.id, media: "short", story: id, board: board.id }) +
    `#${storyFormatId}`);
  await expect(summary(page)).toBeFocused();
  await expect(version(page)).toBeVisible();
});
