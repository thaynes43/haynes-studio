import { useCallback } from "react";

import type { StudioClient } from "./api/client";
import { DeliveryPlayer } from "./delivery-player";
import { loadDelivery } from "./production-review-data";
import type { RunView } from "./run-data";
import { Empty, Problem } from "./shell-ui";
import { useRequest } from "./use-request";

export function RunDelivery({ api, run }: { api: StudioClient; run: RunView }) {
  const { id, delivery_id } = run;
  const load = useCallback((signal: AbortSignal) => loadDelivery(api, { id, delivery_id }, signal), [api, id, delivery_id]);
  const { result, retry } = useRequest(load);
  if (result.status === "loading") return <p role="status" className="muted">Loading delivery…</p>;
  if (result.status === "failure") return <Problem error={result.error} retry={retry} />;
  if (result.data.store.adapter === "legacy_wan_ledger") {
    return <Empty>Playback is unavailable for this imported delivery.</Empty>;
  }
  return <DeliveryPlayer key={result.data.id} delivery={result.data} allowMaster={false} />;
}
