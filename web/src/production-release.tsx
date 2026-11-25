import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, type StudioClient } from "./api/client";
import type { components } from "./api/schema";
import { approvalRefusal, ReviewTime } from "./production-approval";
import { freshSignIn, readObject } from "./production-review-data";
import { Problem } from "./shell-ui";
import { useRequest } from "./use-request";
import "./production-release.css";

type PackageView = components["schemas"]["ReleasePackageView"];

function LicenceRows({ value }: { value: unknown }) {
  const rows = readObject(value).rows;
  if (!Array.isArray(rows)) return null;
  return <ul className="review-results">
    {rows.map((item, index) => {
      const row = readObject(item);
      const entry = readObject(row.register_entry);
      const licence = readObject(entry.licence ?? row.licence);
      const title = [row.engine_key, row.file, licence.name].filter(
        (part): part is string => typeof part === "string",
      ).join(" · ");
      return <li key={index}><details>
        <summary>{title || "Licence row"} · {
          typeof entry.outputs_commercial_use === "string" ? entry.outputs_commercial_use :
            typeof licence.commercial_use === "string" ? licence.commercial_use : "missing"
        }</summary>
        {typeof licence.note === "string" && <p>{licence.note}</p>}
        <pre>{JSON.stringify(row.register_entry ?? row, null, 2)}</pre>
      </details></li>;
    })}
  </ul>;
}

function CheckEvidence({ value }: { value: PackageView["package"] }) {
  const checks = [
    ["Delivery verification", value.release_checks.delivery],
    ["Model licences", value.release_checks.licences],
    ["Run provenance", value.release_checks.provenance],
    ["AI disclosure", value.release_checks.ai_label],
    ["Studio-built run", value.release_checks.canonical_run],
    ["Platform maximum", value.target_checks.length],
    ["Aspect", value.target_checks.aspect],
  ] as const;
  return <section aria-label="Package release checks">
    <h4>Package release checks</h4>
    {checks.map(([name, evidence]) => evidence != null && <details key={name}>
      <summary>{name} · {readObject(evidence).result === "pass" ? "Passed" : "Review evidence"}</summary>
      {name === "Model licences"
        ? <LicenceRows value={evidence} />
        : <pre>{JSON.stringify(evidence, null, 2)}</pre>}
    </details>)}
  </section>;
}

function CopyButton({ label, value }: { label: string; value: string }) {
  const [status, setStatus] = useState("");
  return <div className="release-actions">
    <button type="button" className="pill" onClick={async () => {
      try {
        await navigator.clipboard.writeText(value);
        setStatus("Copied.");
      } catch {
        setStatus("Copy unavailable. Select the text above to copy it.");
      }
    }}>{label}</button>
    <span role="status" className="muted">{status}</span>
  </div>;
}

function PackageDetails({ item, runPath, busy, record }: {
  item: PackageView; runPath: string; busy: boolean; record: (location: string, time?: string) => void;
}) {
  const { package: value, publication } = item;
  const [location, setLocation] = useState("");
  const [localTime, setLocalTime] = useState("");
  const canSignIn = !item.record_publication.allowed && item.record_publication.code === "approval.sign_in_again";

  function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    record(location.trim(), localTime ? new Date(localTime).toISOString() : undefined);
  }

  return <>
    <p role="status">{item.state === "held"
      ? "Package ready, release held. The exact run and master need an active go-live approval."
      : "Releasable. The exact run and master have an active go-live approval."}</p>
    {value.target.account_id && <p className="muted">Target account {value.target.account_id}</p>}
    {value.target.owner_note && <p className="muted">{value.target.owner_note}</p>}
    <CheckEvidence value={value} />
    <section aria-label="Release description">
      <h4>Release description</h4>
      <p className="review-description">{value.description}</p>
      <CopyButton label="Copy description" value={value.description} />
    </section>
    <section aria-label="Platform checklist">
      <h4>Platform checklist</h4>
      <ul>{value.checklist.map((step) => <li key={step}>{step}</li>)}</ul>
      <CopyButton label="Copy checklist" value={value.checklist.map((step) => `- ${step}`).join("\n")} />
    </section>
    <p><a className="pill" href={`/v1/media/${value.master.sha256}`}
      download={`${value.run_id}.mp4`}>Download master</a> <span className="muted">{value.master.bytes.toLocaleString()} bytes</span></p>
    {publication && <div>
      <h4>Publication recorded</h4>
      <p>{publication.location}</p>
      <p>{publication.recorded_by_display_name && `${publication.recorded_by_display_name} · `}
        <ReviewTime value={publication.recorded_at} /></p>
      {publication.published_at && <p>Published <ReviewTime value={publication.published_at} /></p>}
    </div>}
    {!publication && item.state === "releasable" && (item.record_publication.allowed
      ? <form className="release-form" onSubmit={send}>
        <label>Public location
          <input value={location} onChange={(event) => setLocation(event.target.value)}
            required maxLength={2048} disabled={busy} />
        </label>
        <label>Publication time (optional)
          <input type="datetime-local" value={localTime} onChange={(event) => setLocalTime(event.target.value)}
            disabled={busy} />
        </label>
        <button className="pill" disabled={busy || !location.trim()}>Record publication</button>
      </form>
      : canSignIn && <p><a href={freshSignIn(runPath)}>Sign in again to record publication</a></p>)}
  </>;
}

export function ReleasePackages({ api, id, runPath, approvalChange, onPublication }: {
  api: StudioClient; id: string; runPath: string; approvalChange: number;
  onPublication: (signal: AbortSignal) => Promise<void>;
}) {
  const [refresh, setRefresh] = useState(0);
  const load = useCallback(async (signal: AbortSignal) => {
    const { data } = await api.GET("/v1/runs/{id}/release-packages", { params: { path: { id } }, signal });
    if (!data) throw new ApiError(502);
    return data;
    // The package state is derived on the server after either kind of write.
  }, [api, id, approvalChange, refresh]);
  const { result, retry } = useRequest(load);
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);

  const current = result.status === "success" ? result.data : undefined;
  const selected = current?.targets.find(({ id }) => id === target);
  const visible = selected ?? current?.targets.find(({ id }) => id === current.items[0]?.package.target.id);
  const item = current?.items.find(({ package: value }) => value.target.id === visible?.id);

  async function write(action: (signal: AbortSignal) => Promise<unknown>,
                       after?: (signal: AbortSignal) => Promise<void>) {
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);
    setError(undefined);
    try {
      await action(controller.signal);
      if (!controller.signal.aborted) {
        setRefresh((value) => value + 1);
        await after?.(controller.signal);
      }
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure);
    } finally {
      request.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return <section className="release-package" aria-label="Release package">
    <h3>Release package</h3>
    <p>Publish by hand outside Studio.</p>
    {result.status === "loading" && <p role="status" className="muted">Loading release packages…</p>}
    {result.status === "failure" && <Problem error={result.error} retry={retry} />}
    {current?.targets.length === 0 && <p className="muted">This run has no frozen YouTube Shorts target.</p>}
    {current && current.targets.length > 0 && <form className="release-form" onSubmit={(event) => {
      event.preventDefault();
      if (!selected || item) return;
      void write((signal) => api.POST("/v1/runs/{id}/release-packages", {
        signal, params: { path: { id } }, body: { target_id: selected.id },
      }));
    }}>
      <label>Release target
        <select value={visible?.id ?? ""} onChange={(event) => { setTarget(event.target.value); setError(undefined); }} disabled={busy}>
          <option value="" disabled>Choose a target</option>
          {current.targets.map((choice) => <option key={choice.id} value={choice.id}>{choice.name}</option>)}
        </select>
      </label>
      {!item && <button className="pill" disabled={busy || !selected}>Prepare package</button>}
    </form>}
    {item && <PackageDetails key={item.sha256} item={item} runPath={runPath} busy={busy}
      record={(location, published_at) => void write((signal) =>
        api.POST("/v1/runs/{id}/publications", {
          signal, params: { path: { id } }, body: { package_sha256: item.sha256, location, published_at },
        }), onPublication)} />}
    {error != null && <Problem error={error} message={error instanceof ApiError
      ? approvalRefusal(error.code) ?? error.detail?.message : undefined} />}
    {error instanceof ApiError && error.detail?.evidence != null && <details>
      <summary>Refusal evidence</summary>
      {error.code === "approval.licence_missing" ? <LicenceRows value={error.detail.evidence} />
        : <pre>{JSON.stringify(error.detail.evidence, null, 2)}</pre>}
    </details>}
  </section>;
}
