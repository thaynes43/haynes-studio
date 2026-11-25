import { useCallback, useEffect, useMemo, useSyncExternalStore, type ReactNode } from "react";
import { Link, useLocation } from "react-router";

import type { StudioClient } from "./api/client";
import { EditorLanding, EditorPicker } from "./editor-entry";
import { ProductionReview, ProductionStories } from "./production-review";
import { boardLabel, loadRoute, type RouteData } from "./route-data";
import { assetsPath, mediaKinds, parseRoute, routePath, treePath, type Route } from "./routes";
import type { SelectionStore } from "./selections";
import { AccountMenu, Brand, Breadcrumbs, Empty, PageHeading, Problem, Rows, ThemeOptions, type Crumb } from "./shell-ui";
import type { ThemeSettings } from "./theme";
import { useRequest } from "./use-request";

type ContextRoute = Extract<Route, { context: unknown }>;

function trailFor(route: ContextRoute, data: RouteData): Crumb[] {
  const { production, media, story } = route.context;
  const editor = { label: "Editor", to: "/editor" };
  if (route.area === "assets") {
    const trail = [editor, { label: "Assets", to: assetsPath() }];
    if (data.production) {
      trail.push({ label: data.production.name, to: assetsPath({ production }) });
    }
    if (data.board) {
      trail.push({ label: boardLabel(data.board), to: assetsPath(route.context) });
    }
    if (route.generate) trail.push({ label: "Generate", to: assetsPath(route.context, true) });
    return trail;
  }

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
  if (route.area === "assets") return route.generate ? "Generate asset" : "Asset library";
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
  const { production, media, story, board } = route.context;
  if (route.area === "assets") {
    return route.generate
      ? <Empty>Asset generation will appear here.</Empty>
      : <>
          <div className="actions"><Link className="pill" to={assetsPath(route.context, true)}>Generate asset</Link></div>
          <Empty>Assets will appear here.</Empty>
        </>;
  }
  const { area, page } = route;
  if (page === "photo") return <Empty>Reference photo tools will appear here.</Empty>;
  if (page === "compare") return <Empty>Run comparisons will appear here.</Empty>;
  if (page === "runs") return <>
    <div className="actions"><Link className="pill" to={treePath(area, route.context, "compare")}>Compare runs</Link></div>
    <Empty>Runs will appear here.</Empty>
  </>;
  if (story) {
    const boards = data.story?.board_order ?? [];
    return <>
      <div className="actions">
        {area === "board" && board && <Link className="pill" to={treePath(area, route.context, "photo")}>Reference photo</Link>}
        {area === "board" && <Link className="pill" to={treePath(area, { production, media, story }, "runs")}>Runs</Link>}
      </div>
      {board
        ? <Empty>Board editing will appear here.</Empty>
        : boards.length > 0
          ? <Rows items={boards.map((id, index) => ({
              to: treePath(area, { production, media, story, board: id }),
              label: `Panel ${index + 1}`,
            }))} />
          : <Empty>No boards yet.</Empty>}
    </>;
  }

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
  if (area === "productions") {
    if (data.story) return <ProductionReview api={api} data={{ ...data, story: data.story }} context={context} />;
    if (context.media && context.production) return <ProductionStories api={api} media={context.media}
      production={context.production} selections={selections} />;
  }
  return <RouteContents route={route} data={data} />;
}

function ShellPage({
  children, trail, current, title, before,
}: { children?: ReactNode; trail: Crumb[]; current: string; title: string; before?: ReactNode }) {
  return (
    <>
      <Breadcrumbs trail={trail} current={current} />
      <main id="main" aria-labelledby="page-heading">
        <PageHeading>{title}</PageHeading>
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
  const remembered = area === "assets" ? assetsPath(context) : treePath(area, context);
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
    : destinations.assets;
  const saveProblem = error == null ? null : <Problem saving error={error} retry={() => { void selections.retry(); }} />;
  let page: ReactNode;
  if ("context" in route) {
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
