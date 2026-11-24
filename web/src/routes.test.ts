import { describe, expect, test } from "vitest";
import { assetsPath, parseRoute, safePath, treePath } from "./routes";
import { readDestinations } from "./selections";

const production = "prd_01M79V9FC00000000000000001";
const media = "short" as const;
const story = "sty_01M79V9FC00000000000000001";
const board = "brd_01M79V9FC00000000000000002";
const context = { production, media, story, board };

describe("shell routes", () => {
  test("deep routes preserve their own entity context", () => {
    const path = treePath("board", context, "photo");
    expect(parseRoute(path)).toEqual({ area: "board", context, page: "photo" });
    expect(safePath(path)).toBe(path);

    const scoped = assetsPath(context, true);
    expect(safePath(scoped)).toBe(scoped);
    const [pathname, search] = scoped.split("?");
    expect(parseRoute(pathname, search)).toEqual({ area: "assets", context, generate: true });
  });

  test("dropping a scope removes all of its descendants", () => {
    expect(assetsPath({ production })).toBe(`/editor/assets?production=${production}`);
    expect(treePath("board", { production })).toBe(`/editor/board/${production}`);
  });

  test.each([
    "//example.invalid/productions",
    "https://example.invalid/productions",
    "/editor/board/..",
    "/editor/board/%2f",
    "/editor/assets?board=" + board,
    "/editor/board/" + story + "/short",
    "/editor/board/" + production + "/thread",
    "/auth/login",
    "/editor#https://example.invalid",
  ])("rejects an unsupported return path %s", (path) => {
    expect(safePath(path)).toBeUndefined();
  });
});

test("selects only valid destinations from their own route groups", () => {
  const storedBoard = treePath("board", context);
  expect(readDestinations({
    web_shell: {
      productions: "/editor/board",
      assets: "/editor/assets/generate",
      board: storedBoard,
    },
  })).toEqual({ productions: "/productions", assets: "/editor/assets", board: storedBoard });
  expect(readDestinations({ web_shell: ["broken"] })).toEqual({
    productions: "/productions", assets: "/editor/assets", board: "/editor/board",
  });
});
