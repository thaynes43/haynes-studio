import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router";

import { ApiError, type StudioClient } from "./api/client";
import type { components } from "./api/schema";
import { ReviewTime } from "./production-approval";
import type { Run } from "./production-review-data";
import { boardLabel } from "./route-data";
import { treePath, type Context } from "./routes";
import { Problem } from "./shell-ui";
import { useRequest } from "./use-request";
import "./production-feedback.css";

type Schemas = components["schemas"];
type Candidate = Schemas["CandidateDetails"];
type Attribution = Schemas["Attribution"];
type FrozenBoard = Schemas["Board"];
type Write = (signal: AbortSignal) => Promise<void>;
type Submit = (owner: string, write: Write, refreshDraft?: boolean) => void;

function attribution(actor: Attribution) {
  return actor.display_name || actor.key_id || "Signed-in person";
}

function frozenBoardLabel(board: FrozenBoard) {
  return [boardLabel(board), board.title].filter(Boolean).join(" · ");
}

function Refusal({ error, retry }: { error: unknown; retry?: () => void }) {
  return <div>
    <Problem error={error} message={error instanceof ApiError ? error.detail?.message : undefined} retry={retry} />
    {error instanceof ApiError && error.code && <p className="request-id"><code>{error.code}</code></p>}
  </div>;
}

function toggle(values: string[], id: string, selected: boolean) {
  return selected ? [...values, id] : values.filter((value) => value !== id);
}

function CandidateCard({
  api, candidate, context, boards, name, etag, busy, canStart, submit, started, error,
}: {
  api: StudioClient;
  candidate: Candidate;
  context: Context;
  boards: FrozenBoard[];
  name: string;
  etag: string;
  busy: boolean;
  canStart: boolean;
  submit: Submit;
  started: (iteration: Schemas["Iteration"]) => void;
  error: unknown;
}) {
  const [text, setText] = useState("");
  const [boardIds, setBoardIds] = useState<string[]>([]);
  const [noteIds, setNoteIds] = useState<string[]>([]);
  const [replacesId, setReplacesId] = useState<string>();
  const heading = useId();
  const boardNames = new Map(boards.map((board) => [board.id, frozenBoardLabel(board)]));
  const corrected = new Set(candidate.notes.map((note) => note.replaces_id));

  function addNote(event: FormEvent) {
    event.preventDefault();
    submit(candidate.id, async (signal) => {
      const { data } = await api.POST("/v1/candidates/{id}/feedback", {
        signal, params: { path: { id: candidate.id } },
        body: { text, board_ids: boardIds, replaces_id: replacesId },
      });
      if (!data) throw new ApiError(502);
      if (signal.aborted) return;
      setText("");
      setBoardIds([]);
      setReplacesId(undefined);
    });
  }

  function iterate() {
    submit(candidate.id, async (signal) => {
      const { data } = await api.POST("/v1/candidates/{id}/iterations", {
        signal, params: { path: { id: candidate.id }, header: { "If-Match": etag } },
        body: { note_ids: noteIds },
      });
      if (!data) throw new ApiError(502);
      if (!signal.aborted) started(data.iteration);
    }, true);
  }

  return <section className="feedback-candidate" aria-labelledby={heading}>
    <h4 id={heading}>{name}</h4>
    <p className="muted">Presented by {attribution(candidate.presented_by)} · <ReviewTime value={candidate.presented_at} /></p>
    {candidate.answering_runs.length > 0 && <ul className="feedback-run-links" aria-label="Runs answering this candidate">
      {candidate.answering_runs.map(({ id, number }) => <li key={id}>
        <Link to={treePath("productions", { ...context, run: id })}>Run {number}</Link>
      </li>)}
    </ul>}
    {candidate.notes.length > 0 && <ul className="feedback-notes" aria-label="Feedback notes">
      {candidate.notes.map((note) => <li key={note.id}>
        <p id={note.id} className="feedback-text">{note.text}</p>
        <p className="muted">
          {attribution(note.written_by)} · <ReviewTime value={note.written_at} />
          {note.replaces_id && <> · <a href={`#${note.replaces_id}`}>Correction</a></>}
          {corrected.has(note.id) && " · Corrected"}
        </p>
        {note.board_ids.length > 0 && <ul className="feedback-board-names">
          {note.board_ids.map((id) => <li key={id}>{boardNames.get(id) ?? id}</li>)}
        </ul>}
        <div className="feedback-actions">
          <label className="feedback-checkbox">
            <input type="checkbox" checked={noteIds.includes(note.id)}
              disabled={busy || (noteIds.length >= 64 && !noteIds.includes(note.id))}
              aria-describedby={note.id}
              onChange={(event) => setNoteIds(toggle(noteIds, note.id, event.target.checked))} />
            Include in iteration
          </label>
          {!corrected.has(note.id) && <button className="pill" type="button" disabled={busy}
            onClick={() => {
              setReplacesId(note.id);
              setBoardIds(note.board_ids);
              setText((current) => current || note.text);
            }}>Correct note</button>}
        </div>
      </li>)}
    </ul>}
    {candidate.notes.length > 0 && <button className="pill" type="button"
      disabled={busy || !canStart || !noteIds.length} onClick={iterate}>Start an iteration</button>}
    <form className="feedback-form" onSubmit={addNote}>
      <label>{replacesId ? "Corrected feedback" : "Feedback note"}
        <textarea value={text} maxLength={4000} rows={3} disabled={busy}
          onChange={(event) => setText(event.target.value)} />
      </label>
      {boards.length > 0 && <details>
        <summary>Boards (optional){boardIds.length > 0 && ` · ${boardIds.length} selected`}</summary>
        <div className="feedback-board-options">
          {boards.map((board) => <label key={board.id} className="feedback-checkbox">
            <input type="checkbox" checked={boardIds.includes(board.id)}
              disabled={busy || (boardIds.length >= 256 && !boardIds.includes(board.id))}
              onChange={(event) => setBoardIds(toggle(boardIds, board.id, event.target.checked))} />
            {boardNames.get(board.id)}
          </label>)}
        </div>
      </details>}
      <div className="feedback-actions">
        <button className="pill" type="submit" disabled={busy}>{replacesId ? "Save correction" : "Add feedback"}</button>
        {replacesId && <button className="pill" type="button" disabled={busy}
          onClick={() => setReplacesId(undefined)}>Cancel correction</button>}
      </div>
    </form>
    {error != null && <Refusal error={error} />}
  </section>;
}

export function RunAnswers({ context, run, runs }: { context: Context; run: Run; runs: Run[] }) {
  if (!run.answers) return null;
  const previous = runs.find(({ id }) => id === run.answers?.run_id);
  return <p>Answers <Link to={treePath("productions", { ...context, run: run.answers.run_id })}>
    {previous ? `run ${previous.number}` : "previous run"}
  </Link></p>;
}

export function CandidateReview({ api, run, context, reloadDraft }: {
  api: StudioClient; run: Run; context: Context; reloadDraft: (signal: AbortSignal) => Promise<void>;
}) {
  const { id, story_id } = run;
  const loadSnapshot = useCallback(async (signal: AbortSignal) => {
    const { data } = await api.GET("/v1/runs/{id}/snapshot", { signal, params: { path: { id } } });
    if (!data) throw new ApiError(502);
    return data;
  }, [api, id]);
  const loadCandidates = useCallback(async (signal: AbortSignal) => {
    const { data, response } = await api.GET("/v1/stories/{id}/candidates", {
      signal, params: { path: { id: story_id }, query: { run_id: id } },
    });
    const etag = response.headers.get("ETag");
    if (!data || !etag) throw new ApiError(502);
    return { data, etag };
  }, [api, id, story_id]);
  const frozen = useRequest(loadSnapshot);
  const initial = useRequest(loadCandidates);
  const [refreshed, setRefreshed] = useState<Awaited<ReturnType<typeof loadCandidates>>>();
  const current = refreshed ?? (initial.result.status === "success" ? initial.result.data : undefined);
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<{ owner: string; error: unknown }>();
  const [refreshFailure, setRefreshFailure] = useState<unknown>();
  const [iteration, setIteration] = useState<Schemas["Iteration"]>();
  const operation = useRef<AbortController | null>(null);
  useEffect(() => () => operation.current?.abort(), []);
  const snapshot = frozen.result.status === "success" ? frozen.result.data : undefined;
  const targets = snapshot?.format_version?.recipe.targets ?? [];

  async function submit(owner: string, write?: Write, refreshDraft = false) {
    if (operation.current) return;
    const request = new AbortController();
    const { signal } = request;
    operation.current = request;
    setBusy(true);
    setFailure(undefined);
    try {
      if (write) {
        try {
          await write(signal);
        } catch (error) {
          if (signal.aborted) return;
          setFailure({ owner, error });
          if (!(error instanceof ApiError) || error.code !== "conflict.revision") return;
        }
      }
      const next = await loadCandidates(signal);
      if (signal.aborted) return;
      setRefreshed(next);
      if (refreshDraft) await reloadDraft(signal);
      if (!signal.aborted) setRefreshFailure(undefined);
    } catch (error) {
      if (!signal.aborted) setRefreshFailure(error);
    } finally {
      operation.current = null;
      if (!signal.aborted) setBusy(false);
    }
  }

  function present(event: FormEvent) {
    event.preventDefault();
    void submit(id, async (signal) => {
      const { data } = await api.POST("/v1/runs/{id}/candidates", {
        signal, params: { path: { id } }, body: { target_id: target },
      });
      if (!data) throw new ApiError(502);
      if (!signal.aborted) setTarget("");
    });
  }

  return <section className="feedback-review" aria-label="Candidates and feedback">
    <h3>Candidates</h3>
    {initial.result.status === "loading" && <p role="status" className="muted">Loading candidates…</p>}
    {initial.result.status === "failure" && <Refusal error={initial.result.error} retry={initial.retry} />}
    {frozen.result.status === "failure" && <Refusal error={frozen.result.error} retry={frozen.retry} />}
    {current && targets.length > 0 && <form className="feedback-form" onSubmit={present}>
      <label>Target
        <select value={target} disabled={busy} onChange={(event) => setTarget(event.target.value)}>
          <option value="">Choose a target</option>
          {targets.map(({ id, name }) => <option key={id} value={id}>{name}</option>)}
        </select>
      </label>
      <button className="pill" type="submit" disabled={busy}>Present run</button>
    </form>}
    {snapshot && targets.length === 0 && <p className="muted">This run has no pinned targets.</p>}
    {failure?.owner === id && <Refusal error={failure.error} />}
    {refreshFailure != null && <Refusal error={refreshFailure} retry={() => void submit(id, undefined, true)} />}
    {iteration && <p role="status">Draft revision {iteration.started_revision} opened.{" "}
      <Link to={treePath("board", context)}>Open draft</Link>
    </p>}
    {current?.data.items.map((candidate) => <CandidateCard key={candidate.id}
      api={api} candidate={candidate} context={context} busy={busy}
      boards={snapshot?.story.boards ?? []} canStart={refreshFailure == null} etag={current.etag}
      name={targets.find(({ id }) => id === candidate.target_id)?.name ?? candidate.target_id}
      submit={(owner, write, refreshDraft) => void submit(owner, write, refreshDraft)} started={setIteration}
      error={failure?.owner === candidate.id ? failure.error : undefined} />)}
  </section>;
}
