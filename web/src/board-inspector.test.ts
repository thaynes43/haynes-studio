import { afterEach, describe, expect, it, vi } from "vitest";

import { currentResult, currentVoiceId, voicePreviewUrl, type VoiceJob } from "./board-inspector-api";
import {
  boardPatch, changeLines, freshDraft, inspectorStore, keepChanges, methodOptions,
  moveLine, reconcileDraft, voiceInputChanged,
} from "./board-inspector-draft";
import type { Board } from "./route-data";

const version = "asv_01M79V9FC00000000000000001";
const board: Board = {
  schema: "studio.board/v1",
  id: "brd_01M79V9FC00000000000000001",
  story_id: "sty_01M79V9FC00000000000000001",
  number: 1, revision: 1, title: "Opening",
  drafted_by: { kind: "human" }, origin: null,
  cast: [{ slot: "a", asset_version_id: version }],
  lines: [{ id: "lin_01M79V9FC00000000000000001", speaker: "a", text: "Saved script", gap_before_ms: null }],
  notes: [{ id: "nte_01M79V9FC00000000000000001", text: "Original note" }], cues: [],
  timing: { lead_ms: 500, tail_ms: 700, hold_ms: null },
  voice: { style: "cast", current_version_id: null },
  photo: { current_version_id: null, prompt: null, input_asset_version_ids: [] },
  method: { layer: "layered", motion: "s2v" }, layout: { preset: "default", foreground: true }, seeds: {},
  derived: {
    content_ms: null, frames: null, film_start_frame: 0, timing_state: "untimed", voice_state: "absent", photo_state: "absent",
  },
};

const completed: VoiceJob = {
  schema: "studio.job/v1", id: "job_01M79V9FC00000000000000001", target_id: board.id, kind: "voice",
  status: "succeeded", result_is_current: true, result_version_id: version, error: null, updated_at: "2026-11-04T12:01:00Z",
};
const voiced: Board = {
  ...board, revision: 2, voice: { ...board.voice, current_version_id: version },
  derived: { ...board.derived!, content_ms: 2000, frames: 48, timing_state: "timed", voice_state: "current" },
};

function withLocalLine(text: string) {
  const draft = freshDraft(board);
  return { ...draft, values: { ...draft.values, lines: [{ ...draft.values.lines[0], text }] } };
}

afterEach(() => vi.useRealTimers());

describe("draft reconciliation", () => {
  it("preserves the active editor and uses the read revision when only media changes", () => {
    vi.useFakeTimers();
    let draft = withLocalLine("New words being typed");
    setTimeout(() => { draft = reconcileDraft(draft, voiced); }, 5000);
    vi.advanceTimersByTime(5000);
    expect(draft.revision).toBe(2);
    expect(draft.values.lines[0].text).toBe("New words being typed");
    expect(draft.review).toBeUndefined();
    expect(voiceInputChanged(draft, voiced)).toBe(true);
    expect(currentResult(completed, voiced, true)).toBe(false);
    expect(currentVoiceId(voiced, [completed], true)).toBeUndefined();
    expect(boardPatch(draft, voiced)).toEqual({ lines: [{ ...board.lines[0], text: "New words being typed" }] });
  });

  it("requires review when saved fields change and keeps unedited fields from the newer board", () => {
    vi.useFakeTimers();
    const newer = {
      ...board, revision: 3, lines: [{ ...board.lines[0], text: "Saved elsewhere" }],
      notes: [{ ...board.notes[0], text: "New server note" }],
    };
    let local = withLocalLine("Local edit");
    setTimeout(() => { local = reconcileDraft(local, newer); }, 5000);
    vi.advanceTimersByTime(5000);
    expect(local).toMatchObject({ review: true, revision: 1, values: { lines: [{ text: "Local edit" }] } });
    const rebased = keepChanges(local, newer);
    expect(rebased.revision).toBe(3);
    expect(rebased.base.lines[0].text).toBe("Saved elsewhere");
    expect(rebased.values.notes[0].text).toBe("New server note");
    expect(boardPatch(rebased, newer)).toEqual({ lines: [{ ...newer.lines[0], text: "Local edit" }] });
    expect(reconcileDraft({ ...local, review: true }, voiced)).toMatchObject({ revision: 1, review: true });
  });

  it("saves the spoken-to-silent transition in one patch", () => {
    const draft = freshDraft(voiced);
    const values = changeLines(draft.values, [], voiced, null);
    expect(boardPatch({ ...draft, values }, voiced)).toEqual({
      lines: [], timing: { lead_ms: null, tail_ms: null, hold_ms: 1000 },
      voice: { style: null, current_version_id: null }, method: { layer: "layered", motion: "i2v" },
    });
    expect(methodOptions(voiced.cast, [], null)).not.toContainEqual(voiced.method);
  });

  it("makes the first line gap null and initializes a moved line's gap", () => {
    const draft = freshDraft(board);
    const lines = [...draft.values.lines, { key: "new", speaker: "narrator", text: "Second", gap: "550" }];
    const values = { ...draft.values, lines: moveLine(lines, 1, -1) };
    expect(boardPatch({ ...draft, values }, board)).toEqual({
      lines: [
        { speaker: "narrator", text: "Second", gap_before_ms: null },
        { ...board.lines[0], gap_before_ms: 300 },
      ], voice: { style: "narrator", current_version_id: null },
    });
  });
});

describe("voice selection", () => {
  it("requires API currency and the selected version, plus unchanged local inputs", () => {
    expect(currentResult(completed, voiced, false)).toBe(true);
    expect(currentVoiceId(voiced, [completed], false)).toBe(version);
    const stale = { ...completed, result_is_current: false };
    expect(currentResult(stale, voiced, false)).toBe(false);
    expect(currentVoiceId(voiced, [stale], false)).toBeUndefined();
    expect(currentResult(completed, board, false)).toBe(false);
    expect(currentResult(completed, voiced, true)).toBe(false);
    expect(voicePreviewUrl(version, "0".repeat(64))).toBe(`/v1/asset-versions/${version}/media/${"0".repeat(64)}`);
    expect(voicePreviewUrl("../jobs", "0".repeat(64))).toBeUndefined();
    expect(voicePreviewUrl(version, "not a hash")).toBeUndefined();
  });
});

describe("tab persistence", () => {
  it("restores edits and unresolved presses across redraws without sharing between users or boards", () => {
    vi.useFakeTimers();
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
      removeItem: (key: string) => { values.delete(key); },
    } as Storage;
    const store = inspectorStore("one", () => storage);
    const local = { ...withLocalLine("Draft line"), newNote: "Unadded note" };
    setTimeout(() => {
      store.setDraft(board.id, local);
      store.setPress(board.id, { key: "one-press", input: "script-signature" });
    }, 5000);
    vi.advanceTimersByTime(5000);
    const reloaded = inspectorStore("one", () => storage);
    expect(reloaded.draft(board.id)).toEqual(local);
    expect(reloaded.draft("other-board")).toBeUndefined();
    expect(reloaded.press(board.id)).toEqual({ key: "one-press", input: "script-signature" });
    expect(inspectorStore("two", () => storage).draft(board.id)).toBeUndefined();
    reloaded.setDraft(board.id, freshDraft(board));
    reloaded.setPress(board.id);
    expect(inspectorStore("one", () => storage).draft(board.id)).toBeUndefined();
    expect(inspectorStore("one", () => storage).press(board.id)).toBeUndefined();
  });

  it("uses the page's copy when storage fails, including an inaccessible getter", () => {
    const store = inspectorStore("person", () => { throw new Error("Storage blocked"); });
    const local = withLocalLine("Retained in memory");
    expect(store.draft(board.id)).toBeUndefined();
    store.setDraft(board.id, local);
    expect(store.draft(board.id)).toEqual(local);
  });
});
