import { useId, useLayoutEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { ApiError, type StudioClient } from "./api/client";
import { checkName, isNameTaken, isRevisionConflict, maxNameLength, nameIssueFromApi } from "./editor-entry-logic";
import { listProductions, listStories, loadProduction, type Production, type RouteData } from "./route-data";
import { mediaKinds, treePath, type Context, type MediaKind } from "./routes";
import { Empty, Problem, Rows } from "./shell-ui";
import "./editor-entry.css";

export function EditorLanding({ assets }: { assets: string }) {
  return (
    <div className="launch-grid">
      <Link to={treePath("board")} className="launch">
        <span className="launch-icon mark-board" aria-hidden="true" />
        <span><strong>Storyboard editor</strong><small>Script, voice and reference photos.</small></span>
        <span className="arrow" aria-hidden="true">→</span>
      </Link>
      <Link to={assets} className="launch">
        <span className="launch-icon mark-assets" aria-hidden="true" />
        <span><strong>Asset library</strong><small>Cast, costumes, sets and props.</small></span>
        <span className="arrow" aria-hidden="true">→</span>
      </Link>
    </div>
  );
}

function usePickerAction() {
  const navigate = useNavigate();
  const active = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  useLayoutEffect(() => () => active.current?.abort(), []);

  async function run(action: (signal: AbortSignal) => Promise<string | void>) {
    if (active.current) return;
    const request = new AbortController();
    active.current = request;
    setBusy(true);
    setError(undefined);
    try {
      const to = await action(request.signal);
      if (to && !request.signal.aborted) void navigate(to);
    } catch (error) {
      if (!request.signal.aborted) setError(error);
    } finally {
      active.current = null;
      if (!request.signal.aborted) setBusy(false);
    }
  }

  return { busy, error, run, clearError: () => setError(undefined) };
}

type Entity = "production" | "story";
type NameIssue = NonNullable<ReturnType<typeof checkName>["issue"] | ReturnType<typeof nameIssueFromApi>>;
type Choice = { to: string; label: string };
const fieldLabels = { production: "Production name", story: "Story title" };

function nameMessage(entity: Entity, issue: NameIssue) {
  const field = fieldLabels[entity].toLowerCase();
  switch (issue) {
    case "required": return `Enter a ${field}.`;
    case "tooLong": return `Use ${maxNameLength} characters or fewer.`;
    case "duplicate": return entity === "production"
      ? "A production with this name already exists."
      : "A story with this title already exists in this media type.";
    case "rejected": return `Studio rejected this ${field}. Enter 1–${maxNameLength} characters.`;
  }
}

function NamedPicker({ entity, initialChoices, readChoices, create }: {
  entity: Entity;
  initialChoices: Choice[];
  readChoices: (signal: AbortSignal) => Promise<Choice[]>;
  create: (name: string, signal: AbortSignal) => Promise<string>;
}) {
  const inputId = useId();
  const errorId = useId();
  const input = useRef<HTMLInputElement>(null);
  const [choices, setChoices] = useState(initialChoices);
  const [value, setValue] = useState("");
  const [localIssue, setLocalIssue] = useState<NameIssue>();
  const { busy, error, run, clearError } = usePickerAction();
  const issue = localIssue ?? nameIssueFromApi(error);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const checked = checkName(value);
    setLocalIssue(checked.issue);
    if (checked.issue) {
      clearError();
      input.current?.focus();
      return;
    }
    void run(async (signal) => {
      const fresh = await readChoices(signal);
      if (signal.aborted) return;
      setChoices(fresh);
      // A fresh list catches changes since this picker opened and creates whose reply was lost.
      if (isNameTaken(checked.name, fresh.map(({ label }) => label))) {
        setLocalIssue("duplicate");
        input.current?.focus();
        return;
      }
      return create(checked.name, signal);
    });
  }

  return (
    <>
      {choices.length ? <Rows items={choices} /> : (
        <Empty>{entity === "production" ? "No productions yet." : "No stories yet."}</Empty>
      )}
      <form className="editor-create" noValidate onSubmit={submit} aria-busy={busy}>
        <div className="editor-create-fields">
          <div className="editor-name-field">
            <label htmlFor={inputId}>{fieldLabels[entity]}</label>
            <input
              ref={input}
              id={inputId}
              value={value}
              required
              readOnly={busy}
              autoComplete="off"
              aria-invalid={issue ? true : undefined}
              aria-describedby={issue || error != null ? errorId : undefined}
              onChange={(event) => {
                setValue(event.target.value);
                setLocalIssue(undefined);
                clearError();
              }}
            />
          </div>
          <button className="pill primary" type="submit" disabled={busy}>
            {busy ? "Creating…" : `Create ${entity}`}
          </button>
        </div>
        {(issue || error != null) && (
          <Problem id={errorId} error={error} message={issue && nameMessage(entity, issue)} />
        )}
      </form>
    </>
  );
}

function MediaPicker({ api, initial }: { api: StudioClient; initial: Production }) {
  const [production, setProduction] = useState(initial);
  const [reloadError, setReloadError] = useState<unknown>();
  const { busy, error, run } = usePickerAction();
  const { id } = production;
  const missing = (Object.keys(mediaKinds) as MediaKind[])
    .filter((kind) => !production.media_types.some((item) => item.kind === kind));

  async function reload(signal: AbortSignal) {
    setReloadError(undefined);
    try {
      const fresh = await loadProduction(api, id, signal);
      if (!signal.aborted) setProduction(fresh);
    } catch (error) {
      if (!signal.aborted) setReloadError(error);
    }
  }

  function enable(kind: MediaKind) {
    void run(async (signal) => {
      try {
        const { data } = await api.PUT("/v1/productions/{id}/media-types/{kind}", {
          signal, params: { path: { id, kind }, header: { "If-Match": `"${production.revision}"` } },
        });
        if (!data || data.id !== id || !data.media_types.some((item) => item.kind === kind)) throw new ApiError(500);
      } catch (error) {
        if (isRevisionConflict(error) && !signal.aborted) await reload(signal);
        throw error;
      }
      return treePath("board", { production: id, media: kind });
    });
  }

  return (
    <section aria-label="Production media types" aria-busy={busy}>
      {production.media_types.length ? (
        <div className="launch-grid">
          {production.media_types.map(({ kind, aspect }) => (
            <Link key={kind} to={treePath("board", { production: id, media: kind })} className="launch">
              <span className={`launch-icon editor-media-icon ${kind}`} aria-hidden="true" />
              <span><strong>{mediaKinds[kind].label}</strong><small>{aspect}</small></span>
              <span className="arrow" aria-hidden="true">→</span>
            </Link>
          ))}
        </div>
      ) : <Empty>No media types yet.</Empty>}
      {missing.length > 0 && (
        <div className="actions editor-media-actions" role="group" aria-label="Add a media type">
          {missing.map((kind) => {
            const { label, aspect } = mediaKinds[kind];
            return (
              <button key={kind} className="pill" type="button" disabled={busy || reloadError != null} onClick={() => enable(kind)}>
                + {label} · {aspect}
              </button>
            );
          })}
        </div>
      )}
      {busy && <p className="muted" role="status">Updating media types…</p>}
      {error != null && (
        <Problem error={error} message={isRevisionConflict(error)
          ? (reloadError != null ? "This production changed. Reload its media types to continue."
            : "This production changed. Its media types are up to date.")
          : undefined} />
      )}
      {reloadError != null && <Problem error={reloadError} retry={() => { void run(reload); }} />}
    </section>
  );
}

export function EditorPicker({ api, context, data }: { api: StudioClient; context: Context; data: RouteData }) {
  if (data.production) {
    const { id } = data.production;
    const { media } = context;
    if (!media) return <MediaPicker api={api} initial={data.production} />;

    const choices = (stories: NonNullable<RouteData["stories"]>) => stories.map(({ id: story, title }) => ({
      to: treePath("board", { production: id, media, story }), label: title,
    }));
    return (
      <NamedPicker
        entity="story"
        initialChoices={choices(data.stories ?? [])}
        readChoices={async (signal) => choices(await listStories(api, id, media, signal))}
        create={async (title, signal) => {
          const { data } = await api.POST("/v1/productions/{id}/media-types/{kind}/stories", {
            signal, params: { path: { id, kind: media } }, body: { title },
          });
          if (!data) throw new ApiError(500);
          return treePath("board", { production: id, media, story: data.id });
        }}
      />
    );
  }

  const choices = (productions: Production[]) => productions.map(({ id, name }) => ({
    to: treePath("board", { production: id }), label: name,
  }));
  return (
    <NamedPicker
      entity="production"
      initialChoices={choices(data.productions ?? [])}
      readChoices={async (signal) => choices(await listProductions(api, signal))}
      create={async (name, signal) => {
        const { data } = await api.POST("/v1/productions", { signal, body: { name } });
        if (!data) throw new ApiError(500);
        return treePath("board", { production: data.id });
      }}
    />
  );
}
