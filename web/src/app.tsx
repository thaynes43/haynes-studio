import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router";

import { ApiError, createStudioApi } from "./api/client";
import { safeReturnPath } from "./routes";
import { createSelections, loadSelections } from "./selections";
import { Brand, PageHeading, Problem } from "./shell-ui";
import { useTheme, type ThemeSettings } from "./theme";
import { useRequest } from "./use-request";
import { Workspace } from "./workspace";

const returnKey = "haynes-studio-return-path";

function readReturnPath() {
  try {
    return safeReturnPath(sessionStorage.getItem(returnKey));
  } catch {
    return undefined;
  }
}

function saveReturnPath(path: string | undefined) {
  try {
    if (path) sessionStorage.setItem(returnKey, path);
    else sessionStorage.removeItem(returnKey);
  } catch {
    // The callback can still open Productions when tab storage is unavailable.
  }
}

function Screen({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="shell">
      <header className="top"><Brand /></header>
      <main className="session" aria-labelledby="page-heading">
        <PageHeading>{title}</PageHeading>
        {children}
      </main>
    </div>
  );
}

type Api = ReturnType<typeof createStudioApi>;
type SessionState =
  | { status: "checking" }
  | { status: "signedOut"; expired: boolean }
  | { status: "ready"; api: Api; name: string }
  | { status: "failure"; error: unknown };

function SignedIn({
  api, name, theme, endSession,
}: { api: Api; name: string; theme: ThemeSettings; endSession: () => void }) {
  const load = useCallback((signal: AbortSignal) => loadSelections(api.client, signal), [api]);
  const { result, retry } = useRequest(load);
  const initial = result.status === "success" ? result.data : undefined;
  const selections = useMemo(() => initial && createSelections(api.client, initial), [api, initial]);

  if (result.status === "failure") {
    return <Screen title="Haynes Studio"><Problem error={result.error} retry={retry} /></Screen>;
  }
  if (!selections) return <Screen title="Haynes Studio"><p role="status">Loading…</p></Screen>;

  return <Workspace
    api={api.client}
    name={name}
    theme={theme}
    selections={selections}
    signOut={async () => {
      await api.signOut();
      endSession();
    }}
  />;
}

function Session({ theme, retry }: { theme: ThemeSettings; retry: () => void }) {
  const location = useLocation();
  const [state, setState] = useState<SessionState>({ status: "checking" });
  const [returnPath] = useState(() => location.pathname === "/" ? readReturnPath() : undefined);
  const rememberReturnPath = () => saveReturnPath(location.pathname === "/"
    ? returnPath
    : safeReturnPath(location.pathname + location.search + location.hash) ?? safeReturnPath(location.pathname + location.search));

  useEffect(() => {
    const lifetime = new AbortController();
    let expired = false;
    const api = createStudioApi(window.location.origin, lifetime.signal, () => {
      setState({ status: "signedOut", expired });
      lifetime.abort();
    });
    void api.connect().then(({ displayName }) => {
      if (lifetime.signal.aborted) return;
      expired = true;
      saveReturnPath(undefined);
      setState({ status: "ready", api, name: displayName });
    }, (error: unknown) => {
      if (!lifetime.signal.aborted) setState({ status: "failure", error });
    });
    return () => lifetime.abort();
  }, []);

  switch (state.status) {
    case "checking":
      return <Screen title="Haynes Studio"><p role="status">Checking session…</p></Screen>;
    case "signedOut":
      return (
        <Screen key="sign-in" title="Sign in to Haynes Studio">
          {state.expired && <p role="status">Your session expired.</p>}
          <a
            className="pill primary"
            href="/auth/login"
            onClick={rememberReturnPath}
          >Sign in</a>
        </Screen>
      );
    case "failure":
      return (
        <Screen title="Haynes Studio">
          <Problem error={state.error} retry={retry} />
          {state.error instanceof ApiError && state.error.code === "auth.human_required" && (
            <a className="pill primary" href="/auth/login" onClick={rememberReturnPath}>Sign in</a>
          )}
        </Screen>
      );
    case "ready":
      if (location.pathname === "/") return <Navigate to={returnPath ?? "/productions"} replace />;
      return <SignedIn api={state.api} name={state.name} theme={theme} endSession={retry} />;
  }
}

export function App() {
  const theme = useTheme();
  const [attempt, setAttempt] = useState(0);
  const retry = () => setAttempt((value) => value + 1);
  useEffect(() => {
    function onPageShow(event: PageTransitionEvent) {
      if (event.persisted) setAttempt((value) => value + 1);
    }
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, []);
  return <Session key={attempt} theme={theme} retry={retry} />;
}
