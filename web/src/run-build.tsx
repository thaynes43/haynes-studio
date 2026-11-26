import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { ApiError, type StudioClient } from "./api/client";
import { Problem } from "./shell-ui";
import type { StoryboardDraft } from "./storyboard-data";
import { timelineLabels } from "./storyboard-timeline";
import { buildPress, queueBuild, readPreflight, runProblem, runProblems, type BuildPress, type RunProblem } from "./run-data";
import { RunProblemList } from "./run-problems";

type BuildFailure = {
  error: unknown; press: BuildPress; problems: RunProblem[]; ambiguous: boolean;
  reloadFrom?: StoryboardDraft["story"];
};

export function RunBuild({ api, draft, pending, formatConflict, reload, refresh }: {
  api: StudioClient; draft: StoryboardDraft; pending: boolean; formatConflict: boolean; reload: () => void; refresh: () => void;
}) {
  const [sending, setSending] = useState(false);
  const [failure, setFailure] = useState<BuildFailure>();
  const [notice, setNotice] = useState("");
  const request = useRef<AbortController | null>(null);
  const { story, timing } = draft;
  const currentStory = useRef(story);
  useLayoutEffect(() => { currentStory.current = story; }, [story]);
  useEffect(() => () => request.current?.abort(), []);

  const stale = failure?.reloadFrom !== undefined;
  const needsReload = failure?.reloadFrom === story;
  const warning = timelineLabels(timing).warning;
  const locked = pending || needsReload || formatConflict;
  const description = [formatConflict ? "build-format-conflict" : "", warning ? "build-length-warning" : ""]
    .filter(Boolean).join(" ");

  async function build() {
    if (request.current || locked) return;
    const press = failure?.ambiguous ? failure.press : buildPress(story.revision, story.board_order);
    const controller = new AbortController();
    request.current = controller;
    const { signal } = controller;
    setFailure(undefined);
    setNotice("");
    setSending(true);
    try {
      await queueBuild(api, story.id, press, signal);
      if (!signal.aborted) {
        setNotice("Run queued.");
        refresh();
      }
    } catch (error) {
      if (signal.aborted) return;
      const refused = error instanceof ApiError ? error : undefined;
      // A server error may arrive after the queue transaction committed.
      const ambiguous = !refused || refused.status === 0 ||
        (refused.status >= 500 && refused.code !== "run.snapshot_store_unavailable");
      const problems = runProblems(refused?.detail?.evidence?.problems, press.boardOrder);
      const reloadFrom = refused?.code === "conflict.revision" ? currentStory.current : undefined;
      const problem = { error, press, problems, ambiguous, reloadFrom };
      setFailure(problem);
      if (ambiguous) refresh();
      if (refused?.status === 422 && refused.code !== "idempotency.mismatch" && !problems.length) {
        // The enqueue error sends its first violation. The estimate can supply its peers.
        const extra = await readPreflight(api, story.id, press, signal).catch(() => []);
        if (!signal.aborted && extra.length) setFailure({ ...problem, problems: extra });
      }
    } finally {
      request.current = null;
      if (!signal.aborted) setSending(false);
    }
  }

  const refusal = failure?.error instanceof ApiError ? failure.error : undefined;
  const firstProblem = refusal && runProblem({ code: refusal.code, ...refusal.detail }, failure?.press.boardOrder);
  const related = firstProblem && (firstProblem.board || firstProblem.field) ? [firstProblem] : [];
  const problems = failure?.problems ?? [];
  return <div className="run-build">
    <div className="run-build-controls">
      <button className="pill primary" type="button" disabled={sending || locked}
        aria-describedby={description || undefined} onClick={() => void build()}>
        {sending ? "Queueing…" : failure?.ambiguous ? "Retry build" : "Build"}
      </button>
      {formatConflict && <p className="run-build-warning" id="build-format-conflict">
        Review your unsaved format settings before building.
      </p>}
      {warning && <p className="run-build-warning" id="build-length-warning">{warning}</p>}
    </div>
    {notice && <p role="status">{notice}</p>}
    {failure && <div className="run-build-feedback">
      <Problem error={failure.error} message={stale
        ? needsReload ? "The draft changed. Reload the draft before building." : "The previous build used an older draft."
        : failure.ambiguous ? "Studio couldn’t confirm the queue request. Retry this build to check it."
          : refusal?.detail?.message} />
      {refusal?.code && <p className="request-id"><code>{refusal.code}</code></p>}
      <RunProblemList problems={problems.length ? problems : related} order={failure.press.boardOrder} />
      {needsReload && <button className="pill" type="button" disabled={pending} onClick={reload}>Reload draft</button>}
    </div>}
  </div>;
}
