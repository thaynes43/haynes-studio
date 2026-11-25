import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import type { Route } from "@playwright/test";
import type { components } from "../src/api/schema";
import { formatId } from "./studio-storyboard-fixtures";

type Schemas = components["schemas"];
type Story = Schemas["Story"];
const { recipe: defaultRecipe }: { recipe: Schemas["FormatRecipe"] } = JSON.parse(
  readFileSync(new URL("../../docs/reference/fixtures/doll-short-v1.json", import.meta.url), "utf8"),
);
const time = "2026-11-04T12:25:00Z";

export function feedbackFixtures(draft: Story, boards: Schemas["Board"][], runs: Schemas["RunView"][],
                                 releaseMaximum?: number) {
  const recipe = structuredClone(defaultRecipe);
  if (releaseMaximum != null) {
    recipe.targets[0].rules.max_length_ms = releaseMaximum;
    recipe.targets[0].rules.aspect = null;
  }
  const { approved: _approved, published: _published, latest_finished_run: _latest, derived: _derived,
    ...story } = draft;
  const frozen: Schemas["RunSnapshot"] = structuredClone({
    schema: "studio.run-snapshot/v1",
    story: { ...story, format_version_id: formatId, boards: boards.map(({ derived: _boardDerived, ...board }) => board) },
    format_version: { id: formatId, recipe, sha256: createHash("sha256").update(JSON.stringify(recipe)).digest("hex") },
    resolved_asset_versions: [],
    toolchain_request: { studio: "git:fixture" },
  });
  const candidates: Schemas["CandidateDetails"][] = [];
  let iteration: Schemas["Iteration"] | null = null;
  let noteCount = 0;
  const writes: { candidate: string; ifMatch: string | undefined; noteIds: string[] }[] = [];
  const etag = () => `"${draft.revision}"`;
  const who = (display_name: string): Schemas["Attribution"] => ({ kind: "human", display_name });
  const refuse = (route: Route, http_status: number, code: string, message = code) => route.fulfill({
    status: http_status,
    json: { error: { code, status: http_status === 409 ? "conflict" : http_status === 404 ? "not_found" : "invalid",
      http_status, path: "", message, request_id: "fixture-feedback" } } satisfies Schemas["ErrorEnvelope"],
  });

  function list(route: Route, story: Story) {
    const run = new URL(route.request().url()).searchParams.get("run_id");
    return route.fulfill({
      headers: { etag: `"${story.revision}"` },
      json: {
        items: story.id === draft.id ? candidates.filter(({ run_id }) => !run || run_id === run) : [],
        next_cursor: null, revision: story.revision, iteration: story.id === draft.id ? iteration : null,
      } satisfies Schemas["CandidatePage"],
    });
  }

  function snapshot(route: Route, run: Schemas["RunView"]) {
    return route.fulfill({ headers: { etag: `"${run.snapshot.sha256}"` }, json: frozen });
  }

  function present(route: Route, run: Schemas["RunView"], name: string) {
    const { target_id } = route.request().postDataJSON() as Schemas["CandidateWrite"];
    if (!target_id.trim()) return refuse(route, 422, "candidate.target_required", "Choose a target");
    if (!recipe.targets.some(({ id }) => id === target_id)) return refuse(route, 422, "candidate.target_unknown");
    const existing = candidates.find(({ run_id, target_id: target }) => run_id === run.id && target === target_id);
    if (existing) return route.fulfill({ json: existing });
    const record = { id: "cnd_01M79V9FC000000000000000" + String(candidates.length + 1).padStart(2, "0"),
      run_id: run.id, target_id, presented_at: time, presented_by: who(name) };
    candidates.push({ ...record, notes: [], answering_runs: [] });
    return route.fulfill({ status: 201, json: record satisfies Schemas["Candidate"] });
  }

  function write(route: Route, id: string, resource: string, name: string) {
    const candidate = candidates.find((item) => item.id === id);
    if (!candidate) return refuse(route, 404, "not_found");
    const request = route.request();
    if (resource === "feedback") {
      const { text, board_ids = [], replaces_id = null } = request.postDataJSON() as Schemas["FeedbackWrite"];
      if (!text.trim()) return refuse(route, 422, "feedback.text_required", "Enter a feedback note");
      if (board_ids.some((id) => !frozen.story.board_order.includes(id))) return refuse(route, 422, "feedback.board_unknown");
      const note = {
        id: "fbk_01M79V9FC000000000000000" + String(++noteCount).padStart(2, "0"),
        candidate_id: id, text: text.trim(), board_ids, replaces_id, written_at: time, written_by: who(name),
      };
      candidate.notes.push(note);
      return route.fulfill({ status: 201, json: note satisfies Schemas["FeedbackNote"] });
    }
    const { note_ids } = request.postDataJSON() as Schemas["IterationWrite"];
    const ifMatch = request.headers()["if-match"];
    writes.push({ candidate: id, ifMatch, noteIds: note_ids });
    if (ifMatch !== etag()) return refuse(route, 409, "conflict.revision", "The draft revision changed");
    if (note_ids.some((id) => !candidate.notes.some((note) => note.id === id))) return refuse(route, 422, "feedback.note_unknown");
    draft.revision += 1;
    iteration = { candidate_id: candidate.id, run_id: candidate.run_id, note_ids,
      started_at: time, started_revision: draft.revision, started_by: who(name) };
    return route.fulfill({ status: 201, headers: { etag: etag() },
      json: { revision: draft.revision, iteration } satisfies Schemas["IterationStarted"] });
  }

  function appendAnsweringRun() {
    if (!iteration) throw Error("Start an iteration before queueing a fixture run");
    const { candidate_id, run_id, note_ids } = iteration;
    const source = runs.find(({ id }) => id === run_id)!;
    const run: Schemas["RunView"] = { ...source, id: "run_01M79V9FC00000000000000005", number: 5,
      status: "queued", revision: 1, finished_at: null, stages: [], checks: null,
      progress: { percent: 0, stage: null }, delivery_id: null, active_approval_id: null,
      snapshot: { ...source.snapshot, story_revision: draft.revision },
      answers: { candidate_id, run_id, note_ids } };
    runs.push(run);
    candidates.find(({ id }) => id === candidate_id)?.answering_runs.push({ id: run.id, number: run.number });
    return run;
  }

  function clear(route: Route) {
    if (route.request().headers()["if-match"] !== etag()) return refuse(route, 409, "conflict.revision");
    const cleared = iteration !== null;
    if (cleared) {
      iteration = null;
      draft.revision += 1;
    }
    return route.fulfill({ headers: { etag: etag() },
      json: { revision: draft.revision, cleared } satisfies Schemas["IterationCleared"] });
  }

  return { list, snapshot, present, write, writes, appendAnsweringRun, clear, frozen };
}
