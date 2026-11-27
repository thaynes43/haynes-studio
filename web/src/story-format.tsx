import { useCallback, useLayoutEffect, useRef, useState, type FormEvent } from "react";

import type { StudioClient } from "./api/client";
import { storyFormatId } from "./routes";
import { Problem } from "./shell-ui";
import type { StoryboardDraft, StoryboardScope } from "./storyboard-data";
import {
  formatEditsConflict, formatFailure, formatPatch, formatStatus, loadStoryFormatOptions, nextCastSlot, storyFormat,
  type FormatProfile, type StoryFormat, type StoryFormatOptions, type VoiceVersion,
} from "./story-format-data";
import { useRequest } from "./use-request";
import type { FormatChange, StoryboardModel } from "./use-storyboard";
import "./story-format.css";

type FormatEditorProps = {
  api: StudioClient;
  scope: StoryboardScope;
  profile: FormatProfile;
  story: StoryboardDraft["story"];
  model: StoryboardModel;
};
type SaveFailure = { error: unknown; reload: boolean };

const formatLabel = ({ name, number }: { name: string; number: number }) => `${name} · v${number}`;
const voiceLabel = ({ name, number }: VoiceVersion) => `${name} · v${number}`;

export function StoryFormatEditor({ openFromRun, ...props }: FormatEditorProps & { openFromRun: boolean }) {
  const [opened, setOpened] = useState(openFromRun);
  const summary = useRef<HTMLElement>(null);
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<SaveFailure>();
  const { model, story } = props;
  const conflict = model.formatConflict && (model.formatConflict.detail?.message || "The draft changed while you were working.");
  useLayoutEffect(() => {
    if (openFromRun) summary.current?.focus();
  }, [openFromRun]);

  async function saveOrReload(change?: FormatChange) {
    summary.current?.focus();
    setSaving(Boolean(change));
    const reply = await model.updateFormat(change);
    setSaving(false);
    if (!reply) return false;
    setFailure(reply.kind === "failure" ? reply : undefined);
    return reply.kind === "ready" && !reply.conflict;
  }

  const status = saving ? formatStatus(story, true)
    : conflict ? "Format change needs review"
    : failure?.reload ? "Check format save"
    : failure ? "Format save failed" : formatStatus(story, false);

  return <div className="story-format-section">
    <details id={storyFormatId} className="story-format" open={openFromRun || undefined} onToggle={(event) => {
      if (event.currentTarget.open) setOpened(true);
    }}>
      <summary ref={summary}>Format <span className="muted" role="status">{status}</span></summary>
      {opened && <FormatForm {...props} saving={saving} needsReload={Boolean(failure?.reload)} conflict={conflict}
        clearFailure={() => setFailure(undefined)} clearConflict={model.clearFormatConflict} saveFormat={saveOrReload} />}
    </details>
    {failure && <div className="story-format-fields">
      <Problem error={failure.error} message={formatFailure(failure.error)} />
      {failure.reload && <button className="pill" type="button" disabled={model.pending} onClick={() => void saveOrReload()}>
        Reload draft
      </button>}
    </div>}
  </div>;
}

function VoiceSelect({ label, value, voices, required, onChange }: {
  label: string; value: string | null; voices: VoiceVersion[]; required?: boolean; onChange: (value: string) => void;
}) {
  return <label className="inspector-field">{label}
    <select value={value ?? ""} required={required} onChange={(event) => onChange(event.target.value)}>
      <option value="">{required ? "Choose a voice" : "No narrator voice"}</option>
      {value && !voices.some(({ id }) => id === value) && <option value={value}>Saved voice · {value}</option>}
      {voices.map((voice) => <option key={voice.id} value={voice.id}>{voiceLabel(voice)}</option>)}
    </select>
  </label>;
}

function FormatSummary({ title, values, options }: { title: string; values: StoryFormat; options: StoryFormatOptions }) {
  const pinned = options.formats.find(({ id }) => id === values.format_version_id);
  function voice(id: string | null) {
    const found = options.voices.find((version) => version.id === id);
    return found ? voiceLabel(found) : id || "None";
  }
  return <section className="inspector-saved">
    <h3>{title}</h3>
    <p>{pinned ? formatLabel(pinned) : values.format_version_id ?? "No format pinned"}</p>
    <p>Narrator voice · {voice(values.narrator_voice_version_id)}</p>
    {values.cast.length === 0 ? <p>No cast members</p> : <ul>{values.cast.map((member) =>
      <li key={member.slot}>Cast {member.slot.toUpperCase()} · {member.name} · {voice(member.voice_version_id)}</li>)}</ul>}
  </section>;
}

function FormatForm({ api, scope, profile, story, model, saving, needsReload, conflict, clearFailure, clearConflict, saveFormat }: FormatEditorProps & {
  saving: boolean; needsReload: boolean; conflict?: string;
  clearFailure: () => void; clearConflict: () => void;
  saveFormat: (change: FormatChange) => Promise<boolean>;
}) {
  const { width, height } = profile;
  const load = useCallback((signal: AbortSignal) => loadStoryFormatOptions(api, scope, { width, height }, signal),
    [api, scope, width, height]);
  const { result, retry } = useRequest(load);
  const [editing, setEditing] = useState<{ base: StoryFormat; values: StoryFormat }>();
  const [notice, setNotice] = useState("");
  const saved = storyFormat(story);
  const edits = editing ? formatPatch(editing.base, editing.values) : {};
  const values = { ...saved, ...edits };
  const patch = formatPatch(saved, values);
  const review = Boolean(conflict || (editing && formatEditsConflict(editing.base, editing.values, saved)));
  const locked = model.pending || model.draftNeedsReload || saving;
  const canSave = !locked && !review && Boolean(values.format_version_id) && Object.keys(patch).length > 0;

  function edit(next: StoryFormat) {
    setEditing({ base: saved, values: next });
    clearFailure();
    setNotice("");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSave) return;
    if (values.cast.some(({ name }) => !name.trim())) {
      setNotice("Enter a name for each cast member.");
      return;
    }
    setNotice("");
    if (await saveFormat({ revision: story.revision, patch })) {
      setEditing(undefined);
      setNotice("Format settings saved.");
    }
  }

  if (result.status === "loading") return <p className="story-format-fields" role="status">Loading format options…</p>;
  if (result.status === "failure") return <div className="story-format-fields">
    <Problem error={result.error} message={formatFailure(result.error)} retry={retry} />
  </div>;
  const { formats, voices } = result.data;
  const selected = formats.find(({ id }) => id === values.format_version_id);
  const slot = nextCastSlot(values.cast);
  const changeMember = (key: string, change: Partial<StoryFormat["cast"][number]>) =>
    edit({ ...values, cast: values.cast.map((member) => member.slot === key ? { ...member, ...change } : member) });

  return <form className="story-format-fields" onSubmit={(event) => void submit(event)}>
    {review && !needsReload && <div className="story-format-review">
      <p role="alert">{conflict} Review your unsaved format settings and the latest saved version.</p>
      <div className="inspector-comparison">
        <FormatSummary title="Your unsaved version" values={values} options={result.data} />
        <FormatSummary title="Latest saved version" values={saved} options={result.data} />
      </div>
      <div className="inspector-actions">
        <button className="pill" type="button" disabled={locked} onClick={() => { edit(values); clearConflict(); }}>
          Keep my edited fields
        </button>
        <button className="pill" type="button" disabled={locked} onClick={() => { edit(saved); clearConflict(); }}>
          Use latest saved version
        </button>
      </div>
    </div>}
    <fieldset className="story-format-inputs" aria-label="Format settings" disabled={locked || review}>
      <div className="story-format-row">
        <label className="inspector-field">Format version
          <select value={values.format_version_id ?? ""} onChange={(event) => edit({ ...values, format_version_id: event.target.value })}>
            <option value="" disabled>Choose a format</option>
            {values.format_version_id && !selected && <option value={values.format_version_id}>
              Saved format · {values.format_version_id}
            </option>}
            {formats.map((version) => <option key={version.id} value={version.id}>{formatLabel(version)}</option>)}
          </select>
        </label>
        <VoiceSelect label="Narrator voice" value={values.narrator_voice_version_id} voices={voices}
          onChange={(value) => edit({ ...values, narrator_voice_version_id: value || null })} />
      </div>
      {formats.length === 0 && <p className="muted">No formats are available for this media type.</p>}
      {selected && <div className="story-format-targets muted">
        <p>Run targets{selected.recipe.targets.length === 0 && " · None"}</p>
        {selected.recipe.targets.length > 0 && <ul>{selected.recipe.targets.map(({ id, name, rules }) =>
          <li key={id}>{name}{rules.max_length_ms == null && " · No platform maximum. A package can’t be prepared."}</li>)}</ul>}
      </div>}
      {voices.length === 0 && <p className="muted">No voices are available for this story.</p>}
      <fieldset className="inspector-group">
        <legend>Cast</legend>
        {values.cast.length === 0 && <p className="muted">No cast members</p>}
        {values.cast.map(({ slot, name, voice_version_id }) => {
          const label = `Cast ${slot.toUpperCase()}`;
          return <div className="story-format-row" key={slot}>
            <label className="inspector-field">{label} name
              <input value={name} required maxLength={80} onChange={(event) => changeMember(slot, { name: event.target.value })} />
            </label>
            <VoiceSelect label={`${label} voice`} value={voice_version_id} voices={voices} required
              onChange={(value) => changeMember(slot, { voice_version_id: value })} />
            <button className="pill" type="button" aria-label={`Remove ${label.toLowerCase()}`} onClick={() =>
              edit({ ...values, cast: values.cast.filter((member) => member.slot !== slot) })}>Remove</button>
          </div>;
        })}
        <button className="pill" type="button" disabled={!slot || voices.length === 0} onClick={() => {
          if (slot) edit({ ...values, cast: [...values.cast, { slot, name: "", voice_version_id: "" }] });
        }}>Add cast member</button>
      </fieldset>
    </fieldset>
    <button className="pill primary" type="submit" disabled={locked} aria-disabled={!canSave}>Save format</button>
    {notice && <p role="status">{notice}</p>}
  </form>;
}
