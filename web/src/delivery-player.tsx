import { useState } from "react";

import { mediaUrl, type Delivery } from "./production-review-data";
import { Empty } from "./shell-ui";
import "./delivery-player.css";

export function DeliveryPlayer({ delivery, allowMaster = true }: { delivery: Delivery; allowMaster?: boolean }) {
  const proxy = mediaUrl(delivery.proxy?.sha256);
  const master = allowMaster ? mediaUrl(delivery.master.sha256) : undefined;
  const [showMaster, setShowMaster] = useState(!proxy);
  const [failedSource, setFailedSource] = useState<string>();
  const source = showMaster ? master : proxy;
  if (!source) return <Empty>Playback is unavailable for this delivery.</Empty>;
  return <>
    <video key={source} className="review-video" src={source} controls playsInline preload="metadata"
      aria-label={showMaster ? "Master video" : "Phone proxy"}
      onLoadedMetadata={() => setFailedSource(undefined)}
      onError={() => setFailedSource(source)} />
    {failedSource === source && <p role="alert">This video could not be played.</p>}
    {proxy && master && <div className="actions review-playback" role="group" aria-label="Playback quality">
      <button className="pill" type="button" aria-pressed={!showMaster} onClick={() => setShowMaster(false)}>Phone proxy</button>
      <button className="pill" type="button" aria-pressed={showMaster} onClick={() => setShowMaster(true)}>Master</button>
    </div>}
  </>;
}
