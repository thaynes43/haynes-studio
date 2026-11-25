import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, type StudioClient } from "./api/client";
import type { Approval, ApprovalReview, ReleaseChecks } from "./approval-review-contract";
import {
  freshSignIn, loadApprovalReview, readObject, releaseDescription, type Delivery, type Run,
} from "./production-review-data";
import { Problem } from "./shell-ui";
import { useRequest } from "./use-request";

const refusals: Record<string, string> = {
  "approval.approver_not_configured": "No go-live approvers are configured.",
  "approval.subject_not_permitted": "Your account does not have go-live approval access.",
  "approval.group_not_permitted": "Studio group access grants sign-in only.",
  "approval.approver_not_permitted": "Go-live decisions require a signed-in approver.",
  "approval.worker_not_permitted": "Worker credentials cannot approve go-live.",
  "approval.sign_in_again": "Sign in again to make a go-live decision.",
  "approval.legacy_run": "Imported runs cannot be approved for go-live.",
  "approval.run_unfinished": "Go-live requires a successful, finished run.",
  "approval.delivery_unverified": "The delivery could not be verified.",
  "approval.delivery_mismatch": "The delivery does not match this run’s recorded master.",
  "approval.not_exact_run": "The reviewed master does not match the delivered master.",
  "approval.provenance_missing": "The run is missing required provenance.",
  "approval.licence_missing": "An engine or model file is missing from the licence register.",
  "approval.ai_label_missing": "Go-live requires the AI-generated label and synthetic-content setting.",
  "approval.licence_register_unavailable": "The model licence register is unavailable.",
  "approval.already_active": "This run already has an active approval.",
  "approval.already_withdrawn": "This approval has already been withdrawn.",
  "approval.review_mismatch": "The approval review does not match this run and master.",
  "approval.review_unavailable": "Go-live review is unavailable.",
};

export function approvalRefusal(code: unknown) {
  return typeof code === "string" && Object.hasOwn(refusals, code) ? refusals[code] : undefined;
}

function ReleaseEvidence({ checks }: { checks: ReleaseChecks }) {
  const items = [
    ["Delivery verification", readObject(checks.delivery).result],
    ["Model licences", readObject(checks.licences).result],
    ["AI disclosure", readObject(checks.ai_label).result],
  ] as const;
  const description = releaseDescription(checks);
  const licences = readObject(checks.licences).rows;
  return <>
    <h4>Release checks</h4>
    <ul className="review-results">
      {items.map(([label, result]) => <li key={label}>
        {label} <strong>{result === "pass" ? "Passed" : result === "fail" ? "Failed" : "Unavailable"}</strong>
      </li>)}
    </ul>
    {Array.isArray(licences) && licences.length > 0 && <details>
      <summary>Licence details</summary>
      <ul className="review-results">
        {licences.map((item: unknown, index) => {
          const row = readObject(item);
          const licence = readObject(row.licence);
          return <li key={index}>
            <div>
              {[row.engine_key, row.file, licence.name, row.state]
                .filter((value): value is string => typeof value === "string").join(" · ")}
              {typeof licence.commercial_use === "string" && <p className="muted">
                Commercial use {licence.commercial_use}
                {licence.attribution_required === true && " · Attribution required"}
              </p>}
              {typeof licence.note === "string" && <p className="muted">{licence.note}</p>}
            </div>
          </li>;
        })}
      </ul>
    </details>}
    {description && <>
      <h4>Release description</h4>
      <p className="review-description">{description}</p>
    </>}
    {readObject(checks.ai_label).platform_setting === true &&
      <p className="review-badges"><span>AI-generated</span></p>}
  </>;
}

export function ReviewTime({ value }: { value: string }) {
  const date = new Date(value);
  return Number.isFinite(date.getTime())
    ? <time dateTime={value}>{date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}</time>
    : null;
}

type ApprovalHistoryItem = ApprovalReview["approvals"][number];

function History({ approvals }: { approvals: ApprovalHistoryItem[] }) {
  if (!approvals.length) return null;
  return <>
    <h4>Approval history</h4>
    <ul className="review-history">
      {approvals.map((approval) => {
        const withdrawnAt = approval.derived.withdrawal?.withdrawn_at;
        return <li key={approval.id}>
          <p><strong>Approved</strong>{approval.approver_display_name && ` by ${approval.approver_display_name}`}
            {" · "}<ReviewTime value={approval.approved_at} /></p>
          {approval.derived.state === "withdrawn" && <p><strong>Withdrawn</strong>
            {typeof withdrawnAt === "string" && <>{" · "}<ReviewTime value={withdrawnAt} /></>}</p>}
        </li>;
      })}
    </ul>
  </>;
}

export function GoLive({
  api, run, delivery, path, onDecision,
}: {
  api: StudioClient; run: Run; delivery?: Delivery; path: string; onDecision: (record: Approval) => void;
}) {
  const load = useCallback((signal: AbortSignal) => loadApprovalReview(api, run, delivery, signal),
    [api, run, delivery]);
  const { result, retry } = useRequest(load);
  const [confirmed, setConfirmed] = useState(false);
  const [working, setWorking] = useState(false);
  const [failure, setFailure] = useState<unknown>();
  const [notice, setNotice] = useState("");
  const request = useRef<AbortController | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => () => request.current?.abort(), []);

  const signInPath = freshSignIn(path);

  async function decide(review: ApprovalReview, approval?: ApprovalHistoryItem) {
    const master = approval?.master_sha256 ?? review.master_sha256;
    if (request.current || failure || !master) return;
    const operation = new AbortController();
    request.current = operation;
    setWorking(true);
    setNotice("");
    try {
      const { data } = approval
        ? await api.POST("/v1/go-live-approvals/{id}/withdraw", {
          signal: operation.signal, params: { path: { id: approval.id } },
        })
        : await api.POST("/v1/runs/{id}/go-live-approvals", {
          signal: operation.signal, params: { path: { id: run.id } },
          body: { master_sha256: master, platform_setting: true },
        });
      if (operation.signal.aborted) return;
      if (!data || data.run_id !== run.id || data.run_snapshot_sha256 !== run.snapshot.sha256 ||
          data.delivery_id !== run.delivery_id || data.master_sha256 !== master ||
          (approval
            ? data.id !== approval.id || data.derived?.state !== "withdrawn"
            : data.derived?.state !== "active")) {
        throw new ApiError(422, "approval.review_mismatch");
      }
      onDecision(data);
      setNotice(approval ? "Go-live approval withdrawn." : "Go-live approval recorded." +
        ("package_evidence_older" in data && data.package_evidence_older
          ? " The package contains older release evidence." : ""));
      setConfirmed(false);
      heading.current?.focus();
      retry();
    } catch (error) {
      if (operation.signal.aborted) return;
      setFailure(error);
      if (error instanceof ApiError && error.code === "approval.sign_in_again") {
        window.location.assign(signInPath);
      }
    } finally {
      request.current = null;
      if (!operation.signal.aborted) setWorking(false);
    }
  }

  return <section className="review-go-live" aria-labelledby="go-live-heading">
    <h3 id="go-live-heading" ref={heading} tabIndex={-1}>Go-live</h3>
    <p className="muted">Publishing is done by hand outside Studio.</p>
    {notice && <p role="status">{notice}</p>}
    {result.status === "loading" && <p role="status" className="muted">Loading go-live review…</p>}
    {result.status === "failure" && (() => {
      const error = result.error;
      const code = error instanceof ApiError ? error.code : undefined;
      const retryable = !(error instanceof ApiError) || error.status === 0 || error.status >= 500;
      return <>
        <Problem error={error} message={approvalRefusal(code)} retry={retryable ? retry : undefined} />
        {code === "approval.sign_in_again" && <a className="pill" href={signInPath}>Sign in again</a>}
      </>;
    })()}
    {result.status === "success" && (() => {
      const review = result.data;
      const active = review.approvals.find((record) => record.derived.state === "active");
      const decision = active ? review.withdraw : review.approve;
      const code = decision.allowed ? undefined : decision.code;
      const failureCode = failure instanceof ApiError ? failure.code : undefined;
      const canApprove = !active && review.approve.allowed && review.master_sha256;
      const canWithdraw = active && review.withdraw.allowed;
      return <>
        {review.release_checks && <ReleaseEvidence checks={review.release_checks} />}
        <History approvals={review.approvals} />
        {failure != null ? <>
          <Problem error={failure} message={approvalRefusal(failureCode)} />
          {failureCode === "approval.sign_in_again"
            ? <a className="pill" href={signInPath}>Sign in again</a>
            : <button type="button" className="pill" onClick={() => {
                setFailure(undefined);
                setConfirmed(false);
                heading.current?.focus();
                retry();
              }}>Refresh go-live status</button>}
        </>
          : !decision.allowed && <>
              <p className="muted">{approvalRefusal(code) ?? "Go-live decision unavailable."}</p>
              {code === "approval.sign_in_again" &&
                <a className="pill" href={signInPath}>Sign in again</a>}
            </>}
        {failure == null && canApprove && <>
          <dl className="review-master"><dt>Run {run.number} master SHA-256</dt><dd><code>{review.master_sha256}</code></dd></dl>
          <label className="review-confirm">
            <input type="checkbox" checked={confirmed} disabled={working}
              onChange={(event) => setConfirmed(event.target.checked)} />
            Confirm the AI-generated platform setting
          </label>
          <button type="button" className="pill primary" disabled={!confirmed || working}
            onClick={() => { if (confirmed) void decide(review); }}>Approve for go-live</button>
        </>}
        {failure == null && canWithdraw && <button type="button" className="pill" disabled={working}
          onClick={() => { void decide(review, active); }}>Withdraw approval</button>}
      </>;
    })()}
  </section>;
}
