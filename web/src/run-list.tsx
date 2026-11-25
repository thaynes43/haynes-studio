import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router";

import { ApiError, type StudioClient } from "./api/client";
import type { components } from "./api/schema";
import { hasDelivery, readObject, runStates } from "./production-review-data";
import { boardLabel } from "./route-data";
import { activeRun, cancelRun, canOverride, retryableRead, runDetail, runProblem, runProblems, visualCheck, type RunView } from "./run-data";
import { RunDelivery } from "./run-delivery";
import { RunProblemList } from "./run-problems";
import { treePath, type Context } from "./routes";
import { Empty, Problem } from "./shell-ui";
import { useRequest } from "./use-request";
import type { RunList } from "./use-run-list";

type Check = components["schemas"]["RunView_check"];
type RunDetail = Awaited<ReturnType<typeof runDetail>>;

const results = { pass: "Passed", pass_with_tolerances: "Passed with tolerances", fail: "Failed", overridden: "Overridden" };
const waitReasons = { gpu_unavailable: "GPU unavailable", lease_busy: "Waiting for the GPU lease" };

function recordedChecks(run: RunView): { check: Check; board?: string }[] {
  return [
    ...(run.checks ?? []).map((check) => ({ check, board: check.board_id })),
    ...run.stages.flatMap(({ checks, board_number }) => (checks ?? []).map((check) => ({
      check, board: board_number ? boardLabel({ number: board_number }) : check.board_id,
    }))),
  ];
}

function time(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return minutes ? `${minutes} min${rest ? ` ${rest} s` : ""}` : `${seconds} s`;
}

function rangeText(range: readonly number[]) {
  return range[0] === range[1] ? time(range[0]) : `${time(range[0])}–${time(range[1])}`;
}

function RunProgress({ run }: { run: RunView }) {
  const { estimate, queue_wait, wait_reason, progress, status } = run;
  const reason = run.transitions?.findLast(({ to }) => to === status)?.reason;
  const error = readObject(run.error);
  const problem = runProblem(error);
  const failure = status === "failed" || status === "held" || (status === "queued" && Boolean(wait_reason));
  const problems = runProblems(error.problems);
  const failedChecks = failure
    ? [...new Set(recordedChecks(run).filter(({ check }) => check.result === "fail").map(({ check }) => check.check))]
    : [];
  return <>
    {status === "queued" && <div>
      {queue_wait && <p title={queue_wait.basis}>
        Queue position {queue_wait.ahead + 1}
        {queue_wait.wall_s ? ` · Wait ${rangeText(queue_wait.wall_s)} (uncertain)` : " · Wait unknown"}
      </p>}
      {wait_reason && <p>{waitReasons[wait_reason]}</p>}
    </div>}
    {status === "running" && <div className="run-progress">
      <progress max={100} value={progress.percent} aria-label={`Run ${run.number} progress`} />
      <span>{progress.stage?.replaceAll("_", " ")} {progress.percent}%</span>
    </div>}
    {activeRun(run) && estimate && <p className="muted" title={estimate.basis}>
      {estimate.uncertain ? "Uncertain estimate" : "Estimate"}
      {estimate.gpu_wall_s && ` · GPU ${rangeText(estimate.gpu_wall_s)}`}
      {estimate.cpu_wall_s && ` · CPU ${rangeText(estimate.cpu_wall_s)}`}
      {!estimate.gpu_wall_s && !estimate.cpu_wall_s && " unavailable"}
    </p>}
    {run.cancel_requested && activeRun(run) && <p role="status">Cancellation requested.</p>}
    {(failure || status === "cancelled") && reason && reason !== problem.message && <p>{reason}</p>}
    {failure && typeof error.stage === "string" && <p>Stage <strong>{error.stage.replaceAll("_", " ")}</strong></p>}
    {failedChecks.length > 0 && <p>{failedChecks.map((check) => <code key={check} className="run-failed-check">{check}</code>)}</p>}
    {failure && <RunProblemList problems={[...(problem.code || problem.message ? [problem] : []), ...problems]} />}
  </>;
}

function OverrideCheck({ api, detail, artifact, onRecorded }: {
  api: StudioClient; detail: RunDetail; artifact: string;
  onRecorded: (record: components["schemas"]["CheckOverrideView"]) => void;
}) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<unknown>();
  const [pending, setPending] = useState(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!detail.etag || controller.current || !reason.trim()) return;
    const request = new AbortController();
    controller.current = request;
    setPending(true);
    setError(undefined);
    try {
      const { data } = await api.POST("/v1/runs/{id}/checks/{check}/overrides", {
        signal: request.signal, params: {
          path: { id: detail.run.id, check: visualCheck }, header: { "If-Match": detail.etag },
        }, body: { artifact, reason: reason.trim() },
      });
      if (!request.signal.aborted && data) onRecorded(data);
    } catch (failure) {
      if (!request.signal.aborted) setError(failure);
    } finally {
      controller.current = null;
      if (!request.signal.aborted) setPending(false);
    }
  }

  return <form className="run-override" onSubmit={(event) => void submit(event)}>
    <p>Artifact <code>{artifact}</code></p>
    <label>Reason for visual override
      <input required maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} />
    </label>
    <button className="pill" type="submit" disabled={pending || !reason.trim()}>Record override</button>
    {error != null && <RunRefusal error={error} />}
  </form>;
}

function RunRefusal({ error }: { error: unknown }) {
  return <div>
    <Problem error={error} message={error instanceof ApiError ? error.detail?.message : undefined} />
    {error instanceof ApiError && error.code && <p className="request-id"><code>{error.code}</code></p>}
  </div>;
}

function RunChecks({ api, detail, change }: { api: StudioClient; detail: RunDetail; change: () => void }) {
  const { run } = detail;
  const [recorded, setRecorded] = useState<components["schemas"]["CheckOverrideView"][]>([]);
  const overrides = [...recorded, ...run.check_overrides ?? []];
  const checks = recordedChecks(run);
  return <section className="run-checks" aria-label="Run checks">
    <h4>Run checks</h4>
    {checks.length ? <ul>{checks.map(({ check, board }, index) => {
      const override = overrides.find(({ check: name, artifact }) => name === check.check && artifact === check.artifact);
      const first = checks.findIndex(({ check: item }) => item.check === check.check && item.result === "fail" &&
        item.artifact === check.artifact) === index;
      return <li key={index}>
        <p>{[board, check.check, check.slot?.toUpperCase()].filter(Boolean).join(" · ")} · <strong>
          {override ? results.overridden : results[check.result]}
        </strong></p>
        {override && <p>{override.reason}</p>}
        {first && !override && detail.etag && canOverride(run, check) && check.artifact &&
          <OverrideCheck api={api} detail={detail} artifact={check.artifact} onRecorded={(record) => {
            setRecorded((prior) => [...prior, record]);
            change();
          }} />}
      </li>;
    })}</ul> : <p className="muted">No checks recorded.</p>}
  </section>;
}

function RunDetails({ api, run, context, refresh }: {
  api: StudioClient; run: RunView; context: Context; refresh: () => void;
}) {
  const { id, story_id, revision } = run;
  const load = useCallback((signal: AbortSignal) =>
    // A list record signals that check details may have changed.
    runDetail(api, story_id, id, signal).then((detail) => {
      if (detail.run.revision < revision) throw new ApiError(409, "conflict.revision");
      return detail;
    }), [api, id, story_id, revision]);
  const { result, retry } = useRequest(load);
  return <div className="run-details">
    {hasDelivery(run) && <>
      <RunDelivery api={api} run={run} />
      <Link className="pill" to={treePath("productions", { ...context, board: undefined, run: id })}>Review in Productions</Link>
    </>}
    {result.status === "loading" && <p role="status" className="muted">Loading checks…</p>}
    {result.status === "failure" && <Problem error={result.error} retry={retry} />}
    {result.status === "success" && <RunChecks api={api} detail={result.data} change={() => { retry(); refresh(); }} />}
  </div>;
}

function RunCard({ api, run, context, feed }: { api: StudioClient; run: RunView; context: Context; feed: RunList }) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>();
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);

  async function cancel() {
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    const { signal } = controller;
    setPending(true);
    setError(undefined);
    try {
      const updated = await cancelRun(api, run, signal);
      if (!signal.aborted) feed.update(updated);
    } catch (failure) {
      if (!signal.aborted) setError(failure);
    } finally {
      request.current = null;
      if (!signal.aborted) {
        setPending(false);
        feed.refresh();
      }
    }
  }

  return <article className="run-card" aria-label={`Run ${run.number}`}>
    <div className="run-card-heading">
      <h3>Run {run.number}</h3>
      <span>{run.status === "held" ? "Paused · Held" : runStates[run.status]}</span>
    </div>
    <RunProgress run={run} />
    <div className="run-card-actions">
      <button type="button" className="pill" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? "Close details" : hasDelivery(run) ? "View run" : "Details"}
      </button>
      {activeRun(run) && !run.cancel_requested && <button type="button" className="pill" disabled={pending}
        onClick={() => void cancel()}>{pending ? "Requesting…" : "Cancel run"}</button>}
    </div>
    {error != null && <RunRefusal error={error} />}
    {open && <RunDetails api={api} run={run} context={context} refresh={feed.refresh} />}
  </article>;
}

export function StoryRuns({ api, context, feed, standalone = false }: {
  api: StudioClient; context: Context; feed: RunList; standalone?: boolean;
}) {
  const { runs, error, refresh } = feed;
  return <section className="story-runs" aria-label={standalone ? "Story runs" : undefined}
    aria-labelledby={standalone ? undefined : "story-runs-heading"}>
    <div className="run-section-heading">
      {!standalone && <h2 id="story-runs-heading">Runs</h2>}
      <div className="run-card-actions">
        {runs && runs.length >= 2 && <Link className="pill" to={treePath("board", context, "compare")}>Compare runs</Link>}
        <button className="pill" type="button" disabled={error != null && !retryableRead(error)} onClick={refresh}>Refresh runs</button>
      </div>
    </div>
    {error != null && <RunRefusal error={error} />}
    {!runs && error == null && <p role="status">Loading runs…</p>}
    {runs?.length === 0 && <Empty>No runs yet.</Empty>}
    {runs?.map((run) => <RunCard key={run.id} api={api} run={run} context={context} feed={feed} />)}
  </section>;
}
