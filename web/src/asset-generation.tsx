import { useCallback, useEffect, useLayoutEffect, useRef, useState, type FormEvent } from "react";

import { ApiError, type StudioClient } from "./api/client";
import { AssetProblem, CandidateReview } from "./asset-candidate-review";
import {
  activeCandidate, loadAssetLanes, loadCandidateJob, loadCandidateResult, queueCandidate, queueMatte,
  type CandidateRequest, type CandidateStatus, type MatteRequest,
} from "./asset-library-data";
import { kindLabel } from "./asset-library-model";
import type { AssetTarget, SelectCutout } from "./asset-version-card";
import type { AssetVersion } from "./photo-composer-model";
import type { Production } from "./route-data";
import { pollRuns } from "./run-polling";
import { useRequest } from "./use-request";

const generationKinds = { cast: true, costume: true, set: true, prop: true } satisfies Record<CandidateRequest["kind"], true>;

function ambiguous(error: unknown) {
  return !(error instanceof ApiError) || error.status === 0 || error.status >= 500;
}

export type CandidatePress<Body> = { body: Body; key: string };

function useCandidatePress<Body>(
  api: StudioClient,
  queue: (api: StudioClient, body: Body, key: string, signal: AbortSignal) => Promise<CandidateStatus>,
  onJob: (id: string) => void,
  presses: Map<string, CandidatePress<Body>>,
  intention: string,
  retainAmbiguous = false,
) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<{ intention: string; value: unknown }>();
  const press = presses.get(intention);
  const request = useRef<AbortController | null>(null);
  const showJob = useRef(onJob);
  useEffect(() => () => request.current?.abort(), []);
  useLayoutEffect(() => { showJob.current = onJob; }, [onJob]);

  async function submit(body: () => Body) {
    if (request.current) return;
    const unresolved = presses.get(intention);
    const attempt = unresolved ?? { body: body(), key: crypto.randomUUID() };
    presses.set(intention, attempt);
    const pending = new AbortController();
    request.current = pending;
    setSaving(true);
    setError(undefined);
    try {
      const queued = await queue(api, attempt.body, attempt.key, pending.signal);
      if (pending.signal.aborted) return;
      presses.delete(intention);
      showJob.current(queued.id);
    } catch (error) {
      if (!pending.signal.aborted) {
        // A refused retry can leave an earlier matte request in the queue.
        if (!ambiguous(error) && !(retainAmbiguous && unresolved)) presses.delete(intention);
        setError({ intention, value: error });
      }
    } finally {
      if (!pending.signal.aborted) {
        request.current = null;
        setSaving(false);
      }
    }
  }
  return { retrying: Boolean(press), saving, error: error?.intention === intention ? error.value : undefined, submit };
}

function useAssetPoll<T>(
  load: (signal: AbortSignal) => Promise<T>, active: (value: T) => boolean, enabled = true,
) {
  const [result, setResult] = useState<{ load: typeof load; value?: T; error?: unknown }>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    const poller = pollRuns(document, {
      read: load,
      onData(next) {
        setResult({ load, value: next });
        return active(next);
      },
      onError(error) {
        setResult((previous) => ({ load, value: previous?.load === load ? previous.value : undefined, error }));
        return ambiguous(error);
      },
    });
    return () => poller.stop();
  }, [active, attempt, enabled, load]);
  const current = result?.load === load ? result : undefined;
  return { value: current?.value, error: current?.error, retry: () => setAttempt((attempt) => attempt + 1) };
}

const keepPollingLane = () => true;
type CandidateJobRecord = Awaited<ReturnType<typeof loadCandidateJob>>;
const keepPollingJob = (job?: CandidateJobRecord) => job !== undefined && activeCandidate(job.status);

export function useCandidateJob(api: StudioClient, id?: string) {
  const load = useCallback((signal: AbortSignal) => id ? loadCandidateJob(api, id, signal) : Promise.resolve(undefined), [api, id]);
  const { value, error, retry } = useAssetPoll(load, keepPollingJob, id !== undefined);
  const refused = error != null && !ambiguous(error);
  const active = id !== undefined && !refused && (!value || activeCandidate(value.status));
  const missing = error instanceof ApiError && error.status === 404;
  return { value: refused ? undefined : value, error, retry, missing, active };
}

function CandidateResult({ api, job, target, onPromoted, onCutout }: {
  api: StudioClient; job: CandidateJobRecord; target?: AssetTarget; onPromoted: () => void; onCutout?: SelectCutout;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const { id: jobId, result_version_id: versionId } = job;
  const spec = job.kind === "matte" ? job.matte : job.asset_candidate;
  const assetId = job.kind === "asset_candidate" ? job.target_id : undefined;
  const sourceVersionId = job.kind === "matte" ? job.target_id : undefined;
  const productionId = spec?.production_id;
  const kind = spec?.kind;
  // A visibility refresh can return the same job in a new object while a
  // promotion request is pending. Keep the review mounted for the same result.
  const load = useCallback((signal: AbortSignal) => loadCandidateResult(api, {
    jobId, versionId, assetId, productionId, kind, sourceVersionId,
  }, signal), [api, jobId, versionId, assetId, productionId, kind, sourceVersionId]);
  const { result, retry } = useRequest(load);
  function refresh() {
    heading.current?.focus();
    retry();
  }
  return <section className="asset-candidates" aria-labelledby="asset-candidates-heading">
    <h2 ref={heading} id="asset-candidates-heading" tabIndex={-1}>Candidates</h2>
    {result.status === "loading" && <p role="status">Loading result…</p>}
    {result.status === "failure" && <AssetProblem error={result.error} retry={refresh} />}
    {result.status === "success" && <CandidateReview key={result.data.id} version={result.data} jobId={jobId}
      api={api} target={target} onPromoted={onPromoted} refresh={refresh} onCutout={onCutout} />}
  </section>;
}

function cutoutAdvice(code: string) {
  switch (code) {
    case "matting.shape_invalid":
    case "matting.target_exceeds_frame":
    case "adapter.request_invalid":
      return "Try another cast slot or another photo.";
    case "matting.sidecar_unavailable":
    case "adapter.not_found":
    case "adapter.busy":
    case "adapter.timeout":
    case "adapter.pin_mismatch":
    case "adapter.command_failed":
    case "adapter.response_invalid":
    case "work.dispatch_unconfirmed":
    case "work.result_rejected":
    case "service_unavailable":
      return "Try requesting the cutout again later.";
  }
}

function CandidateJob({ api, status, matte, paused, focus, target, onPromoted, onCutout }: {
  api: StudioClient; status: ReturnType<typeof useCandidateJob>; matte: boolean; paused: boolean; focus: boolean;
  target?: AssetTarget;
  onPromoted: () => void; onCutout?: SelectCutout;
}) {
  const { value: job, error, retry } = status;
  const region = useRef<HTMLDivElement>(null);
  const statusLine = useRef<HTMLParagraphElement>(null);
  const focused = useRef(false);
  const firstRead = useRef(false);
  useLayoutEffect(() => {
    if (!focus) return;
    const heading = region.current?.querySelector<HTMLElement>("#asset-candidates-heading");
    if (!focused.current) {
      (heading ?? statusLine.current ?? region.current)?.focus();
      focused.current = true;
    } else if (!firstRead.current && heading && document.activeElement === statusLine.current) {
      heading.focus();
    }
    if (job) firstRead.current = true;
  }, [focus, job]);

  const subject = matte ? "Cutout" : "Candidate";
  const jobName = matte ? "cutout job" : "candidate job";
  const label = job ? {
    queued: paused ? `${subject} queued · ${matte ? "matte" : "image"} lane paused` : `${subject} queued`,
    running: `${subject} running`,
    succeeded: `${subject} ready`,
    failed: `${subject} failed`,
    cancelled: `${subject} cancelled`,
  }[job.status] : error == null ? `Reading ${jobName}…` : undefined;
  const advice = matte && job?.status === "failed" && job.error ? cutoutAdvice(job.error.code) : undefined;

  return <div className="asset-job" ref={region} tabIndex={-1}>
    {status.missing ? <p role="alert">{subject} job not found.</p> : <>
      {label && <p ref={statusLine} role="status" tabIndex={-1}>{label}</p>}
      {error != null && <AssetProblem error={error} retry={retry} />}
    </>}
    {matte && job?.status === "queued" && paused &&
      <p className="muted">A signed-in Studio user can resume the matte lane.</p>}
    {job?.status === "failed" && job.error && <p role="alert">
      {job.error.message} · {job.error.code}{advice && <> <span>{advice}</span></>}
    </p>}
    {job?.status === "succeeded" && <CandidateResult api={api} job={job} target={target}
      onPromoted={onPromoted} onCutout={onCutout} />}
  </div>;
}

export function AssetGeneration({ api, generate, production, scopeReady, job, jobStatus, matte, focusJob, target, onJob,
  onPromoted, onCutout, cuttingOut }: {
  api: StudioClient; generate: boolean; production?: Production; scopeReady: boolean;
  job?: string; jobStatus: ReturnType<typeof useCandidateJob>; matte: boolean; focusJob: boolean; target?: AssetTarget;
  onJob: (job?: string) => void; onPromoted: () => void; onCutout?: SelectCutout; cuttingOut: boolean;
}) {
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [kind, setKind] = useState<CandidateRequest["kind"]>("cast");
  const presses = useRef(new Map<string, CandidatePress<CandidateRequest>>()).current;
  const { retrying, saving, error, submit } = useCandidatePress(api, queueCandidate, onJob, presses, "candidate");
  const { active: jobActive } = jobStatus;
  const loadLanes = useCallback((signal: AbortSignal) => loadAssetLanes(api, signal), [api]);
  const lanes = useAssetPoll(loadLanes, keepPollingLane, generate || jobActive);
  const imageLane = lanes.value?.image;
  const jobLane = matte ? lanes.value?.matte : imageLane;
  const unavailable = jobActive || cuttingOut || (!retrying && (!scopeReady || !name.trim() || !prompt.trim()));

  function request(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!unavailable) void submit(() => ({
      name: name.trim(), kind, prompt: prompt.trim(), production_id: production?.id ?? null,
      seed: crypto.getRandomValues(new Uint32Array(1))[0],
    }));
  }

  return <div className={generate ? "asset-generation" : undefined}>
    {generate && <form className="asset-card asset-generate-form" onSubmit={request} aria-label="Generate asset candidate">
      <p role="status" className="asset-lane">
        {imageLane ? (imageLane.paused ? "Image lane paused" : "Shared image lane open") : "Reading image lane…"}
      </p>
      {lanes.error != null && <AssetProblem error={lanes.error} retry={lanes.retry} />}
      {scopeReady && <p className="muted">{production?.name ?? "Shared library"}</p>}
      <label>Name<input value={name} maxLength={100} required disabled={saving || retrying}
        onChange={(event) => setName(event.currentTarget.value)} /></label>
      <label>Kind<select value={kind} disabled={saving || retrying} onChange={(event) => {
        setKind(event.currentTarget.value as CandidateRequest["kind"]);
      }}>
        {Object.keys(generationKinds).map((kind) => <option key={kind} value={kind}>{kindLabel(kind)}</option>)}
      </select></label>
      <label>Prompt<textarea value={prompt} maxLength={1800} rows={5} required disabled={saving || retrying}
        onChange={(event) => setPrompt(event.currentTarget.value)} /></label>
      <button className="pill primary" type="submit" aria-disabled={saving || unavailable}>
        {saving ? "Submitting…" : retrying ? "Retry candidate request" : "Request candidate"}
      </button>
      {error != null && <AssetProblem error={error} />}
    </form>}
    {job && <CandidateJob key={job} status={jobStatus} api={api} matte={matte} focus={focusJob}
      paused={jobLane?.paused === true} target={target}
      onPromoted={onPromoted} onCutout={saving || retrying ? undefined : onCutout} />}
    {job && <div className="asset-actions"><button className="pill" type="button" disabled={saving || retrying || cuttingOut}
      onClick={() => {
        document.getElementById("page-heading")?.focus();
        onJob();
      }}>Close job view</button></div>}
  </div>;
}

export function MatteForm({ api, source, format, slots, presses, onJob, onClose }: {
  api: StudioClient; source: AssetVersion; format: { id: string; format_id: string; number: number };
  slots: string[]; presses: Map<string, CandidatePress<MatteRequest>>;
  onJob: (job: string) => void; onClose: () => void;
}) {
  const [slot, setSlot] = useState("");
  const select = useRef<HTMLSelectElement>(null);
  const intention = JSON.stringify([source.id, format.id, slot]);
  const { retrying, saving, error, submit } = useCandidatePress(api, queueMatte, onJob, presses, intention, true);
  const advice = error instanceof ApiError && error.code ? cutoutAdvice(error.code) : undefined;
  useEffect(() => { select.current?.focus(); }, []);

  function request(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (slots.includes(slot)) void submit(() => ({ source_version_id: source.id, format_version_id: format.id, slot }));
  }

  return <form className="asset-card asset-generate-form" aria-label="Request matte" onSubmit={request}>
    <h2>Cut out {source.name} · v{source.number}</h2>
    <p className="muted">Format {format.format_id} · v{format.number}</p>
    <label>Cast slot<select ref={select} required value={slot}
      disabled={saving} onChange={(event) => setSlot(event.currentTarget.value)}>
      <option value="" disabled>Choose a slot</option>
      {slots.map((value) => <option key={value} value={value}>{value.toUpperCase()}</option>)}
    </select></label>
    <div className="asset-actions">
      <button className="pill primary" type="submit" aria-disabled={!slot || saving}>
        {saving ? "Submitting…" : retrying ? "Retry matte request" : "Request matte"}
      </button>
      <button className="pill" type="button" disabled={saving} onClick={onClose}>Close cutout</button>
    </div>
    {error != null && <AssetProblem error={error} />}
    {advice && <p className="muted">{advice}</p>}
  </form>;
}
