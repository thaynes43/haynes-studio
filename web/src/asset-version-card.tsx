import { useState } from "react";
import { Link } from "react-router";

import { assetOrigins, assetPreview, assetUseProblem, candidateJobId, canCutOut } from "./asset-library-model";
import { photoAssetReturn, type AssetVersion, type PhotoBoardScope } from "./photo-composer-model";
import { mediaUrl, readObject } from "./production-review-data";
import type { Board } from "./route-data";

export type AssetTarget = { scope: PhotoBoardScope; board: Board };
export type SelectCutout = (version: AssetVersion) => void;

function Preview({ url, type, label }: { url: string; type: string; label: string }) {
  const [failed, setFailed] = useState(false);
  const fail = () => setFailed(true);
  if (failed) return <p className="muted" role="status">Preview unavailable.</p>;
  if (type.startsWith("image/")) {
    return <img className="asset-preview-image" src={url} alt={label} loading="lazy" onError={fail} />;
  }
  if (type.startsWith("audio/")) {
    return <audio className="asset-preview-player" src={url} aria-label={label} controls preload="metadata" onError={fail} />;
  }
  if (type === "video/mp4") {
    return <video className="asset-preview-video" src={url} aria-label={label} controls preload="metadata" onError={fail} />;
  }
  return null;
}

function Provenance({ version, jobId }: { version: AssetVersion; jobId?: string }) {
  const { provenance } = version;
  const { external, generator } = provenance;
  const agent = external?.agent;
  const received = readObject(generator.params).upload_sha256;
  const job = jobId ?? candidateJobId(version);
  const digest = (version.content ?? version.voice?.track)?.sha256;
  return <dl className="asset-provenance">
    <div><dt>Recorded</dt><dd><time dateTime={provenance.created_at}>{provenance.created_at.slice(0, 10)}</time></dd></div>
    {job && <div><dt>Source job</dt><dd><code>{job}</code></dd></div>}
    {agent && <div><dt>Uploaded by</dt><dd>{agent.harness} · {agent.session}</dd></div>}
    {generator.model && <div><dt>Model</dt><dd>{generator.model}</dd></div>}
    {generator.prompt && <div><dt>Prompt</dt><dd>{generator.prompt}</dd></div>}
    {generator.source_asset_version_ids?.length ? <div><dt>Source versions</dt><dd>
      {generator.source_asset_version_ids.map((id, index) => <code key={`${id}:${index}`}>{id}</code>)}
    </dd></div> : null}
    {provenance.origin === "imported" && provenance.source_key &&
      <div><dt>Import source</dt><dd>{provenance.source_key}</dd></div>}
    {typeof received === "string" && mediaUrl(received) && <div><dt>Received digest</dt><dd><code>{received}</code></dd></div>}
    {digest && <div><dt>Content digest</dt><dd><code>{digest}</code></dd></div>}
  </dl>;
}

export function VersionDetails({ version, jobId }: { version: AssetVersion; jobId?: string }) {
  const media = assetPreview(version, jobId);
  return <>
    {media && <Preview key={media.url} {...media} label={`${version.name} v${version.number} preview`} />}
    {version.capabilities.length > 0 && <ul className="asset-capabilities" aria-label="Capabilities">
      {version.capabilities.map((capability) => <li key={capability}>{capability}</li>)}
    </ul>}
    <Provenance version={version} jobId={jobId} />
  </>;
}

export function UseAsset({ version, target, declined = false }: {
  version: AssetVersion; target?: AssetTarget; declined?: boolean;
}) {
  const problem = assetUseProblem(version, target?.scope, target?.board.method.layer === "layered", declined);
  if (problem) return <p className="muted">{problem}</p>;
  if (!target) return null;
  const { board, scope } = target;
  if (board.photo.input_asset_version_ids.includes(version.id)) return <p className="muted">Already on board</p>;
  const { to, state } = photoAssetReturn(scope, version.id);
  return <Link className="pill" to={to} state={state}
    aria-label={`Use ${version.name} v${version.number} on board`}>Use on board</Link>;
}

export function CutOutAction({ version, onCutout }: { version: AssetVersion; onCutout?: SelectCutout }) {
  if (!onCutout || !canCutOut(version)) return null;
  return <button type="button" className="pill" onClick={() => onCutout(version)}>Cut out</button>;
}

export function LibraryVersion({ version, latest, target, onCutout }: {
  version: AssetVersion; latest: boolean; target?: AssetTarget; onCutout?: SelectCutout;
}) {
  const [open, setOpen] = useState(latest);
  return <li className="asset-version">
    <details open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>v{version.number} · {assetOrigins[version.provenance.origin]}</summary>
      {open && <div className="asset-version-detail">
        <VersionDetails version={version} />
        <UseAsset version={version} target={target} />
        <CutOutAction version={version} onCutout={onCutout} />
      </div>}
    </details>
  </li>;
}
