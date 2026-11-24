import type { BrowserContext, Route } from "@playwright/test";
import type { components } from "../src/api/schema";
import { treePath } from "../src/routes";

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
  lena: { displayName: "Lena Park", production },
  arden: { displayName: "Arden Rivera", production: secondProduction },
};

type User = keyof typeof people;
type Selection = Schemas["Selections"];
type Failure = { path: string; status: number; detail: Schemas["ErrorDetail"] };

export async function mockStudio(context: BrowserContext, baseURL: string) {
  let current: User | null = "lena";
  let next: User = "lena";
  let failure: Failure | undefined;
  const violations: string[] = [];
  const calls: string[] = [];
  const writes: Array<{ user: User; values: Selection["values"]; revision: number }> = [];
  const selections: Record<User, Selection> = {
    lena: { revision: 0, values: {} },
    arden: { revision: 0, values: {
      web_shell: { productions: treePath("productions", { production: secondProduction.id }) },
    } },
  };

  function reject(
    route: Route, status: number, category: Schemas["ErrorDetail"]["status"], code: string,
  ) {
    const error: Schemas["ErrorEnvelope"] = {
      error: {
        status: category, http_status: status, path: "",
        message: code, code, request_id: `mock-request-${status}`,
      },
    };
    return route.fulfill({ status, json: error });
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
      await route.fulfill({ status: 303, headers: { location: "/" } });
      return;
    }
    const user = current;
    if (!user) return reject(route, 401, "unauthenticated", "auth.required");
    if (method !== "GET" && headers["x-studio-csrf"] !== `test-csrf-${user}`) {
      violations.push(`Missing session CSRF header on ${method} ${path}`);
      return reject(route, 403, "forbidden", "auth.csrf");
    }

    if (failure?.path === path) {
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

    const available = people[user].production;
    if (path === "/v1/productions" && method === "GET") {
      const cursor = url.searchParams.get("cursor");
      const next_cursor = !cursor && user === "lena" ? available.id : null;
      const items = cursor === available.id && user === "lena" ? [secondProduction] : [available];
      await route.fulfill({ json: { items, next_cursor } satisfies Schemas["Page_Production_"] });
      return;
    }
    if (path.startsWith("/v1/productions/") && method === "GET") {
      const [, , , id, types, kind, list] = path.split("/");
      if (id !== available.id && (user !== "lena" || id !== secondProduction.id)) {
        return reject(route, 404, "not_found", "not_found");
      }
      if (!types) {
        await route.fulfill({ json: id === production.id ? production : secondProduction });
        return;
      }
      if (types === "media-types" && kind === "short" && list === "stories") {
        const items = id === production.id ? [story] : [];
        await route.fulfill({ json: { items, next_cursor: null } satisfies Schemas["Page_Story_"] });
        return;
      }
    }
    if (path === `/v1/stories/${story.id}` && method === "GET") {
      if (user !== "lena") return reject(route, 404, "not_found", "not_found");
      await route.fulfill({ json: story });
      return;
    }
    if (path === `/v1/boards/${selectedBoard.id}` && method === "GET") {
      if (user !== "lena") return reject(route, 404, "not_found", "not_found");
      await route.fulfill({ json: selectedBoard });
      return;
    }
    violations.push(`Unexpected API operation ${method} ${path}`);
    return reject(route, 404, "not_found", "not_found");
  });

  return {
    calls, violations, writes, selections,
    expire: () => { current = null; },
    signInAs: (user: User) => { next = user; },
    failNext: (value: Failure) => { failure = value; },
  };
}
