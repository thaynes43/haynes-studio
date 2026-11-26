import { describe, expect, it } from "vitest";

import { ApiError, createStudioApi } from "./api/client";
import { formatEditsConflict, formatFailure, formatPatch, formatStatus, nextCastSlot, patchStoryFormat, type StoryFormat } from "./story-format-data";

const empty: StoryFormat = { format_version_id: null, cast: [], narrator_voice_version_id: null };
const cast = [{ slot: "a", name: "Ada", voice_version_id: "asv_01M79V9FC00000000000000020" }];
const pinned: StoryFormat = { ...empty, format_version_id: "fmv_01M79V9FC00000000000000010", cast };

describe("story format settings", () => {
  it("labels empty, pinned and saving states from the saved draft", () => {
    expect(formatStatus(empty, false)).toBe("No format pinned");
    expect(formatStatus(pinned, false)).toBe("Format pinned");
    expect(formatStatus(empty, true)).toBe("Saving format…");
    expect(formatStatus(pinned, true)).toBe("Saving format…");
  });

  it("shows the API refusal and distinguishes a lost connection", () => {
    expect(formatFailure(new ApiError(422, "format.frame_mismatch", "test-format", {
      message: "That format’s frame size does not match the story’s media kind",
    }))).toBe("That format’s frame size does not match the story’s media kind");
    expect(formatFailure(new ApiError(0))).toBe("Studio could not be reached. Check your connection.");
  });

  it("submits only changed settings and retains the existing cast slots", () => {
    const narrator_voice_version_id = "asv_01M79V9FC00000000000000021";
    expect(formatPatch(pinned, { ...pinned, cast: structuredClone(cast) })).toEqual({});
    expect(formatPatch(pinned, { ...pinned, narrator_voice_version_id })).toEqual({ narrator_voice_version_id });
    expect(formatPatch(empty, { ...pinned, narrator_voice_version_id })).toEqual({ ...pinned, narrator_voice_version_id });
    expect(nextCastSlot(cast)).toBe("b");
    expect(nextCastSlot([{ ...cast[0], slot: "b" }])).toBe("a");
  });

  it("flags overlapping changes and keeps independent edits or matching saves", () => {
    const editing = { ...pinned, cast: [{ ...cast[0], name: "Lucia" }] };
    expect(formatEditsConflict(pinned, editing, { ...pinned, cast: [] })).toBe(true);
    expect(formatEditsConflict(pinned, editing, { ...pinned, format_version_id: null })).toBe(false);
    expect(formatEditsConflict(pinned, editing, editing)).toBe(false);
  });

  const id = "sty_01M79V9FC00000000000000001";
  async function saveWithReply(body: { id: string; revision?: number }, etag?: string) {
    const { signal } = new AbortController();
    const api = createStudioApi("https://studio.example.invalid", signal, () => {}, async (input) => {
      const request = input as Request;
      if (new URL(request.url).pathname === "/v1/me") {
        return Response.json({ principal: { kind: "human", iss: "issuer", sub: "person" }, csrf_token: "csrf" });
      }
      return Response.json(body, { headers: etag === undefined ? undefined : { etag } });
    });
    await api.connect();
    return patchStoryFormat(api.client, id, 3, { format_version_id: pinned.format_version_id }, signal);
  }

  it.each([
    { name: "a matching strong ETag", etag: '"4"' },
    { name: "a matching weak ETag", etag: 'W/"4"' },
    { name: "no ETag", etag: undefined },
  ])("accepts the next revision with $name", async ({ etag }) => {
    await expect(saveWithReply({ id, revision: 4 }, etag)).resolves.toBe(4);
  });

  it.each([
    { name: "another story", body: { id: "sty_01M79V9FC00000000000000002", revision: 4 }, etag: '"4"' },
    { name: "the sent revision", body: { id, revision: 3 }, etag: '"3"' },
    { name: "a missing revision", body: { id }, etag: '"4"' },
    { name: "revision 6 in the body and 4 in the ETag", body: { id, revision: 6 }, etag: '"4"' },
    { name: "a different revision in the ETag", body: { id, revision: 4 }, etag: '"6"' },
    { name: "a matching ETag that skips the next revision", body: { id, revision: 6 }, etag: '"6"' },
  ])("refuses a successful PATCH response with $name", async ({ body, etag }) => {
    await expect(saveWithReply(body, etag)).rejects.toMatchObject({ status: 502 });
  });
});
