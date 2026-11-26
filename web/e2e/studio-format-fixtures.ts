import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

import type { components } from "../src/api/schema";
import { formatFixture } from "./studio-inspector-fixtures";
import type { TestMedia } from "./studio-review-media";

type Schemas = components["schemas"];
type AssetVersion = Schemas["AssetVersion"];
export const shortFormat = "fmv_01M79V9FC00000000000000010";
export const oldShortFormat = "fmv_01M79V9FC00000000000000009";
export const wideFormat = "fmv_01M79V9FC00000000000000011";
export const castVoice = "asv_01M79V9FC00000000000000020";
export const narratorVoice = "asv_01M79V9FC00000000000000021";

const shortsTarget = {
  id: "shorts", name: "Shorts release", platform: "youtube-shorts", account_id: null,
  state: "placeholder", owner_note: null, rules: { ai_label_required: true, aspect: null, max_length_ms: 60000 },
} satisfies Schemas["FormatRecipe"]["targets"][number];
const shortRecipe: Schemas["FormatRecipe"] = {
  ...formatFixture.recipe,
  targets: [
    { id: "private-feedback", name: "Private feedback", platform: "private", account_id: null,
      state: "placeholder", owner_note: null, rules: { ai_label_required: null, aspect: null, max_length_ms: null } },
    shortsTarget,
  ],
};

// Match store.canonical_json for these fixtures, whose only numbers are integers.
function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const fields = value as Record<string, unknown>;
    const entries = Object.keys(fields).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(fields[key])}`);
    return `{${entries.join(",")}}`;
  }
  if (typeof value === "number" && !Number.isSafeInteger(value)) throw new Error("Expected an integer fixture value");
  return JSON.stringify(value);
}

function canonicalHash(document: object) {
  return createHash("sha256").update(canonicalJson(document)).digest("hex");
}

function version(id: string, format_id: string, number: number, recipe: Schemas["FormatRecipe"]): Schemas["VersionView"] {
  return { id, format_id, number, recipe, sha256: canonicalHash(recipe) };
}

export const formats = [{ id: "doll-short", name: "Doll Short" }, { id: "wide-video", name: "Wide Video" }];
export const formatVersions = [
  version(oldShortFormat, "doll-short", 1, { ...formatFixture.recipe, targets: [
    { ...shortsTarget, rules: { ...shortsTarget.rules, max_length_ms: null } },
  ] }),
  version(shortFormat, "doll-short", 2, shortRecipe),
  version(wideFormat, "wide-video", 1, { ...formatFixture.recipe, frame: { fps: 24, width: 1920, height: 1080 } }),
];

// Read the repository's synthetic catalog records so capabilities and provenance stay in step.
const benchmarkAssets: AssetVersion[] = JSON.parse(readFileSync(new URL(
  "../../src/haynes_studio/drafting_benchmark_data/assets.json", import.meta.url,
), "utf8"));
const photoExample: AssetVersion = JSON.parse(readFileSync(new URL(
  "../../docs/contracts/examples/valid/asset-version-photo-external.json", import.meta.url,
), "utf8"));

function voice(id: string, name: string, voiceId: string): AssetVersion {
  const record = benchmarkAssets.find(({ kind, attributes }) => kind === "voice" && attributes["voice_id"] === voiceId);
  if (!record) throw new Error(`Missing stock voice fixture ${voiceId}`);
  return { ...record, id, name, asset_id: id.replace("asv_", "ast_"), scope: { production_id: null } };
}

export const stockVoices = [voice(castVoice, "Cast stock voice", "af_bella"), voice(narratorVoice, "Narrator stock voice", "af_heart")];

export function buildableBoardPhoto(draft: Schemas["Story"], board: Schemas["Board"], file: TestMedia): AssetVersion {
  const id = board.id.replace("brd_", "asv_");
  const inputs = {
    board_id: board.id, composite_signature: null, layer: "whole_frame", prompt: board.photo.prompt,
    schema: "studio.board-photo-inputs/v1", size: draft.media_kind === "short" ? [1080, 1920] : [1920, 1080], sources: [],
  };
  const params = { input_signature: `sha256:${canonicalHash(inputs)}` };
  return {
    ...photoExample, id, asset_id: id.replace("asv_", "ast_"), name: "Board reference photo", number: 1,
    scope: { production_id: draft.production_id, story_id: draft.id, board_id: board.id },
    content: { sha256: file.hash, bytes: file.body.length,
      locator: `productions/${draft.production_id}/sha256/${file.hash.slice(0, 2)}/${file.hash}.png`,
      media_type: "image/png", width: file.body.readUInt32BE(16), height: file.body.readUInt32BE(20) },
    provenance: { ...photoExample.provenance, created_at: board.updated_at!, generator: {
      ...photoExample.provenance.generator, source_asset_version_ids: [], params: params as unknown as Record<string, never>,
    } },
  };
}
