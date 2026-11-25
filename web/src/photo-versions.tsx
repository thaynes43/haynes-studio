import { useState } from "react";

import { photoPreviewUrl, selectedPhotoUrl, type AssetVersion } from "./photo-composer-model";
import { mediaUrl, readObject } from "./production-review-data";

const origins: Record<AssetVersion["provenance"]["origin"], string> = {
  generated: "Generated",
  uploaded: "Agent upload",
  imported: "Imported",
  declared: "Declared",
  derived: "Composite",
};

export function ReferencePicture({ url, label }: { url: string; label: string }) {
  const [failed, setFailed] = useState(false);
  return failed ? <p role="status">Photo unavailable.</p>
    : <img className="photo-composer-picture" src={url} alt={label} onError={() => setFailed(true)} />;
}

function VersionProvenance({ version }: { version: AssetVersion }) {
  const { origin, generator, external } = version.provenance;
  const received = readObject(generator.params).upload_sha256;
  const generatorName = [generator.engine, generator.model].filter(Boolean).join(" · ");
  const sources = generator.source_asset_version_ids ?? [];
  return <dl className="photo-provenance">
    {generatorName && <div><dt>Generator</dt><dd>{generatorName}</dd></div>}
    {typeof generator.seed === "number" && <div><dt>Seed</dt><dd>{generator.seed}</dd></div>}
    {generator.workflow_sha256 && <div><dt>Workflow digest</dt><dd><code>{generator.workflow_sha256}</code></dd></div>}
    {origin === "uploaded" && external?.agent && <div><dt>Uploaded by</dt>
      <dd>{external.agent.harness} · {external.agent.session}</dd></div>}
    {origin === "uploaded" && typeof received === "string" && mediaUrl(received) &&
      <div><dt>Received digest</dt><dd><code>{received}</code></dd></div>}
    {generator.prompt && <div><dt>Prompt</dt><dd>{generator.prompt}</dd></div>}
    {sources.length > 0 && <div><dt>Source versions</dt><dd>{sources.map((id, index) =>
      <code key={`${id}:${index}`}>{id}</code>
    )}</dd></div>}
  </dl>;
}

function VersionRow({ version, selected, dirty, pending, select }: {
  version: AssetVersion; selected: boolean; dirty: boolean; pending: boolean; select: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const url = selected ? selectedPhotoUrl(version) : photoPreviewUrl(version);
  const label = `v${version.number}`;
  return <li className="photo-version">
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>{label} · {origins[version.provenance.origin]}
        {selected && (dirty ? " · Selected for saved inputs" : " · Selected")}
      </summary>
      <div className="photo-version-detail">
        {open && url && <ReferencePicture key={url} url={url} label={`Reference photo ${label}`} />}
        <VersionProvenance version={version} />
      </div>
    </details>
    {version.recorded_without_media ? <p className="muted">Recorded without media. This version can’t be selected.</p>
      : !url ? <p className="muted">Photo media unavailable.</p>
        : !selected && <button className="pill" type="button" aria-disabled={pending}
          onClick={() => { if (!pending) select(version.id); }}>Select {label}</button>}
  </li>;
}

export function PhotoVersions({ versions, selected, dirty, pending, select }: {
  versions: AssetVersion[]; selected: string | null; dirty: boolean; pending: boolean; select: (id: string) => void;
}) {
  return <section className="photo-version-picker" aria-labelledby="photo-versions-heading">
    <h3 id="photo-versions-heading">Photo versions</h3>
    {versions.length ? <ol className="photo-versions">{versions.map((version) => <VersionRow key={version.id}
      version={version} selected={selected === version.id} dirty={dirty} pending={pending} select={select} />)}</ol>
      : <p className="muted">No versions yet.</p>}
  </section>;
}
