import { useCallback } from "react";
import { Link } from "react-router";
import type { StudioClient } from "./api/client";
import type { components } from "./api/schema";
import { boardLabel, collectPages, loadBoard, type Board, type Story } from "./route-data";
import { mediaUrl } from "./production-review-data";
import { treePath, type Context } from "./routes";
import { Empty, Problem } from "./shell-ui";
import { useRequest } from "./use-request";

type AssetVersion = components["schemas"]["AssetVersion"];

async function loadBoardMedia(api: StudioClient, board: Board, signal: AbortSignal) {
  const versions = await collectPages<AssetVersion>((cursor) => api.GET("/v1/assets", {
    signal, params: { query: { board: board.id, cursor } },
  }).then(({ data }) => data));
  const photo = versions.find((asset) => asset.kind === "photo" && asset.id === board.photo.current_version_id);
  const voice = versions.find((asset) => asset.kind === "board_voice" && asset.id === board.voice.current_version_id);
  return {
    photo: mediaUrl(photo?.content?.sha256),
    voice: mediaUrl(voice?.voice?.track?.sha256 ?? voice?.content?.sha256),
  };
}

function BoardMedia({ api, board }: { api: StudioClient; board: Board }) {
  const load = useCallback((signal: AbortSignal) => loadBoardMedia(api, board, signal), [api, board]);
  const { result, retry } = useRequest(load);
  if (result.status === "failure") return <Problem error={result.error} retry={retry} />;
  if (result.status !== "success") return null;
  const { photo, voice } = result.data;
  return <>
    {photo && <img className="review-photo" src={photo} alt={`Reference photo for ${board.title}`} loading="lazy" />}
    {voice && <audio controls preload="none" src={voice} aria-label={`Voice for ${board.title}`} />}
  </>;
}

export function ReviewBoard({
  api, board, story, to,
}: { api: StudioClient; board: Board; story: Story; to?: string }) {
  const title = `${boardLabel(board)} · ${board.title}`;
  const speakers = new Map(story.cast.map(({ slot, name }) => [slot, name]));
  return <article className="review-card">
    <h3>{to ? <Link to={to}>{title}</Link> : title}</h3>
    <p className="review-badges">
      <span>{board.method.layer === "layered" ? "Layered" : "Whole-frame"}</span>
      <span>{board.method.motion === "s2v" ? "Speech-to-video" : "Image-to-video"}</span>
    </p>
    {board.lines.length > 0 && <ul className="review-script" aria-label="Script">
      {board.lines.map(({ id, speaker, text }) => <li key={id}>
        <strong>{speaker === "narrator" ? "Narrator" : speakers.get(speaker) ?? `Cast ${speaker.toUpperCase()}`}</strong>
        <p>{text}</p>
      </li>)}
    </ul>}
    {board.notes.length > 0 && <>
      <h4>Direction</h4>
      <ul className="review-script">{board.notes.map((note) => <li key={note.id}>{note.text}</li>)}</ul>
    </>}
    {Boolean(board.photo.current_version_id || board.voice.current_version_id) &&
      <BoardMedia api={api} board={board} />}
  </article>;
}

export function StoryBoards({
  api, story, context,
}: { api: StudioClient; story: Story; context: Context }) {
  const load = useCallback(async (signal: AbortSignal) => {
    const boards: Board[] = [];
    for (let index = 0; index < story.board_order.length; index += 2) {
      const pair = story.board_order.slice(index, index + 2);
      boards.push(...await Promise.all(pair.map((id) => loadBoard(api, story.id, id, signal))));
    }
    return boards;
  }, [api, story]);
  const { result, retry } = useRequest(load);
  return <section className="review-section" aria-labelledby="boards-heading">
    <h2 id="boards-heading">Draft boards</h2>
    {result.status === "loading" && <p role="status" className="muted">Loading boards…</p>}
    {result.status === "failure" && <Problem error={result.error} retry={retry} />}
    {result.status === "success" && (result.data.length
      ? <ol className="review-boards">{result.data.map((board) => <li key={board.id}>
          <ReviewBoard api={api} board={board} story={story}
            to={treePath("productions", { ...context, run: undefined, board: board.id })} />
        </li>)}</ol>
      : <Empty>No boards yet.</Empty>)}
  </section>;
}
