import { ApiError, type StudioClient } from "./api/client";
import type { components } from "./api/schema";
import type { Context, MediaKind } from "./routes";

export type Production = Pick<components["schemas"]["Production"], "id" | "name" | "media_types" | "revision">;
type Story = Pick<components["schemas"]["Story"], "id" | "title" | "production_id" | "media_kind" | "board_order">;
type Board = Pick<components["schemas"]["Board"], "id" | "story_id" | "number">;
// These are the data needed to draw the shell and its route controls.
export type RouteData = {
  production?: Production;
  productions?: Production[];
  story?: Story;
  stories?: Story[];
  board?: Board;
};

export async function loadProduction(api: StudioClient, id: string, signal: AbortSignal) {
  const { data } = await api.GET("/v1/productions/{id}", {
    signal, params: { path: { id } },
  });
  if (!data || data.id !== id) throw new ApiError(404);
  return data;
}

async function collectPages<T>(
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

export function listStories(api: StudioClient, id: string, kind: MediaKind, signal: AbortSignal) {
  return collectPages<Story>((cursor) =>
    api.GET("/v1/productions/{id}/media-types/{kind}/stories", {
      signal, params: { path: { id, kind }, query: { cursor } },
    }).then(({ data }) => data)
  );
}

export async function loadRoute(
  api: StudioClient,
  context: Context,
  area: "productions" | "board" | "assets",
  signal: AbortSignal,
): Promise<RouteData> {
  const { production: id, media, story: storyId, board: boardId } = context;
  if (!id) {
    if (area === "assets") return {};
    return { productions: await listProductions(api, signal) };
  }

  const production = await loadProduction(api, id, signal);
  if (media && !production.media_types.some(({ kind }) => kind === media)) {
    throw new ApiError(404);
  }

  if (!media) return { production };
  if (!storyId) return { production, stories: await listStories(api, id, media, signal) };

  const { data: story } = await api.GET("/v1/stories/{id}", {
    signal, params: { path: { id: storyId } },
  });
  if (!story || story.id !== storyId || story.production_id !== id || story.media_kind !== media ||
      (boardId && !story.board_order.includes(boardId))) {
    throw new ApiError(404);
  }
  if (!boardId) return { production, story };

  const { data: board } = await api.GET("/v1/boards/{id}", {
    signal, params: { path: { id: boardId } },
  });
  if (!board || board.id !== boardId || board.story_id !== storyId) throw new ApiError(404);
  return { production, story, board };
}

export function boardLabel(board?: Board) {
  return board ? "B" + String(board.number).padStart(2, "0") : "Board";
}
