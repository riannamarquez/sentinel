"use client";

import { useState } from "react";
import type { Approval, Decision, EvaluationReport } from "../api";
import { ShieldIcon } from "./ScorecardStep";
import StepCard, { BUTTON_PRIMARY, BUTTON_SECONDARY } from "./StepCard";

function pts(x: number) {
  const v = Number(x.toFixed(1));
  return `${v > 0 ? "+" : ""}${v} pts`;
}

export default function ApprovalStep({ report, approval, onDecide, loading }: {
  report: EvaluationReport | null;
  approval: Approval | null;
  onDecide: (decision: Decision) => void;
  loading: boolean;
}) {
  // Not sent anywhere: the backend has no field for analyst notes yet.
  const [note, setNote] = useState("");

  if (!report) {
    return (
      <StepCard id="step-approval" label="Human sign-off" title="Your decision"
        subtitle="No production rule changes unless you approve this proposal.">
        <p className="border-t border-line pt-5 text-[15px] text-muted">
          The decision opens once Blue&apos;s proposal has been scored on held-out data.
        </p>
      </StepCard>
    );
  }

  const before = report.baseline_confusion.final_holdout;
  const after = report.candidate_confusion.final_holdout;
  const rows = before && after ? [
    { label: "Catch-rate change", value: pts(((after.tp - before.tp) / report.attack_n) * 100), good: after.tp > before.tp, bad: false },
    { label: "False-positive change", value: pts(((after.fp - before.fp) / report.benign_n) * 100), good: after.fp < before.fp, bad: after.fp > before.fp },
    { label: "Attacks still missed", value: `${after.fn} / ${report.attack_n}`, good: false, bad: false },
  ] : [];

  return (
    <StepCard id="step-approval" label="Human sign-off" title="Your decision"
      subtitle="No production rule changes unless you approve this proposal.">
      <dl className="border-y border-line py-3">
        {rows.map((r) => (
          <div key={r.label} className="flex justify-between py-2.5 text-[15px]">
            <dt className="text-muted">{r.label}</dt>
            <dd className={`tabular-nums ${r.good ? "text-mint" : r.bad ? "text-coral" : "text-ink"}`}>{r.value}</dd>
          </div>
        ))}
      </dl>

      <label className="mt-6 block">
        <span className="flex justify-between text-[15px]">
          <span className="text-ink">Analyst note</span>
          <span className="text-[13px] text-muted">Optional — not saved yet</span>
        </span>
        <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={4} placeholder="Add context for the audit trail…"
          className="mt-2 w-full resize-y rounded-[2px] border border-line bg-page p-3 text-[15px] text-ink placeholder:text-muted/70 focus:border-lavender focus:outline-none" />
      </label>

      <div className="mt-6 space-y-3">
        <button onClick={() => onDecide("approve")} disabled={loading || !!approval || !report.eligible_for_approval}
          className={`${BUTTON_PRIMARY} w-full py-3.5`}>
          Approve rule <span aria-hidden="true">→</span>
        </button>
        <button onClick={() => onDecide("reject")} disabled={loading || !!approval} className={`${BUTTON_SECONDARY} w-full py-3.5`}>
          Reject proposal
        </button>
        {!report.eligible_for_approval && (
          <p className="text-[15px] text-coral">Approval blocked: a safety check failed</p>
        )}
      </div>

      <p className="mt-5 flex gap-2 text-[13px] leading-snug text-muted">
        <span className="mt-0.5 shrink-0">{ShieldIcon}</span>
        Approval records the timestamp, rule version and evaluation hash.
      </p>

      {approval && (
        <div id="approval-result" className="mt-6 scroll-mt-28 space-y-3 border-t border-line pt-6">
          {approval.decision === "approve" ? (
            <div className="rounded-[2px] border-l-2 border-mint bg-green-panel p-5">
              <p className="label-caps text-mint">Approved</p>
              <p className="mt-1 text-[24px] text-ink">Detector v{approval.version_created} approved</p>
              <p className="mt-1 text-[15px] tabular-nums text-muted">
                Version created: v{approval.version_created} · Active version: v{approval.active_version}
              </p>
            </div>
          ) : (
            <div className="rounded-[2px] border-l-2 border-muted bg-card-raised p-5">
              <p className="label-caps text-muted">Rejected</p>
              <p className="mt-1 text-[20px] text-ink">Rejected — detector stays at v{approval.active_version}</p>
            </div>
          )}

          {!approval.rechallenge && (
            <div className="rounded-[2px] border border-line bg-card-raised p-4 text-[15px] text-muted">
              {approval.completion_pending
                ? "Running the rechallenge…"
                : "The rechallenge hasn't finished yet. Your decision is saved; check back in a moment."}
            </div>
          )}

          {approval.rechallenge && (
            <div className={`rounded-[2px] border-l-2 p-4 ${approval.rechallenge.alert ? "border-mint bg-green-panel" : "border-coral bg-red-panel"}`}>
              <p className="text-[15px] text-ink">
                A fresh test attack, not one Red used, was run against the active detector →{" "}
                <span className={approval.rechallenge.alert ? "text-mint" : "text-coral"}>
                  {approval.rechallenge.alert ? "Caught ✓" : "Missed ✗"}
                </span>
              </p>
              <p className="mt-1 text-[13px] text-muted">
                Rules triggered:{" "}
                {approval.rechallenge.triggered_rule_ids.length ? approval.rechallenge.triggered_rule_ids.join(", ") : "none"}
              </p>
            </div>
          )}
        </div>
      )}
    </StepCard>
  );
}
