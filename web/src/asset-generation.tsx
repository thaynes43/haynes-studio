import { useCallback, useEffect, useLayoutEffect, useRef, useState, type FormEvent } from "react";

import { ApiError, type StudioClient } from "./api/client";
import { AssetProblem, CandidateReview } from "./asset-candidate-review";
import {
  activeCandidate, loadCandidateJob, loadCandidateResult, loadImageLane, queueCandidate, type CandidateRequest,
} from "./asset-library-data";
import { kindLabel } from "./asset-library-model";
import type { AssetTarget } from "./asset-version-card";
import type { Production } from "./route-data";
import { pollRuns } from "./run-polling";
import { useRequest } from "./use-request";

const generationKinds = { cast: true, costume: true, set: true, prop: true } satisfies Record<CandidateRequest["kind"], true>;
type Press = { body: CandidateRequest; key: string };

function ambiguous(error: unknown) {
  return !(error instanceof ApiError) || error.status === 0 || error.status >= 500;
}

function useAssetPoll<T>(
  load: (signal: AbortSignal) => Promise<T>, active: (value: T) => boolean, enabled = true,
) {
  const [value, setValue] = useState<T>();
  const [error, setError] = useState<unknown>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    const poller = pollRuns(document, {
      read: load,
      onData(next) {
        setValue(next);
        setError(undefined);
        return active(next);
      },
      onError(error) {
        setError(error);
        return ambiguous(error);
      },
    });
    return () => poller.stop();
  }, [active, attempt, enabled, load]);
  return { value, error, retry: () => setAttempt((attempt) => attempt + 1) };
}

const keepPollingLane = () => true;
const keepPollingJob = (job: Awaited<ReturnType<typeof loadCandidateJob>>) => activeCandidate(job.status);

function CandidateResult({ api, job, target, onPromoted }: {
  api: StudioClient; job: Awaited<ReturnType<typeof loadCandidateJob>>; target?: AssetTarget; onPromoted: () => void;
}) {
  const { id: jobId, result_version_id: versionId, target_id: assetId, asset_candidate: spec } = job;
  const productionId = spec?.production_id;
  const kind = spec?.kind;
  // A visibility refresh can return the same job in a new object while a
  // promotion request is pending. Keep the review mounted for the same result.
  const load = useCallback((signal: AbortSignal) => loadCandidateResult(api, {
    jobId, versionId, assetId, productionId, kind,
  }, signal), [api, jobId, versionId, assetId, productionId, kind]);
  const { result, retry } = useRequest(load);
  return <section className="asset-candidates" aria-labelledby="asset-candidates-heading">
    <h2 id="asset-candidates-heading">Candidates</h2>
    {result.status === "loading" && <p role="status">Loading result…</p>}
    {result.status === "failure" && <AssetProblem error={result.error} retry={retry} />}
    {result.status === "success" && <CandidateReview key={result.data.id} version={result.data} jobId={jobId}
      api={api} target={target} onPromoted={onPromoted} refresh={retry} />}
  </section>;
}

function CandidateJob({ api, id, paused, target, onPromoted, onStatus }: {
  api: StudioClient; id: string; paused: boolean; target?: AssetTarget;
  onPromoted: () => void; onStatus: (id: string, active: boolean) => void;
}) {
  const load = useCallback((signal: AbortSignal) => loadCandidateJob(api, id, signal), [api, id]);
  const { value: job, error, retry } = useAssetPoll(load, keepPollingJob);
  const active = !job || activeCandidate(job.status);
  useEffect(() => { onStatus(id, active); }, [active, id, onStatus]);

  const label = !job ? "Reading candidate job…" : {
    queued: paused ? "Candidate queued · image lane paused" : "Candidate queued",
    running: "Candidate running",
    succeeded: "Candidate ready",
    failed: "Candidate failed",
    cancelled: "Candidate cancelled",
  }[job.status];

  return <div className="asset-job">
    <p role="status">{label}</p>
    {error != null && <AssetProblem error={error} retry={retry} />}
    {job?.status === "failed" && job.error && <p role="alert">{job.error.message} · {job.error.code}</p>}
    {job?.status === "succeeded" && <CandidateResult api={api} job={job} target={target} onPromoted={onPromoted} />}
  </div>;
}

export function AssetGeneration({ api, generate, production, scopeReady, job, target, onJob, onPromoted }: {
  api: StudioClient; generate: boolean; production?: Production; scopeReady: boolean;
  job?: string; target?: AssetTarget; onJob: (job?: string) => void; onPromoted: () => void;
}) {
  const [progress, setProgress] = useState<{ id: string; active: boolean }>();
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [kind, setKind] = useState<CandidateRequest["kind"]>("cast");
  const [press, setPress] = useState<Press>();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>();
  const request = useRef<AbortController | null>(null);
  const showJob = useRef(onJob);
  const jobActive = job !== undefined && (progress?.id !== job || progress.active);
  const loadLane = useCallback((signal: AbortSignal) => loadImageLane(api, signal), [api]);
  const lane = useAssetPoll(loadLane, keepPollingLane, generate || jobActive);
  const onStatus = useCallback((id: string, active: boolean) => setProgress({ id, active }), []);

  useEffect(() => () => request.current?.abort(), []);
  useLayoutEffect(() => { showJob.current = onJob; }, [onJob]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (request.current || jobActive || (!press && (!scopeReady || !name.trim() || !prompt.trim()))) return;
    const attempt = press ?? {
      body: { name: name.trim(), kind, prompt: prompt.trim(), production_id: production?.id ?? null,
        seed: crypto.getRandomValues(new Uint32Array(1))[0] },
      key: crypto.randomUUID(),
    };
    const pending = new AbortController();
    request.current = pending;
    setSaving(true);
    setError(undefined);
    try {
      const queued = await queueCandidate(api, attempt.body, attempt.key, pending.signal);
      if (pending.signal.aborted) return;
      setPress(undefined);
      showJob.current(queued.id);
    } catch (error) {
      if (!pending.signal.aborted) {
        setPress(ambiguous(error) ? attempt : undefined);
        setError(error);
      }
    } finally {
      if (!pending.signal.aborted) {
        request.current = null;
        setSaving(false);
      }
    }
  }

  return <div className={generate ? "asset-generation" : undefined}>
    {generate && <form className="asset-card asset-generate-form" onSubmit={submit} aria-label="Generate asset candidate">
      <p role="status" className="asset-lane">
        {lane.value ? (lane.value.paused ? "Image lane paused" : "Shared image lane open") : "Reading image lane…"}
      </p>
      {lane.error != null && <AssetProblem error={lane.error} retry={lane.retry} />}
      {scopeReady && <p className="muted">{production?.name ?? "Shared library"}</p>}
      <label>Name<input value={name} maxLength={100} required disabled={saving || Boolean(press)}
        onChange={(event) => setName(event.currentTarget.value)} /></label>
      <label>Kind<select value={kind} disabled={saving || Boolean(press)} onChange={(event) => {
        setKind(event.currentTarget.value as CandidateRequest["kind"]);
      }}>
        {Object.keys(generationKinds).map((kind) => <option key={kind} value={kind}>{kindLabel(kind)}</option>)}
      </select></label>
      <label>Prompt<textarea value={prompt} maxLength={1800} rows={5} required disabled={saving || Boolean(press)}
        onChange={(event) => setPrompt(event.currentTarget.value)} /></label>
      <button className="pill primary" type="submit" aria-disabled={saving || jobActive || !scopeReady ||
        (!press && (!name.trim() || !prompt.trim()))}>
        {saving ? "Submitting…" : press ? "Retry candidate request" : "Request candidate"}
      </button>
      {error != null && <AssetProblem error={error} />}
    </form>}
    {job && <CandidateJob key={job} id={job} api={api} paused={lane.value?.paused === true} target={target}
      onPromoted={onPromoted} onStatus={onStatus} />}
    {job && <div className="asset-actions"><button className="pill" type="button" disabled={saving || Boolean(press)}
      onClick={() => {
        document.getElementById("page-heading")?.focus();
        onJob();
      }}>Close job view</button></div>}
  </div>;
}
