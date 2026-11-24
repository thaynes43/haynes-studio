import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";

import { ApiError } from "./api/client";
import { themes, type ThemeSettings } from "./theme";

export function PageHeading({ children }: { children: ReactNode }) {
  const heading = useRef<HTMLHeadingElement>(null);
  useLayoutEffect(() => {
    heading.current?.focus();
  }, []);
  return <h1 id="page-heading" tabIndex={-1} ref={heading}>{children}</h1>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

export function Rows({ items }: { items: Array<{ to: string; label: string; detail?: string }> }) {
  return (
    <ul className="tree">
      {items.map(({ to, label, detail }) => (
        <li key={to}>
          <Link to={to}>
            <span className="folder-mark" aria-hidden="true" />
            <span className="tree-label">
              <strong>{label}</strong>
              {detail && <small>{detail}</small>}
            </span>
            <span className="arrow" aria-hidden="true">→</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function problemText(error: unknown) {
  if (!(error instanceof ApiError)) return "Studio returned an unexpected response.";
  switch (error.status) {
    case 0: return "Studio could not be reached.";
    case 403: return "You don’t have access to this request.";
    case 404: return "This item is no longer available.";
    case 409: return "This item changed while you were working.";
    case 413: return "This request is too large.";
    case 422: return error.code === "method.unavailable"
      ? "This method can’t be built."
      : "Studio couldn’t use this request.";
    case 503: return "Studio is temporarily unavailable.";
    default: return "Studio couldn’t complete this request.";
  }
}

export function Problem({
  error, retry, saving = false, message, id,
}: { error: unknown; retry?: () => void; saving?: boolean; message?: string; id?: string }) {
  const requestId = error instanceof ApiError ? error.requestId : undefined;
  return (
    <div className="problem">
      <div role="alert" id={id}>
        <p>{saving && "Selection couldn’t be saved. "}{message ?? problemText(error)}</p>
        {requestId && <p className="request-id">Request ID {requestId}</p>}
      </div>
      {retry && (
        <button className="pill" type="button" onClick={() => {
          document.getElementById("page-heading")?.focus();
          retry();
        }}>Retry</button>
      )}
    </div>
  );
}

export function ThemeOptions({ settings }: { settings: ThemeSettings }) {
  return (
    <fieldset className="theme">
      <legend>Theme</legend>
      <div className="theme-options">
        {themes.map((theme) => (
          <button
            key={theme}
            type="button"
            className="pill"
            aria-pressed={theme === settings.theme}
            onClick={() => settings.choose(theme)}
          >
            {settings.labels[theme]}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

export function Brand({ signedIn }: { signedIn?: boolean }) {
  const contents = <>
    <span className="brand-mark" aria-hidden="true">H</span>
    <span className="brand-name">Haynes Studio</span>
  </>;
  return signedIn
    ? <Link className="brand" to="/productions" aria-label="Haynes Studio">{contents}</Link>
    : <span className="brand brand-static">{contents}</span>;
}

export function AccountMenu({
  name, theme, signOut,
}: { name: string; theme: ThemeSettings; signOut: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<unknown>();
  const account = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    function closeOutside(event: Event) {
      if (event.target instanceof Node && !account.current?.contains(event.target)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    }
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("focusin", closeOutside);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("focusin", closeOutside);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  async function endSession() {
    setWorking(true);
    setError(undefined);
    try {
      await signOut();
    } catch (error) {
      setError(error);
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="account" ref={account}>
      <button
        ref={trigger}
        className="account-toggle"
        type="button"
        aria-expanded={open}
        aria-controls="account-options"
        onClick={() => setOpen(!open)}
      >
        <span className="avatar" aria-hidden="true">{Array.from(name)[0]?.toLocaleUpperCase()}</span>
        <span className="account-name">{name}</span>
        <span className="caret" aria-hidden="true">⌄</span>
      </button>
      <div className="account-options" id="account-options" hidden={!open}>
        <ThemeOptions settings={theme} />
        <Link to="/settings/user" onClick={() => setOpen(false)}>User settings</Link>
        <Link to="/settings/admin" onClick={() => setOpen(false)}>Admin settings</Link>
        <button type="button" aria-disabled={working} onClick={() => { if (!working) void endSession(); }}>
          {working ? "Signing out…" : "Sign out"}
        </button>
        {error != null && <Problem error={error} />}
      </div>
    </div>
  );
}

export type Crumb = { label: string; to: string };

export function Breadcrumbs({ trail, current }: { trail: Crumb[]; current: string }) {
  const navigate = useNavigate();
  return (
    <nav className="breadcrumbs" aria-label="Breadcrumb">
      <ol>
        {trail.map(({ label, to }, index) => (
          <li key={to}>
            {index > 0 && <span aria-hidden="true">/</span>}
            <button
              type="button"
              aria-current={to === current ? "page" : undefined}
              onClick={() => { if (to !== current) void navigate(to); }}
            >
              {label}
            </button>
          </li>
        ))}
      </ol>
    </nav>
  );
}
