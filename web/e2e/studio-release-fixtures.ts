import { createHash } from "node:crypto";
import type { Route } from "@playwright/test";
import type { components } from "../src/api/schema";
import type { ApprovalReview } from "../src/approval-review-contract";

type Schemas = components["schemas"];
type Package = Schemas["ReleasePackage"];
type Publication = Schemas["PublicationSummary"];

export function releaseFixtures(draft: Schemas["Story"], frozen: Schemas["RunSnapshot"]) {
  const pin = frozen.format_version!;
  const targets = pin.recipe.targets.filter((target) => target.platform === "youtube-shorts") as Schemas["ReleaseTarget"][];
  const packages = new Map<string, { package: Package; sha256: string; bytes: number }>();
  const publications = new Map<string, Publication>();
  const refuse = (route: Route, http_status: number, code: string, message: string) => route.fulfill({
    status: http_status, json: { error: {
      code, status: http_status === 403 ? "forbidden" : http_status === 404 ? "not_found" :
        http_status === 409 ? "conflict" : "invalid",
      http_status, path: "", message, request_id: "fixture-release",
    } } satisfies Schemas["ErrorEnvelope"],
  });

  function view(item: NonNullable<ReturnType<typeof packages.get>>, review: ApprovalReview, refusal?: string) {
    const active = review.approvals.find((approval) =>
      approval.derived.state === "active" && approval.master_sha256 === item.package.master.sha256);
    const publication = publications.get(item.sha256) ?? null;
    const code = refusal ?? (publication ? "release.already_published" : !active ? "release.approval_required" : null);
    return {
      ...item, state: active ? "releasable" : "held",
      held_reason: active ? null : "release.approval_required",
      evidence_status: "current",
      approval_id: active?.id ?? null, publication,
      record_publication: code ? { allowed: false, code } : { allowed: true },
    } satisfies Schemas["ReleasePackageView"];
  }

  function handle(route: Route, run: Schemas["RunView"], delivery: Pick<Schemas["Delivery"], "master"> | undefined,
                  review: ApprovalReview, name: string, subject: string, refusal?: string) {
    const request = route.request();
    if (request.method() === "GET") {
      const items = [...packages.values()].filter((item) => item.package.run_id === run.id)
        .map((item) => view(item, review, refusal));
      return route.fulfill({ json: { targets, items } satisfies Schemas["ReleasePackageList"] });
    }
    if (new URL(request.url()).pathname.endsWith("/publications")) {
      if (refusal) return refuse(route, 403, refusal, "A go-live approver must record publication");
      if (!request.headers()["idempotency-key"]) {
        return refuse(route, 422, "schema.invalid", "Supply an Idempotency-Key");
      }
      const body = request.postDataJSON() as Schemas["PublicationWrite"];
      const item = [...packages.values()].find((saved) => saved.sha256 === body.package_sha256 && saved.package.run_id === run.id);
      if (!item) return refuse(route, 404, "not_found", "Package unavailable");
      const state = view(item, review, refusal);
      if (!state.record_publication.allowed || !state.approval_id) {
        return refuse(route, 409, state.record_publication.allowed ? "release.approval_required" :
          state.record_publication.code, "Publication cannot be recorded");
      }
      const record = {
        schema: "studio.publication/v1", id: "pub_01M79V9FC00000000000000001",
        package_sha256: item.sha256, approval_id: state.approval_id,
        run_id: run.id, master_sha256: item.package.master.sha256,
        location: body.location, recorded_by_display_name: name, recorded_at: "2026-11-04T15:00:00Z",
        published_at: body.published_at ?? null,
      } satisfies Publication;
      publications.set(item.sha256, record);
      draft.published = true;
      return route.fulfill({ status: 201, json: {
        ...record, recorded_by: { kind: "human", iss: "https://identity.example.invalid", sub: subject },
      } satisfies Schemas["Publication"] });
    }
    const { target_id } = request.postDataJSON() as Schemas["ReleasePackageWrite"];
    const target = targets.find(({ id }) => id === target_id);
    if (!target) return refuse(route, 422, "release.target_unknown", "Choose a frozen target");
    if (target.rules.max_length_ms === null) {
      return refuse(route, 422, "release.maximum_unset", "The frozen target must declare a platform maximum");
    }
    const key = `${run.id}/${target_id}`;
    const saved = packages.get(key);
    if (saved) return route.fulfill({ json: { sha256: saved.sha256, bytes: saved.bytes } });
    if (!delivery || !review.release_checks || !run.delivery_id) {
      return refuse(route, 422, "approval.delivery_unverified", "Verified delivery required");
    }
    const { sha256, bytes, media_type, frames, fps } = delivery.master;
    const release_checks = review.release_checks as Package["release_checks"];
    const description = (release_checks.ai_label as { description: string }).description;
    const value: Package = {
      schema: "studio.release-package/v1", run_id: run.id, run_snapshot_sha256: run.snapshot.sha256,
      delivery_id: run.delivery_id, format_version_id: pin.id, format_sha256: pin.sha256,
      master: { sha256, bytes, media_type }, target, description, release_checks,
      checklist: ["Turn on the synthetic-content setting.", "Use the 2:3 master.",
        `Keep the video within the target maximum of ${target.rules.max_length_ms} ms.`],
      target_checks: { length: { result: "pass", frames, fps, max_length_ms: target.rules.max_length_ms },
        aspect: { result: "pass", master_aspect: "2:3", target_aspect: null } },
    };
    const data = JSON.stringify(value);
    const item = { package: value, sha256: createHash("sha256").update(data).digest("hex"), bytes: Buffer.byteLength(data) };
    packages.set(key, item);
    return route.fulfill({ status: 201, json: {
      sha256: item.sha256, bytes: item.bytes,
    } satisfies Schemas["ReleasePackageReceipt"] });
  }

  return { handle };
}
