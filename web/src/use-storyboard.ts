import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";

import { ApiError, type StudioClient } from "./api/client";
import { loadProduction } from "./route-data";
import { treePath } from "./routes";
import { addBoard, loadStoryboardDraft, removeBoard, reorderBoards, type StoryboardDraft, type StoryboardScope } from "./storyboard-data";
import { boardPosition, moveBoard, selectBoard } from "./storyboard-timeline";
import { useRequest } from "./use-request";

const changedDraft = "The draft changed. Loaded the latest version.";
type Change = (signal: AbortSignal) => Promise<{ message?: string; addedId?: string; movedId?: string }>;

export function useStoryboard(api: StudioClient, scope: StoryboardScope, requested?: string) {
  const navigate = useNavigate();
  const load = useCallback(async (signal: AbortSignal) => {
    const production = await loadProduction(api, scope.production, signal);
    if (!production.media_types.some(({ kind }) => kind === scope.media)) throw new ApiError(404);
    return { production, draft: await loadStoryboardDraft(api, scope, signal) };
  }, [api, scope]);
  const { result, retry } = useRequest(load);
  const [refreshed, setRefreshed] = useState<{ draft: StoryboardDraft; previousOrder: string[] }>();
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState<{ error: unknown; reload?: boolean; message?: string }>();
  const [pending, setPending] = useState(false);
  const [focus, setFocus] = useState<{ board?: string }>();
  const lifetime = useRef<AbortController>(null);
  const working = useRef(false);
  const currentRoute = useRef(requested);

  useLayoutEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    return () => controller.abort();
  }, []);
  useLayoutEffect(() => { currentRoute.current = requested; }, [requested]);

  const draft = refreshed?.draft ?? (result.status === "success" ? result.data.draft : undefined);
  const selected = draft && selectBoard(draft.story.board_order, requested, refreshed?.previousOrder);
  const selectedIndex = draft?.boards.findIndex(({ record }) => record.id === selected) ?? -1;

  useEffect(() => {
    if (!draft || selected === requested) return;
    if (requested) {
      setNotice((message) => message === "Board removed." ? message
        : `${message === changedDraft ? `${message} ` : ""}That board is no longer available.`);
    }
    void navigate(treePath("board", { ...scope, board: selected }), { replace: true });
  }, [draft, navigate, requested, scope, selected]);

  async function update(change?: Change) {
    const signal = lifetime.current?.signal;
    if (!draft || !signal || signal.aborted || working.current || (change && problem?.reload)) return;
    working.current = true;
    const routeAtStart = currentRoute.current;
    setPending(true);
    setNotice("");
    setProblem(undefined);

    try {
      let outcome: Awaited<ReturnType<Change>> = { message: "Draft reloaded." };
      if (change) {
        try {
          outcome = await change(signal);
        } catch (error) {
          if (signal.aborted) return;
          if (error instanceof ApiError && (error.status === 409 || error.status === 404)) {
            outcome = { message: changedDraft };
          } else {
            const reload = !(error instanceof ApiError) || error.status === 0 || error.status >= 500;
            setProblem({ error, reload });
            return;
          }
        }
      }

      const latest = await loadStoryboardDraft(api, scope, signal);
      if (signal.aborted) return;
      setRefreshed({ draft: latest, previousOrder: draft.story.board_order });
      const moved = outcome.movedId ? latest.story.board_order.indexOf(outcome.movedId) : -1;
      setNotice(moved >= 0 ? `Moved to ${boardPosition(moved).toLowerCase()}.` : outcome.message ?? "");
      if (routeAtStart !== currentRoute.current) return;
      const next = selectBoard(latest.story.board_order, outcome.addedId ?? routeAtStart, draft.story.board_order);
      if (outcome.addedId && next === outcome.addedId) {
        void navigate(treePath("board", { ...scope, board: next }));
      }
      setFocus({ board: next });
    } catch (error) {
      if (!signal.aborted) setProblem({ error, reload: true, message: "Couldn’t reload the draft." });
    } finally {
      working.current = false;
      if (!signal.aborted) setPending(false);
    }
  }

  return {
    result, retry, draft, selected, selectedIndex, pending, notice, problem, focus,
    clearNotice: () => setNotice(""),
    reload: () => void update(),
    add: () => draft && void update(async (signal) => ({ message: "Board added.", addedId: await addBoard(api, draft, signal) })),
    remove: () => {
      const panel = draft?.boards[selectedIndex];
      if (panel) void update(async (signal) => {
        await removeBoard(api, panel.record, signal);
        return { message: "Board removed." };
      });
    },
    move: (direction: -1 | 1) => {
      if (!draft || !selected) return;
      const order = moveBoard(draft.story.board_order, selected, direction);
      if (order) void update(async (signal) => {
        await reorderBoards(api, draft, order, signal);
        return { movedId: selected };
      });
    },
  };
}

export type StoryboardModel = ReturnType<typeof useStoryboard>;
