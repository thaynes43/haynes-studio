import { useId, useRef, type ReactNode } from "react";

import type { InspectorStory } from "./board-inspector-api";
import { sameMethod, type Cue, type DraftLine, type DraftNote, type Method, type Values } from "./board-inspector-draft";

const layerNames = { layered: "Layered", whole_frame: "Whole-frame" } satisfies Record<Method["layer"], string>;
const motionNames = { s2v: "Speech-to-video", i2v: "Image-to-video" } satisfies Record<Method["motion"], string>;

export function InspectorSection({ title, children, open }: { title: string; children: ReactNode; open?: boolean }) {
  return <details className="inspector-section" open={open}>
    <summary>{title}</summary>
    <div className="inspector-fields">{children}</div>
  </details>;
}

export function NumberField({ label, value, update, min, max, step = "1" }: {
  label: string; value: string | number; update: (value: string) => void;
  min?: number; max?: number; step?: string;
}) {
  return <label className="inspector-field">{label}
    <input type="number" value={value} min={min} max={max} step={step} onChange={(event) => update(event.target.value)} />
  </label>;
}

export function ScriptFields({ story, lines, onChange, onMove, lineVoice }: {
  story: InspectorStory; lines: DraftLine[]; onChange: (lines: DraftLine[]) => void;
  onMove: (index: number, direction: -1 | 1) => void; lineVoice: (id?: string) => ReactNode;
}) {
  const add = useRef<HTMLButtonElement>(null);
  const speakers = [...story.cast.map(({ slot, name }) => ({ id: slot, name })), { id: "narrator", name: "Narrator" }];
  function update(index: number, changes: Partial<DraftLine>) {
    onChange(lines.map((line, i) => i === index ? { ...line, ...changes } : line));
  }
  return <>
    {lines.map(({ key, id, speaker, text, gap }, index) => {
      const n = index + 1;
      return <fieldset className="inspector-group" key={key}>
        <legend>Line {n}</legend>
        <label className="inspector-field">Speaker
          <select aria-label={`Speaker for line ${n}`} value={speaker}
            onChange={(event) => update(index, { speaker: event.target.value })}>
            {!speakers.some(({ id }) => id === speaker) && <option value={speaker}>{speaker}</option>}
            {speakers.map(({ id, name }) => <option key={id} value={id}>{name}</option>)}
          </select>
        </label>
        <label className="inspector-field">Dialogue
          <textarea aria-label={`Dialogue for line ${n}`} rows={2} maxLength={1200} value={text}
            onChange={(event) => update(index, { text: event.target.value })} />
        </label>
        {index > 0 && <NumberField label={`Gap before line ${n} (ms)`} value={gap} min={0} max={120000}
          update={(gap) => update(index, { gap })} />}
        <div className="inspector-actions">
          <button className="pill" type="button" aria-label={`Move line ${n} earlier`} aria-disabled={index === 0}
            onClick={() => onMove(index, -1)}>↑</button>
          <button className="pill" type="button" aria-label={`Move line ${n} later`} aria-disabled={n === lines.length}
            onClick={() => onMove(index, 1)}>↓</button>
          <button className="pill" type="button" aria-label={`Remove line ${n}`}
            onClick={() => { onChange(lines.filter((_, i) => i !== index)); add.current?.focus(); }}>Remove</button>
        </div>
        {lineVoice(id)}
      </fieldset>;
    })}
    <button ref={add} className="pill" type="button" disabled={lines.length >= 256} onClick={() =>
      onChange([...lines, { key: crypto.randomUUID(), speaker: speakers[0].id, text: "", gap: "300" }])}>Add line</button>
  </>;
}

export function MethodFields({ values, options, onChange }: {
  values: Values; options: Method[]; onChange: (method: Method) => void;
}) {
  const { method, lines } = values;
  const layers = [...new Set(options.map(({ layer }) => layer))];
  const motions = options.filter(({ layer }) => layer === method.layer);
  const valid = options.some((option) => sameMethod(option, method));
  return <>
    {layers.length === 0 ? <p>No buildable method for this shot.</p> : <>
      <fieldset className="inspector-badges">
        <legend>Layer</legend>
        {layers.map((layer) => <button className="pill" type="button" key={layer}
          aria-pressed={layer === method.layer} onClick={() => {
            const choices = options.filter((option) => option.layer === layer);
            onChange(choices.find(({ motion }) => motion === method.motion) ?? choices[0]);
          }}>{layerNames[layer]}</button>)}
      </fieldset>
      {!valid && <p>Choose a buildable method.</p>}
    </>}
    <fieldset className="inspector-badges">
      <legend>Motion</legend>
      {motions.map((option) => <button className="pill" type="button" key={option.motion}
        aria-pressed={sameMethod(option, method)} onClick={() => onChange(option)}>{motionNames[option.motion]}</button>)}
      {!lines.length && <button className="pill" type="button" disabled aria-describedby="inspector-s2v-reason">
        Speech-to-video
      </button>}
    </fieldset>
    {!lines.length && <p id="inspector-s2v-reason" className="muted">Needs a spoken line.</p>}
  </>;
}

export function DirectionFields({ values, newNote, updateNewNote, updateNotes, add, updateCue, disabled }: {
  values: Values; newNote: string; updateNewNote: (text: string) => void;
  updateNotes: (notes: DraftNote[]) => void; add: (note: DraftNote) => void; updateCue: (cue: Cue) => void; disabled: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const { notes, cues, lines } = values;
  function addNote() {
    if (disabled || !newNote.trim()) return;
    add({ key: crypto.randomUUID(), text: newNote });
    input.current?.focus();
  }
  return <div className="inspector-direction">
    <InspectorSection title="Direction" open>
      {notes.map((note, index) => <div className="inspector-note" key={note.key}>
        <input aria-label={`Note ${index + 1}`} maxLength={200} value={note.text}
          onChange={(event) => updateNotes(notes.map((item) => item.key === note.key ? { ...item, text: event.target.value } : item))} />
        <button className="pill" type="button" aria-label={`Remove note ${index + 1}`}
          onClick={() => { updateNotes(notes.filter(({ key }) => key !== note.key)); input.current?.focus(); }}>×</button>
      </div>)}
      {cues.length > 0 && <div className="inspector-fields">
        <h3>Build cues</h3>
        {cues.map((cue, index) => <CueFields key={cue.id} cue={cue} index={index} lines={lines} update={updateCue} />)}
      </div>}
    </InspectorSection>
    <div className="inspector-note inspector-add-note">
      <input ref={input} type="text" aria-label="New direction note" placeholder="Add a direction note"
        maxLength={200} value={newNote} onChange={(event) => updateNewNote(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.nativeEvent.isComposing) {
            event.preventDefault();
            addNote();
          }
        }} />
      <button className="pill" type="button" aria-label="Add note" disabled={!newNote.trim()} onClick={addNote}>+</button>
    </div>
  </div>;
}

function CueFields({ cue, index, lines, update }: {
  cue: Cue; index: number; lines: DraftLine[]; update: (cue: Cue) => void;
}) {
  const { anchor } = cue;
  const existingLines = lines.filter(({ id }) => id);
  function field(label: string, value: string | number, change: (value: string) => Cue, integer = true) {
    return <NumberField label={label} value={value} step={integer ? "1" : "any"} update={(value) => update(change(value))} />;
  }
  return <fieldset className="inspector-group">
    <legend>{cue.type === "sound" ? "Sound" : cue.type === "move" ? "Move" : "Camera"} cue {index + 1}</legend>
    <label className="inspector-field">Anchor
      <select value={anchor.after_line_id} onChange={(event) => update({ ...cue, anchor: { ...anchor, after_line_id: event.target.value } })}>
        <option value="">Board start</option>
        {lines.map(({ id }, i) => id && <option key={id} value={id}>After line {i + 1}</option>)}
        {anchor.after_line_id && !existingLines.some(({ id }) => id === anchor.after_line_id) &&
          <option value={anchor.after_line_id}>Deleted line</option>}
      </select>
    </label>
    {anchor.after_line_id
      ? field("Offset (ms)", anchor.offset_ms, (offset_ms) => ({ ...cue, anchor: { ...anchor, offset_ms } }))
      : field("Start (ms)", anchor.at_ms, (at_ms) => ({ ...cue, anchor: { ...anchor, at_ms } }))}
    {cue.type === "sound" && <>
      <label className="inspector-field">Sound version ID
        <input value={cue.asset_version_id} onChange={(event) => update({ ...cue, asset_version_id: event.target.value })} />
      </label>
      {field("Trim start (ms)", cue.trim_ms[0], (value) => ({ ...cue, trim_ms: [value, cue.trim_ms[1]] }))}
      {field("Trim end (ms)", cue.trim_ms[1], (value) => ({ ...cue, trim_ms: [cue.trim_ms[0], value] }))}
      {field("Level (dBFS)", cue.level_rms_dbfs, (level_rms_dbfs) => ({ ...cue, level_rms_dbfs }), false)}
    </>}
    {cue.type !== "sound" && field("Duration (ms)", cue.duration_ms, (duration_ms) => ({ ...cue, duration_ms }))}
    {cue.type === "move" && <>
      <label className="inspector-field">Cast slot
        <input value={cue.slot} maxLength={1} onChange={(event) => update({ ...cue, slot: event.target.value })} />
      </label>
      {field("Horizontal move (px)", cue.dx_px, (dx_px) => ({ ...cue, dx_px }), false)}
      {field("Vertical move (px)", cue.dy_px, (dy_px) => ({ ...cue, dy_px }), false)}
      {field("Rotation (°)", cue.angle_deg, (angle_deg) => ({ ...cue, angle_deg }), false)}
      {field("Steps", cue.steps, (steps) => ({ ...cue, steps }))}
    </>}
    {cue.type === "camera" && <>
      {field("Start zoom", cue.zoom_from, (zoom_from) => ({ ...cue, zoom_from }), false)}
      {field("End zoom", cue.zoom_to, (zoom_to) => ({ ...cue, zoom_to }), false)}
      {field("Center X (px)", cue.center_px[0], (value) => ({ ...cue, center_px: [value, cue.center_px[1]] }), false)}
      {field("Center Y (px)", cue.center_px[1], (value) => ({ ...cue, center_px: [cue.center_px[0], value] }), false)}
      <p className="muted">Cubic ease out</p>
    </>}
  </fieldset>;
}

export function ComparedValues({ title, values, changes, story }: {
  title: string; values: Values; changes: (keyof Values)[]; story: InspectorStory;
}) {
  const { lines, timing, notes, cues, method } = values;
  const heading = useId();
  return <section className="inspector-saved" aria-labelledby={heading}>
    <h3 id={heading}>{title}</h3>
    {changes.includes("lines") && <>
      <strong>Script</strong>
      {lines.length ? <ol>{lines.map(({ key, speaker, text, gap }) => <li key={key}>
        <strong>{story.cast.find(({ slot }) => slot === speaker)?.name ?? (speaker === "narrator" ? "Narrator" : speaker)}</strong>
        <p>{text}</p>{gap && <small>Gap {gap} ms</small>}
      </li>)}</ol> : <p>No dialogue.</p>}
    </>}
    {changes.includes("timing") && <div>
      <strong>Timing</strong>
      <p>{lines.length ? `Lead ${timing.lead} ms · Tail ${timing.tail} ms` : `Hold ${timing.hold} ms`}</p>
    </div>}
    {changes.includes("method") && <div><strong>Method</strong>
      <p>{layerNames[method.layer]} · {motionNames[method.motion]}</p>
    </div>}
    {changes.includes("notes") && <div><strong>Direction</strong>
      {notes.length ? <ul>{notes.map(({ key, text }) => <li key={key}>{text}</li>)}</ul> : <p>No notes.</p>}
    </div>}
    {changes.includes("cues") && <div><strong>Build cues</strong>
      {cues.length ? <fieldset disabled className="inspector-fields">
        {cues.map((cue, index) => <CueFields key={cue.id} cue={cue} lines={lines} index={index} update={() => {}} />)}
      </fieldset> : <p>No cues.</p>}
    </div>}
  </section>;
}
