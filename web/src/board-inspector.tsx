import { useCallback, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { ApiError, type StudioClient } from "./api/client";
import {
  activeJob, currentResult, currentVoiceId, inspectorProblem, queueVoice, useInspectorFormat, useVoiceJobs,
  useVoiceVersion, voicePressInput, voicePreviewUrl, type InspectorStory, type VoiceJob,
} from "./board-inspector-api";
import {
  boardPatch, boardValues, changedFields, changeLines, freshDraft, inspectorStore, keepChanges, methodOptions,
  moveLine, normalizeGaps, reconcileDraft, voiceInputChanged, type BoardDraft, type DraftLine, type InspectorStore,
} from "./board-inspector-draft";
import { ComparedValues, DirectionFields, InspectorSection, MethodFields, NumberField, ScriptFields } from "./board-inspector-fields";
import { loadBoard, type Board } from "./route-data";
import { Problem } from "./shell-ui";
import { useRequest } from "./use-request";
import "./board-inspector.css";

export type InspectorVoiceState = { board: string; revision: number; current: boolean };

type InspectorProps = {
  api: StudioClient;
  board: Board;
  story: InspectorStory;
  fps: number;
  timelinePending: boolean;
  onRefresh: () => void;
  onVoiceState: (state: InspectorVoiceState) => void;
};

export function BoardInspector({ children, ...props }: InspectorProps & { children?: ReactNode }) {
  const { api, board } = props;
  const readAccount = useCallback(async (signal: AbortSignal) => {
    const { data } = await api.GET("/v1/me", { signal });
    if (data?.principal.kind !== "human" || !data.principal.iss || !data.principal.sub) throw new ApiError(403);
    const identity = new TextEncoder().encode(JSON.stringify([data.principal.iss, data.principal.sub]));
    const hash = await crypto.subtle.digest("SHA-256", identity);
    return Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, "0")).join("");
  }, [api]);
  const { result } = useRequest(readAccount);
  const account = result.status === "success" ? result.data : undefined;
  const store = useMemo(() => inspectorStore(account), [account]);

  return <>
    <h2>Board inspector</h2>
    {children}
    {result.status === "loading" ? <p className="inspector-message" role="status">Loading inspector…</p>
      : <InspectorForm key={`${account ?? "memory"}:${board.id}`} {...props} store={store} />}
  </>;
}

function VoiceAudio({ id, hash, label }: { id: string; hash: unknown; label: string }) {
  const src = voicePreviewUrl(id, hash);
  const [failed, setFailed] = useState(false);
  if (!src) return null;
  return <div className="inspector-audio">
    <audio controls preload="none" src={src} aria-label={label} onError={() => setFailed(true)} />
    {failed && <p role="status">Voice playback unavailable.</p>}
  </div>;
}

function JobStatus({ job, board, dirty, paused }: { job: VoiceJob; board: Board; dirty: boolean; paused: boolean }) {
  if (job.status === "queued") return <p role="status">{paused ? "Queued · voice lane paused" : "Queued in voice lane"}</p>;
  if (job.status === "running") return <p role="status">Generating voice…</p>;
  if (job.status === "succeeded") return <p role="status">{currentResult(job, board, dirty) ? "Voice ready" : "Voice ready · stale"}</p>;
  if (job.status === "cancelled") return <p role="status">Voice job cancelled.</p>;
  const code = typeof job.error?.code === "string" ? job.error.code : undefined;
  const message = typeof job.error?.message === "string" ? job.error.message : undefined;
  return <p role="alert">Voice generation failed. {message}{code && code !== message ? ` (${code})` : ""}</p>;
}

function InspectorForm({
  api, board: panel, story, fps, store, timelinePending, onRefresh, onVoiceState,
}: InspectorProps & { store: InspectorStore }) {
  const [observed, setObserved] = useState(panel);
  const board = observed.revision >= panel.revision ? observed : panel;
  const [stored, setStored] = useState(() => store.draft(board.id) ?? freshDraft(board));
  const local = reconcileDraft(stored, board);
  const { values, newNote } = local;
  const changes = changedFields(local);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<unknown>();
  const [notice, setNotice] = useState("");
  const [loadedConflict, setLoadedConflict] = useState(false);
  const [press, setPress] = useState(() => store.press(board.id));
  const [posting, setPosting] = useState(false);
  const [jobError, setJobError] = useState<unknown>();
  const operation = useRef<AbortController>(null);
  useLayoutEffect(() => {
    const controller = new AbortController();
    operation.current = controller;
    return () => controller.abort();
  }, []);
  const inFlight = useRef(false);

  const receiveBoard = useCallback((latest: Board) => {
    setObserved((previous) => latest.revision >= previous.revision ? latest : previous);
  }, []);
  const voiceFeed = useVoiceJobs(api, board.story_id, board.id, receiveBoard);
  const format = useInspectorFormat(api, story.format_version_id);
  const voiceDirty = voiceInputChanged(local, board);
  const id = voiceFeed.ready ? currentVoiceId(board, voiceFeed.jobs, voiceDirty) : undefined;
  const voiceVersion = useVoiceVersion(api, story, board.id, id);
  const latest = voiceFeed.jobs.at(-1);
  const active = voiceFeed.jobs.filter(activeJob);
  const visibleJobs = latest && !active.includes(latest) ? [...active, latest] : active;
  const stale = voiceDirty || board.derived?.voice_state === "stale" ||
    Boolean(latest?.status === "succeeded" && !currentResult(latest, board, voiceDirty));
  const voiceFingerprint = voicePressInput(board, story);
  const samePress = press?.input === voiceFingerprint;
  const spoken = values.lines.length > 0;
  const conflictReady = Boolean(local.review && (loadedConflict || board.revision > local.revision));
  const timingDirty = changes.includes("timing") || voiceDirty;

  useLayoutEffect(() => {
    onVoiceState({ board: board.id, revision: board.revision, current: Boolean(id) });
  }, [board.id, board.revision, id, onVoiceState]);

  const boardAhead = board.revision > panel.revision || (board.revision === panel.revision &&
    (board.derived?.voice_state !== panel.derived?.voice_state ||
      board.derived?.frames !== panel.derived?.frames || board.derived?.photo_state !== panel.derived?.photo_state));
  useLayoutEffect(() => {
    if (boardAhead) onRefresh();
  }, [board, boardAhead, onRefresh]);

  function remember(draft: BoardDraft) {
    store.setDraft(board.id, draft);
    setStored(draft);
  }

  function change(next: BoardDraft) {
    setNotice("");
    setSaveError(undefined);
    remember(next);
  }

  function changeScript(lines: DraftLine[]) {
    change({ ...local, values: changeLines(values, lines, board, format.recipe) });
  }

  async function readConflict(signal: AbortSignal) {
    try {
      const latest = await loadBoard(api, board.story_id, board.id, signal);
      if (signal.aborted) return;
      receiveBoard(latest);
      setLoadedConflict(true);
    } catch (error) {
      if (!signal.aborted) setSaveError(error);
    }
  }

  async function save() {
    const signal = operation.current?.signal;
    if (!signal || signal.aborted || inFlight.current || timelinePending || local.review || !changes.length) return;
    inFlight.current = true;
    setSaving(true);
    setNotice("");
    setSaveError(undefined);
    try {
      const { data } = await api.PATCH("/v1/boards/{id}", {
        signal, params: { path: { id: board.id }, header: { "If-Match": `"${local.revision}"` } },
        body: boardPatch(local, board),
      });
      if (!data || data.id !== board.id || data.story_id !== board.story_id) throw new ApiError(500);
      if (signal.aborted) return;
      receiveBoard(data);
      remember(freshDraft(data, newNote));
      setNotice("Board saved.");
    } catch (error) {
      if (signal.aborted) return;
      if (error instanceof ApiError && error.status === 409) {
        remember({ ...local, review: true });
        await readConflict(signal);
      } else setSaveError(error);
    } finally {
      inFlight.current = false;
      if (!signal.aborted) setSaving(false);
    }
  }

  async function generate() {
    const signal = operation.current?.signal;
    if (!signal || signal.aborted || inFlight.current || !spoken || voiceDirty || local.review ||
        (press && !samePress) || (!press && active.length > 0)) return;
    const request = press ?? { key: crypto.randomUUID(), input: voiceFingerprint };
    store.setPress(board.id, request);
    setPress(request);
    inFlight.current = true;
    setPosting(true);
    setJobError(undefined);
    try {
      const job = await queueVoice(api, board.id, request.key, signal);
      if (signal.aborted) return;
      store.setPress(board.id);
      setPress(undefined);
      voiceFeed.submitted(job);
    } catch (error) {
      if (signal.aborted) return;
      if (error instanceof ApiError && error.status > 0 && error.status < 500) {
        store.setPress(board.id);
        setPress(undefined);
      }
      setJobError(error);
    } finally {
      inFlight.current = false;
      if (!signal.aborted) setPosting(false);
    }
  }

  function resolve(keep: boolean) {
    change(keep ? keepChanges(local, board) : freshDraft(board, newNote));
    setLoadedConflict(false);
  }

  const sendLabel = posting ? "Submitting…" : press ? "Retry voice request" : stale || id ? "Regenerate voice" : "Generate voice";
  const frames = board.derived?.frames;
  const canGenerate = voiceFeed.ready && !saving && !posting && !timelinePending && !voiceDirty && !local.review &&
    (press ? samePress : !active.length);

  return <>
    {local.review && <div className="inspector-conflict">
      <p role="alert">{conflictReady ? "The board changed. Review both versions before saving."
        : saving ? "The board changed. Loading the latest version…" : "Load the latest board to review your edits."}</p>
      {conflictReady ? <>
        <div className="inspector-comparison">
          <ComparedValues title="Your unsaved version" values={values} changes={changes} story={story} />
          <ComparedValues title="Latest saved version" values={boardValues(board)} changes={changes} story={story} />
        </div>
        <div className="inspector-actions">
          <button className="pill" type="button" disabled={saving} onClick={() => resolve(true)}>Keep my edited fields</button>
          <button className="pill" type="button" disabled={saving} onClick={() => resolve(false)}>Use latest saved version</button>
        </div>
      </> : <button className="pill" type="button" disabled={saving} onClick={() => {
        const signal = operation.current?.signal;
        if (signal) { setSaveError(undefined); void readConflict(signal); }
      }}>Load latest board</button>}
    </div>}
    <fieldset className="inspector-form" disabled={saving}>
      <InspectorSection title="Script" open>
        <ScriptFields story={story} lines={values.lines} onChange={(lines) =>
          changeScript(lines.length === values.lines.length ? lines : normalizeGaps(lines, values.lines[0]?.key))}
          onMove={(index, direction) => {
            const lines = moveLine(values.lines, index, direction);
            if (lines !== values.lines) changeScript(lines);
          }}
          lineVoice={(lineId) => {
            const take = voiceVersion.voice?.takes.find(({ line_id }) => line_id === lineId);
            return id && take && <VoiceAudio key={id} id={id} hash={take.sha256} label="Current line take" />;
          }} />
      </InspectorSection>
      <InspectorSection title="Voice & timing" open>
        {spoken ? <>
          <NumberField label="Lead (ms)" min={0} max={120000} value={values.timing.lead} update={(lead) =>
            change({ ...local, values: { ...values, timing: { ...values.timing, lead } } })} />
          <NumberField label="Tail (ms)" min={250} value={values.timing.tail} update={(tail) =>
            change({ ...local, values: { ...values, timing: { ...values.timing, tail } } })} />
          <p role="status">{!timingDirty && typeof frames === "number"
            ? `Board length ${(frames / fps).toFixed(3)} s`
            : timingDirty ? "Save changes to update timing." : "Timing pending"}</p>
          {id && voiceVersion.voice?.track && <VoiceAudio key={id} id={id}
            hash={voiceVersion.voice.track.sha256} label="Current board voice" />}
          {voiceVersion.error && <Problem error={voiceVersion.error} message="The current voice could not be loaded." retry={voiceVersion.retry} />}
          {stale && latest?.status !== "succeeded" && <p className="muted">Voice is stale.</p>}
          {voiceDirty && <p className="muted">Save the script before generating voice.</p>}
          {press && !samePress ? <>
            <p className="muted">The saved script changed since the last request.</p>
            <button className="pill" type="button" onClick={() => {
              store.setPress(board.id); setPress(undefined); setJobError(undefined);
            }}>Clear previous request</button>
          </> : <button type="button" className="pill" disabled={!canGenerate} onClick={() => void generate()}>{sendLabel}</button>}
        </> : <NumberField label="Silent hold (ms)" min={100} max={120000} value={values.timing.hold} update={(hold) =>
          change({ ...local, values: { ...values, timing: { ...values.timing, hold } } })} />}
        {voiceFeed.paused && !active.some(({ status }) => status === "queued") && <p role="status">Voice lane paused</p>}
        {visibleJobs.map((job) => <JobStatus key={job.id} job={job} board={board} dirty={voiceDirty} paused={voiceFeed.paused} />)}
        {voiceFeed.error !== undefined && <Problem error={voiceFeed.error} message={`Voice status unavailable. ${inspectorProblem(voiceFeed.error)}`} />}
        {jobError !== undefined && <Problem error={jobError} message={`Voice request failed. ${inspectorProblem(jobError)}`} />}
      </InspectorSection>
      <InspectorSection title="Method">
        {format.error !== undefined ? <Problem error={format.error} message="The pinned format could not be loaded." retry={format.retry} />
          : format.recipe === undefined ? <p role="status">Loading format…</p>
            : <MethodFields values={values} options={methodOptions(board.cast, values.lines, format.recipe)}
              onChange={(method) => change({ ...local, values: { ...values, method } })} />}
      </InspectorSection>
      <DirectionFields values={values} newNote={newNote} disabled={saving}
        updateNewNote={(newNote) => change({ ...local, newNote })}
        add={(note) => change({ ...local, newNote: "", values: { ...values, notes: [...values.notes, note] } })}
        updateNotes={(notes) => change({ ...local, values: { ...values, notes } })}
        updateCue={(next) => change({ ...local, values: { ...values, cues: values.cues.map((cue) => cue.id === next.id ? next : cue) } })} />
    </fieldset>
    <div className="inspector-footer">
      {(changes.length > 0 || newNote) && <p className="muted">{store.canRestore
        ? "Unsaved edits stay in this tab until it closes." : "Unsaved edits stay on this page."}</p>}
      <button className="pill primary" type="button" disabled={saving || posting || timelinePending || !changes.length || Boolean(local.review)}
        onClick={() => void save()}>{saving ? "Saving…" : "Save board"}</button>
      {saveError !== undefined && <Problem error={saveError}
        message={`${local.review ? "Latest board unavailable." : "Board save failed."} ${inspectorProblem(saveError)}`} />}
      <p className="inspector-save-status" role="status">{notice}</p>
    </div>
  </>;
}
