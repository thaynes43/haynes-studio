import type { Approval, ApprovalReview, ReleaseChecks } from "../src/approval-review-contract";
import type { components } from "../src/api/schema";
import type { ReviewMedia } from "./studio-review-media";

type Schemas = components["schemas"];
export const oldRun = "run_01M79V9FC00000000000000001";
export const latestRun = "run_01M79V9FC00000000000000002";
export const importedRun = "run_01M79V9FC00000000000000003";
export const runningRun = "run_01M79V9FC00000000000000004";
export const photoVersion = "asv_01M79V9FC00000000000000001";
export const voiceVersion = "asv_01M79V9FC00000000000000002";
export const description = "This video was AI-generated.\nVideo: Local video model\nVoice: Local voice model";
const approvedAt = "2026-11-04T14:00:00Z";
const frozenAt = "2026-11-04T12:00:00Z";
const principal = { kind: "human", iss: "https://identity.example.invalid", sub: "lena" } as const;
const allowed = { allowed: true } as const;
const refused = (code: string) => ({ allowed: false, code }) as const;

export function reviewFixtures(story: Schemas["Story"], media: ReviewMedia) {
  const delivery = {
    schema: "studio.delivery/v1", created_at: frozenAt, run_id: oldRun,
    id: "dlv_01M79V9FC00000000000000001", legacy: null,
    master: {
      audio_codec: "aac", video_codec: "h264", media_type: "video/mp4", fps: 24, frames: 12,
      width: 96, height: 144, sha256: media.master.hash, bytes: media.master.body.length,
      locator: "blobs/" + media.master.hash, legacy_path: null,
    },
    proxy: { sha256: media.proxy.hash, width: 64, height: 96, bytes: media.proxy.body.length },
    store: { adapter: "local", writable: true },
    verification: { sha256_verified: true, expected_frames: 12, decoded_frames: 12 },
  } satisfies Omit<Schemas["Delivery"], "proxy"> & { proxy: { sha256: string; width: number; height: number; bytes: number } };
  const baseRun = {
    schema: "studio.run/v1", id: oldRun, number: 1, story_id: story.id, status: "succeeded",
    active_approval_id: null,
    queued_at: frozenAt, queued_by: principal, finished_at: "2026-11-04T12:10:00Z",
    snapshot: { story_revision: 1, board_count: 2, sha256: "1".repeat(64), locator: "frozen" },
    delivery_id: delivery.id, checks: [{ check: "audio.loudness", result: "pass" }],
    revision: 1, cancel_requested: false, estimate_methods: [], idempotency_key: null, legacy: null,
    outputs: null, progress: { percent: 100, stage: "delivered" }, provenance: null, queue_wait: null,
    stages: story.board_order.map((id, index) => ({
      board_id: id, board_number: index === 0 ? 12 : 7,
      checks: [{ check: "layered.decal_gate", artifact: "segment", result: "pass" as const, slot: "a" }],
      clips: [], film_start_frame: index * 6, frames: 6,
      method: { layer: "layered" as const, motion: "s2v" as const }, segment_sha256: null,
    })), wait_reason: null,
  } satisfies Schemas["RunView"];
  const deliveries = new Map([
    [oldRun, delivery],
    [latestRun, {
      ...delivery, run_id: latestRun, id: "dlv_01M79V9FC00000000000000002",
    }],
    [importedRun, {
      ...delivery, run_id: importedRun, id: "dlv_01M79V9FC00000000000000003",
      master: { ...delivery.master, locator: null, legacy_path: "legacy/master.mp4" },
      proxy: null,
      store: { adapter: "legacy_wan_ledger", writable: false },
    }],
  ] as [string, Omit<Schemas["Delivery"], "proxy"> & { proxy: typeof delivery.proxy | null }][]);
  deliveries.set(oldRun, { ...delivery, master: {
    ...delivery.master, width: 80, height: 120, sha256: media.olderMaster.hash,
    locator: "blobs/" + media.olderMaster.hash, bytes: media.olderMaster.body.length,
  } });
  const runs: Schemas["RunView"][] = [
    baseRun,
    { ...baseRun, id: latestRun, number: 2, delivery_id: deliveries.get(latestRun)!.id,
      queued_at: "2026-11-04T12:11:00Z", finished_at: "2026-11-04T12:21:00Z",
      snapshot: { ...baseRun.snapshot, sha256: "2".repeat(64) } },
    { ...baseRun, id: importedRun, number: 3, status: "imported", delivery_id: deliveries.get(importedRun)!.id,
      queued_at: "2026-11-04T12:22:00Z", finished_at: null },
    { ...baseRun, id: runningRun, number: 4, status: "running", delivery_id: null,
      queued_at: "2026-11-04T12:23:00Z", finished_at: null, checks: null },
  ];
  const approvals: Approval[] = [];

  function history(id: string) {
    return approvals.filter((record) => record.run_id === id).toReversed();
  }

  function preview(run: Schemas["RunView"], identityRefusal?: string, runRefusal?: string): ApprovalReview {
    const delivered = deliveries.get(run.id);
    const releaseRefusal = runRefusal ?? (run.status === "imported" ? "approval.legacy_run" : undefined);
    const master = delivered?.master.sha256 ?? null;
    const records = history(run.id);
    const active = records.some((record) => record.derived.state === "active");
    const checks: ReleaseChecks | null = delivered && !releaseRefusal ? {
      delivery: { result: "pass", delivery_id: delivered.id, master_sha256: master, verification: delivered.verification },
      licences: { result: "pass", rows: [{ engine_key: "video-local", state: "unknown" }] },
      ai_label: { result: "pass", platform_setting: true, description_line: true, description },
    } : releaseRefusal === "approval.licence_missing" ? {
      licences: { result: "fail", rows: [{ engine_key: "video-local", state: "missing" }] },
    } : null;
    const refusal = identityRefusal ?? releaseRefusal;
    return {
      run_id: run.id, master_sha256: master,
      approve: refusal ? refused(refusal) : active ? refused("approval.already_active") : allowed,
      withdraw: identityRefusal ? refused(identityRefusal) : active ? allowed : refused("approval.already_withdrawn"),
      release_checks: checks, approvals: records,
    };
  }

  function approve(run: Schemas["RunView"], evidence: ApprovalReview) {
    const record: Approval = {
      schema: "studio.go-live-approval/v1", id: "apr_01M79V9FC0000000000000000" + (approvals.length + 1),
      run_id: run.id, run_snapshot_sha256: run.snapshot.sha256, delivery_id: run.delivery_id!,
      master_sha256: evidence.master_sha256!, approver: principal, approver_display_name: "Lena Park",
      auth_time: frozenAt, approved_at: approvedAt, release_checks: evidence.release_checks!,
      derived: { state: "active", publication_ids: [], withdrawal: null },
    };
    approvals.push(record);
    return record;
  }

  function withdraw(approval: Approval) {
    approval.derived = {
      ...approval.derived, state: "withdrawn", withdrawal: { withdrawn_at: "2026-11-04T14:03:00Z" },
    };
    return approval;
  }

  return { approvals, deliveries, history, runs, preview, approve, withdraw };
}
