import { useCallback, useEffect, useMemo, useSyncExternalStore, type ReactNode } from "react";
import { Link, useLocation } from "react-router";

import type { StudioClient } from "./api/client";
import { AssetLibraryPage } from "./asset-library";
import { EditorLanding, EditorPicker } from "./editor-entry";
import { ProductionReview, ProductionStories } from "./production-review";
import { boardLabel, loadRoute, type RouteData } from "./route-data";
import { assetsDestination, assetsPath, mediaKinds, parseRoute, routePath, treePath, type Route } from "./routes";
import { RunBuild } from "./run-build";
import { RunCompare } from "./run-compare";
import { StoryRuns } from "./run-list";
import type { SelectionStore } from "./selections";
import { AccountMenu, Brand, Breadcrumbs, Empty, PageHeading, Problem, Rows, ThemeOptions, type Crumb } from "./shell-ui";
import type { StoryboardScope } from "./storyboard-data";
import { boardPosition } from "./storyboard-timeline";
import { StoryboardWorkspace } from "./storyboard-workspace";
import type { ThemeSettings } from "./theme";
import { useRequest } from "./use-request";
import { useRunList } from "./use-run-list";
import { useStoryboard } from "./use-storyboard";
import "./story-runs.css";

type ContextRoute = Extract<Route, { area: "productions" | "board" }>;

function trailFor(route: ContextRoute, data: RouteData): Crumb[] {
  const { production, media, story } = route.context;
  const editor = { label: "Editor", to: "/editor" };
  const { area } = route;
  const trail = area === "productions"
    ? [{ label: "Productions", to: treePath(area) }]
    : [editor, { label: "Storyboard", to: treePath(area) }];
  if (data.production) trail.push({ label: data.production.name, to: treePath(area, { production }) });
  if (media && data.production) {
    trail.push({ label: mediaKinds[media].label, to: treePath(area, { production, media }) });
  }
  if (data.story) trail.push({ label: data.story.title, to: treePath(area, { production, media, story }) });
  if (area === "productions" && data.run) {
    trail.push({ label: `Run ${data.run.number}`, to: treePath(area, route.context) });
  }
  if (data.board) trail.push({ label: boardLabel(data.board), to: treePath(area, route.context) });
  if (data.story && (route.page === "runs" || route.page === "compare")) {
    trail.push({ label: "Runs", to: treePath(area, route.context, "runs") });
  }
  if (data.story && route.page === "compare") {
    trail.push({ label: "Compare", to: treePath(area, route.context, "compare") });
  }
  if (data.story && route.page === "photo") {
    trail.push({ label: "Reference photo", to: treePath(area, route.context, "photo") });
  }
  return trail;
}

function treeHeading(route: ContextRoute, data: RouteData) {
  const { production, media, story, board } = route.context;
  if (route.page === "photo") return "Reference photo";
  if (route.page === "runs") return "Runs";
  if (route.page === "compare") return "Compare runs";
  if (board) return boardLabel(data.board);
  if (story) return data.story?.title ?? "Story";
  if (media) return route.area === "board" ? "Choose a story" : mediaKinds[media].plural;
  if (production) return route.area === "board" ? "Media types" : data.production?.name ?? "Production";
  return route.area === "board" ? "Choose a production" : "Productions";
}

function RouteContents({ route, data }: { route: ContextRoute; data: RouteData }) {
  const { production, media } = route.context;
  const { area } = route;
  if (media) {
    return data.stories?.length
      ? <Rows items={data.stories.map(({ id, title }) => ({
          to: treePath(area, { production, media, story: id }), label: title,
        }))} />
      : <Empty>No stories yet.</Empty>;
  }
  if (data.production) {
    return data.production.media_types.length
      ? <Rows items={data.production.media_types.map(({ kind, aspect }) => ({
          to: treePath(area, { production, media: kind }),
          label: mediaKinds[kind].plural,
          detail: aspect,
        }))} />
      : <Empty>No media types yet.</Empty>;
  }
  return data.productions?.length
    ? <Rows items={data.productions.map(({ id, name }) => ({
        to: treePath(area, { production: id }), label: name,
      }))} />
    : <Empty>No productions yet.</Empty>;
}

function ContextContents({ api, route, data, selections }: {
  api: StudioClient; route: ContextRoute; data: RouteData; selections: SelectionStore;
}) {
  const { area, context } = route;
  if (area === "board" && !context.story) return <EditorPicker api={api} context={context} data={data} />;
  if (area === "board" && data.story) {
    if (route.page === "runs") return <RunsPage api={api} context={context} story={data.story.id} />;
    if (route.page === "compare") return <RunCompare api={api} context={context} story={data.story.id} />;
  }
  if (area === "productions") {
    if (data.story) return <ProductionReview api={api} data={{ ...data, story: data.story }} context={context} />;
    if (context.media && context.production) return <ProductionStories api={api} media={context.media}
      production={context.production} selections={selections} />;
  }
  return <RouteContents route={route} data={data} />;
}

function RunsPage({ api, context, story }: { api: StudioClient; context: ContextRoute["context"]; story: string }) {
  const feed = useRunList(api, story);
  return <StoryRuns api={api} context={context} feed={feed} standalone />;
}

function ShellPage({
  children, trail, current, title, before, action,
}: { children?: ReactNode; trail: Crumb[]; current: string; title: string; before?: ReactNode; action?: ReactNode }) {
  return (
    <>
      <Breadcrumbs trail={trail} current={current} />
      <main id="main" aria-labelledby="page-heading">
        {action ? <div className="story-run-header"><PageHeading>{title}</PageHeading>{action}</div>
          : <PageHeading>{title}</PageHeading>}
        {before}
        {children}
      </main>
    </>
  );
}

function ContextPage({
  api, route, selections, before,
}: { api: StudioClient; route: ContextRoute; selections: SelectionStore; before?: ReactNode }) {
  const { context, area } = route;
  const load = useCallback((signal: AbortSignal) => loadRoute(api, context, area, signal), [api, context, area]);
  const { result, retry } = useRequest(load);
  const valid = result.status === "success";
  const remembered = treePath(area, context);
  useEffect(() => {
    if (valid) selections.remember(area, remembered);
  }, [area, remembered, selections, valid]);
  const data = result.status === "success" ? result.data : {};
  return (
    <ShellPage title={treeHeading(route, data)} trail={trailFor(route, data)} current={routePath(route)} before={before}>
      {result.status === "loading" && <p role="status" className="muted">Loading…</p>}
      {result.status === "failure" && <Problem error={result.error} retry={retry} />}
      {result.status === "success" && <ContextContents api={api} route={route} data={data} selections={selections} />}
    </ShellPage>
  );
}

function StoryboardPage({ api, production, media, story, board, photoRoute, selections, before }: StoryboardScope & {
  api: StudioClient; board?: string; photoRoute: boolean; selections: SelectionStore; before?: ReactNode;
}) {
  const scope = useMemo(() => ({ production, media, story }), [production, media, story]);
  const model = useStoryboard(api, scope, board);
  const { result, draft, selected, selectedIndex, retry } = model;
  const runs = useRunList(api, draft?.story.id);
  const context = { ...scope, board };
  const current = treePath("board", context);
  const data = result.status === "success" ? { production: result.data.production, story: draft?.story } : {};
  const trail = trailFor({ area: "board", context }, data);
  if (board === selected && selectedIndex >= 0) trail.push({ label: boardPosition(selectedIndex), to: current });
  const photoPath = photoRoute && board === selected ? treePath("board", context, "photo") : undefined;
  if (photoPath) trail.push({ label: "Reference photo", to: photoPath });

  useEffect(() => {
    if (draft && board === selected) selections.remember("board", current);
  }, [board, current, draft, selected, selections]);

  return <ShellPage title={draft?.story.title ?? "Story"} trail={trail} current={photoPath ?? current} before={before}
    action={draft && <RunBuild api={api} draft={draft} pending={model.pending} reload={model.reload} refresh={runs.refresh} />}>
    {result.status === "loading" && <p role="status" className="muted">Loading…</p>}
    {result.status === "failure" && <Problem error={result.error} retry={retry} />}
    {draft && <>
      <StoryboardWorkspace api={api} model={model} scope={scope} photoRoute={Boolean(photoPath)} />
      <div className="actions">
        {selected && <Link className="pill" to={treePath("board", { ...scope, board: selected }, "photo")}>Reference photo</Link>}
        <Link className="pill" to={treePath("board", scope, "runs")}>Runs</Link>
      </div>
      <StoryRuns api={api} context={scope} feed={runs} />
    </>}
  </ShellPage>;
}

export function Workspace({
  api, name, theme, signOut, selections,
}: {
  api: StudioClient;
  name: string;
  theme: ThemeSettings;
  signOut: () => Promise<void>;
  selections: SelectionStore;
}) {
  const location = useLocation();
  const { pathname, search } = location;
  const route = useMemo(() => parseRoute(pathname, search), [pathname, search]);
  const { destinations, error } = useSyncExternalStore(selections.subscribe, selections.snapshot);
  const inEditor = route.area === "editor" || route.area === "board" || route.area === "assets";
  const assets = route.area === "board" && route.context.production
    ? assetsPath(route.context)
    : route.area === "assets" ? assetsDestination(route.context, route.filters) : destinations.assets;
  const saveProblem = error == null ? null : <Problem saving error={error} retry={() => { void selections.retry(); }} />;
  let page: ReactNode;
  if (route.area === "board" && (!route.page || route.page === "photo") &&
      route.context.production && route.context.media && route.context.story) {
    const { production, media, story, board } = route.context;
    page = <StoryboardPage key={treePath("board", { production, media, story })} api={api} production={production}
      media={media} story={story} board={board} photoRoute={route.page === "photo"} selections={selections} before={saveProblem} />;
  } else if (route.area === "assets") {
    page = <AssetLibraryPage key={assetsPath(route.context)} api={api} route={route} selections={selections}
      before={saveProblem} />;
  } else if ("context" in route) {
    page = <ContextPage key={location.key} api={api} route={route} selections={selections} before={saveProblem} />;
  } else {
    const title = route.area === "editor" ? "Editor" : route.area === "user"
      ? "User settings" : route.area === "admin" ? "Admin settings" : "Page unavailable";
    page = (
      <ShellPage
        key={location.key}
        title={title}
        trail={route.area === "missing" ? [] : [{ label: title, to: location.pathname }]}
        current={location.pathname}
        before={saveProblem}
      >
        {route.area === "editor" && <EditorLanding assets={assets} />}
        {route.area === "user" && (
          <div className="settings">
            <dl><div><dt>Display name</dt><dd>{name}</dd></div></dl>
            <ThemeOptions settings={theme} />
          </div>
        )}
        {route.area === "admin" && <Empty>No admin settings yet.</Empty>}
        {route.area === "missing" && <Link className="pill" to="/productions">Go to Productions</Link>}
      </ShellPage>
    );
  }
  return (
    <div className="shell">
      <a className="skip" href="#page-heading" onClick={(event) => {
        event.preventDefault();
        document.getElementById("page-heading")?.focus();
      }}>Skip to content</a>
      <header className="top">
        <Brand signedIn />
        <nav aria-label="Main" className="topnav">
          <Link to={destinations.productions} aria-current={route.area === "productions" ? "true" : undefined}>Productions</Link>
          <Link to="/editor" aria-current={inEditor ? "true" : undefined}>Editor</Link>
        </nav>
        <AccountMenu key={location.key} name={name} theme={theme} signOut={signOut} />
      </header>
      {(route.area === "board" || route.area === "assets") && (
        <nav className="subnav" aria-label="Editor">
          <Link to={destinations.board} aria-current={route.area === "board" ? "true" : undefined}>Board</Link>
          <Link to={assets} aria-current={route.area === "assets" ? "true" : undefined}>Assets</Link>
        </nav>
      )}
      {page}
    </div>
  );
}
