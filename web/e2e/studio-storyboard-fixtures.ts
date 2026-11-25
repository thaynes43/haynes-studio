import type { components } from "../src/api/schema";
import type { ReviewMedia, TestMedia } from "./studio-review-media";
import { photoVersion, voiceVersion } from "./studio-review-fixtures";

type Schemas = components["schemas"];
type Board = Schemas["Board"];
type AssetVersion = Schemas["AssetVersion"];

export const formatId = "fmv_01M79V9FC00000000000000001";
const formatLength = { format_version_id: formatId, min_ms: 3500, max_ms: 5000 };

export function boardVersions(production: string, board: Board, media: Pick<ReviewMedia, "photo" | "voice">) {
  const common = {
    schema: "studio.asset-version/v1", state: "board", number: 1, labels: [], attributes: {}, legacy: null,
    scope: { production_id: production, story_id: board.story_id, board_id: board.id },
  } as const;
  const content = (file: TestMedia, media_type: "image/png" | "audio/wav") => ({
    sha256: file.hash, bytes: file.body.length, locator: `blobs/${file.hash}`, media_type,
  });
  const provenance = (role: "image" | "voice") => ({
    created_by: board.drafted_by, created_at: "2026-11-04T12:00:00Z",
    generator: { role }, origin: "generated" as const,
  });
  const signature = `sha256:${"0".repeat(64)}`;
  const line = board.lines[0];
  return [
    {
      ...common, id: photoVersion, asset_id: photoVersion.replace("asv_", "ast_"), name: "Opening photo",
      labels: [], capabilities: ["opaque_photo"], kind: "photo", provenance: provenance("image"),
      content: content(media.photo, "image/png"),
    },
    {
      ...common, id: voiceVersion, asset_id: voiceVersion.replace("asv_", "ast_"), name: "Opening voice",
      labels: [], capabilities: ["board_voice"], kind: "board_voice", provenance: provenance("voice"),
      content: null, voice: {
        input_signature: signature, lead_ms: 0, gaps_ms: [], speech_end_ms: 200,
        track: content(media.voice, "audio/wav"), takes: [{
          line_id: line.id, speaker: line.speaker, text: line.text,
          voice_version_id: "asv_01M79V9FC00000000000000003", voice_id: "fixture-voice", engine: "fixture",
          offset_ms: 0, duration_ms: 200, duration_source: "samples", samples: 1600, sample_rate: 8000,
          sha256: media.voice.hash, signature,
        }],
      },
    },
  ] satisfies AssetVersion[];
}

export function storyTiming(
  draft: Schemas["Story"], boards: Map<string, Board>, versions: AssetVersion[],
  matches: (board: Board, voice: NonNullable<AssetVersion["voice"]>) => boolean = () => true,
): Schemas["Timing"] {
  let known = 0;
  let start: number | null = 0;
  const fps = 24;
  const build_blockers: Schemas["Timing"]["build_blockers"] = [];
  const rows = draft.board_order.map((id): Schemas["Timing"]["boards"][number] => {
    const board = boards.get(id)!;
    const voice = versions.find(({ id }) => id === board.voice.current_version_id)?.voice;
    const current = voice && matches(board, voice);
    const content = board.lines.length ? current ? voice.speech_end_ms + Number(board.timing.tail_ms) : undefined : Number(board.timing.hold_ms);
    if (content === undefined) {
      start = null;
      const code = voice ? "voice.stale" : "voice.absent";
      build_blockers.push({ board_id: id, code });
      return { board_id: id, frames: null, film_start_frame: null, state: "untimed", reason: code };
    }
    const frames = Math.ceil(content * fps / 1000);
    const film_start_frame = start;
    known += frames;
    if (start !== null) start += frames;
    return { board_id: id, frames, film_start_frame, state: "timed" };
  });
  const range = draft.format_version_id === formatId ? formatLength : null;
  const warnings: Schemas["Timing"]["warnings"] = [];
  if (range && known * 1000 > range.max_ms * fps) warnings.push({
    code: "format.length_exceeded", severity: "warning", build_allowed: true, decision: "D45",
    message: `The story runs ${(known / fps).toFixed(3)} s, past the format maximum of ${range.max_ms / 1000} s.`,
  });
  return {
    schema: "studio.story-timing/v1", story_id: draft.id, story_revision: draft.revision, fps, boards: rows,
    frames_known: known, complete: start !== null, format_length: range, warnings,
    build_allowed: build_blockers.length === 0, build_blockers,
  };
}
