import { createHash } from "node:crypto";

import type { components } from "../src/api/schema";
import { formatFixture } from "./studio-inspector-fixtures";

type Schemas = components["schemas"];
export const shortFormat = "fmv_01M79V9FC00000000000000010";
const oldShortFormat = "fmv_01M79V9FC00000000000000009";
const wideFormat = "fmv_01M79V9FC00000000000000011";
export const castVoice = "asv_01M79V9FC00000000000000020";
export const narratorVoice = "asv_01M79V9FC00000000000000021";

const shortRecipe: Schemas["FormatRecipe"] = {
  ...formatFixture.recipe,
  targets: [
    { id: "private-feedback", name: "Private feedback", platform: "private", account_id: null,
      state: "placeholder", owner_note: null, rules: { ai_label_required: null, aspect: null, max_length_ms: null } },
    { id: "shorts", name: "Shorts release", platform: "youtube-shorts", account_id: null,
      state: "placeholder", owner_note: null, rules: { ai_label_required: true, aspect: null, max_length_ms: 60000 } },
  ],
};

function version(id: string, format_id: string, number: number, recipe: Schemas["FormatRecipe"]): Schemas["VersionView"] {
  return { id, format_id, number, recipe, sha256: createHash("sha256").update(JSON.stringify(recipe)).digest("hex") };
}

export const formats = [{ id: "doll-short", name: "Doll Short" }, { id: "wide-video", name: "Wide Video" }];
export const formatVersions = [
  version(oldShortFormat, "doll-short", 1, formatFixture.recipe),
  version(shortFormat, "doll-short", 2, shortRecipe),
  version(wideFormat, "wide-video", 1, { ...formatFixture.recipe, frame: { fps: 24, width: 1920, height: 1080 } }),
];

function voice(id: string, name: string, voice_id: string): Schemas["AssetVersion"] {
  return {
    id, name, attributes: { voice_id }, schema: "studio.asset-version/v1", asset_id: id.replace("asv_", "ast_"),
    kind: "voice", capabilities: [], labels: [], number: 1, state: "promoted", scope: { production_id: null },
    content: null, legacy: null,
    provenance: { origin: "declared", generator: { role: "voice", engine: "Kokoro", model: "kokoro-82m" },
      created_at: "2026-11-04T12:00:00Z", created_by: { kind: "cli" } },
  };
}

export const stockVoices = [voice(castVoice, "Cast stock voice", "bf_emma"), voice(narratorVoice, "Narrator stock voice", "af_heart")];
