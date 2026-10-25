import type { Approval, Decision, EvaluationReport } from "../api";
import StepCard from "./StepCard";

export default function ApprovalStep({ report, approval, onDecide, loading }: {
  report: EvaluationReport;
  approval: Approval | null;
  onDecide: (decision: Decision) => void;
  loading: boolean;
}) {
  return (
    <StepCard id="step-approval" title="6. Your decision" subtitle="Nothing changes unless you approve.">
      <div className="flex flex-wrap items-center gap-4">
        <button onClick={() => onDecide("approve")} disabled={loading || !!approval || !report.eligible_for_approval}
          className="rounded-lg bg-emerald-600 px-4 py-2 text-white disabled:opacity-50">
          Approve
        </button>
        <button onClick={() => onDecide("reject")} disabled={loading || !!approval}
          className="rounded-lg bg-slate-400 px-4 py-2 text-white disabled:opacity-50">
          Reject
        </button>
        {!report.eligible_for_approval && (
          <span className="text-sm font-medium text-red-700">Approval blocked: a safety check failed</span>
        )}
      </div>

      {approval && (
        <div id="approval-result" className="mt-4 space-y-4">
          {approval.decision === "approve" ? (
            <div className="rounded-lg border-2 border-emerald-300 bg-emerald-50 p-6">
              <p className="text-2xl font-bold text-emerald-800">Detector v{approval.version_created} approved</p>
              <p className="mt-1 text-sm text-emerald-900">
                Version created: v{approval.version_created} · Active version: v{approval.active_version}
              </p>
            </div>
          ) : (
            <div className="rounded-lg border-2 border-slate-300 bg-slate-50 p-4">
              <p className="font-semibold">Rejected — detector stays at v{approval.active_version}</p>
            </div>
          )}

          {approval.rechallenge && (
            <div className={`rounded-lg border-2 p-4 ${approval.rechallenge.alert ? "border-emerald-300 bg-emerald-50" : "border-red-300 bg-red-50"}`}>
              <p className="font-semibold">
                A fresh test attack, not one Red used, was run against the active detector →{" "}
                {approval.rechallenge.alert ? "Caught ✓" : "Missed ✗"}
              </p>
              <p className="mt-1 text-xs text-slate-500">
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
