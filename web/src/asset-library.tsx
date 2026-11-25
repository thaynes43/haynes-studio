import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";

import type { StudioClient } from "./api/client";
import { AssetProblem, CandidateReview } from "./asset-candidate-review";
import { AssetGeneration, useCandidateJob } from "./asset-generation";
import { boardPhotoHistory, listAssetScope, loadAssetContext } from "./asset-library-data";
import { assetKinds, assetOrigins, assetTarget, groupAssets, kindLabel, visibleAssetScope, widenAssetScope } from "./asset-library-model";
import { LibraryVersion, type AssetTarget } from "./asset-version-card";
import { loadBoard } from "./route-data";
import {
  assetSearch, assetSearchLimit, assetsDestination, assetsPath, liveAssetFilters, routePath, treePath,
  type AssetFilters, type AssetScope, type AssetsRoute,
} from "./routes";
import type { SelectionStore } from "./selections";
import { Breadcrumbs, Empty, PageHeading, Problem } from "./shell-ui";
import { boardPosition } from "./storyboard-timeline";
import { useRequest } from "./use-request";
import "./asset-library.css";

type AssetContext = Awaited<ReturnType<typeof loadAssetContext>>;
type ChangeFilters = (change: Partial<AssetFilters>, replace?: boolean) => void;

function ScopeFilters({ scope, data, board, change }: {
  scope: AssetScope; data: AssetContext; board: number; change: ChangeFilters;
}) {
  const restoreFocus = useRef(false);
  const row = useRef<HTMLDivElement>(null);
  const chips: Array<{ level: Exclude<AssetScope, "library">; label: string }> = [];
  if (scope !== "library") chips.push({ level: "production", label: data.production?.name ?? "Production" });
  if (scope === "story" || scope === "board") chips.push({ level: "story", label: data.story?.title ?? "Story" });
  if (scope === "board") chips.push({ level: "board", label: board >= 0 ? boardPosition(board) : "Board" });

  useLayoutEffect(() => {
    if (!restoreFocus.current) return;
    restoreFocus.current = false;
    (row.current?.querySelector<HTMLButtonElement>("button:last-child") ?? document.getElementById("asset-search"))?.focus();
  }, [scope]);

  return <div ref={row} className="asset-scope" role="group" aria-label="Asset scope filters">
    {chips.map(({ level, label }) => <button key={level} type="button" className="pill"
      aria-label={`Remove ${level} filter · ${label}`} onClick={() => {
        restoreFocus.current = true;
        change({ scope: widenAssetScope(level) });
      }}>
      {label} <span aria-hidden="true">×</span>
    </button>)}
    {!chips.length && <span className="muted">All productions</span>}
  </div>;
}

function AssetResults({ api, route, scope, story, change, target, revision }: {
  api: StudioClient; route: AssetsRoute; scope: AssetScope; story: AssetContext["story"];
  change: ChangeFilters; target?: AssetTarget; revision: number;
}) {
  const { context, filters } = route;
  const [search, setSearch] = useState(filters.search ?? "");
  useLayoutEffect(() => {
    // Skip intermediate router renders while rapid typing has already moved the address on.
    const current = liveAssetFilters(filters, window.location.pathname, window.location.search);
    if (current.search === filters.search) setSearch(filters.search ?? "");
  }, [filters]);
  const { production, board } = context;
  const load = useCallback((signal: AbortSignal) => listAssetScope(api, scope, { production, board }, story, signal),
    [api, scope, production, board, story]);
  const { result, retry } = useRequest(load);
  const processedRevision = useRef(revision);
  useEffect(() => {
    if (processedRevision.current !== revision) {
      processedRevision.current = revision;
      retry();
    }
  }, [retry, revision]);
  const versions = result.status === "success" ? result.data : [];
  const groups = groupAssets(versions, { ...filters, search });
  const kinds = assetKinds(versions);
  const unavailableKind = filters.kind && !kinds.some((kind) => kind === filters.kind);

  return <>
    <div className="asset-controls">
      <label htmlFor="asset-search">Search
        <input id="asset-search" type="search" maxLength={assetSearchLimit} placeholder="Name or label"
          value={search} onChange={(event) => {
            const value = assetSearch(event.currentTarget.value);
            setSearch(value ?? "");
            change({ search: value }, true);
          }} />
      </label>
      <label>Kind <select value={filters.kind ?? ""} onChange={(event) => change({ kind: event.currentTarget.value || undefined })}>
        <option value="">All kinds</option>
        {unavailableKind && <option value={filters.kind}>{kindLabel(filters.kind!)}</option>}
        {kinds.map((kind) => <option key={kind} value={kind}>{kindLabel(kind)}</option>)}
      </select></label>
    </div>
    {result.status === "loading" && <p role="status" className="muted">Loading assets…</p>}
    {result.status === "failure" && <AssetProblem error={result.error} retry={retry} />}
    {result.status === "success" && (groups.length ? <ul className="asset-grid" aria-label="Assets">
      {groups.map(([asset, ...older]) => <li key={asset.asset_id} className="asset-card">
        <article aria-label={asset.name}>
          <div className="asset-card-title">
            <h2>{asset.name}</h2>
            <p className="muted">{[kindLabel(asset.kind), ...asset.labels].join(" · ")}</p>
          </div>
          <ol className="asset-versions" aria-label={`${asset.name} versions`}>
            <LibraryVersion key={asset.id} version={asset} latest target={target} />
            {older.map((version) => <LibraryVersion key={version.id} version={version} latest={false} target={target} />)}
          </ol>
        </article>
      </li>)}
    </ul> : <Empty>No matching assets.</Empty>)}
  </>;
}

function UploadedPhotos({ api, board, target, onPromoted, focusHistory }: {
  api: StudioClient; board: string; target?: AssetTarget; onPromoted: () => void; focusHistory: () => void;
}) {
  const load = useCallback((signal: AbortSignal) => boardPhotoHistory(api, board, signal), [api, board]);
  const { result, retry } = useRequest(load);
  function refresh() {
    focusHistory();
    retry();
  }
  if (result.status === "loading") return <p role="status">Loading board photos…</p>;
  if (result.status === "failure") return <AssetProblem error={result.error} retry={refresh} />;
  const photos = result.data.filter((version) => version.kind === "photo" && version.state === "board" &&
    version.scope.board_id === board).sort((a, b) => b.number - a.number || b.id.localeCompare(a.id));
  return photos.length ? <ol className="asset-history">
    {photos.map((version) => <li key={version.id}>
      <details>
        <summary>{version.name} · v{version.number} · {assetOrigins[version.provenance.origin]}</summary>
        <div className="asset-version-detail">
          <CandidateReview api={api} version={version} target={target} onPromoted={onPromoted} refresh={refresh} />
        </div>
      </details>
    </li>)}
  </ol> : <p className="muted">No board photos.</p>;
}

export function AssetLibraryPage({ api, route, selections, before }: {
  api: StudioClient; route: AssetsRoute; selections: SelectionStore; before?: ReactNode;
}) {
  const navigate = useNavigate();
  const { context, filters, generate } = route;
  const { production, media, story, board } = context;
  const scope = visibleAssetScope(context, filters);
  const targetScope = assetTarget(context, filters);
  const targetId = targetScope?.board;
  const [catalogRevision, setCatalogRevision] = useState(0);
  const refresh = useCallback(() => setCatalogRevision((revision) => revision + 1), []);
  const [showHistory, setShowHistory] = useState(false);
  const history = useRef<HTMLElement>(null);
  const stable = useMemo(() => ({ production, media, story }), [production, media, story]);
  const load = useCallback((signal: AbortSignal) => loadAssetContext(api, stable, signal), [api, stable]);
  const tree = useRequest(load);
  const data = tree.result.status === "success" ? tree.result.data : undefined;
  const ready = data !== undefined;
  const index = targetId ? data?.story?.board_order.indexOf(targetId) : undefined;
  const validTargetId = index !== undefined && index >= 0 ? targetId : undefined;
  const loadTarget = useCallback((signal: AbortSignal) => validTargetId && story
    ? loadBoard(api, story, validTargetId, signal) : Promise.resolve(undefined), [api, validTargetId, story]);
  const targetBoard = useRequest(loadTarget);
  const record = targetBoard.result.status === "success" ? targetBoard.result.data : undefined;
  const target = targetScope && validTargetId && record && record.id === validTargetId
    ? { scope: targetScope, board: record } : undefined;
  const targetReady = target !== undefined;
  const jobStatus = useCandidateJob(api, filters.job);
  const linkFilters = { ...filters, job: jobStatus.value?.id };
  const path = routePath(route);
  const libraryPath = assetsPath(context, false, linkFilters);
  const destination = assetsDestination(context, filters);

  useEffect(() => {
    if (!ready || (targetId && !targetReady)) return;
    selections.remember("assets", destination);
  }, [destination, ready, selections, targetId, targetReady]);

  function change(next: Partial<AssetFilters>, replace = false) {
    const current = liveAssetFilters(filters, window.location.pathname, window.location.search);
    const job = jobStatus.missing && current.job === filters.job ? undefined : current.job;
    void navigate(assetsPath(context, generate, { ...current, job, ...next }), { replace, preventScrollReset: true });
  }

  const atScope = (scope: AssetScope) => assetsPath(context, false, { ...linkFilters, scope });
  const trail = [{ label: "Editor", to: "/editor" }, { label: "Assets", to: atScope("library") }];
  if (scope !== "library" && data?.production) trail.push({ label: data.production.name, to: atScope("production") });
  if ((scope === "story" || scope === "board") && data?.story) {
    trail.push({ label: data.story.title, to: atScope("story") });
  }
  const boardIndex = data?.story?.board_order.indexOf(board ?? "") ?? -1;
  if (scope === "board" && boardIndex >= 0) trail.push({ label: boardPosition(boardIndex), to: libraryPath });
  if (generate) trail.push({ label: "Generate", to: path });
  const scopeReady = scope === "library" || data?.production !== undefined;

  return <>
    <Breadcrumbs trail={trail} current={path} />
    <main id="main" aria-labelledby="page-heading">
      <div className="asset-library">
        <div className="asset-library-heading">
          <PageHeading key={generate ? "generate" : "library"}>{generate ? "Generate asset" : "Asset library"}</PageHeading>
          {generate ? <Link className="pill" to={libraryPath}>Back to library</Link>
            : <Link className="pill primary" to={assetsPath(context, true, linkFilters)}>Generate asset</Link>}
        </div>
        {before}
        {tree.result.status === "failure" && <Problem error={tree.result.error} retry={tree.retry} />}
        {!generate && <ScopeFilters scope={scope} data={data ?? {}} board={boardIndex} change={change} />}
        {data?.story && data.story.board_order.length > 0 && <div className="asset-target">
          <label>Target board <select value={validTargetId ?? ""} onChange={(event) => {
            change({ target: event.currentTarget.value });
          }}>
            {!validTargetId && <option value="" disabled>Choose a board</option>}
            {data.story.board_order.map((id, index) => <option key={id} value={id}>{boardPosition(index)}</option>)}
          </select></label>
          {target && <Link className="pill" to={treePath("board", target.scope, "photo")}>Return to board</Link>}
          {index === -1 && <p className="muted" role="status">Target board unavailable.</p>}
          {targetBoard.result.status === "failure" && <AssetProblem error={targetBoard.result.error} retry={targetBoard.retry} />}
        </div>}
        {(generate || filters.job) && <AssetGeneration key={generate ? "generate" : "result"} api={api}
          generate={generate} production={scope === "library" ? undefined : data?.production}
          scopeReady={scopeReady} job={filters.job} jobStatus={jobStatus} target={target} onJob={(job) => change({ job })}
          onPromoted={refresh} />}
        {!generate && <>
          {(scope === "library" || scope === "production" || ready) &&
            <AssetResults key={scope} api={api} route={route} scope={scope}
              story={scope === "story" || scope === "board" ? data?.story : undefined}
              change={change} target={target} revision={catalogRevision} />}
          {scope === "board" && board && data?.story?.board_order.includes(board) &&
            <details className="asset-board-history" onToggle={(event) => setShowHistory(event.currentTarget.open)}>
              <summary ref={history}>Board photo history</summary>
              {showHistory && <UploadedPhotos api={api} board={board} target={target} onPromoted={refresh}
                focusHistory={() => history.current?.focus()} />}
            </details>}
        </>}
      </div>
    </main>
  </>;
}
