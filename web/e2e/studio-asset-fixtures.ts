import { createHash } from "node:crypto";

import type { Route } from "@playwright/test";
import type { components } from "../src/api/schema";
import { photoVersionId } from "./studio-photo-fixtures";
import { mediaResponse, type TestMedia } from "./studio-review-media";

type Schemas = components["schemas"];
type Version = Schemas["AssetVersion"];
type Board = Schemas["Board"];
type Candidate = Schemas["CandidateRequest"];
type Job = Schemas["JobView"];
type ErrorDetail = Schemas["ErrorDetail"];

const when = "2026-11-04T12:01:00Z";
const creator = { kind: "human" } as const;
export const knownHiddenCandidate = photoVersionId(214);
export const librarySound = photoVersionId(222);
export const libraryRecorded = photoVersionId(213);

function sound(): TestMedia {
  const samples = 8000;
  const body = Buffer.alloc(44 + samples * 2);
  body.write("RIFF", 0);
  body.writeUInt32LE(body.length - 8, 4);
  body.write("WAVEfmt ", 8);
  body.writeUInt32LE(16, 16);
  body.writeUInt16LE(1, 20);
  body.writeUInt16LE(1, 22);
  body.writeUInt32LE(8000, 24);
  body.writeUInt32LE(16000, 28);
  body.writeUInt16LE(2, 32);
  body.writeUInt16LE(16, 34);
  body.write("data", 36);
  body.writeUInt32LE(samples * 2, 40);
  return { body, mime: "audio/wav", hash: createHash("sha256").update(body).digest("hex") };
}

function content(file: TestMedia, mime: "audio/wav" | "image/png") {
  return { media_type: mime, sha256: file.hash, bytes: file.body.length, locator: `fixture/${file.hash}` };
}

function pageOf(versions: Version[], cursor: string | null) {
  const items = versions.filter(({ id }) => !cursor || id > cursor).sort((a, b) => a.id.localeCompare(b.id));
  return { items: items.slice(0, 2), next_cursor: items.length > 2 ? items[1].id : null };
}

function pins(board: Board) {
  return new Set([
    board.photo.current_version_id, board.voice.current_version_id, ...board.photo.input_asset_version_ids,
    ...board.cast.flatMap(({ asset_version_id, motion_asset_version_id }) => [asset_version_id, motion_asset_version_id]),
    ...board.cues.flatMap((cue) => cue.type === "sound" && "asset_version_id" in cue ? [cue.asset_version_id] : []),
  ]);
}

export function assetFixtures(versions: Version[], media: TestMedia[], draft: Schemas["Story"], sibling: Board) {
  const files = new Map(media.map((file) => [file.hash, file]));
  const first = versions.find(({ name }) => name === "Ada portrait")!;
  const wav = sound();
  files.set(wav.hash, wav);
  versions.push(
    { ...first, id: photoVersionId(221), number: 2, capabilities: ["rgba_cutout"], content: content(media[5], "image/png"),
      labels: ["Character"] },
    { ...first, id: librarySound, asset_id: librarySound.replace("asv_", "ast_"),
      name: "Dining bell", kind: "sound", capabilities: ["sound_effect"], labels: ["Kitchen"],
      content: content(wav, "audio/wav"), provenance: { ...first.provenance, origin: "imported", generator: { role: "sound" },
        source_key: "fixture:dining-bell" } },
    { ...first, id: photoVersionId(223), asset_id: photoVersionId(223).replace("asv_", "ast_"),
      name: "Series outline", kind: "character_card", labels: [], capabilities: [], content: null,
      provenance: { ...first.provenance, origin: "declared" } },
  );
  sibling.cast = sibling.cast.map((entry) => ({ ...entry, asset_version_id: photoVersionId(221) }));
  draft.beds = [...draft.beds, {
    id: photoVersionId(222).replace("asv_", "cue_"), type: "bed", clock: "film", asset_version_id: librarySound,
    level_rms_dbfs: -18,
  }];
  const jobs = new Map<string, Job>();
  const requests = new Map<string, { job: Job; body: Candidate }>();
  const presses: { key: string; body: Candidate }[] = [];
  const promotions: string[] = [];
  let dropReply = false;
  let paused = false;
  let waitForReply: Promise<void> | undefined;

  const update = (id: string, patch: Partial<Job>) => Object.assign(jobs.get(id)!, patch);

  function complete(id: string) {
    const job = jobs.get(id)!;
    const spec = job.asset_candidate!;
    const result: Version = {
      ...first, id: photoVersionId(500 + jobs.size), asset_id: job.target_id, number: 1,
      name: spec.name, kind: spec.kind, labels: spec.labels,
      scope: { production_id: spec.production_id }, state: "candidate",
      content: content(media[4], "image/png"), capabilities: [spec.kind === "set" ? "opaque_plate" : "opaque_photo"],
      provenance: { created_at: when, created_by: creator, origin: "generated", source_key: `asset-candidate:${id}`,
        generator: { role: "image", model: "Fixture image lane", prompt: spec.prompt, seed: spec.seed } },
    };
    versions.push(result);
    update(id, { status: "succeeded", result_version_id: result.id, result_is_current: false });
    return result;
  }

  function missing(route: Route) {
    return reject(route, 404, "not_found", "not_found");
  }

  function reject(route: Route, status: number, category: ErrorDetail["status"], code: string) {
    return route.fulfill({ status, json: { error: {
      status: category, http_status: status, path: "", code, message: code, request_id: "mock-asset",
    } } satisfies Schemas["ErrorEnvelope"] });
  }

  function visibleTo(version: Version, allowed: Set<string>) {
    return version.scope.production_id === null || allowed.has(version.scope.production_id);
  }

  function mediaResult(route: Route, hash: string, file?: TestMedia) {
    const media = files.get(hash) ?? file;
    return media ? route.fulfill(mediaResponse(route, media)) : missing(route);
  }

  function respond(route: Route, url: URL, allowed: Set<string>, boards: Map<string, Board>,
    user: string, photoFiles?: Map<string, TestMedia>) {
    const request = route.request();
    const method = request.method();
    const path = url.pathname;
    const cursor = url.searchParams.get("cursor");
    const reads = method === "GET" || method === "HEAD";

    if (path === "/v1/assets" && method === "GET") {
      const scope = url.searchParams.get("production");
      const boardId = url.searchParams.get("board");
      const board = boardId && boards.get(boardId);
      if ((scope && !allowed.has(scope)) || (boardId && !board)) return missing(route);
      const kind = url.searchParams.get("kind");
      const references = board ? pins(board) : undefined;
      const visible = versions.filter((version) => version.state !== "candidate" && visibleTo(version, allowed) &&
        (!scope || !version.scope.production_id || version.scope.production_id === scope) &&
        (!references || references.has(version.id)) && (!kind || version.kind === kind));
      return route.fulfill({ json: pageOf(visible, cursor) });
    }

    if (path === "/v1/asset-jobs" && method === "POST") {
      const key = request.headers()["idempotency-key"];
      const body = request.postDataJSON() as Candidate;
      if (!key || !body.name.trim() || !body.prompt.trim() || !Number.isSafeInteger(body.seed)) {
        return reject(route, 422, "invalid", "schema.invalid");
      }
      presses.push({ key, body });
      const lookup = `${user}:${key}`;
      const existing = requests.get(lookup);
      if (existing) {
        if (JSON.stringify(existing.body) !== JSON.stringify(body)) return reject(route, 422, "invalid", "idempotency.mismatch");
        return route.fulfill({ status: 200, json: jobStatus(existing.job), headers: { location: `/v1/jobs/${existing.job.id}` } });
      }
      const id = photoVersionId(500 + jobs.size + 1).replace("asv_", "job_");
      const job: Job = {
        schema: "studio.job/v1", id, target_id: id.replace("job_", "ast_"), kind: "asset_candidate", status: "queued",
        created_at: when, created_by: creator, updated_at: when, input_signature: "a".repeat(64),
        result_is_current: null, result_version_id: null, error: null,
        asset_candidate: { ...body, production_id: body.production_id ?? null, labels: body.labels ?? [],
          model: "Fixture image lane", request_size: [1104, 1472] },
      };
      jobs.set(id, job);
      requests.set(lookup, { job, body });
      if (dropReply) {
        dropReply = false;
        return route.abort("failed");
      }
      const reply = () => route.fulfill({ status: 202, json: jobStatus(job), headers: { location: `/v1/jobs/${id}` } });
      const held = waitForReply;
      waitForReply = undefined;
      return held ? held.then(reply) : reply();
    }

    if (path.startsWith("/v1/jobs/") && reads) {
      const [, , , id, resource, hash] = path.split("/");
      const job = jobs.get(id);
      if (!job) return;
      if (!resource) return route.fulfill({ json: job });
      const version = versions.find(({ id }) => id === job.result_version_id);
      if (!version) return missing(route);
      if (resource === "result") return route.fulfill({ json: version });
      if (resource === "media" && version.content?.sha256 === hash && !url.search) return mediaResult(route, hash);
      return missing(route);
    }

    if (path.startsWith("/v1/asset-versions/")) {
      const [, , , id, resource, hash] = path.split("/");
      const version = versions.find((version) => version.id === id);
      if (!version || !visibleTo(version, allowed)) return missing(route);
      if (resource === "media" && reads) {
        if (!["photo", "board_voice"].includes(version.kind) && version.state !== "candidate") return missing(route);
        if (!version.recorded_without_media && !url.search && (version.content ?? version.voice?.track)?.sha256 === hash) {
          return mediaResult(route, hash, photoFiles?.get(hash));
        }
        return missing(route);
      }
      if (resource === "promote" && method === "POST") {
        if (request.postData() || request.headers()["if-match"]) return reject(route, 422, "invalid", "schema.invalid");
        promotions.push(id);
        if (version.recorded_without_media) return reject(route, 422, "invalid", "asset.recorded_without_media");
        if (version.state === "board" && version.kind === "photo") {
          const existing = versions.find(({ provenance }) => provenance.source_key === `promote:${id}`);
          if (existing) return route.fulfill({ json: existing });
          const copy: Version = { ...version, id: photoVersionId(700 + promotions.length),
            asset_id: photoVersionId(700 + promotions.length).replace("asv_", "ast_"), number: 1, state: "promoted",
            scope: { production_id: version.scope.production_id },
            provenance: { ...version.provenance, origin: "derived", source_key: `promote:${id}` } };
          versions.push(copy);
          return route.fulfill({ json: copy });
        }
        if (version.state === "candidate") version.state = "promoted";
        return route.fulfill({ json: version });
      }
    }

    if (path.startsWith("/v1/media/") && reads) {
      const hash = path.split("/").at(-1)!;
      const pinned = new Set([...boards.values()].flatMap((board) => [...pins(board)]));
      const available = versions.some((version) => visibleTo(version, allowed) && version.state !== "candidate" &&
        !version.recorded_without_media && (version.content ?? version.voice?.track)?.sha256 === hash &&
        ((version.scope.production_id !== null && !version.scope.board_id) || pinned.has(version.id)));
      return available && !url.search ? mediaResult(route, hash, photoFiles?.get(hash)) : missing(route);
    }
  }

  return {
    respond, presses, promotions, versions,
    latestJob: () => Array.from(jobs.values()).at(-1),
    pause: (value: boolean) => { paused = value; },
    paused: () => paused,
    loseReply: () => { dropReply = true; },
    holdReply: () => {
      let release = () => {};
      waitForReply = new Promise<void>((resolve) => { release = resolve; });
      return release;
    },
    start: (id: string) => update(id, { status: "running" }),
    fail: (id: string, code: string, message: string) => update(id, { status: "failed", error: { code, message } }),
    complete,
  };
}

function jobStatus({ schema, id, kind, target_id, status, updated_at, result_version_id, result_is_current, error }: Job) {
  return { schema, id, kind, target_id, status, updated_at, result_version_id, result_is_current, error };
}
