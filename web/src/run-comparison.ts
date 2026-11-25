import { ApiError, type StudioClient } from "./api/client";
import type { Board } from "./route-data";
import { readObject } from "./production-review-data";
import type { RunView } from "./run-data";

export type FrozenBoard = Pick<Board, "id" | "title" | "method"> & {
  lines: { speaker: string; text: string; gap_before_ms: number | null }[];
  photo: { current_version_id: string | null };
  voice: { current_version_id: string | null };
};
export type FrozenSnapshot = { boards: FrozenBoard[] };
type SnapshotRef = Pick<RunView, "story_id"> & {
  snapshot: Pick<RunView["snapshot"], "sha256" | "story_revision" | "board_count">;
};

export function parseSnapshot(value: unknown, run: SnapshotRef): FrozenSnapshot | undefined {
  const { schema, story: rawStory } = readObject(value);
  const { id, revision, boards, board_order } = readObject(rawStory);
  if (schema !== "studio.run-snapshot/v1" || id !== run.story_id || revision !== run.snapshot.story_revision ||
      !Array.isArray(boards) || !Array.isArray(board_order) || boards.length !== run.snapshot.board_count ||
      boards.length !== board_order.length || new Set(board_order).size !== boards.length) return;

  const byId = new Map<string, FrozenBoard>();
  for (const raw of boards) {
    const board = readObject(raw);
    const { id, title, lines, photo, voice, method } = board;
    const layer = readObject(method).layer;
    const motion = readObject(method).motion;
    const versionSelected = (asset: unknown) => {
      const version = readObject(asset).current_version_id;
      return typeof version === "string" || version === null;
    };
    if (typeof id !== "string" || typeof title !== "string" || !Array.isArray(lines) ||
        !lines.every((raw: unknown) => {
          const { speaker, text, gap_before_ms } = readObject(raw);
          return typeof speaker === "string" && typeof text === "string" &&
            (typeof gap_before_ms === "number" || gap_before_ms === null);
        }) || !versionSelected(photo) || !versionSelected(voice) ||
        (layer !== "layered" && layer !== "whole_frame") || (motion !== "s2v" && motion !== "i2v")) return;
    byId.set(id, board as FrozenBoard);
  }

  const ordered = board_order.map((id: unknown) => typeof id === "string" ? byId.get(id) : undefined);
  return ordered.every((board) => board !== undefined) ? { boards: ordered } : undefined;
}

export async function loadFrozenSnapshot(api: StudioClient, run: SnapshotRef, signal: AbortSignal) {
  const { sha256 } = run.snapshot;
  if (!/^[a-f0-9]{64}$/.test(sha256)) return;
  try {
    const { data, response } = await api.GET("/v1/media/{sha256}", {
      signal, params: { path: { sha256 } }, parseAs: "arrayBuffer",
    });
    if (!data || response.headers.get("Content-Type")?.split(";")[0] !== "application/json") return;
    const hash = await crypto.subtle.digest("SHA-256", data);
    const digest = Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, "0")).join("");
    if (digest !== sha256) return;
    return parseSnapshot(JSON.parse(new TextDecoder().decode(data)), run);
  } catch (error) {
    if (error instanceof SyntaxError || (error instanceof ApiError && error.status === 404)) return;
    throw error;
  }
}

function script(board: FrozenBoard) {
  return JSON.stringify(board.lines.map(({ speaker, text, gap_before_ms }) => [speaker, text, gap_before_ms]));
}

function boardIndex(boards: FrozenBoard[]) {
  return new Map(boards.map((board, index) => [board.id, { board, index }]));
}

function boardsInSameOrder(before: Iterable<string>, after: ReadonlyMap<string, { index: number }>) {
  const shared = [...before].flatMap((id) => {
    const entry = after.get(id);
    return entry ? [{ id, position: entry.index }] : [];
  });
  // Keep a longest increasing subsequence of positions. Each entry in ends
  // indexes the lowest-position board that can end a subsequence of that length.
  const ends: number[] = [];
  const previous: (number | undefined)[] = [];
  for (const [index, { position }] of shared.entries()) {
    let low = 0;
    let high = ends.length;
    while (low < high) {
      const middle = Math.floor((low + high) / 2);
      if (shared[ends[middle]].position < position) low = middle + 1;
      else high = middle;
    }
    previous[index] = low > 0 ? ends[low - 1] : undefined;
    ends[low] = index;
  }

  const unchanged = new Set<string>();
  for (let index = ends.at(-1); index !== undefined; index = previous[index]) {
    unchanged.add(shared[index].id);
  }
  return unchanged;
}

export function compareSnapshots(before: FrozenSnapshot, after: FrozenSnapshot) {
  const left = boardIndex(before.boards);
  const right = boardIndex(after.boards);
  const unchangedOrder = boardsInSameOrder(left.keys(), right);
  return [...new Set([...right.keys(), ...left.keys()])].map((id) => {
    const from = left.get(id);
    const to = right.get(id);
    const changes: string[] = [];
    if (!from) changes.push("Added");
    else if (!to) changes.push("Removed");
    else {
      if (!unchangedOrder.has(id)) changes.push("Reordered");
      if (script(from.board) !== script(to.board)) changes.push("Script");
      if (from.board.photo.current_version_id !== to.board.photo.current_version_id) changes.push("Photo version");
      if (from.board.voice.current_version_id !== to.board.voice.current_version_id) changes.push("Voice version");
      if (from.board.method.layer !== to.board.method.layer ||
          from.board.method.motion !== to.board.method.motion) changes.push("Method");
    }
    return { id, from, to, changes };
  });
}
