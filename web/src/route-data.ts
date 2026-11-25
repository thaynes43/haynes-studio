import { ApiError, type StudioClient } from "./api/client";
import type { components } from "./api/schema";
import type { Run } from "./production-review-data";
import type { Context, MediaKind } from "./routes";

export type Production = Pick<components["schemas"]["Production"], "id" | "name" | "media_types" | "revision">;
export type Story = Pick<components["schemas"]["Story"],
  "id" | "title" | "production_id" | "media_kind" | "board_order" | "approved" | "published" | "cast">;
export type Board = components["schemas"]["Board"];
// These are the data needed to draw the shell and its route controls.
export type RouteData = {
  production?: Production;
  productions?: Production[];
  story?: Story;
  stories?: Story[];
  board?: Board;
  run?: Run;
};

export async function loadProduction(api: StudioClient, id: string, signal: AbortSignal) {
  const { data } = await api.GET("/v1/productions/{id}", {
    signal, params: { path: { id } },
  });
  if (!data || data.id !== id) throw new ApiError(404);
  return data;
}

export async function collectPages<T>(
  read: (cursor?: string) => Promise<{ items: T[]; next_cursor: string | null } | undefined>,
): Promise<T[]> {
  const items: T[] = [];
  const seen = new Set<string>();
  let cursor: string | undefined;
  do {
    const page = await read(cursor);
    if (!page) throw new ApiError(500);
    items.push(...page.items);
    cursor = page.next_cursor ?? undefined;
    if (cursor) {
      if (seen.has(cursor)) throw new ApiError(500);
      seen.add(cursor);
    }
  } while (cursor);
  return items;
}

export function listProductions(api: StudioClient, signal: AbortSignal) {
  return collectPages<Production>((cursor) =>
    api.GET("/v1/productions", { signal, params: { query: { cursor } } }).then(({ data }) => data)
  );
}

export function listStories(
  api: StudioClient, id: string, kind: MediaKind, signal: AbortSignal,
  filters?: { publication?: "published" | "unpublished"; approved?: boolean },
) {
  return collectPages<Story>((cursor) =>
    api.GET("/v1/productions/{id}/media-types/{kind}/stories", {
      signal, params: { path: { id, kind }, query: { ...filters, cursor } },
    }).then(({ data }) => data)
  );
}

export async function loadBoard(api: StudioClient, story: string, id: string, signal: AbortSignal) {
  const { data } = await api.GET("/v1/boards/{id}", { signal, params: { path: { id } } });
  if (!data || data.id !== id || data.story_id !== story) throw new ApiError(404);
  return data;
}

export async function loadRoute(
  api: StudioClient,
  context: Context,
  area: "productions" | "board" | "assets",
  signal: AbortSignal,
): Promise<RouteData> {
  const { production: id, media, story: storyId, board: boardId, run: runId } = context;
  if (!id) {
    if (area === "assets") return {};
    return { productions: await listProductions(api, signal) };
  }

  const production = await loadProduction(api, id, signal);
  if (media && !production.media_types.some(({ kind }) => kind === media)) {
    throw new ApiError(404);
  }

  if (!media) return { production };
  if (!storyId) return area === "productions"
    ? { production }
    : { production, stories: await listStories(api, id, media, signal) };

  const { data: story } = await api.GET("/v1/stories/{id}", {
    signal, params: { path: { id: storyId } },
  });
  if (!story || story.id !== storyId || story.production_id !== id || story.media_kind !== media ||
      (boardId && !story.board_order.includes(boardId))) {
    throw new ApiError(404);
  }
  if (runId) {
    const { data: run } = await api.GET("/v1/runs/{id}", { signal, params: { path: { id: runId } } });
    if (!run || run.id !== runId || run.story_id !== story.id) throw new ApiError(404);
    return { production, story, run };
  }
  if (!boardId) return { production, story };

  return { production, story, board: await loadBoard(api, storyId, boardId, signal) };
}

export function boardLabel(board?: Pick<Board, "number">) {
  return board ? "B" + String(board.number).padStart(2, "0") : "Board";
}
