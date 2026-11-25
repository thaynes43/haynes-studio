import type { components } from "./api/schema";

export type Approval = components["schemas"]["ApprovalView"];
export type ReleaseChecks = Approval["release_checks"];
export type ApprovalReview = components["schemas"]["ApprovalReview"];
