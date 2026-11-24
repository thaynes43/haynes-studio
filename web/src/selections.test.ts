import { expect, test, vi } from "vitest";
import { createStudioApi } from "./api/client";
import type { components } from "./api/schema";
import { createSelections } from "./selections";
import { treePath } from "./routes";

const production = "prd_01M79V9FC00000000000000001";
const origin = "https://studio.example.invalid";

test("retries a stale revision and serializes changes without replacing other preferences", async () => {
  type Schemas = components["schemas"];
  const vars = {
    server: { revision: 2, values: { editor_inspector: { open: true }, web_shell: { future: true } } } as Schemas["Selections"],
    writes: [] as Array<{ etag: string | null; values: Schemas["SelectionWrite"]["values"] }>,
  };
  const send: typeof fetch = async (input) => {
    const request = input as Request;
    if (request.url.endsWith("/me")) {
      return Response.json({
        principal: { kind: "human", iss: "https://identity.example.invalid", sub: "example-user" },
        csrf_token: "test-csrf",
      } satisfies Schemas["Me"]);
    }
    if (request.method === "GET") {
      return Response.json(vars.server, { headers: { etag: `"${vars.server.revision}"` } });
    }
    const { values } = await request.json() as Schemas["SelectionWrite"];
    const etag = request.headers.get("If-Match");
    vars.writes.push({ etag, values });
    if (etag !== `"${vars.server.revision}"`) {
      return Response.json({
        error: {
          code: "conflict.revision", status: "conflict", http_status: 409,
          message: "Revision changed", path: "/revision", request_id: "mock-409",
          current_revision: vars.server.revision,
        },
      } satisfies Schemas["ErrorEnvelope"], { status: 409 });
    }
    vars.server = { revision: vars.server.revision + 1, values };
    return Response.json(vars.server, { headers: { etag: `"${vars.server.revision}"` } });
  };
  const api = createStudioApi(origin, new AbortController().signal, vi.fn(), send);
  await api.connect();
  const selections = createSelections(api.client, { etag: '"1"', values: {} });
  const reviewed = treePath("productions", { production });
  const selected = treePath("board", { production, media: "short" });

  selections.remember("productions", reviewed);
  selections.remember("board", selected);
  expect(selections.snapshot().destinations).toMatchObject({ productions: reviewed, board: selected });

  await vi.waitFor(() => expect(vars.server.revision).toBe(4));
  expect(vars.writes.map(({ etag }) => etag)).toEqual(['"1"', '"2"', '"3"']);
  expect(vars.server.values).toEqual({
    editor_inspector: { open: true },
    web_shell: { future: true, productions: reviewed, board: selected },
  });
  expect(selections.snapshot().error).toBeUndefined();
});
