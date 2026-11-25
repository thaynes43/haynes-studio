import { expect, test } from "@playwright/test";
import { treePath } from "../src/routes";
import { mockStudio, story, storyContext } from "./studio-api";
import { oldRun } from "./studio-review-fixtures";
import { generateReviewMedia, type ReviewMedia } from "./studio-review-media";

let reviewMedia: ReviewMedia;
test.beforeAll(async ({ browser }) => { reviewMedia = await generateReviewMedia(browser); });

const runPath = (run: string) => treePath("productions", { ...storyContext, run });
const targetName = "Tom's YouTube Shorts channel";

for (const viewport of [{ width: 400, height: 860 }, { width: 1280, height: 900 }]) {
  test.describe(`feedback at ${viewport.width}×${viewport.height}`, () => {
    test.use({ viewport });

    test("presents a run and walks from frozen feedback to an answering run", async ({ page, context, baseURL }) => {
      const api = await mockStudio(context, baseURL!, { reviewMedia });
      await page.goto(runPath(oldRun));
      await page.getByRole("checkbox", { name: "Confirm the AI-generated platform setting" }).check();
      await page.getByRole("button", { name: "Approve for go-live", exact: true }).click();
      await expect(page.getByText("Go-live approval recorded.")).toBeVisible();

      const candidates = page.getByRole("region", { name: "Candidates and feedback" });
      const present = candidates.getByRole("button", { name: "Present run" });
      await present.click();
      await expect(candidates.getByText("candidate.target_required", { exact: true })).toBeVisible();
      await candidates.getByRole("combobox", { name: "Target", exact: true }).selectOption("tom-shorts");
      api.failNext({ path: `/v1/runs/${oldRun}/candidates`, method: "POST", status: 422, detail: {
        code: "candidate.target_unknown", status: "invalid", http_status: 422, path: "/target_id",
        message: "This target is outside the frozen recipe", request_id: "fixture-target",
      } });
      await present.click();
      await expect(candidates.getByText("candidate.target_unknown", { exact: true })).toBeVisible();
      await present.click();

      const candidate = page.getByRole("region", { name: targetName });
      const note = candidate.getByRole("textbox", { name: "Feedback note" });
      await candidate.getByRole("button", { name: "Add feedback" }).click();
      await expect(candidate.getByText("feedback.text_required", { exact: true })).toBeVisible();
      await candidate.getByText("Boards (optional)").click();
      await candidate.getByRole("checkbox", { name: "B12 · Opening panel" }).check();
      await note.fill("Hold the first reaction for a beat.");
      await candidate.getByRole("button", { name: "Add feedback" }).click();
      const recorded = candidate.getByRole("list", { name: "Feedback notes" });
      await expect(recorded.getByText("Hold the first reaction for a beat.")).toBeVisible();
      await expect(recorded.getByText("B12 · Opening panel")).toBeVisible();

      await candidate.getByRole("button", { name: "Correct note" }).click();
      const correction = candidate.getByRole("textbox", { name: "Corrected feedback" });
      await expect(correction).toHaveValue("Hold the first reaction for a beat.");
      await correction.fill("Hold the first reaction for two beats.");
      await candidate.getByRole("button", { name: "Save correction" }).click();
      await expect(recorded.getByText("Hold the first reaction for a beat.")).toBeVisible();
      const revised = recorded.getByRole("listitem").filter({ hasText: "Hold the first reaction for two beats." });
      await expect(revised.getByRole("link", { name: "Correction" })).toBeVisible();

      await note.fill("Keep this next note while the draft reloads.");
      await revised.getByRole("checkbox", { name: "Include in iteration" }).check();
      api.editDraftBoard(story.board_order[0], { title: "Current draft opening" });
      const iterate = candidate.getByRole("button", { name: "Start an iteration" });
      await iterate.click();
      await expect(candidate.getByText("conflict.revision", { exact: true })).toBeVisible();
      await expect(note).toHaveValue("Keep this next note while the draft reloads.");
      await expect(iterate).toBeEnabled();
      await expect(page.getByRole("link", { name: "B12 · Current draft opening" })).toBeVisible();
      await expect(revised.getByText("B12 · Opening panel")).toBeVisible();
      expect(api.feedback.writes.map(({ ifMatch }) => ifMatch)).toEqual(['"1"']);
      if (viewport.width === 400) {
        api.failNext({ path: `/v1/stories/${story.id}/candidates`, method: "GET", status: 503, detail: {
          code: "service_unavailable", status: "service_unavailable", http_status: 503, path: "",
          message: "Candidate refresh is unavailable", request_id: "fixture-refresh",
        } });
      }
      await iterate.click();
      await expect(candidates.getByRole("link", { name: "Open draft" })).toHaveAttribute(
        "href", treePath("board", storyContext),
      );
      if (viewport.width === 400) {
        await expect(candidates.getByText("service_unavailable", { exact: true })).toBeVisible();
        await expect(iterate).toBeDisabled();
        await candidates.getByRole("button", { name: "Retry" }).click();
        await expect(iterate).toBeEnabled();
      }
      expect(api.feedback.writes.map(({ ifMatch }) => ifMatch)).toEqual(['"1"', '"2"']);
      await expect(note).toHaveValue("Keep this next note while the draft reloads.");
      await expect(page.getByText("Approved", { exact: true })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

      const answer = api.feedback.appendAnsweringRun();
      await page.goto(runPath(oldRun));
      const forward = page.getByRole("list", { name: "Runs answering this candidate" }).getByRole("link", { name: "Run 5" });
      await expect(forward).toHaveAttribute("href", runPath(answer.id));
      await forward.click();
      const previous = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "Run 5" }) })
        .getByRole("link", { name: "run 1", exact: true });
      await expect(previous).toHaveAttribute("href", runPath(oldRun));
      await previous.click();
      await expect(page.getByRole("list", { name: "Feedback notes" })).toBeVisible();
      const clear = candidates.getByRole("button", { name: "Clear draft iteration" });
      await clear.click();
      await expect(clear).toHaveCount(0);
      await expect(forward).toHaveAttribute("href", runPath(answer.id));
      expect(api.violations).toEqual([]);
    });
  });
}
