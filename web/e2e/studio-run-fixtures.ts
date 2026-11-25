import { createHash } from "node:crypto";

import type { components } from "../src/api/schema";
import { reviewFixtures } from "./studio-review-fixtures";
import type { ReviewMedia } from "./studio-review-media";

type Schemas = components["schemas"];
type RunError = {
  code: string; message: string; stage: string | null; board_id: string | null; board_number: number | null;
};
type FixtureRun = Omit<Schemas["RunView"], "error" | "outputs" | "provenance"> & {
  error: RunError | null;
  outputs: Schemas["RunView_outputs"] | null;
  provenance: Schemas["RunView_provenance"] | null;
};
type Status = Exclude<FixtureRun["status"], "imported">;

const timestamp = (second: number) => new Date(Date.UTC(2026, 10, 4, 12, 0, second)).toISOString();
const actor = { kind: "human", iss: "https://identity.example.invalid", sub: "lena" } as const;
const estimate = {
  basis: "Fixture wall-time range", uncertain: true, cpu_wall_s: [5, 15], gpu_wall_s: [90, 210],
} satisfies Schemas["EstimateRange"];

export function runFixtures(story: Schemas["Story"], media: ReviewMedia) {
  const fixtures = reviewFixtures(story, media);
  const runs: FixtureRun[] = [];
  const deliveries = new Map<string, NonNullable<ReturnType<typeof fixtures.deliveries.get>>>();
  const snapshots = new Map<string, { story: Schemas["Story"] & { boards: Schemas["Board"][] } }>();
  const presses: { key: string; revision: string }[] = [];
  const cancelWrites: { id: string; revision: string }[] = [];
  const overrideWrites: { id: string; revision: string; body: Schemas["CheckOverride"] }[] = [];
  let now = 0;

  function add(draft: Schemas["Story"], boards: Schemas["Board"][], key: string) {
    const number = runs.length + 1;
    const id = `run_01M79V9FC000000000000000${String(number).padStart(2, "0")}`;
    const frozen = {
      schema: "studio.run-snapshot/v1",
      story: structuredClone({ ...draft, boards }),
      resolved_asset_versions: [],
      toolchain_request: { studio: "git:fixture" },
    };
    const sha256 = createHash("sha256").update(JSON.stringify(frozen)).digest("hex");
    snapshots.set(id, frozen);
    const queued_at = timestamp(++now);
    const run: FixtureRun = {
      id, number,
      schema: "studio.run/v1", story_id: draft.id, queued_at, idempotency_key: key, queued_by: actor,
      snapshot: {
        sha256, story_revision: draft.revision, board_count: boards.length,
        locator: `productions/${draft.production_id}/blobs/${sha256}.json`,
      },
      revision: 1, status: "queued", cancel_requested: false, delivery_id: null, active_approval_id: null,
      progress: { percent: 0, stage: null }, stages: [], checks: null, outputs: null, provenance: null,
      legacy: null, estimate, estimate_methods: [], wait_reason: null, queue_wait: null, error: null,
      transitions: [{ from: null, to: "queued", at: queued_at, by: actor, reason: "Queued" }],
      check_overrides: [], wan_attempts: [],
    };
    runs.push(run);
    return run;
  }

  function view(run: FixtureRun, detail = false) {
    const { check_overrides, wan_attempts, ...base } = run;
    const ahead = runs.filter((item) => item.number < run.number && active(item)).length;
    const queue_wait = run.status === "queued" ? {
      ahead, basis: "Estimated serial lane wait", uncertain: true as const,
      wall_s: run.wait_reason ? null : [ahead * 15, ahead * 210],
    } : null;
    return { ...base, queue_wait, ...(detail ? { check_overrides, wan_attempts } : {}) };
  }

  const active = (run: FixtureRun) => run.status === "queued" || run.status === "running" || run.status === "held";

  function advance(id: string, status: Status, reason: string, fields: Partial<FixtureRun> = {}) {
    const run = runs.find((item) => item.id === id);
    if (!run || !active(run)) throw new Error("Run is not active");
    if (status === "running" && runs.find(active) !== run) throw new Error("Only the FIFO head can start");
    const from = run.status as "queued" | "running" | "held";
    const at = timestamp(++now);
    Object.assign(run, fields, { status, revision: run.revision + 1 });
    run.transitions!.push({ from, to: status, at, by: actor, reason });
    if (status === "running") run.started_at ??= at;
    if (!active(run)) run.finished_at = at;
    if (status === "succeeded") {
      const source = fixtures.deliveries.values().next().value!;
      const id = `dlv_01M79V9FC000000000000000${String(run.number).padStart(2, "0")}`;
      const proxy = source.proxy!;
      const delivery = {
        ...source, id, run_id: run.id, created_at: at,
        proxy: run.number === 1 ? proxy : { ...proxy, sha256: media.olderMaster.hash, bytes: media.olderMaster.body.length, width: 80, height: 120 },
      };
      deliveries.set(run.id, delivery);
      run.delivery_id = id;
      run.progress = { percent: 100, stage: "delivered" };
      run.outputs = {
        fps: 24, frames: delivery.master.frames,
        master_sha256: delivery.master.sha256, proxy_sha256: delivery.proxy.sha256,
      };
      run.provenance = {
        toolchain: { studio: "git:fixture" }, engines: [], inputs_externally_generated: [],
        usage: null, public: { ai_generated: true, credits: [] },
      };
      run.checks = [{ check: "audio.loudness", result: "pass" }];
    }
    return run;
  }

  return { runs, deliveries, snapshots, presses, cancelWrites, overrideWrites, estimate, add, advance, view };
}
