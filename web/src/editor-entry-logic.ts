import { ApiError } from "./api/client";

export const maxNameLength = 80;

function nameKey(value: string) {
  return value.trim().normalize("NFC").toLowerCase();
}

export function checkName(value: string) {
  const name = value.trim();
  if (!name) return { issue: "required" } as const;
  if (Array.from(name).length > maxNameLength) return { issue: "tooLong" } as const;
  return { name } as const;
}

export function isNameTaken(name: string, names: string[]) {
  const key = nameKey(name);
  return names.some((existing) => nameKey(existing) === key);
}

export function nameIssueFromApi(error: unknown) {
  if (!(error instanceof ApiError)) return undefined;
  if (error.code === "ref.duplicate") return "duplicate";
  if (error.code === "schema.invalid" || error.code === "schema.unknown_field") return "rejected";
  return undefined;
}

export function isRevisionConflict(error: unknown) {
  return error instanceof ApiError && error.status === 409 && error.code === "conflict.revision";
}
