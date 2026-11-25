import { ApiError, type StudioClient } from "./api/client";
import type { components } from "./api/schema";
import type { ApprovalReview, ReleaseChecks } from "./approval-review-contract";
import { collectPages } from "./route-data";

export type Run = Pick<components["schemas"]["RunView"],
  "id" | "story_id" | "number" | "status" | "queued_at" | "snapshot" | "delivery_id" |
  "active_approval_id" | "checks" | "stages" | "answers"> &
  Partial<Pick<components["schemas"]["RunView"], "legacy">>;
export type Delivery = components["schemas"]["Delivery"];

export const runStates: Record<Run["status"], string> = {
  queued: "Queued", running: "Running", succeeded: "Finished", failed: "Failed",
  cancelled: "Cancelled", held: "Held", imported: "Imported",
};

export function newestRuns<T extends Run>(runs: T[]) {
  return runs.toSorted((left, right) => right.number - left.number);
}

export function hasDelivery(run: Run) {
  return run.status === "succeeded" || run.status === "imported";
}

function readRunPage(api: StudioClient, story: string, signal: AbortSignal, cursor?: string) {
  return api.GET("/v1/stories/{id}/runs", {
    signal, params: { path: { id: story }, query: { cursor } },
  }).then(({ data }) => data);
}

export type RunView = NonNullable<Awaited<ReturnType<typeof readRunPage>>>["items"][number];

export async function loadRuns(api: StudioClient, story: string, signal: AbortSignal) {
  const runs = await collectPages<RunView>((cursor) => readRunPage(api, story, signal, cursor));
  if (runs.some((run) => run.story_id !== story)) throw new ApiError(404);
  return newestRuns(runs);
}

export async function loadDelivery(api: StudioClient, run: Pick<Run, "id" | "delivery_id">, signal: AbortSignal) {
  const { data } = await api.GET("/v1/runs/{id}/delivery", {
    signal, params: { path: { id: run.id } },
  });
  if (!data || data.run_id !== run.id || (run.delivery_id && data.id !== run.delivery_id)) {
    throw new ApiError(422, "approval.delivery_mismatch");
  }
  return data;
}

export function mediaUrl(hash: unknown) {
  return typeof hash === "string" && /^[0-9a-f]{64}$/.test(hash) ? "/v1/media/" + hash : undefined;
}

export function readObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
}

export function releaseDescription(checks: ReleaseChecks | null) {
  const label = readObject(checks?.ai_label);
  return typeof label.description === "string" ? label.description : undefined;
}

export function releaseChecksPass(checks: ReleaseChecks | null, master: string, delivery: string) {
  const verified = readObject(checks?.delivery);
  const label = readObject(checks?.ai_label);
  return verified.result === "pass" && verified.master_sha256 === master && verified.delivery_id === delivery &&
    readObject(checks?.licences).result === "pass" && label.result === "pass" &&
    label.platform_setting === true && label.description_line === true && Boolean(releaseDescription(checks));
}

export async function loadApprovalReview(
  api: StudioClient, run: Run, delivery: Delivery | undefined, signal: AbortSignal,
) {
  const { data } = await api.GET("/v1/runs/{id}/go-live-approvals", {
    signal, params: { path: { id: run.id } },
  });
  if (data?.run_id !== run.id || typeof data.approve?.allowed !== "boolean" ||
      typeof data.withdraw?.allowed !== "boolean" || !Array.isArray(data.approvals)) {
    throw new ApiError(503, "approval.review_unavailable");
  }
  if (data.approve.allowed && (run.status !== "succeeded" || !delivery || run.delivery_id !== delivery.id ||
      delivery.store.adapter === "legacy_wan_ledger" ||
      data.master_sha256 !== delivery.master.sha256 ||
      !mediaUrl(data.master_sha256) || !releaseChecksPass(data.release_checks, data.master_sha256, delivery.id))) {
    throw new ApiError(422, "approval.review_mismatch");
  }
  const active = data.approvals.filter((approval) => approval?.derived?.state === "active");
  if (active.length > 1 || (data.withdraw.allowed && !active.length) || (data.approve.allowed && active.length) ||
      data.approvals.some((approval) => approval?.run_id !== run.id ||
        approval.run_snapshot_sha256 !== run.snapshot.sha256 ||
        approval.delivery_id !== run.delivery_id || !mediaUrl(approval.master_sha256) ||
        (delivery && approval.master_sha256 !== delivery.master.sha256) ||
        (approval.derived?.state !== "active" && approval.derived?.state !== "withdrawn") ||
        typeof approval.id !== "string" || !/^apr_[0-7][0-9A-HJKMNP-TV-Z]{25}$/.test(approval.id))) {
    throw new ApiError(422, "approval.review_mismatch");
  }
  return data satisfies ApprovalReview;
}

export const freshSignIn = (returnTo: string) =>
  "/auth/login?" + new URLSearchParams({ fresh: "true", return_to: returnTo });
