import { ApiError, type StudioClient } from "./api/client";
import type { components } from "./api/schema";
import { mediaUrl } from "./production-review-data";
import { collectPages, loadBoard, type Board } from "./route-data";
import type { MediaKind } from "./routes";

export type StoryboardScope = { production: string; media: MediaKind; story: string };
type AssetVersion = components["schemas"]["AssetVersion"];

async function loadMedia(api: StudioClient, production: string, board: Board, signal: AbortSignal) {
  if (!board.photo.current_version_id && !board.voice.current_version_id) return {};
  const versions = await collectPages<AssetVersion>((cursor) => api.GET("/v1/assets", {
    signal, params: { query: { production, board: board.id, cursor } },
  }).then(({ data }) => data));
  const selected = versions.filter(({ scope }) => scope.production_id === production &&
    scope.story_id === board.story_id && scope.board_id === board.id);
  const photo = selected.find(({ kind, id }) => kind === "photo" && id === board.photo.current_version_id);
  const voice = selected.find(({ kind, id }) => kind === "board_voice" && id === board.voice.current_version_id);
  return {
    photo: mediaUrl(photo?.content?.sha256),
    voice: mediaUrl(voice?.voice?.track?.sha256),
    voiceMs: voice?.voice?.speech_end_ms,
  };
}

async function loadBoards(api: StudioClient, scope: StoryboardScope, order: string[], signal: AbortSignal) {
  const boards = [];
  for (let index = 0; index < order.length; index += 2) {
    const pair = order.slice(index, index + 2);
    boards.push(...await Promise.all(pair.map(async (id) => {
      const record = await loadBoard(api, scope.story, id, signal);
      return { record, ...await loadMedia(api, scope.production, record, signal) };
    })));
  }
  return boards;
}

export async function loadStoryboardDraft(api: StudioClient, scope: StoryboardScope, signal: AbortSignal) {
  const params = { path: { id: scope.story } };
  for (let attempt = 0; attempt < 2; attempt++) {
    const { data: story } = await api.GET("/v1/stories/{id}", { signal, params });
    if (!story || story.id !== scope.story || story.production_id !== scope.production || story.media_kind !== scope.media) {
      throw new ApiError(404);
    }
    const boards = await loadBoards(api, scope, story.board_order, signal).catch((error: unknown) => {
      if (error instanceof ApiError && error.status === 404) return error;
      throw error;
    });
    const { data: timing } = await api.GET("/v1/stories/{id}/timing", { signal, params });
    if (!timing || timing.story_id !== story.id) throw new ApiError(404);
    // A change during these reads can make a board disappear or move its film start.
    if (timing.story_revision !== story.revision) continue;
    if (boards instanceof ApiError) throw boards;
    return { story, boards, timing };
  }
  throw new ApiError(409, "conflict.revision");
}

export type StoryboardDraft = Awaited<ReturnType<typeof loadStoryboardDraft>>;
export type StoryboardPanel = StoryboardDraft["boards"][number];

export async function addBoard(api: StudioClient, draft: StoryboardDraft, signal: AbortSignal) {
  const { story } = draft;
  const { data } = await api.POST("/v1/stories/{id}/boards", {
    signal, params: { path: { id: story.id }, header: { "If-Match": `"${story.revision}"` } }, body: {},
  });
  if (!data || data.story_id !== story.id) throw new ApiError(500);
  return data.id;
}

export async function reorderBoards(api: StudioClient, draft: StoryboardDraft, order: string[], signal: AbortSignal) {
  const { story } = draft;
  await api.PUT("/v1/stories/{id}/board-order", {
    signal, params: { path: { id: story.id }, header: { "If-Match": `"${story.revision}"` } },
    body: { board_order: order },
  });
}

export async function removeBoard(api: StudioClient, board: Board, signal: AbortSignal) {
  await api.DELETE("/v1/boards/{id}", {
    signal, params: { path: { id: board.id }, header: { "If-Match": `"${board.revision}"` } },
  });
}
