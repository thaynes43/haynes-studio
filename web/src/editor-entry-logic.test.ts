import { describe, expect, it } from "vitest";

import { ApiError } from "./api/client";
import { checkName, isNameTaken, isRevisionConflict, nameIssueFromApi } from "./editor-entry-logic";

describe("checking a name or title", () => {
  it("trims the submitted value and preserves its casing", () => {
    expect(checkName("  Early Shift  ")).toEqual({ name: "Early Shift" });
  });

  it("requires a name and counts Unicode code points up to the API limit", () => {
    const name = "🎬".repeat(80);
    expect(checkName(" \t ")).toEqual({ issue: "required" });
    expect(checkName(name)).toEqual({ name });
    expect(checkName(`${name}a`)).toEqual({ issue: "tooLong" });
  });

  it("matches differently cased and canonically equivalent names", () => {
    expect(isNameTaken("Cafe\u0301", ["  CAFÉ "])).toBe(true);
    expect(isNameTaken("Early Shift", ["Late Shift"])).toBe(false);
  });
});

it("distinguishes field errors from other API errors", () => {
  expect(nameIssueFromApi(new ApiError(422, "ref.duplicate"))).toBe("duplicate");
  expect(nameIssueFromApi(new ApiError(422, "schema.invalid"))).toBe("rejected");
  expect(nameIssueFromApi(new ApiError(403, "auth.csrf"))).toBeUndefined();
});

it("reloads only for the revision conflict code and status", () => {
  expect(isRevisionConflict(new ApiError(409, "conflict.revision"))).toBe(true);
  expect(isRevisionConflict(new ApiError(409, "ref.duplicate"))).toBe(false);
  expect(isRevisionConflict(new ApiError(422, "schema.invalid"))).toBe(false);
});
