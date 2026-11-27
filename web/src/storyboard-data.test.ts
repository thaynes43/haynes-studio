import { describe, expect, it } from "vitest";

import { stalePhotoLabel } from "./storyboard-data";

describe("stalePhotoLabel", () => {
  it("labels any photo the API reports as stale", () => {
    expect(stalePhotoLabel("stale")).toBe("Reference photo stale");
  });

  it.each(["absent", "generating", "current", undefined] as const)("shows no stale label for %s", (state) => {
    expect(stalePhotoLabel(state)).toBeUndefined();
  });
});
