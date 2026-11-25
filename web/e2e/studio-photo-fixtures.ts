import { createHash } from "node:crypto";
import type { Browser } from "@playwright/test";
import type { components } from "../src/api/schema";
import type { TestMedia } from "./studio-review-media";

type Schemas = components["schemas"];
type Board = Schemas["Board"];
type Story = Schemas["Story"];
type Version = Schemas["AssetVersion"];
type Job = Schemas["JobStatus"];

const now = "2026-11-04T12:01:00Z";
const agent = "Fixture agent";
const session = "photo-fixture";
export const workflowDigest = "a".repeat(64);
export const uploadDigest = "b".repeat(64);
export const photoVersionId = (number: number) => `asv_01M79V9FC000000000000${String(number).padStart(5, "0")}`;
export const castPin = photoVersionId(210);
export const setPin = photoVersionId(211);
export const propPin = photoVersionId(212);
export const unavailablePin = photoVersionId(213);

export async function generatePhotoMedia(browser: Browser): Promise<TestMedia[]> {
  const page = await browser.newPage();
  try {
    const samples = await page.evaluate(() => ["#5a3747", "#215552", "#9c6a38", "#9d9971", "#44629c", "#b1495a"].map((color, i) => {
      const canvas = Object.assign(document.createElement("canvas"), { width: 36, height: 64 });
      const context = canvas.getContext("2d")!;
      context.fillStyle = color;
      if (i === 5) context.fillRect(8, 12, 16, 40);
      else context.fillRect(0, 0, canvas.width, canvas.height);
      return canvas.toDataURL("image/png").split(",")[1];
    }));
    return samples.map((data) => {
      const body = Buffer.from(data, "base64");
      return { body, hash: createHash("sha256").update(body).digest("hex"), mime: "image/png" };
    });
  } finally {
    await page.close();
  }
}

function input(board: Board, story: Story) {
  return JSON.stringify(board.method.layer === "layered" ?
    [board.method.layer, story.set, board.cast, board.layout, board.cues] :
    [board.method.layer, board.photo.prompt, board.photo.input_asset_version_ids]);
}

export function photoFixtures(
  versions: Version[], media: TestMedia[], story: Story, layered: Board, whole: Board,
) {
  const savedInputs = new Map<string, string>();
  const files = new Map<string, TestMedia>();
  const presses: { board: string; key: string; seed: number; saved: Board["photo"] }[] = [];
  const jobs = new Map<string, {
    job: Job; requester: string; key: string; seed: number; input: string;
    layer: Board["method"]["layer"]; selected: string | null;
  }>();
  let paused = false;
  let dropReply = false;
  let nextVersion = 103;

  story.cast = [{ slot: "a", name: "Ada", voice_version_id: photoVersionId(219) }];
  story.set = {
    asset_version_id: setPin, motion_asset_version_id: null, foreground_edge_px: null,
    foreground_feather_px: null, legacy_fire: null,
  };
  layered.method = { layer: "layered", motion: "i2v" };
  layered.cast = [{ slot: "a", asset_version_id: castPin }];
  Object.assign(story, { layouts: { center: { x: .5, bottom: 1560, height: 900 } } });
  whole.photo = { prompt: "Ada at the table.", input_asset_version_ids: [castPin], current_version_id: photoVersionId(100) };

  function version(board: Board, serial: number, number: number, file: TestMedia,
    origin: Version["provenance"]["origin"], generator: Version["provenance"]["generator"]) {
    return {
      id: photoVersionId(serial), schema: "studio.asset-version/v1", asset_id: photoVersionId(100).replace("asv_", "ast_"),
      scope: { board_id: board.id, story_id: board.story_id, production_id: story.production_id },
      capabilities: ["opaque_photo"], kind: "photo", state: "board", number, labels: [], attributes: {},
      legacy: null, name: "Board photo",
      content: { sha256: file.hash, locator: `blobs/${file.hash}`, bytes: file.body.length, media_type: "image/png" },
      provenance: { created_at: new Date(Date.parse(now) + serial * 1000).toISOString(), created_by: board.drafted_by, origin, generator },
    } satisfies Version;
  }

  const first = version(whole, 100, 1, media[0], "generated",
    { role: "image", engine: "ComfyUI", model: "Fixture image model", seed: 17, workflow_sha256: workflowDigest });
  savedInputs.set(first.id, input(whole, story));
  const uploaded: Version = version(whole, 101, 2, media[1], "uploaded",
    { role: "image", model: "Fixture upload model", prompt: "Ada by the window." });
  const agentId = photoVersionId(33).replace("asv_", "key_");
  uploaded.provenance.created_by = { kind: "agent", key_id: agentId } as Version["provenance"]["created_by"];
  uploaded.provenance.external = {
    agent: { kind: "agent", harness: agent, session, key_id: agentId },
    declared_by: "agent", externally_generated: true, paid_api: false, server_computed_sha256: true,
  };
  // The generated transport type cannot name keys in the canonical generator params object.
  Object.assign(uploaded.provenance.generator, { params: { upload_sha256: uploadDigest } });
  const imported: Version = {
    ...version(whole, 102, 3, media[2], "imported", { role: "image" }), recorded_without_media: true,
  };
  versions.push(first, uploaded, imported);
  files.set(media[0].hash, media[0]);
  files.set(media[1].hash, media[1]);

  const catalog = ([
    [210, "cast", "Ada portrait", "rgba_cutout"], [211, "set", "Cabin", "opaque_plate"],
    [212, "prop", "Soup bowl", "opaque_photo"], [213, "prop", "Recorded spoon", "opaque_photo"],
    [214, "prop", "Candidate prop", "opaque_photo"], [215, "prop", "Other production prop", "opaque_photo"],
  ] as const).map(([serial, kind, name, capability]): Version => ({
    ...version(whole, serial, 1, media[serial === 210 ? 5 : 0], serial === 213 ? "imported" : "generated", { role: "image" }),
    scope: { production_id: serial === 212 ? null : serial === 215 ? story.production_id.slice(0, -1) + "2" : story.production_id },
    asset_id: photoVersionId(serial).replace("asv_", "ast_"), kind, name, capabilities: [capability],
    state: serial === 214 ? "candidate" : "promoted",
    ...(serial === 213 ? { recorded_without_media: true } : {}),
  }));
  versions.push(...catalog);

  function forBoard(id: string) {
    return [...jobs.values()].filter(({ job }) => job.target_id === id).map(({ job }) => job);
  }

  function submit(board: Board, key: string, seed: number, requester: string) {
    presses.push({ board: board.id, key, seed, saved: structuredClone(board.photo) });
    const existing = [...jobs.values()].find((item) => item.key === key && item.job.target_id === board.id && item.requester === requester);
    if (existing) return { job: existing.job, created: false, lost: false, mismatch: seed !== existing.seed };
    const id = photoVersionId(100 + jobs.size).replace("asv_", "job_");
    const job: Job = {
      id, target_id: board.id, schema: "studio.job/v1", kind: "photo", status: "queued",
      result_is_current: null, result_version_id: null, error: null, updated_at: now,
    };
    jobs.set(id, {
      job, requester, key, seed, input: input(board, story), layer: board.method.layer,
      selected: board.photo.current_version_id,
    });
    const lost = dropReply;
    dropReply = false;
    return { job, created: true, lost, mismatch: false };
  }

  function complete(id: string, board: Board) {
    const held = jobs.get(id)!;
    if (held.job.status !== "running") throw new Error("Start the fixture job before completing it");
    const number = nextVersion++;
    const file = media[number === 103 ? 3 : 4];
    const composite = held.layer === "layered";
    const result = version(board, number, composite ? 1 : number - 99, file, composite ? "derived" : "generated",
      composite ? { role: "composite", engine: "Fixture compositor", source_asset_version_ids: [setPin, castPin] }
        : { role: "image", engine: "ComfyUI", seed: held.seed, workflow_sha256: workflowDigest });
    if (composite) result.asset_id = photoVersionId(200).replace("asv_", "ast_");
    versions.push(result);
    files.set(file.hash, file);
    savedInputs.set(result.id, held.input);
    const current = held.input === input(board, story) && held.selected === board.photo.current_version_id;
    Object.assign(held.job, { status: "succeeded", result_version_id: result.id, result_is_current: current });
    if (current) {
      board.photo = { ...board.photo, current_version_id: result.id };
      board.revision++;
      story.revision++;
    }
    return { result, file, current };
  }

  return {
    catalog, files, presses, forBoard, submit, complete,
    latest: () => [...jobs.values()].at(-1)?.job,
    paused: () => paused,
    pause: (value: boolean) => { paused = value; },
    loseNextReply: () => { dropReply = true; },
    status(board: Board) {
      if (forBoard(board.id).some(({ status }) => status === "queued" || status === "running")) return "generating" as const;
      const selected = board.photo.current_version_id;
      return selected ? savedInputs.get(selected) === input(board, story) ? "current" as const : "stale" as const : "absent" as const;
    },
    start(id: string) {
      const { job } = jobs.get(id)!;
      if (paused || job.status !== "queued") throw new Error("Fixture photo job cannot run");
      job.status = "running";
    },
    fail(id: string, code: string, message: string) {
      const { job } = jobs.get(id)!;
      if (job.status !== "running") throw new Error("Start the fixture job before failing it");
      job.status = "failed";
      job.error = { code, message };
    },
  };
}
