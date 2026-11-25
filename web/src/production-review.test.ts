import { expect, test } from "vitest";
import { approvalRefusal } from "./production-approval";
import { readProductionFilters, toggleProductionFilter } from "./production-filters";
import { freshSignIn, mediaUrl, releaseChecksPass } from "./production-review-data";
import { safePath, treePath } from "./routes";

test("filter toggles combine approval with one publication state at a time", () => {
  const initial = readProductionFilters({ publication: "bad", approved: "true" });
  expect(initial).toEqual({});
  const unpublished = toggleProductionFilter(initial, "unpublished");
  const both = toggleProductionFilter(unpublished, "approved");
  expect(both).toEqual({ publication: "unpublished", approved: true });
  expect(toggleProductionFilter(both, "published")).toEqual({ publication: "published", approved: true });
  expect(toggleProductionFilter(both, "unpublished")).toEqual({ approved: true });
  expect(toggleProductionFilter(both, "approved")).toEqual(unpublished);
});

test("approval evidence must match the exact delivered master and include all passed checks", () => {
  const master = "a".repeat(64);
  const delivery = "dlv_01M79V9FC00000000000000001";
  const label = {
    result: "pass", platform_setting: true, description_line: true,
    description: "This video was AI-generated.",
  };
  const checks = {
    delivery: { result: "pass", master_sha256: master, delivery_id: delivery },
    licences: { result: "pass" },
    ai_label: label,
  };
  expect(releaseChecksPass(checks, master, delivery)).toBe(true);
  expect(releaseChecksPass(checks, "b".repeat(64), delivery)).toBe(false);
  expect(releaseChecksPass(checks, master, "different")).toBe(false);
  expect(releaseChecksPass({ ...checks, licences: { result: "fail" } }, master, delivery)).toBe(false);
  expect(releaseChecksPass({ ...checks, ai_label: { ...label, platform_setting: false } }, master, delivery)).toBe(false);
  expect(releaseChecksPass(null, master, delivery)).toBe(false);
});

test("same-origin media and re-sign-in URLs use canonical hashes and run routes", () => {
  const hash = "a".repeat(64);
  expect(mediaUrl(hash)).toBe(`/v1/media/${hash}`);
  expect(mediaUrl(hash + "?token=value")).toBeUndefined();
  expect(mediaUrl("https://example.invalid/video")).toBeUndefined();
  const path = treePath("productions", {
    production: "prd_01M79V9FC00000000000000001",
    media: "short",
    story: "sty_01M79V9FC00000000000000001",
    run: "run_01M79V9FC00000000000000001",
  });
  expect(safePath(path)).toBe(path);
  expect(safePath(path.replace("/runs/run_", "/runs/sty_"))).toBeUndefined();
  const login = new URL(freshSignIn(path), "https://studio.example.invalid");
  expect(login.pathname).toBe("/auth/login");
  expect(login.searchParams.get("return_to")).toBe(path);
  expect(login.searchParams.get("fresh")).toBe("true");
});

test("unrecognized refusal codes fall back to the shell's generic problem", () => {
  expect(approvalRefusal("approval.unknown")).toBeUndefined();
  expect(approvalRefusal("constructor")).toBeUndefined();
  expect(approvalRefusal(null)).toBeUndefined();
});
