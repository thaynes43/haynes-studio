import type { components } from "./api/schema";

export type StoryTiming = components["schemas"]["Timing"];

export function boardPosition(index: number) {
  return `Board ${String(index + 1).padStart(2, "0")}`;
}

export function selectBoard(order: readonly string[], requested?: string, previousOrder?: readonly string[]) {
  if (requested && order.includes(requested)) return requested;
  if (!requested || !previousOrder) return order[0];
  const lastIndex = previousOrder.indexOf(requested);
  if (lastIndex < 0) return order[0];

  const active = new Set(order);
  for (let distance = 1; distance < previousOrder.length; distance++) {
    const after = previousOrder[lastIndex + distance];
    const before = previousOrder[lastIndex - distance];
    if (active.has(after)) return after;
    if (active.has(before)) return before;
  }
  return order[Math.min(lastIndex, order.length - 1)];
}

export function moveBoard(order: readonly string[], id: string, direction: -1 | 1) {
  const from = order.indexOf(id);
  const to = from + direction;
  if (from < 0 || to < 0 || to >= order.length) return undefined;
  const changed = [...order];
  [changed[from], changed[to]] = [changed[to], changed[from]];
  return changed;
}

const frameSeconds = (frames: number, fps: number) => (frames / fps).toFixed(3);
const millisSeconds = (ms: number) => (ms / 1000).toString();

export function timelineLabels(timing: StoryTiming) {
  const { fps, format_length: range } = timing;
  const boards = new Map(timing.boards.map(({ board_id, frames, film_start_frame }) => [board_id, {
    length: frames === null ? "Timing pending" : `${frameSeconds(frames, fps)} s`,
    range: frames === null || film_start_frame === null
      ? "Timing pending"
      : `${frameSeconds(film_start_frame, fps)}–${frameSeconds(film_start_frame + frames, fps)} s`,
  }]));
  return {
    boards,
    length: `${timing.complete ? "" : "At least "}${frameSeconds(timing.frames_known, fps)} s`,
    advisory: range ? `Target ${millisSeconds(range.min_ms)}–${millisSeconds(range.max_ms)} s` : undefined,
    warning: timing.warnings.find(({ code }) => code === "format.length_exceeded")?.message,
  };
}
