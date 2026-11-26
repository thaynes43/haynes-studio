import type { components } from "./api/schema";

export type MediaKind = components["schemas"]["StudioDefs_media_kind"];
export type TreeArea = "productions" | "board";
export type Context = {
  production?: string;
  media?: MediaKind;
  story?: string;
  board?: string;
  run?: string;
};
type BoardPage = "photo" | "runs" | "compare";

export type AssetScope = "board" | "story" | "production" | "library";
export type AssetFilters = {
  scope?: AssetScope;
  target?: string;
  kind?: string;
  search?: string;
  job?: string;
  jobKind?: "matte";
};
export type AssetsRoute = { area: "assets"; context: Context; generate: boolean; filters: AssetFilters };

export type Route =
  | { area: TreeArea; context: Context; page?: BoardPage }
  | AssetsRoute
  | { area: "editor" | "user" | "admin" | "missing" };

export const mediaKinds = {
  short: { label: "Short", plural: "Shorts", aspect: "9:16" },
  video: { label: "Video", plural: "Videos", aspect: "16:9" },
} satisfies Record<MediaKind, { label: string; plural: string; aspect: string }>;

export const storyFormatId = "story-format";

function isId(value: string | undefined | null, prefix: "prd" | "sty" | "brd" | "run" | "job") {
  return typeof value === "string" && value.length === 30 && value.startsWith(prefix + "_") &&
    /^[0-7][0-9A-HJKMNP-TV-Z]{25}$/.test(value.slice(4));
}

function isMedia(value: string | undefined | null): value is MediaKind {
  return value === "short" || value === "video";
}

export function treePath(area: TreeArea, context: Context = {}, page?: BoardPage) {
  const { production, media, story, board, run } = context;
  const base = area === "productions" ? "/productions" : "/editor/board";
  const suffix = page === "compare" ? "/runs/compare" : page ? "/" + page : "";
  return base + (production ? "/" + production : "") + (media ? "/" + media : "") +
    (story ? "/" + story : "") + (board ? "/boards/" + board : "") +
    (area === "productions" && run ? "/runs/" + run : "") + suffix;
}

export const assetSearchLimit = 180;

export function assetSearch(value?: string) {
  // Match the API's login return-path rules for decoded query values.
  return value?.replace(/[\\\x00-\x1f\x7f]/g, "").slice(0, assetSearchLimit) || undefined;
}

export function defaultAssetScope(context: Context): AssetScope {
  if (context.board) return "board";
  if (context.story) return "story";
  if (context.production) return "production";
  return "library";
}

export const assetScopes: readonly AssetScope[] = ["board", "story", "production", "library"];
const isAssetKind = (kind?: string) => kind !== undefined && /^[a-z][a-z0-9_-]{0,39}$/.test(kind);

export function assetsPath(context: Context = {}, generate = false, filters: AssetFilters = {}) {
  const query = new URLSearchParams();
  if (context.production) query.set("production", context.production);
  if (context.production && context.story && context.media) {
    query.set("media", context.media);
    query.set("story", context.story);
    if (context.board) query.set("board", context.board);
  }
  const initial = defaultAssetScope(context);
  if (filters.scope && assetScopes.indexOf(filters.scope) > assetScopes.indexOf(initial)) {
    query.set("scope", filters.scope);
  }
  if (context.story && filters.target && filters.target !== context.board && isId(filters.target, "brd")) {
    query.set("target", filters.target);
  }
  if (filters.kind && isAssetKind(filters.kind)) query.set("kind", filters.kind);
  const search = assetSearch(filters.search);
  if (search) query.set("q", search);
  if (filters.job && isId(filters.job, "job")) {
    query.set("job", filters.job);
    if (filters.jobKind === "matte") query.set("job_kind", "matte");
  }
  return (generate ? "/editor/assets/generate" : "/editor/assets") + (query.size ? "?" + query : "");
}

/**
 * The filters to start a change from. The router updates the address before a page
 * re-renders, so the filters a component last rendered with can be one step behind:
 * a change made straight after typing in search would be built from them and drop
 * the last key. Read the address as it is now; fall back to the rendered filters
 * when the address is not an Assets address.
 */
export function liveAssetFilters(rendered: AssetFilters, pathname: string, search: string): AssetFilters {
  const live = parseRoute(pathname, search);
  return live.area === "assets" ? live.filters : rendered;
}

export function assetsDestination(context: Context, { scope, target, kind }: AssetFilters) {
  return assetsPath(context, false, { scope, target, kind });
}

export function parseRoute(pathname: string, search = ""): Route {
  const missing = { area: "missing" } as const;
  if (pathname === "/" || pathname === "/productions") return { area: "productions", context: {} };
  if (pathname === "/editor") return { area: "editor" };
  if (pathname === "/settings/user") return { area: "user" };
  if (pathname === "/settings/admin") return { area: "admin" };
  if (pathname === "/editor/assets" || pathname === "/editor/assets/generate") {
    const query = new URLSearchParams(search);
    const production = query.get("production") ?? undefined;
    const media = query.get("media") ?? undefined;
    const story = query.get("story") ?? undefined;
    const board = query.get("board") ?? undefined;
    if (production && !isId(production, "prd")) return missing;
    if ((media || story || board) && (!production || !isMedia(media) || !isId(story, "sty"))) return missing;
    if (board && !isId(board, "brd")) return missing;
    const context = { production, media: isMedia(media) ? media : undefined, story, board };
    const requestedScope = assetScopes.find((scope) => scope === query.get("scope"));
    const initial = defaultAssetScope(context);
    const target = query.get("target") ?? undefined;
    const kind = query.get("kind") ?? undefined;
    const job = query.get("job") ?? undefined;
    return {
      area: "assets",
      context,
      generate: pathname.endsWith("/generate"),
      filters: {
        scope: requestedScope && assetScopes.indexOf(requestedScope) > assetScopes.indexOf(initial)
          ? requestedScope : undefined,
        target: story && target !== board && isId(target, "brd") ? target : undefined,
        kind: isAssetKind(kind) ? kind : undefined,
        search: assetSearch(query.get("q") ?? undefined),
        job: isId(job, "job") ? job : undefined,
        jobKind: isId(job, "job") && query.get("job_kind") === "matte" ? "matte" : undefined,
      },
    };
  }

  const segments = pathname.split("/").slice(1);
  let area: TreeArea;
  if (segments[0] === "productions") {
    area = "productions";
    segments.splice(0, 1);
  } else if (segments[0] === "editor" && segments[1] === "board") {
    area = "board";
    segments.splice(0, 2);
  } else {
    return missing;
  }

  const [production, media, story, ...tail] = segments;
  if (production !== undefined && !isId(production, "prd") ||
      media !== undefined && !isMedia(media) ||
      story !== undefined && !isId(story, "sty")) return missing;
  const context = { production, media: isMedia(media) ? media : undefined, story };
  if (!tail.length) return { area, context };

  const [branch, item, child] = tail;
  if (branch === "boards" && isId(item, "brd")) {
    if (tail.length === 2) return { area, context: { ...context, board: item } };
    if (area === "board" && tail.length === 3 && child === "photo") {
      return { area, context: { ...context, board: item }, page: "photo" };
    }
  }
  if (area === "board" && branch === "runs") {
    if (tail.length === 1) return { area, context, page: "runs" };
    if (tail.length === 2 && item === "compare") return { area, context, page: "compare" };
  }
  if (area === "productions" && branch === "runs" && tail.length === 2 && isId(item, "run")) {
    return { area, context: { ...context, run: item } };
  }
  return missing;
}

export function routePath(route: Exclude<Route, { area: "editor" | "user" | "admin" | "missing" }>) {
  return route.area === "assets"
    ? assetsPath(route.context, route.generate, route.filters)
    : treePath(route.area, route.context, route.page);
}

/** Only this app's canonical paths may cross a sign-in redirect or be used as saved links. */
export function safePath(value: unknown) {
  if (typeof value !== "string" || value.length > 2048 || /[\\#]/.test(value)) return undefined;
  const [pathname, search = "", extra] = value.split("?");
  if (extra !== undefined) return undefined;
  const route = parseRoute(pathname, search);
  if (route.area !== "assets" && value.length > 512) return undefined;
  switch (route.area) {
    case "missing": return undefined;
    case "editor":
    case "user":
    case "admin":
      return search ? undefined : pathname;
    default:
      return routePath(route);
  }
}
