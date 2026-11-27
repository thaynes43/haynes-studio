import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";

import type { StudioClient } from "./api/client";
import { BoardInspector, type InspectorVoiceState } from "./board-inspector";
import { PhotoComposer, type StagePhotoState } from "./photo-composer";
import { treePath } from "./routes";
import { Empty, Problem } from "./shell-ui";
import type { StoryboardPanel, StoryboardScope } from "./storyboard-data";
import { boardPosition, timelineLabels } from "./storyboard-timeline";
import type { StoryboardModel } from "./use-storyboard";
import "./storyboard-workspace.css";

const panelElementId = (id: string) => `storyboard-panel-${id}`;

function BoardPicture({ url, alt, placeholder }: { url?: string; alt: string; placeholder?: ReactNode }) {
  const [failed, setFailed] = useState(false);
  return url && !failed ? <img src={url} alt={alt} onError={() => setFailed(true)} /> : placeholder;
}

function VoiceStrip({ panel }: { panel: StoryboardPanel }) {
  const [failed, setFailed] = useState(false);
  if (!panel.voice) return null;
  return <div className="storyboard-voice">
    {panel.voiceMs !== undefined && <div className="storyboard-duration">
      <span aria-hidden="true" />
      <span>Voice {(panel.voiceMs / 1000).toString()} s</span>
    </div>}
    <audio controls preload="none" src={panel.voice} aria-label="Selected voice take" onError={() => setFailed(true)} />
    {failed && <p role="status">Voice playback unavailable.</p>}
  </div>;
}

function Stage({ panel, index, range, aspect, voiceCurrent, photoUnsaved }: {
  panel?: StoryboardPanel; index: number; range?: string; aspect: "short" | "video"; voiceCurrent: boolean; photoUnsaved: boolean;
}) {
  if (!panel) return <section className="storyboard-stage" aria-label="Selected board stage">
    <Empty>No boards yet.</Empty>
  </section>;
  const { record, photo } = panel;
  const number = boardPosition(index);
  const layer = record.method.layer === "layered" ? "Layered" : "Whole-frame";
  const motion = record.method.motion === "s2v" ? "Speech-to-video" : "Image-to-video";
  return <section className="storyboard-stage" aria-label="Selected board stage">
    <div className="storyboard-stage-meta">
      <code aria-label="Board ID">{record.id}</code>
      <span aria-label="Time range">{range}</span>
      {photoUnsaved ? <span>Photo inputs unsaved</span>
        : record.derived?.photo_state === "stale" && <span>Reference photo stale</span>}
    </div>
    <div className="storyboard-preview">
      <div className={`storyboard-picture storyboard-picture-${aspect}`}>
        <BoardPicture key={photo} url={photo} alt={`Reference photo for ${number.toLowerCase()}`} placeholder={
          <div className="storyboard-placeholder"><h2>{number}</h2><p>{layer} · {motion}</p></div>
        } />
      </div>
    </div>
    {voiceCurrent && <VoiceStrip key={panel.voice} panel={panel} />}
  </section>;
}

export function StoryboardWorkspace({ api, model, scope, photoRoute }: {
  api: StudioClient; model: StoryboardModel; scope: StoryboardScope; photoRoute: boolean;
}) {
  const { draft, focus, notice, pending, problem, selected, selectedIndex } = model;
  const strip = useRef<HTMLOListElement>(null);
  const add = useRef<HTMLButtonElement>(null);
  const [voiceState, setVoiceState] = useState<InspectorVoiceState>();
  const [photoState, setPhotoState] = useState<StagePhotoState>();
  useLayoutEffect(() => {
    if (!focus) return;
    const button = focus.board ? document.getElementById(panelElementId(focus.board)) : add.current;
    button?.focus({ preventScroll: true });
  }, [focus]);
  useLayoutEffect(() => {
    const list = strip.current;
    const link = selected && document.getElementById(panelElementId(selected));
    if (!list || !link) return;
    const viewport = list.getBoundingClientRect();
    const card = link.getBoundingClientRect();
    if (card.left < viewport.left + 6) list.scrollLeft += card.left - viewport.left - 6;
    if (card.right > viewport.right - 6) list.scrollLeft += card.right - viewport.right + 6;
  }, [draft, selected]);

  if (!draft) return null;
  const labels = timelineLabels(draft.timing);
  const locked = pending || model.draftNeedsReload;
  const selectedTiming = selected ? labels.boards.get(selected) : undefined;
  const panel = draft.boards[selectedIndex];
  return <div className="storyboard-workspace">
    <Stage key={selected} panel={panel} index={selectedIndex} aspect={scope.media} range={selectedTiming?.range}
      photoUnsaved={Boolean(photoState?.board === selected && photoState?.unsaved)}
      voiceCurrent={Boolean(voiceState?.current && voiceState.board === selected && voiceState.revision === panel?.record.revision)} />
    <section className="storyboard-timeline" aria-labelledby="storyboard-timeline-heading">
      <div className="storyboard-timeline-heading">
        <h2 id="storyboard-timeline-heading">Panel timeline</h2>
        <p className="storyboard-length"><span>{labels.length}</span>{labels.advisory && <span>{labels.advisory}</span>}</p>
      </div>
      {labels.warning && <p className="storyboard-warning">{labels.warning}</p>}
      {draft.boards.length > 0 && <ol className="storyboard-filmstrip" role="list" aria-label="Boards" ref={strip}>
        {draft.boards.map(({ record, photo }, index) => {
          const number = boardPosition(index);
          return <li key={record.id}>
            <Link id={panelElementId(record.id)} to={treePath("board", { ...scope, board: record.id })}
              aria-current={record.id === selected ? "page" : undefined} onClick={model.clearNotice}>
              <div className="storyboard-thumb" aria-hidden="true">
                <BoardPicture key={photo} url={photo} alt="" placeholder={<span />} />
              </div>
              <strong>{number}</strong>
              <span>{labels.boards.get(record.id)?.length}</span>
            </Link>
          </li>;
        })}
      </ol>}
      <div className="storyboard-controls">
        <button ref={add} type="button" className="pill primary" aria-disabled={locked} onClick={model.add}>Add board</button>
        {selected && <>
          <button type="button" className="pill" aria-disabled={locked || selectedIndex <= 0} onClick={() => model.move(-1)}>Move earlier</button>
          <button type="button" className="pill" aria-disabled={locked || selectedIndex >= draft.boards.length - 1} onClick={() => model.move(1)}>Move later</button>
          <button type="button" className="pill" aria-disabled={locked} onClick={model.remove}>Remove board</button>
        </>}
      </div>
      <p role="status" className="storyboard-status">{pending ? "Updating draft…" : notice}</p>
      {problem && <>
        <Problem error={problem.error} message={problem.message} />
        {problem.reload && <button className="pill" type="button" onClick={model.reload}>Reload draft</button>}
      </>}
    </section>
    <aside className="storyboard-inspector" aria-label="Board inspector">
      {panel && <BoardInspector api={api} board={panel.record} story={draft.story} fps={draft.timing.fps} timelinePending={locked}
        onRefresh={model.refreshFromInspector} onVoiceState={setVoiceState}>
        <PhotoComposer key={panel.record.id} api={api} panel={panel.record} story={draft.story} scope={scope}
          photoRoute={photoRoute} timelinePending={locked} onRefresh={model.refreshFromInspector} onPhotoState={setPhotoState} />
      </BoardInspector>}
    </aside>
  </div>;
}
