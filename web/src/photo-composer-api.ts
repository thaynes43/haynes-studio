import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, type StudioClient } from "./api/client";
import {
  boardPhotoVersions, type AssetVersion, type PhotoBoardScope, type PhotoInputs, type PhotoJob,
} from "./photo-composer-model";
import { collectPages, loadBoard, type Board } from "./route-data";
import { pollRuns } from "./run-polling";
import { useRequest } from "./use-request";

function boardParams(id: string) {
  return { path: { id } };
}

export function usePhotoCatalog(api: StudioClient, production: string, enabled: boolean) {
  const load = useCallback(async (signal: AbortSignal) => {
    if (!enabled) return [];
    return collectPages<AssetVersion>((cursor) => api.GET("/v1/assets", {
      signal, params: { query: { production, cursor } },
    }).then(({ data }) => data));
  }, [api, enabled, production]);
  return useRequest(load);
}

type Feed = { board: Board; jobs: PhotoJob[]; versions: AssetVersion[]; paused: boolean };

export function usePhotoFeed(api: StudioClient, scope: PhotoBoardScope, enabled: boolean) {
  const [feed, setFeed] = useState<Feed>();
  const [error, setError] = useState<unknown>();
  const poller = useRef<ReturnType<typeof pollRuns>>(null);

  useEffect(() => {
    if (!enabled) return;
    const poll = pollRuns(document, {
      read: async (signal) => {
        const params = boardParams(scope.board);
        const [jobs, lanes] = await Promise.all([
          collectPages<PhotoJob>((cursor) => api.GET("/v1/boards/{id}/jobs", {
            signal, params: { ...params, query: { cursor } },
          }).then(({ data }) => data)),
          api.GET("/v1/queue/lanes", { signal }).then(({ data }) => data),
        ]);
        const lane = lanes?.items.find(({ lane }) => lane === "image");
        if (!lane) throw new ApiError(500);
        const board = await loadBoard(api, scope.story, scope.board, signal);
        const versions = await collectPages<AssetVersion>((cursor) => api.GET("/v1/boards/{id}/photo-versions", {
          signal, params: { ...params, query: { cursor } },
        }).then(({ data }) => data));
        return {
          board, versions: boardPhotoVersions(versions, scope), paused: lane.paused,
          jobs: jobs.filter(({ kind, target_id }) => kind === "photo" && target_id === scope.board),
        };
      },
      onData: (data) => {
        setFeed(data);
        setError(undefined);
        return true;
      },
      onError: (error) => {
        setError(error);
        return !(error instanceof ApiError) || error.status === 0 || error.status >= 500;
      },
    });
    poller.current = poll;
    return () => {
      poll.stop();
      poller.current = null;
    };
  }, [api, enabled, scope]);

  return { feed, error, refresh: () => poller.current?.refresh() };
}

export async function patchPhoto(api: StudioClient, board: Board, inputs: PhotoInputs,
  selected: string | null, signal: AbortSignal) {
  const { data } = await api.PATCH("/v1/boards/{id}", {
    signal, params: { ...boardParams(board.id), header: { "If-Match": `"${board.revision}"` } },
    body: { photo: { ...inputs, current_version_id: selected } },
  });
  if (!data || data.id !== board.id || data.story_id !== board.story_id) throw new ApiError(500);
  return data;
}

export async function queuePhoto(api: StudioClient, id: string, key: string, seed: number, signal: AbortSignal) {
  const { data } = await api.POST("/v1/boards/{id}/photo-jobs", {
    signal, params: { ...boardParams(id), header: { "Idempotency-Key": key } }, body: { seed },
  });
  if (!data || data.kind !== "photo" || data.target_id !== id) throw new ApiError(500);
  return data;
}
