import { ApiError, type StudioClient } from "./api/client";
import type { components } from "./api/schema";
import { assetsDestination, parseRoute, safePath } from "./routes";
import { readProductionFilters, type ProductionFilters } from "./production-filters";

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
type Changes = Partial<Destinations> & { production_filters?: Record<string, ProductionFilters> };

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function mergeChanges(earlier: Changes, later: Changes): Changes {
  if (!later.production_filters) return { ...earlier, ...later };
  return {
    ...earlier,
    ...later,
    production_filters: { ...earlier.production_filters, ...later.production_filters },
  };
}

function applyChanges(values: SelectionDocument["values"], changes: Changes): SelectionDocument["values"] {
  const shell = object(values[namespace]);
  const filters = changes.production_filters && {
    ...object(shell.production_filters), ...changes.production_filters,
  };
  return {
    ...values,
    [namespace]: { ...shell, ...changes, ...(filters && { production_filters: filters }) },
  };
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
    result[key] = route.area === "assets" ? assetsDestination(route.context, route.filters) : path;
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
  let pending: Changes = {};
  let saving = false;
  let optimistic = initial.values;
  let snapshot = readSnapshot(initial.values);
  const listeners = new Set<() => void>();

  function readSnapshot(values: SelectionDocument["values"], error?: unknown) {
    return {
      destinations: readDestinations(values),
      productionFilters: object(object(values[namespace]).production_filters),
      error,
    };
  }

  function publish(values: SelectionDocument["values"], error?: unknown) {
    optimistic = values;
    snapshot = readSnapshot(values, error);
    for (const listener of listeners) listener();
  }

  async function write(changes: Changes) {
    const { data, response } = await client.PUT("/v1/me/selections", {
      params: { header: { "If-Match": confirmed.etag } },
      body: { values: applyChanges(confirmed.values, changes) },
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
          pending = mergeChanges(changes, pending);
          publish(applyChanges(confirmed.values, pending), error);
          return;
        }
        publish(applyChanges(confirmed.values, pending));
      }
    } finally {
      saving = false;
    }
  }

  function remember(changes: Changes) {
    pending = mergeChanges(pending, changes);
    publish(applyChanges(optimistic, changes), snapshot.error);
    void flush();
  }

  return {
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    snapshot: () => snapshot,
    remember(key: Destination, path: string) {
      if (snapshot.destinations[key] === path) return;
      remember({ [key]: path });
    },
    rememberProductionFilters(path: string, filters: ProductionFilters) {
      remember({ production_filters: { [path]: readProductionFilters(filters) } });
    },
    retry: flush,
  };
}

export type SelectionStore = ReturnType<typeof createSelections>;
