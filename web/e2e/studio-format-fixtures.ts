import { createHash } from "node:crypto";

import type { components } from "../src/api/schema";
import { formatFixture } from "./studio-inspector-fixtures";
import type { TestMedia } from "./studio-review-media";

type Schemas = components["schemas"];
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

function version(id: string, format_id: string, number: number, recipe: Schemas["FormatRecipe"]): Schemas["VersionView"] {
  return { id, format_id, number, recipe, sha256: createHash("sha256").update(JSON.stringify(recipe)).digest("hex") };
}

export const formats = [{ id: "doll-short", name: "Doll Short" }, { id: "wide-video", name: "Wide Video" }];
export const formatVersions = [
  version(oldShortFormat, "doll-short", 1, { ...formatFixture.recipe, targets: [
    { ...shortsTarget, rules: { ...shortsTarget.rules, max_length_ms: null } },
  ] }),
  version(shortFormat, "doll-short", 2, shortRecipe),
  version(wideFormat, "wide-video", 1, { ...formatFixture.recipe, frame: { fps: 24, width: 1920, height: 1080 } }),
];

const fixtureLicence = {
  attribution_required: null, checked_at: null, checked_by: null, commercial_use: "unknown",
  name: null, note: "Test fixture", url: null,
} satisfies Schemas["AssetVersion_licence"];

function voice(id: string, name: string, voice_id: string): Schemas["AssetVersion"] {
  return {
    id, name, attributes: { voice_id }, schema: "studio.asset-version/v1", asset_id: id.replace("asv_", "ast_"),
    kind: "voice", capabilities: [], labels: [], number: 1, state: "promoted", scope: { production_id: null },
    content: null, legacy: null, licence: fixtureLicence,
    provenance: { origin: "declared", generator: { role: "voice", engine: "Kokoro", model: "Kokoro-82M v1.0", voice_id, stock: true },
      created_at: "2026-11-04T12:00:00Z", created_by: { kind: "cli" } },
  };
}

export const stockVoices = [voice(castVoice, "Cast stock voice", "bf_emma"), voice(narratorVoice, "Narrator stock voice", "af_heart")];

export function buildableBoardPhoto(draft: Schemas["Story"], board: Schemas["Board"], file: TestMedia): Schemas["AssetVersion"] {
  const id = board.id.replace("brd_", "asv_");
  // Sorted keys match the signature of a whole-frame photo with no input assets.
  const inputs = {
    board_id: board.id, composite_signature: null, layer: "whole_frame", prompt: board.photo.prompt,
    schema: "studio.board-photo-inputs/v1", size: draft.media_kind === "short" ? [1080, 1920] : [1920, 1080], sources: [],
  };
  const input_signature = "sha256:" + createHash("sha256").update(JSON.stringify(inputs)).digest("hex");
  const params = { input_signature, source_assets: [], engine_png_sha256: file.hash };
  return {
    id, asset_id: id.replace("asv_", "ast_"), name: "Board reference photo", schema: "studio.asset-version/v1",
    kind: "photo", state: "board", number: 1, capabilities: ["opaque_photo"], labels: [], attributes: {}, legacy: null,
    licence: fixtureLicence, scope: { production_id: draft.production_id, story_id: draft.id, board_id: board.id },
    content: { sha256: file.hash, bytes: file.body.length, locator: `productions/${draft.production_id}/blobs/${file.hash}.png`,
      media_type: "image/png", width: file.body.readUInt32BE(16), height: file.body.readUInt32BE(20) },
    provenance: { origin: "generated", source_key: `board-photo:${board.id}`, created_at: board.updated_at!,
      created_by: board.drafted_by, generator: { role: "image", engine: "ComfyUI", model: "Qwen-Image 2.1",
        source_asset_version_ids: [], params: params as unknown as Record<string, never> } },
  };
}
