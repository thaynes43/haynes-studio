import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, type StudioClient } from "./api/client";
import type { components } from "./api/schema";
import { mediaUrl } from "./production-review-data";
import { collectPages, loadBoard, type Board } from "./route-data";
import { pollRuns } from "./run-polling";
import { useRequest } from "./use-request";

type Schemas = components["schemas"];
export type VoiceJob = Schemas["JobStatus"];
export type VoiceVersion = Exclude<Schemas["AssetVersion"]["voice"], null | undefined>;
export type InspectorStory = Pick<Schemas["Story"], "id" | "production_id" | "cast" | "format_version_id" | "narrator_voice_version_id">;

export const activeJob = ({ status }: VoiceJob) => status === "queued" || status === "running";

export function currentResult(job: VoiceJob, board: Board, unsavedInput: boolean) {
  return job.status === "succeeded" && job.result_is_current === true &&
    Boolean(job.result_version_id) && job.result_version_id === board.voice.current_version_id &&
    board.derived?.voice_state === "current" && !unsavedInput;
}

export function currentVoiceId(board: Board, jobs: VoiceJob[], unsavedInput: boolean) {
  const id = board.voice.current_version_id;
  if (unsavedInput || board.derived?.voice_state !== "current" ||
      typeof id !== "string" || !/^asv_[0-9A-HJKMNP-TV-Z]{26}$/.test(id)) return;
  const job = jobs.findLast(({ result_version_id }) => result_version_id === id);
  if (!job || currentResult(job, board, false)) return id;
}

export function voicePreviewUrl(id: string, hash: unknown) {
  const url = mediaUrl(hash);
  return url && /^asv_[0-9A-HJKMNP-TV-Z]{26}$/.test(id) ? `/v1/asset-versions/${id}${url.slice(3)}` : undefined;
}

export function voicePressInput(board: Board, story: InspectorStory) {
  return JSON.stringify({
    lines: board.lines.map(({ id, text, speaker, gap_before_ms }) => ({
      id, text, speaker, gap_before_ms, voice: speaker === "narrator" ? story.narrator_voice_version_id :
        story.cast.find(({ slot }) => slot === speaker)?.voice_version_id,
    })),
    lead: board.timing.lead_ms,
  });
}

export function inspectorProblem(error: unknown) {
  if (error instanceof Error && !(error instanceof ApiError)) return error.message;
  if (!(error instanceof ApiError)) return "Studio returned an unexpected response.";
  if (error.code === "method.s2v_needs_line") return "Speech-to-video needs a spoken line (method.s2v_needs_line).";
  if (error.code === "method.s2v_needs_onscreen_speaker") {
    return "Speech-to-video needs an on-screen speaker (method.s2v_needs_onscreen_speaker).";
  }
  return error.code ? `${error.detail?.message || "Studio refused the request."} (${error.code})`
    : error.status === 0 ? "Studio could not be reached." : `Studio returned HTTP ${error.status}.`;
}

export function useInspectorFormat(api: StudioClient, id: string | null) {
  const load = useCallback(async (signal: AbortSignal) => {
    if (!id) return null;
    const { data } = await api.GET("/v1/format-versions/{id}", { signal, params: { path: { id } } });
    if (!data || data.id !== id) throw new ApiError(404);
    return data;
  }, [api, id]);
  const { result, retry } = useRequest(load);
  return {
    recipe: id ? (result.status === "success" && result.data?.id === id ? result.data.recipe : undefined) : null,
    error: result.status === "failure" ? result.error : undefined,
    retry,
  };
}

export function useVoiceVersion(api: StudioClient, story: InspectorStory, board: string, id?: string) {
  const load = useCallback(async (signal: AbortSignal) => {
    if (!id) return;
    let cursor: string | undefined;
    const seen = new Set<string>();
    do {
      const { data } = await api.GET("/v1/boards/{id}/voice-versions", {
        signal, params: { path: { id: board }, query: { cursor } },
      });
      if (!data) throw new ApiError(500);
      const version = data.items.find((version) => version.id === id && version.kind === "board_voice" &&
        version.scope.board_id === board && version.scope.story_id === story.id &&
        version.scope.production_id === story.production_id);
      if (version?.voice) return { id, voice: version.voice };
      cursor = data.next_cursor ?? undefined;
      if (cursor && seen.has(cursor)) throw new ApiError(500);
      if (cursor) seen.add(cursor);
    } while (cursor);
    throw new ApiError(404);
  }, [api, board, id, story.id, story.production_id]);
  const { result, retry } = useRequest(load);
  return {
    voice: result.status === "success" && result.data?.id === id ? result.data?.voice : undefined,
    error: id && result.status === "failure" ? result.error : undefined,
    retry,
  };
}

export function useVoiceJobs(api: StudioClient, storyId: string, boardId: string, receiveBoard: (board: Board) => void) {
  const [jobs, setJobs] = useState<VoiceJob[]>([]);
  const [paused, setPaused] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<unknown>();
  const poller = useRef<ReturnType<typeof pollRuns>>(null);
  useEffect(() => {
    const poll = pollRuns(document, {
      read: async (signal) => {
        const [jobs, lanes, board] = await Promise.all([
          collectPages<VoiceJob>((cursor) => api.GET("/v1/boards/{id}/jobs", {
            signal, params: { path: { id: boardId }, query: { cursor } },
          }).then(({ data }) => data)),
          api.GET("/v1/queue/lanes", { signal }).then(({ data }) => data),
          loadBoard(api, storyId, boardId, signal),
        ]);
        const voiceLane = lanes?.items.find(({ lane }) => lane === "voice");
        if (!voiceLane) throw new ApiError(500);
        return { jobs: jobs.filter((job) => job.kind === "voice" && job.target_id === boardId), voiceLane, board };
      },
      onData: ({ jobs, voiceLane, board }) => {
        setJobs(jobs);
        setPaused(voiceLane.paused);
        setReady(true);
        setError(undefined);
        receiveBoard(board);
        return true;
      },
      onError: (error) => {
        setError(error);
        return !(error instanceof ApiError) || error.status === 0 || error.status >= 500;
      },
    });
    poller.current = poll;
    return () => poll.stop();
  }, [api, boardId, storyId, receiveBoard]);

  const submitted = (job: VoiceJob) => {
    setJobs((previous) => [...previous.filter(({ id }) => id !== job.id), job].sort((a, b) => a.id.localeCompare(b.id)));
    poller.current?.refresh();
  };
  return { jobs, paused, ready, error, submitted };
}

export async function queueVoice(api: StudioClient, id: string, key: string, signal: AbortSignal) {
  const { data } = await api.POST("/v1/boards/{id}/voice-jobs", {
    signal, params: { path: { id }, header: { "Idempotency-Key": key } }, body: {},
  });
  if (!data || data.kind !== "voice" || data.target_id !== id) throw new ApiError(500);
  return data;
}
