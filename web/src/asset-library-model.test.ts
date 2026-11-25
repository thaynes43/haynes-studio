import { describe, expect, test } from "vitest";

import { assetKinds, assetPreview, assetTarget, assetUseProblem, groupAssets, visibleAssetScope, widenAssetScope } from "./asset-library-model";
import type { AssetVersion } from "./photo-composer-model";
import { assetsPath, parseRoute, routePath, safePath, type AssetScope } from "./routes";
import { readDestinations } from "./selections";

const target = {
  production: "prd_01M79V9FC00000000000000001",
  media: "short",
  story: "sty_01M79V9FC00000000000000001",
  board: "brd_01M79V9FC00000000000000001",
} as const;
const otherBoard = "brd_01M79V9FC00000000000000002";
const job = "job_01M79V9FC00000000000000001";
const version: AssetVersion = {
  schema: "studio.asset-version/v1", id: "asv_01M79V9FC00000000000000001",
  asset_id: "ast_01M79V9FC00000000000000001", kind: "prop", number: 1, name: "Café tray", labels: ["Dining"],
  scope: { production_id: target.production }, attributes: {}, capabilities: ["opaque_photo"], legacy: null,
  state: "promoted", content: { sha256: "a".repeat(64), bytes: 20, media_type: "image/png", locator: "fixture" },
  provenance: { origin: "generated", created_at: "2026-11-04T00:00:00Z", created_by: { kind: "cli" },
    generator: { role: "image" } },
};

function parse(path: string) {
  const url = new URL(path, "https://studio.example.invalid");
  const route = parseRoute(url.pathname, url.search);
  if (route.area !== "assets") throw new Error("Expected an Assets URL");
  return route;
}

describe("asset library filters", () => {
  test("widens the board, story and production filters while retaining the target", () => {
    let route = parse(assetsPath(target));
    const levels: AssetScope[] = [visibleAssetScope(route.context, route.filters)];
    for (const level of ["board", "story", "production"] as const) {
      route = parse(assetsPath(route.context, false, { scope: widenAssetScope(level) }));
      levels.push(visibleAssetScope(route.context, route.filters));
      expect(assetTarget(route.context, route.filters)).toEqual(target);
    }
    expect(levels).toEqual(["board", "story", "production", "library"]);
    expect(visibleAssetScope({}, {})).toBe("library");
  });

  test("keeps filter, target and candidate across a URL round trip and saved selections", () => {
    const filters = { scope: "story", target: otherBoard, kind: "character_card", search: "café & tea #1", job } as const;
    const url = assetsPath(target, false, filters);
    expect(parse(url).filters).toEqual(filters);
    expect(routePath(parse(url))).toBe(url);
    expect(readDestinations({ web_shell: { assets: url } }).assets).toBe(url);
    expect(assetTarget(target, filters)?.board).toBe(otherBoard);
    expect(safePath(assetsPath(target, false, { ...filters, search: "茶".repeat(180) }))).toBeTruthy();
    expect(parse("/editor/assets?scope=board&target=bad&kind=%2Fetc&job=bad&q=a%5Cb").filters).toEqual({
      search: "ab", scope: undefined, target: undefined, kind: undefined, job: undefined,
    });
  });

  test("discovers kinds from results, searches normalized names and labels, and orders versions newest first", () => {
    const newer = { ...version, id: "asv_01M79V9FC00000000000000002", number: 2 };
    const hidden = { ...version, id: "asv_01M79V9FC00000000000000003", number: 3, state: "candidate" } as const;
    const declared = { ...version, asset_id: "ast_01M79V9FC00000000000000002", kind: "character_card", name: "Outline" } as const;
    const visible = [version, newer, hidden, declared];
    expect(assetKinds(visible)).toEqual(["character_card", "prop"]);
    expect(groupAssets(visible, { search: "CAFE\u0301", kind: "prop" })).toEqual([[newer, version]]);
    expect(groupAssets(visible, { search: "Dining", kind: "character_card" })).toEqual([[declared]]);
  });
});

describe("asset use and private previews", () => {
  test("only an eligible promoted still with media can return to the target board", () => {
    expect(assetUseProblem(version, target, false)).toBeUndefined();
    expect(assetUseProblem({ ...version, state: "candidate" }, target, false)).toBe("Promote before use");
    expect(assetUseProblem({ ...version, state: "candidate" }, target, false, true)).toBe("Declined candidate");
    expect(assetUseProblem({ ...version, recorded_without_media: true }, target, false)).toBe("Recorded without media");
    expect(assetUseProblem({ ...version, scope: { production_id: null } }, target, false)).toBeUndefined();
    expect(assetUseProblem({ ...version, scope: { production_id: otherBoard } }, target, false)).toMatch(/Unavailable/);
    expect(assetUseProblem({ ...version, content: null }, target, false)).toBe("No media");
    expect(assetUseProblem(version, target, true)).toMatch(/Layered/);
    expect(assetUseProblem({ ...version, kind: "sound" }, target, false)).toMatch(/Unavailable/);
  });

  test("chooses canonical preview endpoints and skips records without media", () => {
    const hash = version.content!.sha256;
    expect(assetPreview(version)?.url).toBe(`/v1/media/${hash}`);
    expect(assetPreview({ ...version, state: "candidate" })?.url).toBe(`/v1/asset-versions/${version.id}/media/${hash}`);
    expect(assetPreview({ ...version, state: "board", kind: "photo" })?.url).toBe(`/v1/asset-versions/${version.id}/media/${hash}`);
    expect(assetPreview(version, job)?.url).toBe(`/v1/jobs/${job}/media/${hash}`);
    expect(assetPreview({ ...version, scope: { production_id: null },
      provenance: { ...version.provenance, source_key: `asset-candidate:${job}` } })?.url).toBe(`/v1/jobs/${job}/media/${hash}`);
    expect(assetPreview({ ...version, recorded_without_media: true }, job)).toBeUndefined();
    expect(assetPreview(version, "../jobs")?.url).toBe(`/v1/media/${hash}`);
  });
});
