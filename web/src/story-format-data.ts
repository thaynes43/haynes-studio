import { ApiError, type StudioClient } from "./api/client";
import type { components } from "./api/schema";
import { collectPages } from "./route-data";
import type { StoryboardScope } from "./storyboard-data";

type Schemas = components["schemas"];
type FormatFields = "format_version_id" | "cast" | "narrator_voice_version_id";
export type StoryFormatPatch = Pick<Schemas["StoryPatch"], FormatFields>;
export type StoryFormat = Pick<Schemas["Story"], FormatFields>;
export type FormatVersion = Schemas["VersionView"] & { name: string };
export type VoiceVersion = Schemas["AssetVersion"];
export type FormatProfile = Pick<Schemas["FormatRecipe"]["frame"], "width" | "height">;

async function listFormatOptions(api: StudioClient, profile: FormatProfile, signal: AbortSignal) {
  const formats = await collectPages<Schemas["FormatSummary"]>((cursor) => api.GET("/v1/formats", {
    signal, params: { query: { cursor } },
  }).then(({ data }) => data));
  const options: FormatVersion[] = [];
  for (const { id, name } of formats) {
    const versions = await collectPages<Schemas["VersionSummary"]>((cursor) => api.GET("/v1/formats/{id}/versions", {
      signal, params: { path: { id }, query: { cursor } },
    }).then(({ data }) => data));
    for (const summary of versions.sort((left, right) => right.number - left.number)) {
      const { data } = await api.GET("/v1/format-versions/{id}", {
        signal, params: { path: { id: summary.id } },
      });
      if (!data || data.id !== summary.id || data.format_id !== id) throw new ApiError(502);
      const { width, height } = data.recipe.frame;
      if (width === profile.width && height === profile.height) options.push({ ...data, name });
    }
  }
  return options;
}

export async function loadStoryFormatOptions(api: StudioClient, scope: StoryboardScope, profile: FormatProfile, signal: AbortSignal) {
  const [formats, versions] = await Promise.all([
    listFormatOptions(api, profile, signal),
    collectPages<VoiceVersion>((cursor) => api.GET("/v1/assets", {
      signal, params: { query: { kind: "voice", production: scope.production, cursor } },
    }).then(({ data }) => data)),
  ]);
  const voices = versions.filter(({ kind, scope: asset }) => kind === "voice" && !asset.board_id &&
    (asset.production_id === null || asset.production_id === scope.production) &&
    (!asset.story_id || asset.story_id === scope.story));
  return { formats, voices };
}

export type StoryFormatOptions = Awaited<ReturnType<typeof loadStoryFormatOptions>>;

export function storyFormat({ format_version_id, cast, narrator_voice_version_id }: StoryFormat): StoryFormat {
  return { format_version_id, cast, narrator_voice_version_id };
}

export function formatPatch(base: StoryFormat, values: StoryFormat): StoryFormatPatch {
  const castChanged = values.cast.length !== base.cast.length || values.cast.some((member, index) => {
    const prior = base.cast[index];
    return member.slot !== prior.slot || member.name !== prior.name || member.voice_version_id !== prior.voice_version_id;
  });
  return {
    ...(base.format_version_id !== values.format_version_id && { format_version_id: values.format_version_id }),
    ...(castChanged && { cast: values.cast }),
    ...(base.narrator_voice_version_id !== values.narrator_voice_version_id && { narrator_voice_version_id: values.narrator_voice_version_id }),
  };
}

export function formatEditsConflict(base: StoryFormat, values: StoryFormat, saved: StoryFormat) {
  const edits = formatPatch(base, values);
  const intervening = formatPatch(base, saved);
  return Object.keys(formatPatch(saved, values)).some((field) => field in edits && field in intervening);
}

export function nextCastSlot(cast: StoryFormat["cast"]) {
  return Array.from("abcdefghijklmnopqrstuvwxyz").find((slot) => !cast.some((member) => member.slot === slot));
}

export function formatStatus(saved: StoryFormat, saving: boolean) {
  if (saving) return "Saving format…";
  return saved.format_version_id ? "Format pinned" : "No format pinned";
}

export function formatFailure(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 0) return "Studio could not be reached. Check your connection.";
    if (error.detail?.message) return error.detail.message;
  }
  return "Studio couldn’t complete the format request.";
}

export async function patchStoryFormat(api: StudioClient, id: string, revision: number, body: StoryFormatPatch, signal: AbortSignal) {
  const { data } = await api.PATCH("/v1/stories/{id}", {
    signal, params: { path: { id }, header: { "If-Match": `"${revision}"` } }, body,
  });
  if (!data || data.id !== id || data.revision <= revision) throw new ApiError(502);
  return data.revision;
}
