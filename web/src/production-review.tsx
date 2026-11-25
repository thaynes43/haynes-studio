import { useCallback, useState } from "react";
import { Link } from "react-router";
import { ApiError, type StudioClient } from "./api/client";
import { DeliveryPlayer } from "./delivery-player";
import type { Approval } from "./approval-review-contract";
import { GoLive, ReviewTime, approvalRefusal } from "./production-approval";
import { ReviewBoard, StoryBoards } from "./production-boards";
import { CandidateReview, RunAnswers } from "./production-feedback";
import { readProductionFilters, toggleProductionFilter, type ProductionFilters } from "./production-filters";
import { hasDelivery, loadDelivery, loadRuns, runStates, type Run } from "./production-review-data";
import { boardLabel, listStories, type RouteData, type Story } from "./route-data";
import { treePath, type Context, type MediaKind } from "./routes";
import type { SelectionStore } from "./selections";
import { Empty, Problem, Rows } from "./shell-ui";
import { useRequest } from "./use-request";
import "./production-review.css";

const filterChoices = [
  ["unpublished", "Unpublished"], ["published", "Published"], ["approved", "Approved"],
] as const;

function storyStatus(story: Story) {
  return story.published ? "Published" : "Unpublished";
}

function Stories({ api, production, media, filters }: {
  api: StudioClient; production: string; media: MediaKind; filters: ProductionFilters;
}) {
  const { publication, approved } = filters;
  const load = useCallback((signal: AbortSignal) => listStories(api, production, media, signal,
    { publication, approved }), [api, production, media, publication, approved]);
  const { result, retry } = useRequest(load);
  if (result.status === "loading") return <p role="status" className="muted">Loading stories…</p>;
  if (result.status === "failure") return <Problem error={result.error} retry={retry} />;
  return result.data.length
    ? <Rows items={result.data.map((story) => ({
        to: treePath("productions", { production, media, story: story.id }),
        label: story.title,
        detail: storyStatus(story) + (story.approved ? " · Approved for go-live" : ""),
      }))} />
    : <Empty>{publication || approved ? "No matching stories." : "No stories yet."}</Empty>;
}

export function ProductionStories({ api, production, media, selections }: {
  api: StudioClient; production: string; media: MediaKind; selections: SelectionStore;
}) {
  const path = treePath("productions", { production, media });
  const filters = readProductionFilters(selections.snapshot().productionFilters[path]);
  return <>
    <div className="actions review-filters" role="group" aria-label="Media status">
      {filterChoices.map(([filter, label]) => <button key={filter} type="button" className="pill"
        aria-pressed={filter === "approved" ? filters.approved === true : filters.publication === filter}
        onClick={() => selections.rememberProductionFilters(path,
          toggleProductionFilter(readProductionFilters(selections.snapshot().productionFilters[path]), filter))}>
        {label}
      </button>)}
    </div>
    <Stories key={JSON.stringify(filters)} api={api} production={production} media={media} filters={filters} />
  </>;
}

const resultLabels = { pass: "Passed", pass_with_tolerances: "Passed with tolerances", fail: "Failed", overridden: "Overridden" };

function RunChecks({ run }: { run: Run }) {
  const checks = [
    ...(run.checks ?? []).map((check) => ({ check, board: undefined })),
    ...run.stages.flatMap(({ checks, board_number }) => (checks ?? []).map((check) => ({
      check, board: board_number ? boardLabel({ number: board_number }) : undefined,
    }))),
  ];
  return <section aria-labelledby="run-checks-heading">
    <h3 id="run-checks-heading">Run checks</h3>
    {checks.length
      ? <ul className="review-results">{checks.map(({ check, board }, index) => <li key={index}>
          <span>{[board, check.check.replaceAll("_", " "), check.slot?.toUpperCase()].filter(Boolean).join(" · ")}</span>
          <strong>{resultLabels[check.result] ?? check.result}</strong>
        </li>)}</ul>
      : <p className="muted">No checks recorded.</p>}
  </section>;
}

function FinishedRun({ api, run, path, onDecision }: {
  api: StudioClient; run: Run; path: string; onDecision: (approval: Approval) => void;
}) {
  const load = useCallback((signal: AbortSignal) => loadDelivery(api, run, signal), [api, run]);
  const { result, retry } = useRequest(load);
  if (result.status === "loading") return <p role="status" className="muted">Loading delivery…</p>;
  return <>
    {result.status === "failure" && <Problem error={result.error} retry={retry}
      message={approvalRefusal(result.error instanceof ApiError ? result.error.code : undefined)} />}
    {result.status === "success" && (result.data.store.adapter === "legacy_wan_ledger"
      ? <Empty>Playback is unavailable for this imported delivery.</Empty>
      : <DeliveryPlayer delivery={result.data} />)}
    <RunChecks run={run} />
    <GoLive api={api} run={run} delivery={result.status === "success" ? result.data : undefined}
      path={path} onDecision={onDecision} />
  </>;
}

function StoryRuns({ api, story, context, run, reloadDraft }: {
  api: StudioClient; story: Story; context: Context; run?: Run; reloadDraft: (signal: AbortSignal) => Promise<void>;
}) {
  const load = useCallback((signal: AbortSignal) => loadRuns(api, story.id, signal), [api, story.id]);
  const { result, retry } = useRequest(load);
  const [decisions, setDecisions] = useState<Record<string, boolean>>({});
  const approvalState = (run: Run) => decisions[run.id] ?? Boolean(run.active_approval_id);

  return <section className="review-section" aria-labelledby="runs-heading">
    <h2 id="runs-heading">Runs</h2>
    {result.status === "loading" && <p role="status" className="muted">Loading runs…</p>}
    {result.status === "failure" && <Problem error={result.error} retry={retry} />}
    {result.status === "success" && (() => {
      const runs = result.data;
      const selected = run ?? runs.find((run) => run.status === "succeeded") ?? runs.find(hasDelivery) ?? runs[0];
      if (!runs.length && !context.run) return <Empty>No runs yet.</Empty>;
      return <div className="review-runs">
        <ul className="review-run-list" aria-label="Story runs">{runs.map((run) => <li key={run.id}>
          <Link to={treePath("productions", { ...context, run: run.id })} aria-current={selected?.id === run.id || undefined}>
            <strong>Run {run.number}</strong>
            <span>{runStates[run.status]}{approvalState(run) && " · Approved"}</span>
          </Link>
        </li>)}</ul>
        {selected
          ? <article className="review-card review-run-detail" key={selected.id}>
              <div className="review-run-heading">
                <h3>Run {selected.number}</h3>
                <span>{runStates[selected.status]}</span>
                <ReviewTime value={selected.queued_at} />
              </div>
              <RunAnswers run={selected} runs={runs} context={context} />
              {hasDelivery(selected) && <FinishedRun api={api} run={selected}
                path={treePath("productions", { ...context, run: selected.id })}
                onDecision={(record) => setDecisions((prior) => ({
                  ...prior, [record.run_id]: record.derived.state === "active",
                }))} />}
              {selected.status === "succeeded" && selected.legacy == null &&
                <CandidateReview api={api} run={selected} context={context} reloadDraft={reloadDraft} />}
            </article>
          : <Empty>This run is no longer available in this story.</Empty>}
      </div>;
    })()}
  </section>;
}

export function ProductionReview({ api, data, context }: {
  api: StudioClient; data: RouteData & { story: Story }; context: Context;
}) {
  const { story, board } = data;
  const [refreshedDraft, setRefreshedDraft] = useState<{ source: Story; draft: Story }>();
  const draft = refreshedDraft?.source === story ? refreshedDraft.draft : story;
  async function reloadDraft(signal: AbortSignal) {
    const { data: refreshed } = await api.GET("/v1/stories/{id}", {
      signal, params: { path: { id: story.id } },
    });
    if (!refreshed || refreshed.id !== story.id || refreshed.production_id !== story.production_id ||
        refreshed.media_kind !== story.media_kind) throw new ApiError(404);
    if (!signal.aborted) setRefreshedDraft({ source: story, draft: refreshed });
  }

  return <>
    <div className="review-toolbar">
      {!board && <p className="review-badges"><span>{storyStatus(story)}</span></p>}
      <Link className="pill" to={treePath("board", context)}>Open editor</Link>
    </div>
    {board
      ? <ReviewBoard api={api} board={board} story={story} />
      : <>
          <StoryRuns api={api} story={story} context={context} run={data.run} reloadDraft={reloadDraft} />
          <StoryBoards api={api} story={draft} context={context} />
        </>}
  </>;
}
