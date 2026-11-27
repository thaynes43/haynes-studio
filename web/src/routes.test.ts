import { describe, expect, test } from "vitest";
import { assetSearchLimit, assetsPath, liveAssetFilters, parseRoute, safePath, safeReturnPath, treePath } from "./routes";
import { readDestinations } from "./selections";

const production = "prd_01M79V9FC00000000000000001";
const media = "short" as const;
const story = "sty_01M79V9FC00000000000000001";
const board = "brd_01M79V9FC00000000000000002";
const context = { production, media, story, board };

describe("shell routes", () => {
  test("a filter change starts from the address, not from filters one render behind", () => {
    // The page last rendered with "sOu"; the address already holds the next key.
    const rendered = { scope: "library" as const, kind: "prop", search: "sOu" };
    const address = assetsPath(context, false, { ...rendered, search: "sOuP" });
    const [pathname, search] = address.split("?");
    const live = liveAssetFilters(rendered, pathname, "?" + search);
    expect(live.search).toBe("sOuP");
    expect(assetsPath(context, false, { ...live, target: board })).toContain("q=sOuP");
    // Away from an Assets address the rendered filters are all there is.
    expect(liveAssetFilters(rendered, "/editor", "")).toBe(rendered);
  });

  test("deep routes preserve their own entity context", () => {
    const path = treePath("board", context, "photo");
    expect(parseRoute(path)).toEqual({ area: "board", context, page: "photo" });
    expect(safePath(path)).toBe(path);

    const scoped = assetsPath(context, true);
    expect(safePath(scoped)).toBe(scoped);
    const [pathname, search] = scoped.split("?");
    expect(parseRoute(pathname, search)).toMatchObject({ area: "assets", context, generate: true });
  });

  test("dropping a scope removes all of its descendants", () => {
    expect(assetsPath({ production })).toBe(`/editor/assets?production=${production}`);
    expect(treePath("board", { production })).toBe(`/editor/board/${production}`);
  });

  test("preserves the Format fragment for a storyboard in the sign-in return path", () => {
    const storyPath = treePath("board", { production, media, story });
    const boardPath = treePath("board", context);
    expect(safeReturnPath(storyPath + "#story-format")).toBe(storyPath + "#story-format");
    expect(safeReturnPath(boardPath + "#story-format")).toBe(boardPath + "#story-format");
    expect(safeReturnPath(treePath("board", context, "photo") + "#story-format")).toBeUndefined();
    expect(safeReturnPath("/editor/board#story-format")).toBeUndefined();
    expect(safeReturnPath("/productions#story-format")).toBeUndefined();
    expect(safeReturnPath("//example.invalid" + storyPath + "#story-format")).toBeUndefined();
    expect(safeReturnPath(storyPath + "#story-format#other")).toBeUndefined();
    expect(safeReturnPath(storyPath + "#other")).toBeUndefined();
  });

  test("caps a crafted Assets search query at the input limit", () => {
    const prefix = "a".repeat(assetSearchLimit);
    const query = new URLSearchParams({ q: `${prefix}extra` });
    expect(parseRoute("/editor/assets", query.toString())).toMatchObject({
      area: "assets", filters: { search: prefix },
    });
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
