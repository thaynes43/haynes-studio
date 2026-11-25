import type { components } from "./api/schema";

export type Approval = components["schemas"]["ApprovalView"];
export type ReleaseChecks = Approval["release_checks"];
type Decision = { allowed: true } | { allowed: false; code: string };

export type ApprovalReview = {
  run_id: string;
  master_sha256: string | null;
  approve: Decision;
  withdraw: Decision;
  release_checks: ReleaseChecks | null;
  approvals: Approval[];
};

// Proposed read contract. The generated OpenAPI already defines the two writes.
export type ApprovalReviewPaths = {
  "/v1/runs/{id}/go-live-approvals": {
    get: {
      parameters: { path: { id: string } };
      responses: { 200: { content: { "application/json": ApprovalReview } } };
    };
  };
};
