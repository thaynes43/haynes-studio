import { useCallback, useEffect, useRef, useState } from "react";

import type { StudioClient } from "./api/client";
import { loadRuns } from "./production-review-data";
import { activeRun, retryableRead, type RunView } from "./run-data";
import { pollRuns } from "./run-polling";

export function useRunList(api: StudioClient, story?: string) {
  const [runs, setRuns] = useState<RunView[]>();
  const [error, setError] = useState<unknown>();
  const refreshRef = useRef<() => void>(undefined);

  useEffect(() => {
    if (!story) return;
    const poll = pollRuns(document, {
      read: (signal) => loadRuns(api, story, signal),
      onData(value) {
        setRuns(value);
        setError(undefined);
        return value.some(activeRun);
      },
      onError(failure) {
        setError(failure);
        return retryableRead(failure);
      },
    });
    refreshRef.current = poll.refresh;
    window.addEventListener("online", poll.refresh);
    return () => {
      window.removeEventListener("online", poll.refresh);
      poll.stop();
      refreshRef.current = undefined;
    };
  }, [api, story]);

  function update(run: RunView) {
    setRuns((prior) => prior?.map((entry) => entry.id === run.id && entry.revision <= run.revision ? run : entry));
  }

  return { runs, error, update, refresh: useCallback(() => refreshRef.current?.(), []) };
}

export type RunList = ReturnType<typeof useRunList>;
