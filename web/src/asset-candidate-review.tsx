import { useEffect, useRef, useState } from "react";

import { ApiError, type StudioClient } from "./api/client";
import { promoteAsset } from "./asset-library-data";
import { assetOrigins } from "./asset-library-model";
import { UseAsset, VersionDetails, type AssetTarget } from "./asset-version-card";
import type { AssetVersion } from "./photo-composer-model";
import { Problem } from "./shell-ui";

function declineKey(id: string) {
  return `studio.asset.declined.${id}`;
}

function wasDeclined(id: string) {
  try {
    return sessionStorage.getItem(declineKey(id)) === "true";
  } catch {
    return false;
  }
}

function rememberDecline(id: string, declined: boolean) {
  try {
    if (declined) sessionStorage.setItem(declineKey(id), "true");
    else sessionStorage.removeItem(declineKey(id));
  } catch {
    // The preview can be declined with storage disabled.
  }
}

export function AssetProblem({ error, retry }: { error: unknown; retry?: () => void }) {
  const message = error instanceof ApiError && error.code
    ? [error.detail?.message, error.code].filter((part, i, all) => part && all.indexOf(part) === i).join(" · ")
    : undefined;
  return <Problem error={error} retry={retry} message={message} />;
}

export function CandidateReview({ api, version, jobId, target, onPromoted, refresh }: {
  api: StudioClient; version: AssetVersion; jobId?: string; target?: AssetTarget;
  onPromoted: () => void; refresh?: () => void;
}) {
  const [promoted, setPromoted] = useState<AssetVersion>();
  const [declined, setDeclined] = useState(() => version.state === "candidate" && wasDeclined(version.id));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>();
  const request = useRef<AbortController | null>(null);
  const receipt = useRef<HTMLParagraphElement>(null);
  const stale = error instanceof ApiError && error.status === 409;
  const result = promoted ?? version;
  const isCandidate = result.state === "candidate";
  const canPromote = !result.recorded_without_media && Boolean(result.content) &&
    (isCandidate || (result.state === "board" && result.kind === "photo"));

  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => {
    if (promoted) receipt.current?.focus();
  }, [promoted]);

  async function promote() {
    if (request.current || declined || !canPromote) return;
    const pending = new AbortController();
    request.current = pending;
    setSaving(true);
    setError(undefined);
    try {
      const saved = await promoteAsset(api, result, pending.signal);
      if (pending.signal.aborted) return;
      setPromoted(saved);
      onPromoted();
    } catch (error) {
      if (!pending.signal.aborted) setError(error);
    } finally {
      if (!pending.signal.aborted) {
        request.current = null;
        setSaving(false);
      }
    }
  }

  const label = version.state === "board" ? "promotion" : "candidate review";
  return <article className="asset-card" aria-label={`${version.name} ${label}`}>
    <h3>{version.name}</h3>
    <p className="muted">v{version.number} · {assetOrigins[version.provenance.origin]}</p>
    <VersionDetails version={version} jobId={jobId} />
    {result.state === "promoted" && <p role="status" ref={receipt} tabIndex={-1}>Promoted to library</p>}
    <UseAsset version={result} target={target} declined={isCandidate && declined} />
    {canPromote && <div className="asset-actions">
      {!declined && <button className="pill primary" type="button" aria-disabled={saving}
        onClick={() => void promote()}>{saving ? "Promoting…" : "Promote"}</button>}
      {isCandidate && <button className="pill" type="button" aria-disabled={saving} onClick={() => {
        if (request.current) return;
        rememberDecline(version.id, !declined);
        setDeclined(!declined);
        setError(undefined);
      }}>{declined ? "Review again" : "Decline"}</button>}
    </div>}
    {error != null && <AssetProblem error={error} retry={stale ? refresh : undefined} />}
  </article>;
}
