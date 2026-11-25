import { expect, test as base, type Page } from "@playwright/test";

import { treePath } from "../src/routes";
import { mockStudio, story, storyContext } from "./studio-api";

const test = base.extend<{ api: Awaited<ReturnType<typeof mockStudio>> }>({
  api: async ({ context, baseURL }, use) => {
    const api = await mockStudio(context, baseURL!, { inspector: true });
    await use(api);
    expect(api.violations).toEqual([]);
  },
});
const [first, second] = story.board_order;
const route = (board: string) => treePath("board", { ...storyContext, board });
const inspector = (page: Page) => page.getByRole("complementary", { name: "Board inspector" });
const line = (page: Page, number = 1) => inspector(page).getByRole("textbox", { name: `Dialogue for line ${number}` });
const save = (page: Page) => inspector(page).getByRole("button", { name: "Save board", exact: true });
const tool = (page: Page, name: string) => inspector(page).getByRole("button", { name, exact: true });
const field = (page: Page, name: string) => inspector(page).getByRole("spinbutton", { name, exact: true });
const note = (page: Page, number: number) => inspector(page).getByRole("textbox", { name: `Note ${number}`, exact: true });
const newNote = (page: Page) => inspector(page).getByRole("textbox", { name: "New direction note" });
const stage = (page: Page) => page.getByRole("region", { name: "Selected board stage" });

for (const viewport of [{ width: 400, height: 860 }, { width: 1280, height: 900 }]) {
  test.describe(`${viewport.width} × ${viewport.height}`, () => {
    test.use({ viewport });

    test("persists script, speakers, timing, method, and direction through the API", async ({ page, api }) => {
      await page.goto(route(first));
      await expect(line(page)).toHaveValue("The soup can hear you.");
      const board = inspector(page);
      await expect(board.getByRole("group", { name: "Line 1" }).getByRole("combobox")).toHaveValue("a");
      await line(page).fill("Keep the lid on.");
      await tool(page, "Add line").click();
      await board.getByRole("combobox", { name: "Speaker for line 2" }).selectOption("narrator");
      await line(page, 2).fill("The lid rattles.");
      await tool(page, "Move line 2 earlier").focus();
      await page.keyboard.press("Enter");
      await expect(line(page, 1)).toHaveValue("The lid rattles.");
      await expect(line(page, 2)).toHaveValue("Keep the lid on.");
      await tool(page, "Add line").click();
      await line(page, 3).fill("Remove this take.");
      await tool(page, "Remove line 3").focus();
      await page.keyboard.press("Enter");
      await expect(tool(page, "Add line")).toBeFocused();

      await field(page, "Gap before line 2 (ms)").fill("180");
      await field(page, "Lead (ms)").fill("320");
      await field(page, "Tail (ms)").fill("630");
      await board.getByText("Method", { exact: true }).click();
      await expect(tool(page, "Whole-frame")).toHaveCount(0);
      await tool(page, "Speech-to-video").click();
      await expect(tool(page, "Speech-to-video")).toHaveAttribute("aria-pressed", "true");
      await expect(tool(page, "Image-to-video")).toHaveAttribute("aria-pressed", "false");

      await newNote(page).fill("A small tap");
      await newNote(page).press("Enter");
      await note(page, 2).press("End");
      await note(page, 2).pressSequentially(" after the line");
      await tool(page, "Remove note 1").focus();
      await page.keyboard.press("Enter");
      await expect(newNote(page)).toBeFocused();
      await expect(note(page, 1)).toHaveValue("A small tap after the line");

      const sound = board.getByRole("group", { name: "Sound cue 1" });
      await sound.getByRole("spinbutton", { name: "Level (dBFS)" }).fill("-17");
      const move = board.getByRole("group", { name: "Move cue 2" });
      await move.getByRole("spinbutton", { name: "Horizontal move (px)" }).fill("4.5");
      const camera = board.getByRole("group", { name: "Camera cue 3" });
      await camera.getByRole("spinbutton", { name: "End zoom" }).fill("1.5");

      await save(page).click();
      await expect(board.getByText("Board saved.", { exact: true })).toBeVisible();
      expect(api.contentEdits).toHaveLength(1);
      expect(api.contentEdits[0]).toMatchObject({
        board: first, revision: '"1"', body: {
          lines: [
            { speaker: "narrator", text: "The lid rattles.", gap_before_ms: null },
            { speaker: "a", text: "Keep the lid on.", gap_before_ms: 180 },
          ],
          timing: { lead_ms: 320, tail_ms: 630, hold_ms: null }, voice: { style: "narrator", current_version_id: null },
          method: { layer: "layered", motion: "s2v" }, notes: [{ text: "A small tap after the line" }],
          cues: [{ level_rms_dbfs: -17, trim_ms: null }, { dx_px: 4.5 }, { zoom_to: 1.5 }],
        },
      });
      expect(api.contentEdits[0].body.lines?.[0]).not.toHaveProperty("id");
      expect(api.contentEdits[0].body.lines?.[1]).toHaveProperty("id");
      await page.reload();
      await expect(line(page, 1)).toHaveValue("The lid rattles.");
      await expect(line(page, 2)).toHaveValue("Keep the lid on.");
      await expect(field(page, "Gap before line 2 (ms)")).toHaveValue("180");
      await expect(field(page, "Lead (ms)")).toHaveValue("320");
      await expect(field(page, "Tail (ms)")).toHaveValue("630");
      await expect(note(page, 1)).toHaveValue("A small tap after the line");
      await expect(sound.getByRole("spinbutton", { name: "Level (dBFS)" })).toHaveValue("-17");
      await expect(move.getByRole("spinbutton", { name: "Horizontal move (px)" })).toHaveValue("4.5");
      await expect(camera.getByRole("spinbutton", { name: "End zoom" })).toHaveValue("1.5");

      await page.getByRole("list", { name: "Boards" }).getByRole("link", { name: /Board 02/ }).click();
      await field(page, "Silent hold (ms)").fill("1750");
      await board.getByText("Method", { exact: true }).click();
      await expect(tool(page, "Speech-to-video")).toBeDisabled();
      await expect(board.getByText("Needs a spoken line.")).toBeVisible();
      await tool(page, "Whole-frame").click();
      await save(page).click();
      await expect(board.getByText("Board saved.", { exact: true })).toBeVisible();
      expect(api.contentEdits[1]).toMatchObject({
        board: second, revision: '"1"', body: {
          timing: { hold_ms: 1750, lead_ms: null, tail_ms: null },
          method: { layer: "whole_frame", motion: "i2v" },
        },
      });
      await page.reload();
      await expect(field(page, "Silent hold (ms)")).toHaveValue("1750");
      await board.getByText("Direction", { exact: true }).click();
      await expect(newNote(page)).toBeVisible();
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
      const timeline = (await page.getByRole("region", { name: "Panel timeline" }).boundingBox())!;
      const panel = (await board.boundingBox())!;
      const picture = (await stage(page).boundingBox())!;
      if (viewport.width === 400) expect(panel.y).toBeGreaterThanOrEqual(timeline.y + timeline.height);
      else expect(panel.x).toBeGreaterThanOrEqual(picture.x + picture.width);
    });

    test("keeps edits on refusal and presents both versions after a conflict", async ({ page, api }) => {
      await page.clock.install();
      await page.goto(route(first));
      await line(page).fill("The new line stays here.");
      api.failNext({
        path: `/v1/boards/${first}`, method: "PATCH", status: 422,
        detail: { status: "invalid", code: "schema.invalid", message: "Check the line.", request_id: "mock-refusal", path: "/lines", http_status: 422 },
      });
      await save(page).click();
      await expect(inspector(page).getByRole("alert")).toContainText("Board save failed. Check the line.");
      await expect(line(page)).toHaveValue("The new line stays here.");

      api.editDraftBoard(first, {
        lines: [{ id: "lin_01M79V9FC00000000000000001", speaker: "a", text: "The server has another line.", gap_before_ms: null }],
        notes: [{ id: "nte_01M79V9FC00000000000000001", text: "A newer note" }],
      });
      await save(page).click();
      await expect(inspector(page).getByRole("alert")).toContainText("Review both versions");
      await expect(inspector(page).getByRole("region", { name: "Your unsaved version" })).toContainText("The new line stays here.");
      await expect(inspector(page).getByRole("region", { name: "Latest saved version" })).toContainText("The server has another line.");
      await expect(line(page)).toHaveValue("The new line stays here.");
      await expect(save(page)).toBeDisabled();
      expect(api.contentEdits.map(({ revision }) => revision)).toEqual(['"1"']);
      await tool(page, "Keep my edited fields").click();
      await expect(note(page, 1)).toHaveValue("A newer note");
      await save(page).click();
      await expect(inspector(page).getByText("Board saved.", { exact: true })).toBeVisible();
      expect(api.contentEdits.map(({ revision }) => revision)).toEqual(['"1"', '"2"']);
      expect(api.contentEdits[1].body).not.toHaveProperty("notes");
    });

    test("shows the API refusal if a silent S2V request bypasses the control", async ({ page, api }) => {
      await page.goto(route(second));
      await field(page, "Silent hold (ms)").fill("2400");
      await inspector(page).getByText("Method", { exact: true }).click();
      await expect(tool(page, "Speech-to-video")).toBeDisabled();

      const endpoint = `**/v1/boards/${second}`;
      await page.route(endpoint, async (route) => {
        if (route.request().method() !== "PATCH") return route.fallback();
        const body = { ...route.request().postDataJSON(), method: { layer: "layered", motion: "s2v" } };
        await route.fallback({ postData: JSON.stringify(body) });
      });
      await save(page).click();
      await expect(inspector(page).getByRole("alert")).toContainText("method.s2v_needs_line");
      await expect(field(page, "Silent hold (ms)")).toHaveValue("2400");
      expect(api.contentEdits).toHaveLength(1);
      await page.unroute(endpoint);
      await save(page).click();
      await expect(inspector(page).getByText("Board saved.", { exact: true })).toBeVisible();
      expect(api.contentEdits.map(({ revision }) => revision)).toEqual(['"1"', '"1"']);
    });

    test("keeps focused input through polling and reload, then regenerates with measured timing and ranged playback", async ({ page, api }) => {
      await page.clock.install();
      await page.goto(route(first));
      const board = inspector(page);
      await tool(page, "Generate voice").click();
      await expect(board.getByText("Queued in voice lane")).toBeVisible();
      const original = api.voice.latest()!.id;
      api.voice.start(original);
      await page.clock.runFor(5000);
      await expect(board.getByText("Generating voice…", { exact: true })).toBeVisible();

      await newNote(page).fill("Notes in progress");
      await line(page).fill("The lid needs another line.");
      const completed = api.completeVoice(original, first, 200);
      expect(api.voice.latest()?.result_is_current).toBe(true);
      await page.clock.runFor(5000);
      await expect(board.getByText("Voice ready · stale")).toBeVisible();
      await expect(line(page)).toBeFocused();
      await expect(line(page)).toHaveValue("The lid needs another line.");
      await expect(board.locator("audio")).toHaveCount(0);
      await expect(stage(page).locator("audio")).toHaveCount(0);

      await page.getByRole("list", { name: "Boards" }).getByRole("link", { name: /Board 02/ }).click();
      await expect(field(page, "Silent hold (ms)")).toHaveValue("1000");
      await page.getByRole("list", { name: "Boards" }).getByRole("link", { name: /Board 01/ }).click();
      await expect(line(page)).toHaveValue("The lid needs another line.");
      await page.reload();
      await expect(line(page)).toHaveValue("The lid needs another line.");
      await expect(newNote(page)).toHaveValue("Notes in progress");
      await expect(board.getByText("Voice ready · stale")).toBeVisible();
      await expect(board.locator("audio")).toHaveCount(0);
      await save(page).click();
      await expect(board.getByText("Board saved.")).toBeVisible();
      await expect(board.getByText("Timing pending", { exact: true })).toBeVisible();
      await tool(page, "Regenerate voice").click();
      await expect(board.getByText("Queued in voice lane")).toBeVisible();
      const regenerated = api.voice.latest()!.id;
      api.voice.start(regenerated);
      await page.clock.runFor(5000);
      await expect(board.getByText("Generating voice…")).toBeVisible();
      const { track, lineFile, versionId } = api.completeVoice(regenerated, first, 450);
      expect(versionId).not.toBe(completed.versionId);
      await page.clock.runFor(5000);
      await expect(board.getByText("Board length 1.167 s", { exact: true })).toBeVisible();
      await expect(stage(page).getByLabel("Time range")).toHaveText("0.000–1.167 s");

      const pathname = `/v1/asset-versions/${versionId}/media/${track.hash}`;
      const audio = board.getByLabel("Current board voice");
      await expect(audio).toHaveAttribute("src", pathname);
      await expect(board.getByLabel("Current line take")).toHaveAttribute("src", `/v1/asset-versions/${versionId}/media/${lineFile.hash}`);
      const fetched = page.waitForResponse((response) => new URL(response.url()).pathname === pathname);
      await audio.evaluate(async (element: HTMLAudioElement) => { element.muted = true; await element.play(); });
      const response = await fetched;
      expect(response.request().headers().range).toBe("bytes=0-");
      expect(response.status()).toBe(206);
      expect(response.headers()["content-range"]).toBe(`bytes 0-${track.body.length - 1}/${track.body.length}`);
      expect(api.voice.presses[0].key).not.toBe(api.voice.presses[1].key);
    });

    test("tracks the paused lane, retries a single press, and reports worker failure and a stale saved result", async ({ page, api }) => {
      await page.clock.install();
      api.voice.pause(true);
      api.voice.loseNextReply();
      await page.goto(route(first));
      const board = inspector(page);
      await expect(board.getByText("Voice lane paused", { exact: true })).toBeVisible();
      await tool(page, "Generate voice").click();
      await expect(board.getByText(/Voice request failed/)).toBeVisible();
      await page.reload();
      await expect(board.getByText("Queued · voice lane paused")).toBeVisible();
      await tool(page, "Retry voice request").click();
      const failed = api.voice.latest()!.id;
      expect(api.voice.presses).toHaveLength(2);
      expect(api.voice.presses[0].key).toBe(api.voice.presses[1].key);

      api.voice.pause(false);
      api.voice.start(failed);
      await page.clock.runFor(5000);
      await expect(board.getByText("Generating voice…")).toBeVisible();
      api.voice.fail(failed, "voice.provider_unavailable", "Speech worker unavailable.");
      await page.clock.runFor(5000);
      await expect(board.getByRole("alert")).toContainText("Speech worker unavailable. (voice.provider_unavailable)");
      await tool(page, "Generate voice").click();
      await expect(board.getByText("Queued in voice lane")).toBeVisible();
      const stale = api.voice.latest()!.id;
      api.voice.start(stale);
      await page.clock.runFor(5000);
      await expect(board.getByText("Generating voice…")).toBeVisible();
      await line(page).fill("A different line, already saved.");
      await save(page).click();
      await expect(board.getByText("Board saved.")).toBeVisible();
      api.completeVoice(stale, first, 200);
      expect(api.voice.latest()?.result_is_current).toBe(false);
      await page.clock.runFor(5000);
      await expect(board.getByText("Voice ready · stale")).toBeVisible();
      await expect(line(page)).toHaveValue("A different line, already saved.");
      await expect(tool(page, "Regenerate voice")).toBeEnabled();
      await expect(board.locator("audio")).toHaveCount(0);
    });
  });
}
