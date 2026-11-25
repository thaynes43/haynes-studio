import { useCallback, useState } from "react";
import { Link } from "react-router";

import type { StudioClient } from "./api/client";
import { hasDelivery, runStates } from "./production-review-data";
import { compareSnapshots, loadFrozenSnapshot, type FrozenBoard, type FrozenSnapshot } from "./run-comparison";
import { retryableRead, type RunView } from "./run-data";
import { RunDelivery } from "./run-delivery";
import { treePath, type Context } from "./routes";
import { Empty, Problem } from "./shell-ui";
import { boardPosition } from "./storyboard-timeline";
import { useRequest } from "./use-request";
import { useRunList } from "./use-run-list";

function useSnapshot(api: StudioClient, run: RunView) {
  const { story_id, snapshot: { sha256, board_count, story_revision } } = run;
  const load = useCallback(async (signal: AbortSignal) => ({
    sha256,
    data: await loadFrozenSnapshot(api, { story_id, snapshot: { sha256, board_count, story_revision } }, signal),
  }), [api, story_id, sha256, board_count, story_revision]);
  const { result, retry } = useRequest(load);
  const current = result.status === "success" && result.data.sha256 !== sha256 ? { status: "loading" as const } : result;
  return { result: current, retry, data: current.status === "success" ? current.data.data : undefined };
}

function ComparePlayer({ api, runs, run, other, label, snapshot, onChange }: {
  api: StudioClient; runs: RunView[]; run: RunView; other: RunView; label: string;
  snapshot: ReturnType<typeof useSnapshot>; onChange: (id: string) => void;
}) {
  const { result, retry, data } = snapshot;
  return <section className="run-compare-player" aria-label={label}>
    <label>{label}
      <select value={run.id} onChange={(event) => onChange(event.target.value)}>
        {runs.map(({ id, number, status }) => <option key={id} value={id} disabled={id === other.id}>
          Run {number} · {runStates[status]}
        </option>)}
      </select>
    </label>
    <p className="muted">Draft revision {run.snapshot.story_revision} · {run.snapshot.board_count} boards</p>
    {result.status === "loading" && <p role="status">Loading snapshot…</p>}
    {result.status !== "loading" && !data && <p>Snapshot not available.</p>}
    {result.status === "failure" && retryableRead(result.error) && <button type="button" className="pill" onClick={retry}>
      Retry snapshot
    </button>}
    {hasDelivery(run) ? <RunDelivery key={run.id} api={api} run={run} /> : <p className="muted">Playback unavailable.</p>}
  </section>;
}

function BoardVersions({ entry }: { entry: { board: FrozenBoard; index: number } | undefined }) {
  if (!entry) return <p>Absent</p>;
  const { board, index } = entry;
  return <div>
    <strong>{boardPosition(index)}{board.title && ` · ${board.title}`}</strong>
    <dl className="run-board-versions">
      <div><dt>Photo</dt><dd><code>{board.photo.current_version_id ?? "None"}</code></dd></div>
      <div><dt>Voice</dt><dd><code>{board.voice.current_version_id ?? "None"}</code></dd></div>
    </dl>
  </div>;
}

export function BoardComparison({ left, right, leftRun, rightRun }: {
  left: FrozenSnapshot; right: FrozenSnapshot; leftRun: number; rightRun: number;
}) {
  const rows = compareSnapshots(left, right);
  return <section className="run-compare-boards" aria-label="Board comparison">
    <h2>Boards</h2>
    {rows.length === 0 && <Empty>No boards in these snapshots.</Empty>}
    {rows.map(({ id, from, to, changes }) => <article key={id}>
      <header><code>{id}</code><strong>{changes.length ? changes.join(" · ") : "Unchanged"}</strong></header>
      <div className="run-compare-columns">
        <div><p className="muted">Run {leftRun}</p><BoardVersions entry={from} /></div>
        <div><p className="muted">Run {rightRun}</p><BoardVersions entry={to} /></div>
      </div>
    </article>)}
  </section>;
}

function ComparePair({ api, runs }: { api: StudioClient; runs: RunView[] }) {
  const finished = runs.filter(hasDelivery);
  const defaults = finished.length >= 2 ? finished : runs;
  const [leftId, setLeft] = useState(defaults[1].id);
  const [rightId, setRight] = useState(defaults[0].id);
  const left = runs.find(({ id }) => id === leftId) ?? defaults[1];
  const right = runs.find(({ id }) => id === rightId && id !== left.id) ?? runs.find(({ id }) => id !== left.id)!;
  const leftSnapshot = useSnapshot(api, left);
  const rightSnapshot = useSnapshot(api, right);
  const before = leftSnapshot.data;
  const after = rightSnapshot.data;

  return <>
    <div className="run-compare-columns">
      <ComparePlayer api={api} runs={runs} run={left} other={right} label="Left run"
        snapshot={leftSnapshot} onChange={setLeft} />
      <ComparePlayer api={api} runs={runs} run={right} other={left} label="Right run"
        snapshot={rightSnapshot} onChange={setRight} />
    </div>
    {before && after && <BoardComparison left={before} right={after} leftRun={left.number} rightRun={right.number} />}
  </>;
}

export function RunCompare({ api, context, story }: { api: StudioClient; context: Context; story: string }) {
  const { runs, error, refresh } = useRunList(api, story);
  return <section className="run-compare" aria-label="Run comparison">
    <div className="run-card-actions">
      <Link className="pill" to={treePath("board", context)}>Open storyboard</Link>
    </div>
    {error != null && <Problem error={error} retry={retryableRead(error) ? refresh : undefined} />}
    {!runs && error == null && <p role="status">Loading runs…</p>}
    {runs && (runs.length >= 2 ? <ComparePair api={api} runs={runs} /> : <Empty>Queue two runs to compare them.</Empty>)}
  </section>;
}
