import { eligiblePhotoAsset, isVersionId, type AssetVersion, type PhotoBoardScope } from "./photo-composer-model";
import { mediaUrl } from "./production-review-data";
import { assetScopes, defaultAssetScope, type AssetFilters, type AssetScope, type Context } from "./routes";

export function visibleAssetScope(context: Context, filters: AssetFilters) {
  return filters.scope ?? defaultAssetScope(context);
}

export function widenAssetScope(removed: Exclude<AssetScope, "library">) {
  return assetScopes[assetScopes.indexOf(removed) + 1];
}

export function assetTarget(context: Context, filters: AssetFilters): PhotoBoardScope | undefined {
  const { production, media, story } = context;
  const board = filters.target ?? context.board;
  if (production && media && story && board) return { production, media, story, board };
}

export function kindLabel(kind: string) {
  return kind.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

export function assetKinds(versions: AssetVersion[]) {
  return [...new Set(versions.filter(({ state }) => state !== "candidate").map(({ kind }) => kind))]
    .sort((a, b) => kindLabel(a).localeCompare(kindLabel(b)));
}

export function groupAssets(versions: AssetVersion[], filters: AssetFilters) {
  const search = filters.search?.trim().normalize("NFC").toLowerCase();
  const groups = new Map<string, AssetVersion[]>();
  for (const version of versions) {
    if (version.state === "candidate" || (filters.kind && filters.kind !== version.kind)) continue;
    const text = [version.name, kindLabel(version.kind), ...version.labels].join(" ").normalize("NFC").toLowerCase();
    if (search && !text.includes(search)) continue;
    const group = groups.get(version.asset_id);
    if (group) group.push(version);
    else groups.set(version.asset_id, [version]);
  }
  return [...groups.values()]
    .map((versions) => versions.sort((a, b) => b.number - a.number || b.id.localeCompare(a.id)))
    .sort(([a], [b]) => a.name.localeCompare(b.name) || a.asset_id.localeCompare(b.asset_id));
}

export function candidateJobId(version: AssetVersion) {
  const sourceKey = version.provenance.source_key ?? "";
  return /^asset-candidate:(job_[0-7][0-9A-HJKMNP-TV-Z]{25})$/.exec(sourceKey)?.[1];
}

export function assetPreview(version: AssetVersion, jobId?: string) {
  if (version.recorded_without_media || !isVersionId(version.id)) return;
  const content = version.content ?? version.voice?.track;
  if (!content) return;
  const hashPath = mediaUrl(content.sha256);
  if (!hashPath) return;
  const sourceJob = jobId ?? (version.scope.production_id === null ? candidateJobId(version) : undefined);
  const url = sourceJob && /^job_[0-7][0-9A-HJKMNP-TV-Z]{25}$/.test(sourceJob)
    ? `/v1/jobs/${sourceJob}${hashPath.slice(3)}`
    : version.state === "candidate" || version.kind === "photo" || version.kind === "board_voice"
      ? `/v1/asset-versions/${version.id}${hashPath.slice(3)}`
      : hashPath;
  return { url, type: content.media_type };
}

export function assetUseProblem(version: AssetVersion, target?: PhotoBoardScope, layered = false, declined = false) {
  if (version.recorded_without_media) return "Recorded without media";
  if (declined) return "Declined candidate";
  if (version.state === "candidate") return "Promote before use";
  if (!target) return;
  if (version.state !== "promoted") return "Board version";
  if (!version.content) return "No media";
  if (!eligiblePhotoAsset(version, target)) return "Unavailable for this board’s photo";
  if (layered) return "Layered photos use board cast and set";
}

export const assetOrigins: Record<AssetVersion["provenance"]["origin"], string> = {
  generated: "Generated",
  uploaded: "Agent upload",
  imported: "Imported",
  declared: "Declared",
  derived: "Derived",
};
