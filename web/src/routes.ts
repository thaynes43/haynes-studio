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

export type Route =
  | { area: TreeArea; context: Context; page?: BoardPage }
  | { area: "assets"; context: Context; generate: boolean }
  | { area: "editor" | "user" | "admin" | "missing" };

export const mediaKinds = {
  short: { label: "Short", plural: "Shorts", aspect: "9:16" },
  video: { label: "Video", plural: "Videos", aspect: "16:9" },
} satisfies Record<MediaKind, { label: string; plural: string; aspect: string }>;

function isId(value: string | undefined | null, prefix: "prd" | "sty" | "brd" | "run") {
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

export function assetsPath(context: Context = {}, generate = false) {
  const query = new URLSearchParams();
  if (context.production) query.set("production", context.production);
  if (context.board && context.story && context.media) {
    query.set("media", context.media);
    query.set("story", context.story);
    query.set("board", context.board);
  }
  return (generate ? "/editor/assets/generate" : "/editor/assets") + (query.size ? "?" + query : "");
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
    if ((media || story || board) &&
        (!production || !isMedia(media) || !isId(story, "sty") || !isId(board, "brd"))) return missing;
    return {
      area: "assets",
      context: { production, media: isMedia(media) ? media : undefined, story, board },
      generate: pathname.endsWith("/generate"),
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
    ? assetsPath(route.context, route.generate)
    : treePath(route.area, route.context, route.page);
}

/** Only this app's canonical paths may cross a sign-in redirect or be used as saved links. */
export function safePath(value: unknown) {
  if (typeof value !== "string" || value.length > 512 || /[\\#]/.test(value)) return undefined;
  const [pathname, search = "", extra] = value.split("?");
  if (extra !== undefined) return undefined;
  const route = parseRoute(pathname, search);
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
