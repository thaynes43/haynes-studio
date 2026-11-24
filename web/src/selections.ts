import { ApiError, type StudioClient } from "./api/client";
import type { components } from "./api/schema";
import { parseRoute, safePath } from "./routes";

const namespace = "web_shell";
const destinations = {
  productions: "/productions",
  board: "/editor/board",
  assets: "/editor/assets",
};
type Destinations = typeof destinations;
export type Destination = keyof Destinations;
type SelectionDocument = components["schemas"]["Selections"];
type SelectionVersion = {
  values: SelectionDocument["values"];
  etag: string;
};

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

export function readDestinations(values: SelectionDocument["values"]): Destinations {
  const saved = object(values[namespace]);
  const result = { ...destinations };
  for (const key of Object.keys(result) as Destination[]) {
    const path = safePath(saved[key]);
    if (!path) continue;
    const [pathname, search] = path.split("?");
    const route = parseRoute(pathname, search);
    if (route.area !== key) continue;
    if (route.area === "assets" ? route.generate : route.page) continue;
    result[key] = path;
  }
  return result;
}

function selectionVersion(data: SelectionDocument | undefined, response: Response): SelectionVersion {
  const etag = response.headers.get("ETag");
  if (!data || !etag) throw new ApiError(500);
  return { values: data.values, etag };
}

export async function loadSelections(client: StudioClient, signal?: AbortSignal) {
  const { data, response } = await client.GET("/v1/me/selections", { signal });
  return selectionVersion(data, response);
}

export function createSelections(client: StudioClient, initial: SelectionVersion) {
  let confirmed = initial;
  let pending: Partial<Destinations> = {};
  let saving = false;
  let snapshot = { destinations: readDestinations(initial.values), error: undefined as unknown };
  const listeners = new Set<() => void>();

  function publish(next: Destinations, error?: unknown) {
    snapshot = { destinations: next, error };
    for (const listener of listeners) listener();
  }

  async function write(changes: Partial<Destinations>) {
    const { data, response } = await client.PUT("/v1/me/selections", {
      params: { header: { "If-Match": confirmed.etag } },
      body: { values: {
        ...confirmed.values,
        [namespace]: { ...object(confirmed.values[namespace]), ...changes },
      } },
    });
    return selectionVersion(data, response);
  }

  async function flush() {
    if (saving) return;
    saving = true;
    try {
      while (Object.keys(pending).length) {
        const changes = pending;
        pending = {};
        try {
          try {
            confirmed = await write(changes);
          } catch (error) {
            if (!(error instanceof ApiError) || error.code !== "conflict.revision") throw error;
            confirmed = await loadSelections(client);
            confirmed = await write(changes);
          }
        } catch (error) {
          pending = { ...changes, ...pending };
          publish({ ...readDestinations(confirmed.values), ...pending }, error);
          return;
        }
        publish({ ...readDestinations(confirmed.values), ...pending });
      }
    } finally {
      saving = false;
    }
  }

  return {
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    snapshot: () => snapshot,
    remember(key: Destination, path: string) {
      if (snapshot.destinations[key] === path) return;
      pending[key] = path;
      publish({ ...snapshot.destinations, [key]: path }, snapshot.error);
      void flush();
    },
    retry: flush,
  };
}

export type SelectionStore = ReturnType<typeof createSelections>;
