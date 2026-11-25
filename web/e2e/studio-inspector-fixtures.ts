import { createHash } from "node:crypto";

import type { components } from "../src/api/schema";
import type { TestMedia } from "./studio-review-media";
import { formatId } from "./studio-storyboard-fixtures";

type Schemas = components["schemas"];
type Board = Schemas["Board"];
type VoiceJob = Schemas["JobStatus"];

const layered = { layer: "layered", motion: "i2v" } as const;
const wholeFrame = { layer: "whole_frame", motion: "i2v" } as const;
export const formatFixture = {
  id: formatId, format_id: formatId.replace("fmv_", "fmt_"), number: 1, sha256: "a".repeat(64),
  recipe: {
    schema: "studio.format-recipe/v1", frame: { fps: 24, height: 1920, width: 1080 },
    length: { min_ms: 3500, max_ms: 5000 },
    shot_types: {
      speaking: [{ layer: "layered", motion: "s2v" }, layered],
      reaction: [layered, wholeFrame],
      ambient: [wholeFrame],
    },
    human_gates: ["go_live"], notes: [], targets: [], checks: {},
    audio: { style: [], line_rms_dbfs: null, master_lufs: null, true_peak_dbtp: null },
    cast: { rules: [], team_costumes: {} }, voice: { engine: null, style: [] },
  },
} satisfies Schemas["VersionView"];

const fixtureAsv = (number: number) => `asv_01M79V9FC000000000000${String(number).padStart(5, "0")}`;

export function inspectorBoards(story: Schemas["Story"], first: Board, second: Board) {
  story.format_version_id = formatId;
  story.cast = [{ slot: "a", name: "Ada", voice_version_id: fixtureAsv(20) }];
  story.narrator_voice_version_id = fixtureAsv(21);
  const cast = [{ slot: "a", asset_version_id: fixtureAsv(22) }];
  first.cast = cast;
  first.lines = first.lines.map((line) => ({ ...line, speaker: "a" }));
  first.voice = { style: "cast", current_version_id: null };
  first.method = layered;
  const cues = [
    { id: "cue_01M79V9FC00000000000000001", type: "sound", anchor: { at_ms: 10 }, asset_version_id: fixtureAsv(23),
      level_rms_dbfs: -20, trim_ms: null } satisfies Schemas["StudioDefs_sound_cue"],
    { id: "cue_01M79V9FC00000000000000002", type: "move", anchor: { at_ms: 20 }, slot: "a",
      duration_ms: 0, dx_px: 2, dy_px: 0, angle_deg: 0, steps: 3 } satisfies Schemas["StudioDefs_move_cue"],
    { id: "cue_01M79V9FC00000000000000003", type: "camera", anchor: { at_ms: 0 }, duration_ms: 100,
      zoom_from: 1, zoom_to: 1.2, center_px: [540, 960], easing: "ease_out_cubic" } satisfies Schemas["StudioDefs_camera_cue"],
  ];
  first.cues = cues;
  second.cast = cast;
  second.method = layered;
}

function voiceWav(duration: number): TestMedia {
  const samples = duration * 8;
  const body = Buffer.alloc(44 + samples * 2);
  body.write("RIFF", 0);
  body.writeUInt32LE(body.length - 8, 4);
  body.write("WAVEfmt ", 8);
  body.writeUInt32LE(16, 16);
  body.writeUInt16LE(1, 20);
  body.writeUInt16LE(1, 22);
  body.writeUInt32LE(8000, 24);
  body.writeUInt32LE(16000, 28);
  body.writeUInt16LE(2, 32);
  body.writeUInt16LE(16, 34);
  body.write("data", 36);
  body.writeUInt32LE(samples * 2, 40);
  return { body, mime: "audio/wav", hash: createHash("sha256").update(body).digest("hex") };
}

const now = "2026-11-04T12:01:00Z";
export function voiceFixtures(versions: Schemas["AssetVersion"][]) {
  const jobs = new Map<string, { job: VoiceJob; saved: Board; requester: string; key: string }>();
  const files = new Map<string, TestMedia>();
  const presses: { board: string; key: string }[] = [];
  let paused = false;
  let dropReply = false;

  function submit(board: Board, key: string, requester: string) {
    presses.push({ board: board.id, key });
    const existing = [...jobs.values()].find((held) => held.key === key && held.saved.id === board.id && held.requester === requester);
    if (existing) return { job: existing.job, created: false, lost: false };
    const id = `job_01M79V9FC000000000000${String(jobs.size + 1).padStart(5, "0")}`;
    const job: VoiceJob = {
      id, target_id: board.id, schema: "studio.job/v1", kind: "voice", status: "queued",
      result_is_current: null, result_version_id: null, error: null, updated_at: now,
    };
    jobs.set(id, { job, saved: structuredClone(board), key, requester });
    const lost = dropReply;
    dropReply = false;
    return { job, created: true, lost };
  }

  function input({ lines, timing, voice }: Board) {
    return JSON.stringify([lines, timing.lead_ms, voice.current_version_id]);
  }
  function matches({ lines, timing }: Board, voice: NonNullable<Schemas["AssetVersion"]["voice"]>) {
    return voice.lead_ms === timing.lead_ms && voice.takes.length === lines.length &&
      voice.takes.every((take, index) => {
        const line = lines[index];
        return take.line_id === line.id && take.text === line.text && take.speaker === line.speaker &&
          (index === 0 || voice.gaps_ms[index - 1] === line.gap_before_ms);
      });
  }

  function complete(id: string, board: Board, story: Schemas["Story"], duration: number) {
    const { job, saved } = jobs.get(id)!;
    if (job.status !== "running") throw new Error("Start the fixture job before completing it");
    const lineFile = voiceWav(duration);
    let position = Number(saved.timing.lead_ms);
    const takes = saved.lines.map((line, index) => {
      if (index) position += Number(line.gap_before_ms);
      const signature = `sha256:${createHash("sha256").update(line.text).digest("hex")}`;
      const take = {
        line_id: line.id, speaker: line.speaker, text: line.text, signature,
        voice_version_id: line.speaker === "narrator" ? story.narrator_voice_version_id! : story.cast[0].voice_version_id,
        voice_id: "af_heart", engine: "fixture", offset_ms: position, duration_ms: duration, duration_source: "samples" as const,
        samples: duration * 8, sample_rate: 8000, sha256: lineFile.hash,
      };
      position += duration;
      return take;
    });
    const track = voiceWav(position);
    const versionId = fixtureAsv(100 + jobs.size);
    files.set(track.hash, track);
    files.set(lineFile.hash, lineFile);
    versions.push({
      id: versionId, schema: "studio.asset-version/v1", asset_id: versionId.replace("asv_", "ast_"),
      capabilities: ["board_voice"], kind: "board_voice", state: "board", number: 1, labels: [], attributes: {},
      scope: { board_id: board.id, story_id: story.id, production_id: story.production_id }, legacy: null, name: "Board voice",
      content: null, provenance: { created_by: board.drafted_by, created_at: now, origin: "generated", generator: { role: "voice" } },
      voice: {
        speech_end_ms: position, takes, lead_ms: Number(saved.timing.lead_ms),
        gaps_ms: saved.lines.slice(1).map(({ gap_before_ms }) => Number(gap_before_ms)),
        input_signature: takes[0].signature, track: {
          sha256: track.hash, locator: `blobs/${track.hash}`, bytes: track.body.length, media_type: "audio/wav",
        },
      },
    });
    job.status = "succeeded";
    job.result_version_id = versionId;
    job.result_is_current = input(saved) === input(board);
    if (job.result_is_current) {
      board.voice = { ...board.voice, current_version_id: versionId };
      board.revision++;
      story.revision++;
    }
    return { track, lineFile, versionId };
  }
  return {
    submit, complete, presses, files, matches,
    pause: (value: boolean) => { paused = value; },
    paused: () => paused,
    loseNextReply: () => { dropReply = true; },
    latest: () => [...jobs.values()].at(-1)?.job,
    forBoard: (board: string) => [...jobs.values()].filter(({ job }) => job.target_id === board).map(({ job }) => job),
    start: (id: string) => {
      const job = jobs.get(id)!.job;
      if (paused || job.status !== "queued") throw new Error("Fixture voice job cannot run");
      job.status = "running";
    },
    fail: (id: string, code: string, message: string) => {
      const job = jobs.get(id)!.job;
      if (job.status !== "running") throw new Error("Start the fixture job before failing it");
      job.status = "failed";
      job.error = { code, message };
    },
  };
}
