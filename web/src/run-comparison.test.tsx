import { createHash } from "node:crypto";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import contractSnapshot from "../../docs/contracts/examples/valid/run-snapshot.json";
import { createStudioApi } from "./api/client";
import { BoardComparison } from "./run-compare";
import { compareSnapshots, loadFrozenSnapshot, parseSnapshot, type FrozenBoard } from "./run-comparison";

const reference = {
  story_id: contractSnapshot.story.id,
  snapshot: { sha256: "a".repeat(64), story_revision: contractSnapshot.story.revision, board_count: contractSnapshot.story.boards.length },
};

function makeBoard(id: string): FrozenBoard {
  return {
    id, title: "Panel", method: { layer: "layered", motion: "s2v" },
    lines: [{ speaker: "a", text: "First take", gap_before_ms: null }],
    photo: { current_version_id: "photo-one" }, voice: { current_version_id: "voice-one" },
  };
}

describe("frozen snapshot comparison", () => {
  it("reads the canonical snapshot in board order and rejects the wrong story, revision or board set", () => {
    const shuffled = structuredClone(contractSnapshot);
    shuffled.story.boards.reverse();
    expect(parseSnapshot(shuffled, reference)?.boards.map(({ id }) => id)).toEqual(contractSnapshot.story.board_order);
    expect(parseSnapshot(shuffled, { ...reference, story_id: "another-story" })).toBeUndefined();
    expect(parseSnapshot(shuffled, { ...reference, snapshot: { ...reference.snapshot, story_revision: 99 } })).toBeUndefined();
    shuffled.story.board_order[0] = "missing";
    expect(parseSnapshot(shuffled, reference)).toBeUndefined();
  });

  it("pairs by stable ID and records added, removed, reordered, script, version and method changes", () => {
    const [first, second, removed, fixed] = ["first", "second", "removed", "fixed"].map(makeBoard);
    const added = makeBoard("added");
    const changed: FrozenBoard = {
      ...first,
      lines: [{ speaker: "b", text: "Second take", gap_before_ms: 500 }],
      photo: { current_version_id: "photo-two" }, voice: { current_version_id: null },
      method: { layer: "whole_frame", motion: "i2v" },
    };
    const rows = compareSnapshots({ boards: [first, second, removed, fixed] }, { boards: [added, second, changed, fixed] });
    expect(rows.map(({ id, changes }) => [id, changes])).toEqual([
      ["added", ["Added"]], ["second", ["Reordered"]],
      ["first", ["Reordered", "Script", "Photo version", "Voice version", "Method"]],
      ["fixed", []], ["removed", ["Removed"]],
    ]);
    const row = rows.find(({ id }) => id === first.id)!;
    expect(row.from?.index).toBe(0);
    expect(row.to?.index).toBe(2);
    expect(row.from?.board.photo.current_version_id).toBe("photo-one");
    expect(row.to?.board.photo.current_version_id).toBe("photo-two");
    expect(row.from?.board.voice.current_version_id).toBe("voice-one");
    expect(row.to?.board.voice.current_version_id).toBe(null);
  });

  it("distinguishes index shifts caused by an insertion from a reorder", () => {
    const [first, second, added] = ["first", "second", "added"].map(makeBoard);
    const rows = compareSnapshots({ boards: [first, second] }, { boards: [added, first, second] });
    expect(rows.map(({ changes }) => changes)).toEqual([["Added"], [], []]);
  });

  it("reads exact snapshot bytes by hash and handles a missing or mismatched blob", async () => {
    const origin = "https://studio.example.invalid";
    const { signal } = new AbortController();
    const bytes = JSON.stringify(contractSnapshot);
    const sha256 = createHash("sha256").update(bytes).digest("hex");
    const ref = { ...reference, snapshot: { ...reference.snapshot, sha256 } };
    const api = (body: string | null) => createStudioApi(origin, signal, () => {}, async (input) => {
      expect((input as Request).url).toBe(`${origin}/v1/media/${sha256}`);
      return new Response(body, body ? { headers: { "Content-Type": "application/json" } } : { status: 404 });
    }).client;

    await expect(loadFrozenSnapshot(api(bytes), ref, signal)).resolves.toEqual(parseSnapshot(contractSnapshot, ref));
    await expect(loadFrozenSnapshot(api(bytes + "\n"), ref, signal)).resolves.toBeUndefined();
    await expect(loadFrozenSnapshot(api(null), ref, signal)).resolves.toBeUndefined();
  });

  it("renders stable board IDs, positions, version IDs and field changes in the comparison", () => {
    const first = makeBoard("board-first");
    const second = makeBoard("board-second");
    const html = renderToStaticMarkup(<BoardComparison left={{ boards: [first, second, makeBoard("board-removed")] }}
      right={{ boards: [second, { ...first, photo: { current_version_id: "photo-two" }, voice: { current_version_id: "voice-two" } },
        makeBoard("board-added")] }} leftRun={1} rightRun={2} />);
    for (const expected of [
      "board-first", "Board 01", "Board 02", "Reordered · Photo version · Voice version",
      "photo-one", "photo-two", "voice-one", "voice-two", "board-added", "Added", "board-removed", "Removed",
    ]) expect(html).toContain(expected);
  });
});
