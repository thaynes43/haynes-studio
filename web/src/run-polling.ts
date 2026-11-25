export const pollInterval = 5_000;
const maxBackoff = 60_000;

type PollOptions<T> = {
  read: (signal: AbortSignal) => Promise<T>;
  onData: (value: T) => boolean;
  onError: (error: unknown) => boolean;
};

export function pollRuns<T>(environment: Pick<Document, "visibilityState" | "addEventListener" | "removeEventListener">,
  { read, onData, onError }: PollOptions<T>) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let request: AbortController | undefined;
  let failures = 0;
  let stopped = false;
  let refused = false;

  function clear() {
    clearTimeout(timer);
    request?.abort();
  }

  function schedule(delay: number) {
    if (environment.visibilityState === "visible") timer = setTimeout(refresh, delay);
  }

  function refresh() {
    clear();
    if (stopped || refused || environment.visibilityState !== "visible") return;
    const next = new AbortController();
    request = next;
    void read(next.signal).then(
      (value) => {
        if (next.signal.aborted) return;
        failures = 0;
        if (onData(value)) schedule(pollInterval);
      },
      (error: unknown) => {
        if (next.signal.aborted) return;
        failures = Math.min(failures + 1, 4);
        if (onError(error)) schedule(Math.min(maxBackoff, pollInterval * 2 ** failures));
        else refused = true;
      },
    );
  }

  environment.addEventListener("visibilitychange", refresh);
  refresh();
  return {
    refresh,
    stop() {
      stopped = true;
      clear();
      environment.removeEventListener("visibilitychange", refresh);
    },
  };
}
