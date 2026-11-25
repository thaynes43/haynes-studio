import type { BrowserContext, Route } from "@playwright/test";
import type { components, paths } from "../src/api/schema";
import { treePath, type MediaKind } from "../src/routes";
import { latestRun, photoVersion, reviewFixtures, voiceVersion } from "./studio-review-fixtures";
import { mediaResponse, type ReviewMedia } from "./studio-review-media";
import { runFixtures } from "./studio-run-fixtures";
import { boardVersions, formatId, storyTiming } from "./studio-storyboard-fixtures";

type Schemas = components["schemas"];
type BoardCreateBody = paths["/v1/stories/{id}/boards"]["post"]["requestBody"]["content"]["application/json"];

export const production = {
  schema: "studio.production/v1",
  id: "prd_01M79V9FC00000000000000001",
  name: "Yellowbirds",
  revision: 1,
  media_types: [{
    kind: "short",
    aspect: "9:16",
    width: 1080,
    height: 1920,
    fps: 24,
    enabled_at: "2026-11-04T12:00:00Z",
  }],
  labels: [],
} satisfies Schemas["Production"];

const secondProduction = {
  ...production,
  id: "prd_01M79V9FC00000000000000002",
  name: "Bluebirds",
} satisfies Schemas["Production"];

export const story = {
  schema: "studio.story/v1",
  id: "sty_01M79V9FC00000000000000001",
  production_id: production.id,
  media_kind: "short",
  title: "The Winter Menu",
  revision: 1,
  format_version_id: null,
  cast: [],
  narrator_voice_version_id: null,
  set: null,
  layouts: {},
  motion_style: null,
  mix: { line_rms_dbfs: -19, master_lufs: -16, true_peak_dbtp: -1 },
  checks: {},
  beds: [],
  board_order: ["brd_01M79V9FC00000000000000001", "brd_01M79V9FC00000000000000002"],
  origin: null,
  published: false,
  approved: false,
  latest_finished_run: null,
} satisfies Schemas["Story"];

export const storyContext = { production: production.id, media: story.media_kind, story: story.id };
export const boardContext = { ...storyContext, board: story.board_order[1] };
export const otherStoryContext = { ...storyContext, story: "sty_01M79V9FC00000000000000010" };
const selectedBoard = {
  schema: "studio.board/v1",
  id: boardContext.board,
  story_id: story.id,
  number: 7,
  revision: 1,
  title: "Closing panel",
  lines: [],
  timing: { lead_ms: null, tail_ms: null, hold_ms: 1000 },
  voice: { style: null, current_version_id: null },
  photo: { current_version_id: null, input_asset_version_ids: [], prompt: null },
  cast: [],
  layout: { preset: "center", foreground: false },
  method: { layer: "whole_frame", motion: "i2v" },
  seeds: {},
  cues: [],
  notes: [],
  drafted_by: { kind: "human", ...{ iss: "https://identity.example.invalid", sub: "lena" } },
  origin: null,
} satisfies Schemas["Board"];

const people = {
  lena: { displayName: "Lena Park" },
  arden: { displayName: "Arden Rivera" },
};

type User = keyof typeof people;
type Selection = Schemas["Selections"];
type Failure = { path: string; method?: string; status: number; detail: Schemas["ErrorDetail"] };

function pageOf<T extends { id: string }>(items: T[], cursor: string | null) {
  const remaining = cursor ? items.filter(({ id }) => id > cursor) : items;
  return { items: remaining.slice(0, 1), next_cursor: remaining.length > 1 ? remaining[0].id : null };
}

function nextId(first: string, number: number) {
  return first.slice(0, -6) + String(number).padStart(6, "0");
}

export async function mockStudio(context: BrowserContext, baseURL: string, {
  empty = false, reviewMedia, storyboardMedia, runMedia,
}: { empty?: boolean; reviewMedia?: ReviewMedia; storyboardMedia?: Pick<ReviewMedia, "photo" | "voice">; runMedia?: ReviewMedia } = {}) {
  let current: User | null = "lena";
  let next: User = "lena";
  let failure: Failure | undefined;
  let configured = true;
  let reviewAvailable = true;
  let freshRequired = false;
  let runRefusal: string | undefined;
  const review = reviewMedia && reviewFixtures(story, reviewMedia);
  const queue = runMedia && runFixtures(story, runMedia);
  let dropQueueReply: "connection" | "server" | undefined;
  let preflight: Schemas["EstimateView"]["problems"] = [];
  const loginRequests: URLSearchParams[] = [];
  const approvalWrites: Array<{ run: string; body: Schemas["ApprovalWrite"] }> = [];
  const boardWrites: Array<{ method: string; path: string; revision: string | undefined; order?: string[] }> = [];
  const violations: string[] = [];
  const calls: string[] = [];
  const writes: Array<{ user: User; values: Selection["values"]; revision: number }> = [];
  const productions = new Map<string, Schemas["Production"]>([
    [production.id, production], [secondProduction.id, secondProduction],
  ]);
  const visible = {
    lena: new Set(empty ? [] : [production.id, secondProduction.id]),
    arden: new Set(review ? [production.id, secondProduction.id] : [secondProduction.id]),
  };
  const stories: Schemas["Story"][] = [{ ...story }];
  const firstBoard: Schemas["Board"] = {
    ...selectedBoard, id: story.board_order[0], number: 12, title: "Opening panel",
    lines: [{ id: "lin_01M79V9FC00000000000000001", text: "The soup can hear you.", speaker: "narrator", gap_before_ms: null }],
    method: review || queue ? { layer: "layered", motion: "s2v" } : { layer: "whole_frame", motion: "i2v" },
    timing: { lead_ms: 0, tail_ms: 700, hold_ms: null },
    notes: [{ id: "nte_01M79V9FC00000000000000001", text: "Offscreen crunch" }],
    photo: { ...selectedBoard.photo, current_version_id: review || storyboardMedia || queue ? photoVersion : null },
    voice: { current_version_id: review || storyboardMedia || queue ? voiceVersion : null, style: "narrator" },
  };
  const boards = new Map([firstBoard, selectedBoard].map((board) => [board.id, { ...board }]));
  const draftMedia = runMedia ?? storyboardMedia ?? reviewMedia;
  const versions = draftMedia ? boardVersions(production.id, firstBoard, draftMedia) : [];
  let lastBoardId = 2;
  if (storyboardMedia) {
    const more = [1500, 2000].map((hold_ms) => ({
      ...selectedBoard, id: nextId(selectedBoard.id, ++lastBoardId), number: 10 + lastBoardId,
      timing: { ...selectedBoard.timing, hold_ms },
    }));
    const other = {
      ...selectedBoard, id: nextId(selectedBoard.id, ++lastBoardId), story_id: otherStoryContext.story,
      number: firstBoard.number, timing: { ...selectedBoard.timing, hold_ms: 2600 },
    };
    for (const board of [...more, other]) boards.set(board.id, board);
    stories[0].format_version_id = formatId;
    stories[0].board_order = [...story.board_order, ...more.map(({ id }) => id)];
    stories.push({ ...story, id: other.story_id, title: "The Other Menu", board_order: [other.id] });
  }
  if (review) {
    const draft = stories[0];
    draft.latest_finished_run = {
      id: latestRun, status: "succeeded", finished_at: "2026-11-04T12:21:00Z", active_approval_id: null,
    };
    const newProduction = {
      ...production, id: nextId(production.id, 3), name: "Empty production", media_types: [],
    };
    productions.set(newProduction.id, newProduction);
    visible.lena.add(newProduction.id);
    stories.push(
      { ...story, id: nextId(story.id, 2), title: "Ready for release", approved: true, board_order: [] },
      { ...story, id: nextId(story.id, 3), title: "Released and approved", approved: true, published: true, board_order: [] },
      { ...story, id: nextId(story.id, 4), title: "Manual release", published: true, board_order: [] },
    );
  }
  const selections: Record<User, Selection> = {
    lena: { revision: 0, values: {} },
    arden: { revision: 0, values: {
      web_shell: { productions: treePath("productions", { production: secondProduction.id }) },
    } },
  };

  function enableMedia(id: string, kind: MediaKind) {
    const current = productions.get(id);
    if (!current) throw new Error(`Unknown fixture production ${id}`);
    if (current.media_types.some((item) => item.kind === kind)) return current;
    const profile: Schemas["Production"]["media_types"][number] = kind === "short"
      ? production.media_types[0]
      : { kind, aspect: "16:9", width: 1920, height: 1080, fps: 24, enabled_at: "2026-11-04T12:00:00Z" };
    const updated = {
      ...current,
      revision: current.revision + 1,
      media_types: [...current.media_types, profile].sort((a, b) => a.kind.localeCompare(b.kind)),
    };
    productions.set(id, updated);
    return updated;
  }

  function reject(
    route: Route, status: number, category: Schemas["ErrorDetail"]["status"], code: string,
    detail?: Partial<Schemas["ErrorDetail"]>,
  ) {
    const error: Schemas["ErrorEnvelope"] = {
      error: {
        status: category, http_status: status, path: "",
        message: code, code, request_id: `mock-request-${status}`, ...detail,
      },
    };
    return route.fulfill({ status, json: error });
  }

  function approvedState(id: string) {
    return review?.history(id).find((record) => record.derived.state === "active")?.id ?? null;
  }

  function viewRun(run: Schemas["RunView"]) {
    return { ...run, active_approval_id: approvedState(run.id) };
  }

  function viewStory(draft: Schemas["Story"]) {
    if (!review || draft.id !== story.id || !draft.latest_finished_run) return draft;
    return {
      ...draft,
      approved: review.runs.some(({ id }) => approvedState(id)),
      latest_finished_run: { ...draft.latest_finished_run, active_approval_id: approvedState(latestRun) },
    };
  }

  function identityRefusal(user: User) {
    if (!configured) return "approval.approver_not_configured";
    if (user !== "lena") return "approval.subject_not_permitted";
    if (freshRequired) return "approval.sign_in_again";
  }

  function requireRevision(route: Route, revision: number, order?: string[]) {
    const request = route.request();
    const method = request.method();
    const match = request.headers()["if-match"];
    const path = new URL(request.url()).pathname;
    boardWrites.push({ method, path, revision: match, order });
    if (!match) {
      violations.push(`Missing If-Match on ${method} ${path}`);
      return reject(route, 422, "invalid", "schema.invalid", { path: "/revision" });
    }
    if (match !== `"${revision}"`) return reject(route, 409, "conflict", "conflict.revision", { current_revision: revision });
  }

  function setBoardOrder(draft: Schemas["Story"], order: string[]) {
    draft.board_order = order;
    draft.revision += 1;
  }

  await context.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    if (url.origin !== new URL(baseURL).origin) {
      violations.push("Unexpected external request");
      await route.abort();
      return;
    }

    if (!path.startsWith("/v1/") && !path.startsWith("/auth/")) {
      await route.continue();
      return;
    }

    calls.push(`${method} ${path}`);
    const headers = request.headers();
    if ("authorization" in headers || (method === "GET" && "x-studio-csrf" in headers)) {
      violations.push(`Unexpected credential on ${method} ${path}`);
    }
    if (path === "/auth/login" && method === "GET") {
      // Model the completed OIDC round trip. Playwright routes only the first request in a redirect chain.
      current = next;
      loginRequests.push(url.searchParams);
      if (url.searchParams.get("fresh") === "true") freshRequired = false;
      await route.fulfill({ status: 303, headers: { location: url.searchParams.get("return_to") ?? "/" } });
      return;
    }
    const user = current;
    if (!user) return reject(route, 401, "unauthenticated", "auth.required");
    if (method !== "GET" && method !== "HEAD" && headers["x-studio-csrf"] !== `test-csrf-${user}`) {
      violations.push(`Missing session CSRF header on ${method} ${path}`);
      return reject(route, 403, "forbidden", "auth.csrf");
    }

    if (failure?.path === path && (!failure.method || failure.method === method)) {
      const { status, detail } = failure;
      failure = undefined;
      await route.fulfill({ status, json: { error: detail } satisfies Schemas["ErrorEnvelope"] });
      return;
    }
    if (path === "/auth/logout" && method === "POST") {
      current = null;
      await route.fulfill({ status: 204 });
      return;
    }
    if (path === "/v1/me" && method === "GET") {
      const me: Schemas["Me"] = {
        principal: { kind: "human", iss: "https://identity.example.invalid", sub: user },
        display_name: people[user].displayName,
        csrf_token: `test-csrf-${user}`,
      };
      await route.fulfill({ json: me });
      return;
    }

    if (path === "/v1/me/selections" && method === "GET") {
      const value = selections[user];
      await route.fulfill({ headers: { etag: `"${value.revision}"` }, json: value });
      return;
    }
    if (path === "/v1/me/selections" && method === "PUT") {
      if (headers["if-match"] !== `"${selections[user].revision}"`) {
        return reject(route, 409, "conflict", "conflict.revision");
      }
      const { values } = request.postDataJSON() as Schemas["SelectionWrite"];
      const updated = { revision: selections[user].revision + 1, values } satisfies Selection;
      selections[user] = updated;
      writes.push({ user, ...updated });
      await route.fulfill({ headers: { etag: `"${updated.revision}"` }, json: updated });
      return;
    }

    const cursor = url.searchParams.get("cursor");
    if (path === "/v1/productions") {
      if (method === "GET") {
        const available = [...productions.values()].filter(({ id }) => visible[user].has(id));
        return route.fulfill({ json: pageOf(available, cursor) satisfies Schemas["Page_Production_"] });
      }
      if (method === "POST") {
        if (headers["if-match"]) violations.push(`Unexpected If-Match on ${method} ${path}`);
        const { name, labels = [] } = request.postDataJSON() as Schemas["ProductionCreate"];
        if (typeof name !== "string" || !name || Array.from(name).length > 80) {
          return reject(route, 422, "invalid", "schema.invalid", { path: "/name" });
        }
        const id = nextId(production.id, productions.size + 1);
        const doc = { ...production, id, name, labels, media_types: [] } satisfies Schemas["Production"];
        productions.set(id, doc);
        visible[user].add(id);
        return route.fulfill({ status: 201, headers: { etag: '"1"', location: `${path}/${id}` }, json: doc });
      }
    }
    if (path.startsWith("/v1/productions/")) {
      const [, , , id, types, kind, list] = path.split("/");
      const doc = productions.get(id);
      if (!doc || !visible[user].has(id)) {
        return reject(route, 404, "not_found", "not_found");
      }
      if (!types && method === "GET") {
        return route.fulfill({ headers: { etag: `"${doc.revision}"` }, json: doc });
      }
      if (types === "media-types" && (kind === "short" || kind === "video")) {
        if (!list && method === "PUT") {
          if (!headers["if-match"]) {
            violations.push(`Missing If-Match on ${method} ${path}`);
            return reject(route, 422, "invalid", "schema.invalid", { path: "/revision" });
          }
          if (headers["if-match"] !== `"${doc.revision}"`) {
            return reject(route, 409, "conflict", "conflict.revision", {
              path: "/revision", current_revision: doc.revision,
            });
          }
          const updated = enableMedia(id, kind);
          return route.fulfill({ headers: { etag: `"${updated.revision}"` }, json: updated });
        }
        if (list === "stories") {
          if (!doc.media_types.some((item) => item.kind === kind)) {
            return reject(route, 404, "not_found", "not_found");
          }
          if (method === "GET") {
            const publication = url.searchParams.get("publication");
            const approved = url.searchParams.get("approved");
            const items = stories.map(viewStory).filter((item) => item.production_id === id && item.media_kind === kind &&
              (publication === null || item.published === (publication === "published")) &&
              (approved === null || item.approved === (approved === "true")));
            return route.fulfill({ json: pageOf(items, cursor) satisfies Schemas["Page_Story_"] });
          }
          if (method === "POST") {
            if (headers["if-match"]) violations.push(`Unexpected If-Match on ${method} ${path}`);
            const { title } = request.postDataJSON() as Schemas["StoryCreate"];
            if (typeof title !== "string" || !title || Array.from(title).length > 80) {
              return reject(route, 422, "invalid", "schema.invalid", { path: "/title" });
            }
            const draft = {
              ...story,
              id: nextId(story.id, stories.length + 1),
              production_id: id, media_kind: kind, title, board_order: [],
              layouts: { default: {} },
              mix: { line_rms_dbfs: -22, master_lufs: -20, true_peak_dbtp: -3.5 },
            } satisfies Schemas["Story"];
            stories.push(draft);
            return route.fulfill({
              status: 201, headers: { etag: '"1"', location: `/v1/stories/${draft.id}` }, json: draft,
            });
          }
        }
      }
    }
    if (path.startsWith("/v1/stories/")) {
      const [, , , storyId, resource] = path.split("/");
      const draft = stories.find(({ id }) => id === storyId);
      if (!draft || !visible[user].has(draft.production_id)) return reject(route, 404, "not_found", "not_found");
      if (!resource && method === "GET") {
        return route.fulfill({ headers: { etag: `"${draft.revision}"` }, json: viewStory(draft) });
      }
      if (resource === "timing" && method === "GET") {
        return route.fulfill({ json: storyTiming(draft, boards, versions) });
      }
      if (resource === "runs" && method === "GET") {
        if (queue) {
          const items = queue.runs.filter((run) => run.story_id === draft.id).map((run) => queue.view(run));
          return route.fulfill({ json: pageOf(items, cursor) });
        }
        const items = review?.runs.filter((run) => run.story_id === draft.id).map(viewRun) ?? [];
        return route.fulfill({ json: pageOf(items, cursor) });
      }
      if (resource === "runs" && method === "POST" && queue) {
        const key = headers["idempotency-key"];
        const revision = headers["if-match"];
        if (!key || !/^[!-~]{1,255}$/.test(key) || !revision || request.postData() !== null) {
          violations.push("Invalid build request");
          return reject(route, 422, "invalid", "schema.invalid");
        }
        queue.presses.push({ key, revision });
        const repeated = queue.runs.find((run) => run.story_id === draft.id && run.idempotency_key === key);
        if (repeated) return revision !== `"${repeated.snapshot.story_revision}"`
          ? reject(route, 422, "invalid", "idempotency.mismatch")
          : route.fulfill({ status: 200, headers: { etag: `"${repeated.revision}"`, location: `/v1/runs/${repeated.id}` },
            json: queue.view(repeated, true) });
        if (revision !== `"${draft.revision}"`) {
          return reject(route, 409, "conflict", "conflict.revision", { current_revision: draft.revision });
        }
        if (preflight.length) {
          const { rule, message, path, status } = preflight[0];
          return reject(route, 422, status === "unavailable" ? "unavailable" : "invalid", String(rule),
            { message: String(message), path: String(path) });
        }
        const run = queue.add(draft, draft.board_order.map((id) => boards.get(id)!), key);
        const lostReply = dropQueueReply;
        dropQueueReply = undefined;
        if (lostReply === "connection") {
          return route.abort("connectionreset");
        }
        if (lostReply === "server") {
          return reject(route, 500, "internal", "request.failed", { message: "The request could not be completed" });
        }
        return route.fulfill({ status: 201, headers: { etag: '"1"', location: `/v1/runs/${run.id}` }, json: queue.view(run, true) });
      }
      if (resource === "estimate" && method === "GET" && queue) {
        const value: Schemas["EstimateView"] = {
          estimate: queue.estimate, methods: [], problems: preflight,
          queue_wait: { ahead: 0, basis: "Estimated serial lane wait", uncertain: true, wall_s: [0, 0] },
        };
        return route.fulfill({ json: value });
      }
      if (resource === "boards" && method === "POST") {
        const refused = requireRevision(route, draft.revision);
        if (refused) return refused;
        const number = Math.max(0, ...[...boards.values()].filter((board) => board.story_id === storyId).map((board) => board.number)) + 1;
        const requestBody = request.postDataJSON() as BoardCreateBody;
        const board = {
          ...selectedBoard, title: requestBody.title ?? `Board ${number}`, story_id: storyId, number,
          id: nextId(selectedBoard.id, ++lastBoardId), layout: { preset: "default", foreground: true },
        } satisfies Schemas["Board"];
        boards.set(board.id, board);
        setBoardOrder(draft, [...draft.board_order, board.id]);
        return route.fulfill({ status: 201, headers: { etag: '"1"', location: `/v1/boards/${board.id}` }, json: board });
      }
      if (resource === "board-order" && method === "PUT") {
        const { board_order: order } = request.postDataJSON() as Schemas["BoardOrder"];
        const refused = requireRevision(route, draft.revision, order);
        if (refused) return refused;
        if (new Set(order).size !== draft.board_order.length || order.length !== draft.board_order.length ||
          order.some((id) => !draft.board_order.includes(id))) {
          return reject(route, 422, "invalid", "story.board_order");
        }
        setBoardOrder(draft, order);
        return route.fulfill({ headers: { etag: `"${draft.revision}"` }, json: viewStory(draft) });
      }
    }
    if (path.startsWith("/v1/boards/")) {
      const board = boards.get(path.slice("/v1/boards/".length));
      const draft = board && stories.find(({ id }) => id === board.story_id);
      if (!board || !draft || !draft.board_order.includes(board.id) || !visible[user].has(draft.production_id)) {
        return reject(route, 404, "not_found", "not_found");
      }
      if (method === "GET") return route.fulfill({ headers: { etag: `"${board.revision}"` }, json: board });
      if (method === "DELETE") {
        const refused = requireRevision(route, board.revision);
        if (refused) return refused;
        setBoardOrder(draft, draft.board_order.filter((id) => id !== board.id));
        return route.fulfill({ status: 204 });
      }
    }
    if (path === "/v1/assets" && method === "GET") {
      const boardId = url.searchParams.get("board");
      const productionId = url.searchParams.get("production");
      const draft = stories.find(({ board_order }) => boardId && board_order.includes(boardId));
      if (!draft || !visible[user].has(draft.production_id) || (productionId && productionId !== draft.production_id)) {
        return reject(route, 404, "not_found", "not_found");
      }
      return route.fulfill({ json: pageOf(versions.filter((version) => version.scope.board_id === boardId), cursor) });
    }
    if (path.startsWith("/v1/media/") && draftMedia && (method === "GET" || method === "HEAD")) {
      const file = Object.values(draftMedia).find(({ hash }) => path === `/v1/media/${hash}`);
      if (!file || !visible[user].has(production.id)) return reject(route, 404, "not_found", "not_found");
      if (url.search) violations.push("Unexpected query on private media");
      return route.fulfill(mediaResponse(route, file));
    }
    if (path.startsWith("/v1/runs/") && queue) {
      const [, , , id, resource, check, operation] = path.split("/");
      const run = queue.runs.find((item) => item.id === id);
      const draft = run && stories.find((item) => item.id === run.story_id);
      if (!run || !draft || !visible[user].has(draft.production_id)) return reject(route, 404, "not_found", "not_found");
      const etag = () => `"${run.revision}"`;
      if (!resource && method === "GET") return route.fulfill({ headers: { etag: etag() }, json: queue.view(run, true) });
      if (resource === "delivery" && method === "GET") {
        const delivery = queue.deliveries.get(id);
        return delivery ? route.fulfill({ json: delivery }) : reject(route, 404, "not_found", "not_found");
      }
      if (method === "POST" && (resource === "cancel" || (resource === "checks" && operation === "overrides"))) {
        const revision = headers["if-match"];
        if (!revision) {
          violations.push(`Missing If-Match on ${method} ${path}`);
          return reject(route, 422, "invalid", "schema.invalid");
        }
        if (revision !== etag()) return reject(route, 409, "conflict", "conflict.revision", { current_revision: run.revision });
        if (resource === "cancel") {
          queue.cancelWrites.push({ id, revision });
          if (run.wan_attempts?.some(({ state }) => state === "sent")) {
            run.cancel_requested = true;
            run.revision += 1;
          } else if (!run.cancel_requested) {
            queue.advance(id, "cancelled", "Cancelled by a Studio user", {
              cancel_requested: true, progress: { percent: 100, stage: "cancelled" },
            });
          }
          return route.fulfill({ headers: { etag: etag() }, json: queue.view(run, true) });
        }
        const body = request.postDataJSON() as Schemas["CheckOverride"];
        queue.overrideWrites.push({ id, revision, body });
        if (check !== "layered.decal_gate") return reject(route, 403, "forbidden", "check.not_overridable");
        if (!body.reason?.trim() || !/^[0-9a-f]{64}$/.test(body.artifact)) return reject(route, 422, "invalid", "schema.invalid");
        if (run.check_overrides?.some(({ artifact }) => artifact === body.artifact)) {
          return reject(route, 409, "conflict", "check.override_exists");
        }
        if ((run.status !== "succeeded" && run.status !== "failed") ||
            !run.checks?.some((item) => item.check === check && item.result === "fail" && item.artifact === body.artifact)) {
          return reject(route, 409, "conflict", "check.not_overridable");
        }
        const record: Schemas["CheckOverrideView"] = { ...body, check, by: run.queued_by, at: run.queued_at };
        run.check_overrides?.push(record);
        run.revision += 1;
        return route.fulfill({ status: 201, json: record });
      }
    }
    if (path.startsWith("/v1/runs/") && review) {
      const [, , , id, resource] = path.split("/");
      const run = review.runs.find((item) => item.id === id);
      if (!run || !visible[user].has(production.id)) return reject(route, 404, "not_found", "not_found");
      if (!resource && method === "GET") return route.fulfill({ headers: { etag: `"${run.revision}"` }, json: viewRun(run) });
      if (resource === "delivery" && method === "GET") {
        const delivery = review.deliveries.get(id);
        return delivery ? route.fulfill({ json: delivery }) : reject(route, 404, "not_found", "not_found");
      }
      if (resource === "go-live-approvals") {
        const refusal = identityRefusal(user);
        const preview = review.preview(run, refusal, runRefusal);
        if (method === "GET") return reviewAvailable
          ? route.fulfill({ json: preview })
          : reject(route, 405, "invalid", "method.not_allowed");
        if (method === "POST") {
          const body = request.postDataJSON() as Schemas["ApprovalWrite"];
          approvalWrites.push({ run: id, body });
          if (refusal) return reject(route, 403, "forbidden", refusal);
          if (!preview.approve.allowed) return reject(route, 422, "invalid", preview.approve.code);
          if (body.master_sha256 !== preview.master_sha256) return reject(route, 422, "invalid", "approval.not_exact_run");
          if (!body.platform_setting) return reject(route, 422, "invalid", "approval.ai_label_missing");
          return route.fulfill({ status: 201, json: review.approve(run, preview) });
        }
      }
    }
    if (path.startsWith("/v1/go-live-approvals/") && path.endsWith("/withdraw") && review && method === "POST") {
      const refusal = identityRefusal(user);
      if (refusal) return reject(route, 403, "forbidden", refusal);
      const approval = review.approvals.find(({ id }) => path === `/v1/go-live-approvals/${id}/withdraw`);
      if (!approval) return reject(route, 404, "not_found", "not_found");
      if (approval.derived.state === "withdrawn") return reject(route, 409, "conflict", "approval.already_withdrawn");
      return route.fulfill({ status: 201, json: review.withdraw(approval) });
    }
    violations.push(`Unexpected API operation ${method} ${path}`);
    return reject(route, 404, "not_found", "not_found");
  });

  return {
    calls, violations, writes, selections, loginRequests, approvalWrites, boardWrites, queue,
    expire: () => { current = null; },
    signInAs: (user: User) => { next = user; },
    requireFreshSignIn: () => { freshRequired = true; },
    disableApprovals: () => { configured = false; },
    disableApprovalRead: () => { reviewAvailable = false; },
    refuseRun: (code: string) => { runRefusal = code; },
    recordManualPublication: () => { stories[0].published = true; },
    editDraft: () => { stories[0].revision += 1; firstBoard.lines[0].text = "New draft line."; },
    setDraftOrder: (order: string[]) => setBoardOrder(stories[0], order),
    editDraftBoard: (id: string, fields: Partial<Schemas["Board"]>) => {
      const current = boards.get(id)!;
      boards.set(id, { ...current, ...fields, revision: current.revision + 1 });
      stories[0].revision += 1;
    },
    dropNextQueueReply: (mode: "connection" | "server") => { dropQueueReply = mode; },
    preflightProblems: (problems: Schemas["EstimateView"]["problems"]) => { preflight = problems; },
    failNext: (value: Failure) => { failure = value; },
    enableMedia,
  };
}
