import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  addPhotoPin, boardPhotoVersions, eligiblePhotoAsset, photoAssetReturn, photoEditAfterSave, photoPreviewUrl, photoResultCurrent,
  rebasePhotoEdit, returnedPhotoAsset, selectedPhotoUrl, type AssetVersion, type PhotoInputs, type PhotoJob,
} from "./photo-composer-model";
import type { Board } from "./route-data";
import { pollInterval, pollRuns } from "./run-polling";

const scope = {
  production: "prd_01M79V9FC00000000000000001", media: "short",
  story: "sty_01M79V9FC00000000000000001", board: "brd_01M79V9FC00000000000000001",
} as const;
const first = "asv_01M79V9FC00000000000000001";
const second = "asv_01M79V9FC00000000000000002";
const hash = "a".repeat(64);
const before: PhotoInputs = { prompt: "Before", input_asset_version_ids: [first] };
const changed = { ...before, prompt: "After" };
const board = (id: string, state: string) =>
  ({ photo: { current_version_id: id, ...before }, derived: { photo_state: state } }) as Board;
const result = (current: boolean) => ({ status: "succeeded", result_is_current: current, result_version_id: second }) as PhotoJob;

function version(id: string, number: number, created: string): AssetVersion {
  return {
    id, number, kind: "photo", state: "board", scope: {
      production_id: scope.production, story_id: scope.story, board_id: scope.board,
    },
    content: { media_type: "image/png", sha256: hash },
    provenance: { origin: "generated", created_at: created },
  } as AssetVersion;
}

describe("photo composer currency and selection", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("keeps a newer input across durable job reads and respects the API completion flag", async () => {
    const environment = Object.assign(new EventTarget(), { visibilityState: "visible" as const });
    const patch = { base: before, values: changed };
    let saved = before;
    let api = { board: board(first, "generating"), job: { status: "running" } as PhotoJob };
    const onData = vi.fn((value: typeof api) => photoResultCurrent(value.job, value.board, rebasePhotoEdit(patch, saved).dirty));
    const poll = pollRuns(environment, {
      read: async () => api,
      onData(value) { onData(value); return true; },
      onError: () => false,
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(onData).toHaveLastReturnedWith(false);

    api = { board: board(second, "current"), job: result(true) };
    await vi.advanceTimersByTimeAsync(pollInterval);
    expect(onData).toHaveLastReturnedWith(false);
    expect(rebasePhotoEdit(patch, saved)).toEqual({ values: changed, dirty: true, conflict: false });

    saved = changed;
    api = { board: board(first, "stale"), job: result(false) };
    await vi.advanceTimersByTimeAsync(pollInterval);
    expect(onData).toHaveLastReturnedWith(false);
    expect(photoResultCurrent(result(false), board(second, "current"), false)).toBe(false);
    expect(photoResultCurrent(result(true), board(first, "current"), false)).toBe(false);
    expect(photoResultCurrent(result(true), board(second, "stale"), false)).toBe(false);
    expect(photoResultCurrent(result(true), board(second, "current"), false)).toBe(true);
    poll.stop();
  });

  it("rebases independent edits, preserves order and asks about the same field", () => {
    const extraPin = addPhotoPin(before, second);
    const edit = { base: before, values: extraPin };
    expect(rebasePhotoEdit(edit, changed)).toEqual({
      values: { ...changed, input_asset_version_ids: [first, second] }, dirty: true, conflict: false,
    });
    expect(rebasePhotoEdit(edit, { ...before, input_asset_version_ids: [] }).conflict).toBe(true);
    expect(rebasePhotoEdit(edit, extraPin).dirty).toBe(false);
    expect(addPhotoPin(extraPin, first)).toBe(extraPin);
  });

  it("keeps a prompt changed during a revision retry and preserves an independent saved pin", () => {
    const sent = { base: before, values: changed };
    const retried = { ...changed, input_asset_version_ids: [second] };
    const later = { base: before, values: { ...before, prompt: "Newer prompt" } };
    expect(photoEditAfterSave(sent, later, retried)).toEqual({
      base: retried, values: { ...retried, prompt: "Newer prompt" },
    });
    expect(photoEditAfterSave(sent, { base: before, values: before }, retried)?.values)
      .toEqual({ ...before, input_asset_version_ids: [second] });
    expect(photoEditAfterSave(sent, sent, retried)).toBeUndefined();
  });

  it("filters board history, sorts by creation time and blocks media for a recorded-only pin", () => {
    const original = version(first, 9, "2026-11-01T00:00:00Z");
    const imported = { ...version(second, 1, "2026-11-03T00:00:00Z"), recorded_without_media: true } as const;
    const foreign = { ...original, scope: { ...original.scope, board_id: "another-board" } };
    expect(boardPhotoVersions([original, foreign, imported], scope)).toEqual([imported, original]);
    expect(selectedPhotoUrl(original)).toBe(`/v1/media/${hash}`);
    expect(photoPreviewUrl(original)).toBe(`/v1/asset-versions/${first}/media/${hash}`);
    expect(selectedPhotoUrl(imported)).toBeUndefined();
    expect(photoPreviewUrl(imported)).toBeUndefined();
  });

  it("checks return path, ID and catalog scope before adding a returned version", () => {
    const { to, state } = photoAssetReturn(scope, first);
    const asset = {
      ...version(first, 1, "2026-11-01T00:00:00Z"), kind: "prop", state: "promoted", scope: { production_id: null },
    } as const;
    expect(returnedPhotoAsset(state, to, scope)).toBe(first);
    expect(returnedPhotoAsset(state, to.replace("/photo", ""), scope)).toBeUndefined();
    expect(returnedPhotoAsset({ photoAssetVersionId: "/v1/media/abc" }, to, scope)).toBeUndefined();
    expect(eligiblePhotoAsset(asset, scope)).toBe(true);
    expect(eligiblePhotoAsset({ ...asset, state: "candidate" }, scope)).toBe(false);
    expect(eligiblePhotoAsset({ ...asset, recorded_without_media: true }, scope)).toBe(false);
    expect(eligiblePhotoAsset({ ...asset, scope: { production_id: "other" } }, scope)).toBe(false);
  });
});
