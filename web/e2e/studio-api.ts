import type { BrowserContext, Route } from "@playwright/test";
import type { components } from "../src/api/schema";
import { treePath, type MediaKind } from "../src/routes";
import { latestRun, photoVersion, reviewFixtures, voiceVersion } from "./studio-review-fixtures";
import { mediaResponse, type ReviewMedia } from "./studio-review-media";

type Schemas = components["schemas"];

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
  empty = false, reviewMedia,
}: { empty?: boolean; reviewMedia?: ReviewMedia } = {}) {
  let current: User | null = "lena";
  let next: User = "lena";
  let failure: Failure | undefined;
  let configured = true;
  let reviewAvailable = true;
  let freshRequired = false;
  let runRefusal: string | undefined;
  const review = reviewMedia && reviewFixtures(story, reviewMedia);
  const loginRequests: URLSearchParams[] = [];
  const approvalWrites: Array<{ run: string; body: Schemas["ApprovalWrite"] }> = [];
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
    lines: [{ id: "lin_01M79V9FC00000000000000001", text: "The soup can hear you.", speaker: "narrator", gap_before_ms: 0 }],
    method: { layer: "layered", motion: "s2v" },
    notes: [{ id: "nte_01M79V9FC00000000000000001", text: "Offscreen crunch" }],
    photo: { ...selectedBoard.photo, current_version_id: review ? photoVersion : null },
    voice: { current_version_id: review ? voiceVersion : null, style: "narrator" },
  };
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
    if (path.endsWith("/runs") && path.startsWith("/v1/stories/") && method === "GET") {
      const draft = stories.find(({ id }) => path === `/v1/stories/${id}/runs`);
      if (!draft || !visible[user].has(draft.production_id)) return reject(route, 404, "not_found", "not_found");
      const items = review?.runs.filter((run) => run.story_id === draft.id).map(viewRun) ?? [];
      return route.fulfill({ json: pageOf(items, cursor) });
    }
    if (path.startsWith("/v1/stories/") && method === "GET") {
      const draft = stories.find(({ id }) => path === `/v1/stories/${id}`);
      if (!draft || !visible[user].has(draft.production_id)) return reject(route, 404, "not_found", "not_found");
      return route.fulfill({ headers: { etag: `"${draft.revision}"` }, json: viewStory(draft) });
    }
    const board = [firstBoard, selectedBoard].find(({ id }) => path === `/v1/boards/${id}`);
    if (board && method === "GET") {
      if (!visible[user].has(production.id)) return reject(route, 404, "not_found", "not_found");
      return route.fulfill({ json: board });
    }
    if (path === "/v1/assets" && method === "GET" && reviewMedia && url.searchParams.get("board") === firstBoard.id) {
      if (!visible[user].has(production.id)) return reject(route, 404, "not_found", "not_found");
      return route.fulfill({ json: pageOf([
        { id: photoVersion, kind: "photo", content: { sha256: reviewMedia.photo.hash } },
        { id: voiceVersion, kind: "board_voice", voice: { track: { sha256: reviewMedia.voice.hash } } },
      ], cursor) });
    }
    if (path.startsWith("/v1/media/") && reviewMedia && (method === "GET" || method === "HEAD")) {
      const file = Object.values(reviewMedia).find(({ hash }) => path === `/v1/media/${hash}`);
      if (!file || !visible[user].has(production.id)) return reject(route, 404, "not_found", "not_found");
      if (url.search) violations.push("Unexpected query on private media");
      return route.fulfill(mediaResponse(route, file));
    }
    if (path.startsWith("/v1/runs/") && review) {
      const [, , , id, resource] = path.split("/");
      const run = review.runs.find((item) => item.id === id);
      if (!run || !visible[user].has(production.id)) return reject(route, 404, "not_found", "not_found");
      if (!resource && method === "GET") return route.fulfill({ json: viewRun(run) });
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
    calls, violations, writes, selections, loginRequests, approvalWrites,
    expire: () => { current = null; },
    signInAs: (user: User) => { next = user; },
    requireFreshSignIn: () => { freshRequired = true; },
    disableApprovals: () => { configured = false; },
    disableApprovalRead: () => { reviewAvailable = false; },
    refuseRun: (code: string) => { runRefusal = code; },
    recordManualPublication: () => { stories[0].published = true; },
    editDraft: () => { stories[0].revision += 1; firstBoard.lines[0].text = "New draft line."; },
    failNext: (value: Failure) => { failure = value; },
    enableMedia,
  };
}
