import { expect, test, vi } from "vitest";
import { createStudioApi } from "./client";
import type { components } from "./schema";

const origin = "https://studio.example.invalid";
const me: components["schemas"]["Me"] = {
  principal: { kind: "human", iss: "https://identity.example.invalid", sub: "example-user" },
  display_name: "Example Editor",
  csrf_token: "test-csrf",
};

test("uses same-origin cookie credentials and attaches CSRF only on writes", async () => {
  const send = vi.fn<typeof fetch>().mockImplementation(async (input) => {
    const request = input as Request;
    if (request.url === origin + "/v1/me") return Response.json(me);
    return new Response(null, { status: 204 });
  });
  const unauthorized = vi.fn();
  const api = createStudioApi(origin, new AbortController().signal, unauthorized, send);
  await expect(api.signOut()).rejects.toMatchObject({ status: 403 });
  expect(send).not.toHaveBeenCalled();

  await expect(api.connect()).resolves.toEqual({ displayName: "Example Editor" });
  await expect(api.client.POST("/auth/logout", { baseUrl: "https://other.example.invalid" }))
    .rejects.toMatchObject({ status: 403, code: "auth.origin" });
  await api.signOut();

  const [read, write] = send.mock.calls.map(([request]) => request as Request);
  expect(read.credentials).toBe("same-origin");
  expect(read.cache).toBe("no-store");
  expect(read.headers.has("X-Studio-CSRF")).toBe(false);
  expect(write.url).toBe(origin + "/auth/logout");
  expect(write.headers.get("X-Studio-CSRF")).toBe("test-csrf");
  expect(write.headers.has("Authorization")).toBe(false);
  expect(write.redirect).toBe("error");
  expect(unauthorized).not.toHaveBeenCalled();
});

test("reports 401 from a write and discards the session CSRF value", async () => {
  const unauthorized = vi.fn();
  const send = vi.fn<typeof fetch>()
    .mockResolvedValueOnce(Response.json(me))
    .mockResolvedValueOnce(new Response("Unauthorized", { status: 401 }));
  const api = createStudioApi(origin, new AbortController().signal, unauthorized, send);
  await api.connect();
  await expect(api.signOut()).rejects.toMatchObject({ status: 401 });
  expect(unauthorized).toHaveBeenCalledOnce();
  await expect(api.signOut()).rejects.toMatchObject({ status: 403 });
  expect(send).toHaveBeenCalledTimes(2);
});

test("handles non-JSON error responses and fails closed for a non-human principal", async () => {
  const unauthorized = vi.fn();
  const send = vi.fn<typeof fetch>()
    .mockResolvedValueOnce(new Response("<html>Error</html>", { status: 502 }))
    .mockResolvedValueOnce(Response.json({ ...me, principal: { kind: "agent" } }));
  const api = createStudioApi(origin, new AbortController().signal, unauthorized, send);
  await expect(api.connect()).rejects.toMatchObject({ status: 502 });
  await expect(api.connect()).rejects.toMatchObject({ status: 403, code: "auth.human_required" });
  expect(unauthorized).not.toHaveBeenCalled();
});
