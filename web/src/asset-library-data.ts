import { ApiError, type StudioClient } from "./api/client";
import type { components } from "./api/schema";
import type { AssetVersion } from "./photo-composer-model";
import { collectPages, loadProduction, type Production } from "./route-data";
import type { AssetScope, Context } from "./routes";

type Story = components["schemas"]["Story"];
type AssetStory = Pick<Story, "id" | "title" | "board_order" | "narrator_voice_version_id" | "cast" | "beds"> & {
  set: Pick<NonNullable<Story["set"]>, "asset_version_id" | "motion_asset_version_id"> | null;
};
export type CandidateRequest = components["schemas"]["CandidateRequest"];
export type CandidateStatus = components["schemas"]["JobStatus"];

export async function loadAssetContext(api: StudioClient, context: Context, signal: AbortSignal):
  Promise<{ production?: Production; story?: AssetStory }> {
  const { production, story, media } = context;
  if (!production) return {};
  const record = await loadProduction(api, production, signal);
  if (!story) return { production: record };
  const { data } = await api.GET("/v1/stories/{id}", { signal, params: { path: { id: story } } });
  if (!data || data.id !== story || data.production_id !== production || data.media_kind !== media) {
    throw new ApiError(404);
  }
  return { production: record, story: data };
}

function listVersions(api: StudioClient, signal: AbortSignal, production?: string, board?: string) {
  return collectPages<AssetVersion>((cursor) => api.GET("/v1/assets", {
    signal, params: { query: { production, board, cursor } },
  }).then(({ data }) => data));
}

export function boardPhotoHistory(api: StudioClient, board: string, signal: AbortSignal) {
  return collectPages<AssetVersion>((cursor) => api.GET("/v1/boards/{id}/photo-versions", {
    signal, params: { path: { id: board }, query: { cursor } },
  }).then(({ data }) => data));
}

function storyPins(story: AssetStory) {
  return new Set([
    story.narrator_voice_version_id, story.set?.asset_version_id, story.set?.motion_asset_version_id,
    ...story.cast.map(({ voice_version_id }) => voice_version_id),
    ...story.beds.map(({ asset_version_id }) => asset_version_id),
  ].filter(Boolean));
}

export async function listAssetScope(api: StudioClient, scope: AssetScope, context: Context,
  story: AssetStory | undefined, signal: AbortSignal) {
  const { production, board } = context;
  if (scope === "library") return listVersions(api, signal);
  if (scope === "production") return listVersions(api, signal, production);
  if (!story || (scope === "board" && (!board || !story.board_order.includes(board)))) throw new ApiError(404);
  if (scope === "board") return listVersions(api, signal, production, board);

  // The catalog exposes board references and production scope. A story also
  // has direct pins, such as its set, stock voices and sound beds.
  const found = new Map<string, AssetVersion>();
  const pins = storyPins(story);
  if (pins.size) {
    for (const version of await listVersions(api, signal, production)) {
      if (pins.has(version.id)) found.set(version.id, version);
    }
  }
  for (let index = 0; index < story.board_order.length; index += 2) {
    const boards = story.board_order.slice(index, index + 2);
    const pages = await Promise.all(boards.map((id) => listVersions(api, signal, production, id)));
    for (const version of pages.flat()) found.set(version.id, version);
  }
  return [...found.values()];
}

export const activeCandidate = (status: CandidateStatus["status"]) => status === "queued" || status === "running";

export async function queueCandidate(api: StudioClient, body: CandidateRequest, key: string, signal: AbortSignal) {
  const { data } = await api.POST("/v1/asset-jobs", {
    signal, params: { header: { "Idempotency-Key": key } }, body,
  });
  if (!data || data.kind !== "asset_candidate" || !/^job_[0-7][0-9A-HJKMNP-TV-Z]{25}$/.test(data.id)) {
    throw new ApiError(500);
  }
  return data;
}

export async function loadCandidateJob(api: StudioClient, id: string, signal: AbortSignal) {
  const { data: job } = await api.GET("/v1/jobs/{id}", { signal, params: { path: { id } } });
  if (!job || job.id !== id || job.kind !== "asset_candidate" || !job.asset_candidate) throw new ApiError(404);
  return job;
}

export async function loadCandidateResult(api: StudioClient, id: string, job: Awaited<ReturnType<typeof loadCandidateJob>>,
  signal: AbortSignal) {
  const { data } = await api.GET("/v1/jobs/{id}/result", { signal, params: { path: { id } } });
  if (!data || data.id !== job.result_version_id || data.asset_id !== job.target_id ||
      data.scope.production_id !== job.asset_candidate?.production_id || data.kind !== job.asset_candidate?.kind ||
      (data.state !== "candidate" && data.state !== "promoted")) throw new ApiError(500);
  return data;
}

export async function loadImageLane(api: StudioClient, signal: AbortSignal) {
  const { data } = await api.GET("/v1/queue/lanes", { signal });
  const lane = data?.items.find(({ lane }) => lane === "image");
  if (!lane) throw new ApiError(500);
  return lane;
}

export async function promoteAsset(api: StudioClient, version: AssetVersion, signal: AbortSignal) {
  // This create-only decision is serialized and idempotent on the source
  // version ID. The API accepts neither a body nor a revision precondition.
  const { data } = await api.POST("/v1/asset-versions/{id}/promote", {
    signal, params: { path: { id: version.id } },
  });
  if (!data || data.state !== "promoted" || data.kind !== version.kind ||
      data.scope.production_id !== version.scope.production_id || data.scope.board_id ||
      (version.state === "candidate" ? data.id !== version.id || data.asset_id !== version.asset_id
        : data.provenance.source_key !== `promote:${version.id}`)) {
    throw new ApiError(500);
  }
  return data;
}
