import { ApiError, type StudioClient } from "./api/client";
import type { components } from "./api/schema";
import { readObject, type RunView } from "./production-review-data";

export type { RunView };

export function activeRun(run: Pick<RunView, "status">) {
  return run.status === "queued" || run.status === "running" || run.status === "held";
}

export const visualCheck = "layered.decal_gate";
export const visibilityCheck = "occlusion.visibility";

export function canOverride(run: RunView, check: components["schemas"]["RunView_check"]) {
  return (run.status === "failed" || run.status === "succeeded") && run.check_overrides !== undefined &&
    (check.check === visualCheck ||
      (check.check === visibilityCheck && readObject(check.actual).result === "uncertain")) &&
    check.result === "fail" && typeof check.artifact === "string" &&
    /^[a-f0-9]{64}$/.test(check.artifact) && !run.check_overrides.some(({ artifact }) => artifact === check.artifact);
}

export type BuildPress = {
  key: string;
  revision: number;
  boardOrder: readonly string[];
};

export function buildPress(revision: number, boardOrder: readonly string[], key: string = crypto.randomUUID()): BuildPress {
  return { key, revision, boardOrder: [...boardOrder] };
}

export async function queueBuild(api: StudioClient, id: string, press: BuildPress, signal: AbortSignal) {
  await api.POST("/v1/stories/{id}/runs", {
    signal, params: { path: { id }, header: { "If-Match": `"${press.revision}"`, "Idempotency-Key": press.key } },
  });
}

export async function runDetail(api: StudioClient, story: string, id: string, signal: AbortSignal) {
  const { data: run, response } = await api.GET("/v1/runs/{id}", { signal, params: { path: { id } } });
  if (!run || run.id !== id || run.story_id !== story) throw new ApiError(404);
  const etag = response.headers.get("ETag");
  return { run, etag: etag === `"${run.revision}"` ? etag : undefined };
}

export async function cancelRun(api: StudioClient, run: RunView, signal: AbortSignal) {
  const current = await runDetail(api, run.story_id, run.id, signal);
  if (!activeRun(current.run) || current.run.cancel_requested) return current.run;
  if (!current.etag) throw new ApiError(500);
  const { data } = await api.POST("/v1/runs/{id}/cancel", {
    signal, params: { path: { id: run.id }, header: { "If-Match": current.etag } },
  });
  if (!data || data.id !== run.id || data.story_id !== run.story_id) throw new ApiError(500);
  return data;
}

export type RunProblem = { code?: string; message?: string; board?: string; field?: string };

function fieldText(value: unknown) {
  return typeof value === "string" && value ? value : undefined;
}

export function runProblem(raw: unknown, boardOrder: readonly string[] = []): RunProblem {
  const { code, rule, message, board_id, board_number, field, path } = readObject(raw);
  const pointer = fieldText(path);
  const boardPath = pointer && /^\/boards\/(\d+)(\/.*)?$/.exec(pointer);
  const id = fieldText(board_id) ?? (boardPath ? boardOrder[Number(boardPath[1])] : undefined);
  return {
    code: fieldText(code) ?? fieldText(rule),
    message: fieldText(message),
    board: id ?? (typeof board_number === "number" ? `B${String(board_number).padStart(2, "0")}` : undefined),
    field: fieldText(field) ?? (boardPath ? boardPath[2] : pointer),
  };
}

export function runProblems(value: unknown, order?: readonly string[]) {
  return Array.isArray(value) ? value.map((entry) => runProblem(entry, order))
    .filter(({ code, message }) => code || message) : [];
}

export async function readPreflight(api: StudioClient, id: string, press: BuildPress, signal: AbortSignal) {
  const params = { path: { id } };
  const currentRevision = async () => {
    const { data } = await api.GET("/v1/stories/{id}", { signal, params });
    return data?.id === id ? data.revision : undefined;
  };
  // Estimates have no revision field. Both reads must agree with the attempted revision.
  if (await currentRevision() !== press.revision) return [];
  const { data } = await api.GET("/v1/stories/{id}/estimate", { signal, params });
  if (await currentRevision() !== press.revision) return [];
  return runProblems(data?.problems, press.boardOrder);
}

export function retryableRead(error: unknown) {
  return !(error instanceof ApiError) || error.status === 0 || error.status >= 500;
}
