import { describe, expect, it } from "vitest";

import { boardPosition, moveBoard, selectBoard, timelineLabels, type StoryTiming } from "./storyboard-timeline";

const timing: StoryTiming = {
  schema: "studio.story-timing/v1", story_id: "story", story_revision: 5, fps: 24,
  frames_known: 58, complete: false, format_length: { format_version_id: "format", min_ms: 500, max_ms: 2200 },
  warnings: [{ code: "format.length_exceeded", severity: "warning", build_allowed: true, message: "Timed boards exceed the target." }],
  build_allowed: false, build_blockers: [{ board_id: "next", code: "voice.absent" }],
  boards: [
    { board_id: "opening", state: "timed", film_start_frame: 0, frames: 22 },
    { board_id: "next", state: "untimed", film_start_frame: null, frames: null, reason: "voice.absent" },
    { board_id: "hold", state: "timed", film_start_frame: null, frames: 36 },
  ],
};

describe("storyboard timeline", () => {
  it("displays canonical frame lengths, positions, lower bound, and advisory", () => {
    const labels = timelineLabels(timing);
    expect(labels.boards.get("opening")).toEqual({ length: "0.917 s", range: "0.000–0.917 s" });
    expect(labels.boards.get("next")).toEqual({ length: "Timing pending", range: "Timing pending" });
    expect(labels.boards.get("hold")).toEqual({ length: "1.500 s", range: "Timing pending" });
    expect(labels.length).toBe("At least 2.417 s");
    expect(labels.advisory).toBe("Target 0.5–2.2 s");
    expect(labels.warning).toBe("Timed boards exceed the target.");
  });

  it("displays complete and empty totals using the API's frame sum", () => {
    const complete = timelineLabels({ ...timing, complete: true, format_length: null, warnings: [] });
    expect(complete).toMatchObject({ length: "2.417 s", advisory: undefined, warning: undefined });
    const empty = timelineLabels({ ...timing, boards: [], complete: true, frames_known: 0 });
    expect(empty.length).toBe("0.000 s");
  });

  it("moves stable IDs and displays their new positions", () => {
    const order = ["c", "a", "b"] as const;
    const earlier = moveBoard(order, "a", -1)!;
    const later = moveBoard(order, "a", 1)!;
    expect(earlier).toEqual(["a", "c", "b"]);
    expect(later).toEqual(["c", "b", "a"]);
    expect(boardPosition(later.indexOf("a"))).toBe("Board 03");
    expect(order).toEqual(["c", "a", "b"]);
    expect(moveBoard(order, "missing", 1)).toBeUndefined();
    expect(moveBoard(order, "c", -1)).toBeUndefined();
    expect(moveBoard(order, "b", 1)).toBeUndefined();
  });

  it("keeps a surviving ID, otherwise prefers its former slot and falls back to the first board", () => {
    const previously = ["a", "b", "c"];
    expect(selectBoard(["b", "c", "a"], "b", previously)).toBe("b");
    expect(selectBoard(["a", "c"], "b", previously)).toBe("c");
    expect(selectBoard(["a", "b"], "c", previously)).toBe("b");
    expect(selectBoard(["d", "a"], "c", ["a", "b", "c", "d"])).toBe("d");
    expect(selectBoard(["a", "b"], "unknown", previously)).toBe("a");
    expect(selectBoard(["a", "b"])).toBe("a");
    expect(selectBoard([], "a", previously)).toBeUndefined();
  });
});
