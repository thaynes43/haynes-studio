import { useEffect, useState } from "react";

type Result<T> =
  | { status: "loading" }
  | { status: "success"; data: T }
  | { status: "failure"; error: unknown };

export function useRequest<T>(load: (signal: AbortSignal) => Promise<T>) {
  const [result, setResult] = useState<Result<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const request = new AbortController();
    setResult({ status: "loading" });
    void load(request.signal).then(
      (data) => { if (!request.signal.aborted) setResult({ status: "success", data }); },
      (error: unknown) => { if (!request.signal.aborted) setResult({ status: "failure", error }); },
    );
    return () => request.abort();
  }, [load, attempt]);

  return { result, retry: () => setAttempt((value) => value + 1) };
}
