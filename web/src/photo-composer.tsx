import { useEffect, useEffectEvent, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router";

import type { StudioClient } from "./api/client";
import { inspectorProblem } from "./board-inspector-api";
import { usePhotoCatalog, usePhotoFeed } from "./photo-composer-api";
import {
  addPhotoPin, eligiblePhotoAsset, photoJobActive, photoResultCurrent, returnedPhotoAsset, selectedPhotoUrl,
  type AssetVersion, type PhotoJob,
} from "./photo-composer-model";
import { PhotoVersions, ReferencePicture } from "./photo-versions";
import type { Board } from "./route-data";
import { assetsPath } from "./routes";
import { Problem } from "./shell-ui";
import type { StoryboardScope } from "./storyboard-data";
import { usePhotoComposer, type PhotoStory } from "./use-photo-composer";
import "./photo-composer.css";

export type StagePhotoState = { board: string; unsaved: boolean };

function JobStatus({ job, board, dirty, paused }: { job: PhotoJob; board: Board; dirty: boolean; paused: boolean }) {
  if (job.status === "queued") return <p role="status">
    {paused ? "Queued · image lane paused" : "Waiting in the shared household image queue"}
  </p>;
  if (job.status === "running") return <p role="status">
    {board.method.layer === "layered" ? "Compositing photo…" : "Photo job running…"}
  </p>;
  if (job.status === "succeeded") return <p role="status">
    {photoResultCurrent(job, board, dirty) ? "Photo ready" : "Photo saved · not current"}
  </p>;
  if (job.status === "cancelled") return <p role="status">Photo job cancelled.</p>;
  const reason = typeof job.error?.message === "string" ? job.error.message : "";
  const code = typeof job.error?.code === "string" ? job.error.code : "";
  return <p role="alert">Photo job failed. {reason}{code && code !== reason ? ` (${code})` : ""}</p>;
}

function assetLabel(version: AssetVersion) {
  return `${version.name} · v${version.number}`;
}

function LayerInputs({ story, board, assets }: { story: PhotoStory; board: Board; assets: Map<string, AssetVersion> }) {
  const setId = story.set?.asset_version_id;
  const set = setId ? assets.get(setId) : undefined;
  return <section className="photo-layers" aria-labelledby="photo-layers-heading">
    <h3 id="photo-layers-heading">Composite layers</h3>
    <ul>
      <li>Set · {set ? assetLabel(set) : setId ?? "No set pinned"}</li>
      {board.cast.map(({ slot, asset_version_id }) => {
        const name = story.cast.find((entry) => entry.slot === slot)?.name ?? slot;
        const asset = assets.get(asset_version_id);
        return <li key={slot}>{name} · {asset ? assetLabel(asset) : asset_version_id}</li>;
      })}
      {board.layout.foreground && story.set?.foreground_edge_px && <li>Set foreground</li>}
    </ul>
    <p className="muted">Layout {board.layout.preset}{board.cues.some(({ type }) => type === "camera") && " · End camera framing"}</p>
  </section>;
}

export function PhotoComposer({
  api, panel, story, scope, photoRoute, timelinePending, onRefresh, onPhotoState,
}: {
  api: StudioClient; panel: Board; story: PhotoStory; scope: StoryboardScope; photoRoute: boolean;
  timelinePending: boolean; onRefresh: () => void; onPhotoState: (state: StagePhotoState) => void;
}) {
  const [open, setOpen] = useState(photoRoute);
  const [opened, setOpened] = useState(photoRoute);
  const summary = useRef<HTMLElement>(null);
  const target = useMemo(() => ({ ...scope, board: panel.id }), [scope, panel.id]);
  const location = useLocation();
  const navigate = useNavigate();
  const returned = returnedPhotoAsset(location.state, location.pathname, target);
  const consumed = useRef<string>(null);
  const [returnNotice, setReturnNotice] = useState("");
  const load = opened || photoRoute;
  const catalog = usePhotoCatalog(api, target.production, load);
  const { feed, error, refresh } = usePhotoFeed(api, target, load);
  const form = usePhotoComposer({
    api, board: panel, polledBoard: feed?.board, story, locked: timelinePending, refresh,
  });
  const { board, values, dirty, conflict, press, phase } = form;
  const layered = board.method.layer === "layered";
  const unsaved = !layered && dirty;
  const versions = feed?.versions ?? [];
  const selected = versions.find(({ id }) => id === board.photo.current_version_id);
  const url = selectedPhotoUrl(selected);
  const catalogVersions = catalog.result.status === "success" ? catalog.result.data : [];
  const assets = new Map(catalogVersions.map((version) => [version.id, version]));
  const pins = values.input_asset_version_ids;
  const choices = catalogVersions.filter((version) => !pins.includes(version.id) && eligiblePhotoAsset(version, target));
  const storyAssets = new Set([story.set?.asset_version_id, ...board.cast.map(({ asset_version_id }) => asset_version_id)]);
  const storySlots = new Set(story.cast.map(({ slot }) => slot));
  const fromStory = (version: AssetVersion) => storyAssets.has(version.id) ||
    (version.kind === "cast" && storySlots.has(version.attributes.character_slot ?? ""));
  const choiceGroups = [
    { label: "Story assets", versions: choices.filter(fromStory) },
    { label: "Library", versions: choices.filter((version) => !fromStory(version)) },
  ];
  const active = feed?.jobs.filter(photoJobActive) ?? [];
  const posted = form.posted && !feed?.jobs.some(({ id }) => id === form.posted?.id) ? form.posted : undefined;
  const latestJob = posted ?? feed?.jobs.reduce<PhotoJob | undefined>((latest, next) =>
    !latest || next.id > latest.id ? next : latest, undefined);
  const visibleJobs = latestJob && !active.includes(latestJob) ? [...active, latestJob] : active;
  const hasActive = active.length > 0 || Boolean(posted && photoJobActive(posted));
  const paused = feed?.paused ?? false;
  const stale = board.derived?.photo_state === "stale";
  const generationLabel = press ? "Retry photo request" : layered ? "Recomposite"
    : stale || selected || latestJob?.status === "succeeded" ? "Regenerate photo" : "Generate photo";
  const busy = Boolean(phase) || timelinePending;
  const canGenerate = Boolean(feed) && error === undefined && !busy &&
    (press ? form.retryMatches && !unsaved : !hasActive &&
      (layered || (Boolean(values.prompt?.trim()) && !conflict)));

  useLayoutEffect(() => {
    if (photoRoute) {
      setOpen(true);
      setOpened(true);
      summary.current?.focus();
    }
  }, [photoRoute]);
  useLayoutEffect(() => {
    onPhotoState({ board: board.id, unsaved });
  }, [board.id, onPhotoState, unsaved]);
  useEffect(() => {
    if (board.revision > panel.revision || (board.revision === panel.revision &&
      board.derived?.photo_state !== panel.derived?.photo_state)) onRefresh();
  }, [board, onRefresh, panel]);

  const addReturnedAsset = useEffectEvent(() => {
    if (!returned || consumed.current === location.key || catalog.result.status !== "success" || !feed || busy) return;
    consumed.current = location.key;
    const version = assets.get(returned);
    if (layered || !version || !eligiblePhotoAsset(version, target)) {
      setReturnNotice("This asset can’t be used on this board.");
    } else if (!pins.includes(version.id)) form.changeInputs(addPhotoPin(values, version.id));
    void navigate(location.pathname, { replace: true });
  });
  useEffect(() => { addReturnedAsset(); }, [busy, catalog.result, feed, location.key, returned]);

  return <details className="photo-composer inspector-section" open={open} onToggle={(event) => {
    setOpen(event.currentTarget.open);
    if (event.currentTarget.open) setOpened(true);
  }}>
    <summary ref={summary}>Reference photo{stale && <span className="photo-composer-state">Stale</span>}</summary>
    {opened && <div className="inspector-fields photo-composer-fields">
      {url ? <ReferencePicture key={url} url={url} label="Selected reference photo" />
        : feed && <p className="muted">{selected?.recorded_without_media ? "Selected version recorded without media." : "No reference photo."}</p>}
      {unsaved && <p className="muted">Photo inputs unsaved.</p>}
      {stale && <p role="status">Photo inputs changed.</p>}
      {layered ? <LayerInputs story={story} board={board} assets={assets} /> : <>
        {pins.length > 0 && <ul className="photo-chips" aria-label="Pinned photo assets">
          {pins.map((id, index) => {
            const asset = assets.get(id);
            const label = asset ? assetLabel(asset) : id;
            return <li key={`${id}:${index}`}><button className="pill" type="button"
              aria-label={`Remove ${label} from photo`}
              onClick={() => form.changeInputs({ ...values, input_asset_version_ids: pins.filter((_, i) => i !== index) })}>
              {label} <span aria-hidden="true">×</span>
            </button></li>;
          })}
        </ul>}
        <div className="photo-actions">
          <Link className="pill" to={assetsPath(target)}>Browse Assets</Link>
        </div>
        {choices.length > 0 && <label className="inspector-field">
          Add pinned asset
          <select value="" onChange={(event) => {
            const id = event.currentTarget.value;
            if (choices.some((version) => version.id === id)) form.changeInputs(addPhotoPin(values, id));
          }}>
            <option value="" disabled>Choose an asset version</option>
            {choiceGroups.filter(({ versions }) => versions.length).map(({ label, versions }) =>
              <optgroup key={label} label={label}>
                {versions.map((version) => <option key={version.id} value={version.id}>{assetLabel(version)}</option>)}
              </optgroup>
            )}
          </select>
        </label>}
        <label className="inspector-field">
          Photo prompt
          <textarea rows={3} maxLength={1800} value={values.prompt ?? ""}
            onChange={(event) => form.changeInputs({ ...values, prompt: event.currentTarget.value || null })} />
        </label>
      </>}
      {catalog.result.status === "failure" && <Problem error={catalog.result.error}
        message={`Reference assets unavailable. ${inspectorProblem(catalog.result.error)}`} retry={catalog.retry} />}
      {returnNotice && <p role="status">{returnNotice}</p>}
      {!layered && conflict && <div className="photo-input-conflict">
        <p role="alert">Someone changed the saved photo inputs. Keep your edits or use the saved inputs.</p>
        <div className="photo-actions">
          <button className="pill" type="button" disabled={busy} onClick={() => form.resolve(true)}>Keep my photo inputs</button>
          <button className="pill" type="button" disabled={busy} onClick={() => form.resolve(false)}>Use saved photo inputs</button>
        </div>
      </div>}
      <div className="photo-actions">
        {press && !form.retryMatches ? <button className="pill" type="button" disabled={busy} onClick={form.discardPress}>
          Clear previous photo request
        </button> : <button className="pill primary" type="button" disabled={!canGenerate} onClick={form.generate}>
          {phase === "submitting" ? "Submitting…" : generationLabel}
        </button>}
        {unsaved && !conflict && <button className="pill" type="button" disabled={busy} onClick={form.save}>Save photo inputs</button>}
      </div>
      {phase === "saving" && <p role="status">Saving photo inputs…</p>}
      {paused && !visibleJobs.some(({ status }) => status === "queued") && <p role="status">Image lane paused</p>}
      {visibleJobs.map((job) => <JobStatus key={job.id} job={job} board={board} dirty={unsaved} paused={paused} />)}
      {!feed && error === undefined && <p role="status">Loading photo status…</p>}
      {error !== undefined && <Problem error={error} message={`Photo status unavailable. ${inspectorProblem(error)}`} />}
      {form.actionError !== undefined && <Problem error={form.actionError} message={inspectorProblem(form.actionError)} />}
      {form.saveError !== undefined && <Problem error={form.saveError} message={`Couldn’t save photo inputs. ${inspectorProblem(form.saveError)}`} />}
      {form.notice && <p role="status">{form.notice}</p>}
      {feed && <PhotoVersions versions={versions} selected={board.photo.current_version_id} dirty={unsaved}
        pending={busy} select={form.select} />}
    </div>}
  </details>;
}
