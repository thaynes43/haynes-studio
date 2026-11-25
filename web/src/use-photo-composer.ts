import { useEffect, useEffectEvent, useLayoutEffect, useRef, useState } from "react";

import { ApiError, type StudioClient } from "./api/client";
import { patchPhoto, queuePhoto } from "./photo-composer-api";
import {
  photoEditAfterSave, photoInputs, rebasePhotoEdit, type PhotoEdit, type PhotoInputs, type PhotoJob,
} from "./photo-composer-model";
import { readObject } from "./production-review-data";
import { loadBoard, type Board } from "./route-data";
import type { StoryboardDraft } from "./storyboard-data";

export type PhotoStory = Pick<StoryboardDraft["story"], "cast" | "set" | "layouts">;
type Press = { key: string; input: string; seed: number };
type Memory = { edit?: PhotoEdit; press?: Press };
const drafts = new WeakMap<StudioClient, Map<string, Memory>>();
export const photoSaveDelay = 450;

function boardMemory(api: StudioClient, id: string) {
  let session = drafts.get(api);
  if (!session) {
    session = new Map();
    drafts.set(api, session);
  }
  let memory = session.get(id);
  if (!memory) {
    memory = {};
    session.set(id, memory);
  }
  return memory;
}

function pressInput(board: Board, story: PhotoStory) {
  if (board.method.layer === "whole_frame") {
    return JSON.stringify(["whole_frame", board.photo.prompt?.normalize("NFC"), board.photo.input_asset_version_ids]);
  }
  const camera = readObject(board.cues.findLast(({ type }) => type === "camera"));
  return JSON.stringify([
    "layered", story.set?.asset_version_id,
    board.cast.map(({ slot, asset_version_id }) => [slot, asset_version_id]),
    story.layouts[board.layout.preset],
    board.layout.foreground ? [story.set?.foreground_edge_px, story.set?.foreground_feather_px] : null,
    [camera.zoom_to, camera.center_px],
  ]);
}

export function usePhotoComposer({
  api, board: panel, polledBoard, story, locked, refresh,
}: {
  api: StudioClient; board: Board; polledBoard?: Board; story: PhotoStory; locked: boolean; refresh: () => void;
}) {
  const memory = boardMemory(api, panel.id);
  const [edit, setEdit] = useState(memory.edit);
  const [press, setPress] = useState(memory.press);
  const [written, setWritten] = useState<Board>();
  const [posted, setPosted] = useState<PhotoJob>();
  const [phase, setPhase] = useState<"saving" | "submitting" | "selecting">();
  const [saveError, setSaveError] = useState<unknown>();
  const [actionError, setActionError] = useState<unknown>();
  const [notice, setNotice] = useState("");
  const operation = useRef<AbortController>(null);
  const working = useRef(false);

  useLayoutEffect(() => {
    const lifetime = new AbortController();
    operation.current = lifetime;
    return () => lifetime.abort();
  }, []);

  let board = panel;
  if (written && written.revision >= board.revision) board = written;
  if (polledBoard && polledBoard.revision >= board.revision) board = polledBoard;
  const saved = photoInputs(board);
  const { values, dirty, conflict } = rebasePhotoEdit(edit, saved);
  const layered = board.method.layer === "layered";
  const retryMatches = press?.input === pressInput(board, story);

  function rememberEdit(next?: PhotoEdit) {
    memory.edit = next;
    setEdit(next);
  }

  function rememberPress(next?: Press) {
    memory.press = next;
    setPress(next);
  }

  function changeInputs(next: PhotoInputs) {
    rememberEdit({ base: conflict && edit ? edit.base : saved, values: next });
    setSaveError(undefined);
    setNotice("");
  }

  async function observeConflict(signal: AbortSignal) {
    const latest = await loadBoard(api, board.story_id, board.id, signal);
    if (signal.aborted) throw signal.reason;
    setWritten(latest);
    refresh();
    return latest;
  }

  async function saveInputs(initial: Board, signal: AbortSignal) {
    let target = initial;
    for (let attempt = 0; attempt < 2; attempt++) {
      const saving = memory.edit;
      const pending = rebasePhotoEdit(saving, photoInputs(target));
      if (target.method.layer !== "whole_frame" || pending.conflict) return;
      if (!pending.dirty) return target;

      try {
        const updated = await patchPhoto(api, target, pending.values, target.photo.current_version_id, signal);
        if (signal.aborted) throw signal.reason;
        rememberEdit(photoEditAfterSave(saving, memory.edit, photoInputs(updated)));
        setWritten(updated);
        refresh();
        return updated;
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 409 || signal.aborted) throw error;
        // A job or another inspector write can advance the revision without
        // changing either photo input. Retry once after rebasing the fields.
        target = await observeConflict(signal);
        if (attempt === 1) throw error;
      }
    }
  }

  async function perform(action: "save" | "generate" | "retry" | "select", selection?: string) {
    const signal = operation.current?.signal;
    if (!signal || signal.aborted || locked || working.current) return;
    working.current = true;
    setNotice("");
    const writingInputs = action === "save" || (action === "generate" && !layered && dirty);
    let savingInputs = writingInputs;
    setPhase(writingInputs ? "saving" : action === "select" ? "selecting" : "submitting");
    if (writingInputs) setSaveError(undefined);
    if (action !== "save") setActionError(undefined);
    try {
      if (action === "select" && selection) {
        try {
          const updated = await patchPhoto(api, board, saved, selection, signal);
          if (!signal.aborted) setWritten(updated);
        } catch (error) {
          if (!(error instanceof ApiError) || error.status !== 409 || signal.aborted) throw error;
          await observeConflict(signal);
          setNotice("Board changed. Latest photo selection loaded.");
        }
        return;
      }
      const target = writingInputs ? await saveInputs(board, signal) : board;
      savingInputs = false;
      if (!target || signal.aborted || action === "save") return;
      if (rebasePhotoEdit(memory.edit, photoInputs(target)).dirty && target.method.layer === "whole_frame") {
        setNotice("Photo inputs changed. Generate when they’re saved.");
        return;
      }
      const input = pressInput(target, story);
      const request = action === "retry" ? memory.press : {
        key: crypto.randomUUID(), input,
        seed: target.method.layer === "layered" ? 0 : crypto.getRandomValues(new Uint32Array(1))[0],
      };
      if (!request || request.input !== input) return;
      rememberPress(request);
      setPhase("submitting");
      const job = await queuePhoto(api, target.id, request.key, request.seed, signal);
      if (signal.aborted) return;
      rememberPress();
      setPosted(job);
    } catch (error) {
      if (signal.aborted) return;
      if (savingInputs) setSaveError(error);
      else {
        if (action !== "select" && error instanceof ApiError && error.status >= 400 && error.status < 500) {
          rememberPress();
        }
        setActionError(error);
      }
    } finally {
      working.current = false;
      if (!signal.aborted) {
        setPhase(undefined);
        if (action !== "save") refresh();
      }
    }
  }

  const autosave = useEffectEvent(() => { void perform("save"); });
  useEffect(() => {
    if (layered || locked || !dirty || conflict || phase || saveError !== undefined) return;
    const timer = setTimeout(autosave, photoSaveDelay);
    return () => clearTimeout(timer);
  }, [conflict, dirty, edit, layered, locked, phase, saveError]);

  return {
    board, values, dirty, conflict, press, posted, phase, saveError, actionError, notice, retryMatches, changeInputs,
    save: () => void perform("save"),
    generate: () => void perform(press ? "retry" : "generate"),
    select: (id: string) => void perform("select", id),
    resolve: (keep: boolean) => {
      rememberEdit(keep ? { base: saved, values } : undefined);
      setSaveError(undefined);
    },
    discardPress: () => {
      rememberPress();
      setActionError(undefined);
    },
  };
}
