import type { components } from "./api/schema";
import { mediaUrl, readObject } from "./production-review-data";
import type { Board } from "./route-data";
import { treePath } from "./routes";
import type { StoryboardScope } from "./storyboard-data";

export type AssetVersion = components["schemas"]["AssetVersion"];
export type PhotoJob = components["schemas"]["JobStatus"];
export type PhotoBoardScope = StoryboardScope & { board: string };
export type PhotoInputs = Pick<Board["photo"], "prompt" | "input_asset_version_ids">;
export type PhotoEdit = { base: PhotoInputs; values: PhotoInputs };

export function photoInputs({ photo }: Board): PhotoInputs {
  return { prompt: photo.prompt, input_asset_version_ids: photo.input_asset_version_ids };
}

function samePins(a: string[], b: string[]) {
  return a.length === b.length && a.every((id, index) => id === b[index]);
}

function samePrompt(a: string | null, b: string | null) {
  return a?.normalize("NFC") === b?.normalize("NFC");
}

export function samePhotoInputs(a: PhotoInputs, b: PhotoInputs) {
  return samePrompt(a.prompt, b.prompt) && samePins(a.input_asset_version_ids, b.input_asset_version_ids);
}

// Rebase only the fields the person edited. A concurrent edit to the same
// field needs a choice before the composer can save it.
export function rebasePhotoEdit(edit: PhotoEdit | undefined, saved: PhotoInputs) {
  if (!edit) return { values: saved, dirty: false, conflict: false };
  const { base, values } = edit;
  const promptEdited = !samePrompt(base.prompt, values.prompt);
  const pinsEdited = !samePins(base.input_asset_version_ids, values.input_asset_version_ids);
  const combined = {
    prompt: promptEdited ? values.prompt : saved.prompt,
    input_asset_version_ids: pinsEdited ? values.input_asset_version_ids : saved.input_asset_version_ids,
  };
  const conflict =
    (promptEdited && !samePrompt(base.prompt, saved.prompt) && !samePrompt(values.prompt, saved.prompt)) ||
    (pinsEdited && !samePins(base.input_asset_version_ids, saved.input_asset_version_ids) &&
      !samePins(values.input_asset_version_ids, saved.input_asset_version_ids));
  return { values: combined, dirty: !samePhotoInputs(combined, saved), conflict };
}

export function photoEditAfterSave(sent: PhotoEdit | undefined, later: PhotoEdit | undefined, saved: PhotoInputs) {
  if (!later || later === sent) return;
  // The late edit may come from a render before a revision retry. Compare
  // against the inputs that render showed before applying the new edit.
  const seen = rebasePhotoEdit(sent, later.base).values;
  const remaining = rebasePhotoEdit({ base: seen, values: later.values }, saved);
  if (remaining.dirty) return { base: saved, values: remaining.values };
}

export function addPhotoPin(inputs: PhotoInputs, id: string): PhotoInputs {
  const pins = inputs.input_asset_version_ids;
  return pins.includes(id) ? inputs : { ...inputs, input_asset_version_ids: [...pins, id] };
}

export const photoJobActive = ({ status }: PhotoJob) => status === "queued" || status === "running";

export function photoResultCurrent(job: PhotoJob, board: Board, unsaved: boolean) {
  return job.status === "succeeded" && job.result_is_current === true &&
    Boolean(job.result_version_id) && job.result_version_id === board.photo.current_version_id &&
    board.derived?.photo_state === "current" && !unsaved;
}

export function isVersionId(value: unknown): value is string {
  return typeof value === "string" && /^asv_[0-7][0-9A-HJKMNP-TV-Z]{25}$/.test(value);
}

export function selectedPhotoUrl(version?: AssetVersion) {
  if (!version || version.recorded_without_media ||
      !["image/png", "image/jpeg", "image/webp"].some((type) => type === version.content?.media_type)) return;
  return mediaUrl(version.content?.sha256);
}

export function photoPreviewUrl(version: AssetVersion) {
  const url = selectedPhotoUrl(version);
  if (url && isVersionId(version.id)) return `/v1/asset-versions/${version.id}${url.slice(3)}`;
}

export function boardPhotoVersions(versions: AssetVersion[], scope: PhotoBoardScope) {
  return versions.filter((version) => version.kind === "photo" && version.state === "board" &&
    version.scope.production_id === scope.production && version.scope.story_id === scope.story &&
    version.scope.board_id === scope.board
  ).sort((a, b) => Date.parse(b.provenance.created_at) - Date.parse(a.provenance.created_at) ||
    b.number - a.number || b.id.localeCompare(a.id));
}

export function eligiblePhotoAsset(asset: AssetVersion, scope: PhotoBoardScope) {
  return isVersionId(asset.id) && asset.state === "promoted" && Boolean(selectedPhotoUrl(asset)) &&
    ["cast", "costume", "prop", "set", "photo"].includes(asset.kind) &&
    (asset.scope.production_id === null || asset.scope.production_id === scope.production) &&
    (asset.scope.story_id === null || asset.scope.story_id === undefined || asset.scope.story_id === scope.story) &&
    !asset.scope.board_id;
}

export function photoAssetReturn(scope: PhotoBoardScope, versionId: string) {
  return { to: treePath("board", scope, "photo"), state: { photoAssetVersionId: versionId } };
}

export function returnedPhotoAsset(state: unknown, path: string, scope: PhotoBoardScope) {
  if (path !== treePath("board", scope, "photo")) return;
  const id = readObject(state).photoAssetVersionId;
  return isVersionId(id) ? id : undefined;
}
