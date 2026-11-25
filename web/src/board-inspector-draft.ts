import type { components } from "./api/schema";
import type { Board } from "./route-data";

type Schemas = components["schemas"];
export type DraftLine = Pick<Board["lines"][number], "speaker" | "text"> & { id?: string; key: string; gap: string };
export type DraftNote = Schemas["NoteInput"] & { key: string };
export type Method = Board["method"];
export type Recipe = Schemas["FormatRecipe"];
type BoardCue = Schemas["StudioDefs_sound_cue"] | Schemas["StudioDefs_move_cue"] | Schemas["StudioDefs_camera_cue"];
type EditableNumbers<T> = { [K in keyof T]: T[K] extends number ? number | string : T[K] };
export type Anchor = EditableNumbers<Required<Schemas["StudioDefs_anchor"]>>;
export type Cue = Omit<EditableNumbers<Schemas["StudioDefs_sound_cue"]>, "anchor" | "trim_ms"> & {
  anchor: Anchor; trim_ms: [number | string, number | string];
} | Omit<EditableNumbers<Schemas["StudioDefs_move_cue"]>, "anchor"> & { anchor: Anchor }
  | Omit<EditableNumbers<Schemas["StudioDefs_camera_cue"]>, "anchor" | "center_px"> & {
    anchor: Anchor; center_px: [number | string, number | string];
  };

export type Values = {
  lines: DraftLine[];
  timing: { lead: string; tail: string; hold: string };
  method: Method;
  notes: DraftNote[];
  cues: Cue[];
};

export type BoardDraft = {
  revision: number;
  base: Values;
  values: Values;
  newNote: string;
  review?: boolean;
};

const fields = ["lines", "timing", "method", "notes", "cues"] as const;
type Field = typeof fields[number];
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const timeText = (value: unknown) => typeof value === "number" ? String(value) : "";

function cueDraft(cue: BoardCue): Cue {
  const anchor = {
    at_ms: cue.anchor.at_ms ?? 0,
    after_line_id: cue.anchor.after_line_id ?? "",
    offset_ms: cue.anchor.offset_ms ?? 0,
  };
  if (cue.type === "sound") return { ...cue, anchor, trim_ms: cue.trim_ms ?? ["", ""] };
  return { ...cue, anchor };
}

export function boardValues(board: Board): Values {
  return {
    lines: board.lines.map(({ id, speaker, text, gap_before_ms }) =>
      ({ id, key: id, speaker, text, gap: timeText(gap_before_ms) })),
    timing: { lead: timeText(board.timing.lead_ms), tail: timeText(board.timing.tail_ms), hold: timeText(board.timing.hold_ms) },
    method: board.method,
    notes: board.notes.map(({ id, text }) => ({ id, key: id, text })),
    // The generated oneOf exposes the discriminator but drops the fields in each branch.
    cues: (board.cues as BoardCue[]).map(cueDraft),
  };
}

export function freshDraft(board: Board, newNote = ""): BoardDraft {
  const values = boardValues(board);
  return { revision: board.revision, base: values, values, newNote };
}

export function changedFields({ base, values }: BoardDraft) {
  return fields.filter((field) => !same(base[field], values[field]));
}

export function reconcileDraft(local: BoardDraft, board: Board): BoardDraft {
  if (local.review || local.revision === board.revision) return local;
  const latest = freshDraft(board, local.newNote);
  if (!changedFields(local).length) return latest;
  // Job selection and board ordering can advance the revision without editing inspector fields.
  if (board.revision > local.revision && same(local.base, latest.base)) return { ...local, revision: board.revision };
  return { ...local, review: true };
}

function retainExistingIds<T extends { id?: string }>(items: T[], latest: T[]) {
  const ids = new Set(latest.map(({ id }) => id));
  return items.map((item) => ids.has(item.id) ? item : { ...item, id: undefined });
}

export function keepChanges(local: BoardDraft, board: Board): BoardDraft {
  const latest = freshDraft(board, local.newNote);
  const changes = changedFields(local);
  const values = { ...latest.values };
  if (changes.includes("lines")) values.lines = retainExistingIds(local.values.lines, values.lines);
  if (changes.includes("notes")) values.notes = retainExistingIds(local.values.notes, values.notes);
  if (changes.includes("cues")) {
    // The inspector edits existing cues. A deleted cue stays deleted in a rebase.
    const ids = new Set(values.cues.map(({ id }) => id));
    values.cues = local.values.cues.filter(({ id }) => ids.has(id));
    const editedIds = new Set(local.base.cues.map(({ id }) => id));
    values.cues.push(...latest.values.cues.filter(({ id }) => !editedIds.has(id)));
  }
  if (changes.includes("method")) values.method = local.values.method;
  if (changes.includes("timing")) values.timing = local.values.timing;
  return { ...latest, values };
}

export function voiceInputChanged(local: BoardDraft, board: Board) {
  const saved = boardValues(board);
  return !same(local.values.lines, saved.lines) || local.values.timing.lead !== saved.timing.lead;
}

export function moveLine(lines: DraftLine[], index: number, direction: -1 | 1) {
  const to = index + direction;
  if (to < 0 || to >= lines.length) return lines;
  const reordered = [...lines];
  [reordered[index], reordered[to]] = [reordered[to], reordered[index]];
  return normalizeGaps(reordered, lines[0]?.key);
}

export function normalizeGaps(lines: DraftLine[], previousFirst?: string) {
  return lines.map((line, index) => index === 0 ? { ...line, gap: "" }
    : line.key === previousFirst ? { ...line, gap: "300" } : line);
}

const matrix: Method[] = [
  { layer: "layered", motion: "s2v" },
  { layer: "layered", motion: "i2v" },
  { layer: "whole_frame", motion: "i2v" },
];

export function sameMethod(a: Method, b: Method) {
  return a.layer === b.layer && a.motion === b.motion;
}

export function methodOptions(cast: Board["cast"], lines: DraftLine[], recipe: Recipe | null) {
  const speaking = lines.some(({ speaker }) => cast.some(({ slot }) => slot === speaker));
  const shot = speaking ? "speaking" : cast.length ? "reaction" : "ambient";
  const allowed = recipe ? recipe.shot_types[shot] ?? [] : matrix;
  return allowed.filter((method) => matrix.some((cell) => sameMethod(cell, method)) &&
    (method.layer !== "layered" || cast.length > 0) && (method.motion !== "s2v" || speaking));
}

export function changeLines(values: Values, lines: DraftLine[], board: Board, recipe: Recipe | null | undefined): Values {
  const switched = Boolean(lines.length) !== Boolean(values.lines.length);
  const timing = switched ? lines.length
    ? { lead: "500", tail: "700", hold: "" }
    : { lead: "", tail: "", hold: "1000" }
    : values.timing;
  const options = recipe !== undefined ? methodOptions(board.cast, lines, recipe) : [];
  const fallback = !lines.length && values.method.motion === "s2v"
    ? { ...values.method, motion: "i2v" } as const : values.method;
  const method = options.find((option) => sameMethod(option, values.method))
    ?? options.find((option) => sameMethod(option, fallback)) ?? options[0] ?? fallback;
  return { ...values, lines, timing, method };
}

function numberInput(value: string | number, name: string) {
  const number = Number(value);
  if (value === "" || !Number.isFinite(number)) throw new Error(`Enter a number for ${name}.`);
  return number;
}

function cueInput(cue: Cue): BoardCue {
  const number = (value: string | number, name: string) => numberInput(value, `${cue.type} ${name}`);
  const { after_line_id, at_ms, offset_ms } = cue.anchor;
  const anchor = after_line_id
    ? { after_line_id, offset_ms: number(offset_ms, "offset") }
    : { at_ms: number(at_ms, "start") };
  switch (cue.type) {
    case "sound": {
      const [start, end] = cue.trim_ms;
      return { ...cue, anchor,
        trim_ms: start === "" && end === "" ? null : [number(start, "trim start"), number(end, "trim end")],
        level_rms_dbfs: number(cue.level_rms_dbfs, "level") };
    }
    case "move":
      return { ...cue, anchor, duration_ms: number(cue.duration_ms, "duration"), dx_px: number(cue.dx_px, "horizontal move"),
        dy_px: number(cue.dy_px, "vertical move"), angle_deg: number(cue.angle_deg, "rotation"), steps: number(cue.steps, "steps") };
    case "camera":
      return { ...cue, anchor, duration_ms: number(cue.duration_ms, "duration"), zoom_from: number(cue.zoom_from, "start zoom"),
        zoom_to: number(cue.zoom_to, "end zoom"), center_px: [number(cue.center_px[0], "center X"), number(cue.center_px[1], "center Y")] };
  }
}

export function boardPatch(local: BoardDraft, board: Board): Schemas["BoardPatch"] {
  const fields = changedFields(local);
  const { lines, method, notes, timing, cues } = local.values;
  const patch: Schemas["BoardPatch"] = {};
  if (fields.includes("lines")) {
    patch.lines = lines.map(({ id, speaker, text, gap }, i) => ({
      ...(id ? { id } : {}), speaker, text, gap_before_ms: i ? numberInput(gap, `line ${i + 1} gap`) : null,
    }));
    const style = !lines.length ? null : lines.some(({ speaker }) => speaker === "narrator") ? "narrator" : "cast";
    if (style !== board.voice.style || (!lines.length && board.voice.current_version_id)) {
      patch.voice = { style, current_version_id: lines.length ? board.voice.current_version_id : null };
    }
  }
  if (fields.includes("timing") || Boolean(lines.length) !== Boolean(board.lines.length)) {
    patch.timing = lines.length ? {
      lead_ms: numberInput(timing.lead, "lead"), tail_ms: numberInput(timing.tail, "tail"), hold_ms: null,
    } : { hold_ms: numberInput(timing.hold, "hold"), lead_ms: null, tail_ms: null };
  }
  if (fields.includes("method")) patch.method = method;
  if (fields.includes("notes")) patch.notes = notes.map(({ id, text }) => ({ ...(id ? { id } : {}), text }));
  if (fields.includes("cues")) patch.cues = cues.map(cueInput);
  return patch;
}

function isDraft(value: unknown): value is BoardDraft {
  if (!value || typeof value !== "object" || !("revision" in value) ||
      !("base" in value) || !("values" in value) || !("newNote" in value)) return false;
  const validValues = (data: unknown) => {
    if (!data || typeof data !== "object") return false;
    const values = data as Values;
    return Array.isArray(values.lines) && values.lines.every((line) => line && typeof line.text === "string" &&
      typeof line.speaker === "string" && typeof line.gap === "string" && typeof line.key === "string") &&
      Array.isArray(values.notes) && values.notes.every((note) => note && typeof note.text === "string" && typeof note.key === "string") &&
      Array.isArray(values.cues) && values.cues.every((cue) => cue?.anchor && typeof cue.id === "string" &&
        (cue.type === "move" || (cue.type === "camera" && Array.isArray(cue.center_px)) ||
          (cue.type === "sound" && Array.isArray(cue.trim_ms)))) &&
      values.timing && [values.timing.lead, values.timing.tail, values.timing.hold].every((time) => typeof time === "string") &&
      values.method && ["layered", "whole_frame"].includes(values.method.layer) && ["s2v", "i2v"].includes(values.method.motion);
  };
  return Number.isSafeInteger(value.revision) && typeof value.newNote === "string" &&
    validValues(value.base) && validValues(value.values);
}

export type VoicePress = { key: string; input: string };
export type InspectorStore = ReturnType<typeof inspectorStore>;

export function inspectorStore(account?: string, storage = () => window.sessionStorage) {
  let canRestore = Boolean(account);
  const drafts = new Map<string, BoardDraft>();
  const presses = new Map<string, VoicePress>();

  function storageKey(kind: "draft" | "voice", id: string) {
    return `studio.inspector.v1/${account}/${id}/${kind}`;
  }

  function read<T>(kind: "draft" | "voice", id: string, memory: Map<string, T>, valid: (value: unknown) => value is T) {
    if (memory.has(id)) return memory.get(id);
    if (!account) return;
    try {
      const raw = storage().getItem(storageKey(kind, id));
      const value: unknown = raw && JSON.parse(raw);
      if (valid(value)) {
        memory.set(id, value);
        return value;
      }
    } catch {
      canRestore = false;
    }
  }

  function write<T>(kind: "draft" | "voice", id: string, memory: Map<string, T>, value?: T) {
    if (value) memory.set(id, value);
    else memory.delete(id);
    if (!account) return;
    try {
      const key = storageKey(kind, id);
      if (value) storage().setItem(key, JSON.stringify(value));
      else storage().removeItem(key);
    } catch {
      canRestore = false;
    }
  }

  return {
    get canRestore() { return canRestore; },
    draft: (id: string) => read("draft", id, drafts, isDraft),
    setDraft: (id: string, value: BoardDraft) =>
      write("draft", id, drafts, value.review || value.newNote || changedFields(value).length ? value : undefined),
    press: (id: string) => read("voice", id, presses, (value): value is VoicePress =>
      Boolean(value && typeof value === "object" && "key" in value && typeof value.key === "string" &&
        "input" in value && typeof value.input === "string")),
    setPress: (id: string, value?: VoicePress) => write("voice", id, presses, value),
  };
}
