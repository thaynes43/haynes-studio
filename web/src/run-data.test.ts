import { afterEach, expect, it, vi } from "vitest";

import { createStudioApi } from "./api/client";
import { buildPress, queueBuild, runProblem } from "./run-data";

afterEach(() => vi.useRealTimers());

it("replays one press with its original key and revision after an ambiguous reply", async () => {
  vi.useFakeTimers();
  const lifetime = new AbortController();
  const origin = "https://studio.example.invalid";
  const writes: { key: string | null; revision: string | null }[] = [];
  const accepted = new Set<string | null>();
  const send = vi.fn<typeof fetch>(async (input) => {
    const request = input as Request;
    if (request.method === "GET") return Response.json({
      display_name: "Test operator", principal: { kind: "human", iss: origin, sub: "person" }, csrf_token: "test",
    });
    const key = request.headers.get("Idempotency-Key");
    writes.push({ key, revision: request.headers.get("If-Match") });
    if (accepted.has(key)) return Response.json({ id: "same-run" });
    accepted.add(key);
    if (writes.length === 1) {
      await new Promise((resolve) => setTimeout(resolve, 100));
      throw new TypeError("lost response after acceptance");
    }
    return Response.json({ id: "next-run" }, { status: 201 });
  });
  const api = createStudioApi(origin, lifetime.signal, () => {}, send);
  await api.connect();

  const boardOrder = ["first", "second"];
  const press = buildPress(4, boardOrder);
  const failed = expect(queueBuild(api.client, "story", press, lifetime.signal)).rejects.toMatchObject({ status: 0 });
  await vi.advanceTimersByTimeAsync(100);
  await failed;
  boardOrder.reverse();
  await queueBuild(api.client, "story", press, lifetime.signal);
  const next = buildPress(5, boardOrder);
  await queueBuild(api.client, "story", next, lifetime.signal);

  expect(writes).toEqual([
    { key: press.key, revision: '"4"' }, { key: press.key, revision: '"4"' }, { key: next.key, revision: '"5"' },
  ]);
  expect(accepted.size).toBe(2);
  expect(press.boardOrder).toEqual(["first", "second"]);
  expect(runProblem({ code: "voice.absent", path: "/boards/1/voice", message: "Missing voice" }, press.boardOrder))
    .toEqual({ code: "voice.absent", board: "second", field: "/voice", message: "Missing voice" });
});
