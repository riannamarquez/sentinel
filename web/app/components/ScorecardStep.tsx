import type { EvaluationReport, GateResult, MissReason } from "../api";
import StepCard, { BUTTON_PRIMARY, Chip } from "./StepCard";

const GATES: Record<string, string> = {
  schema_valid: "The fix is a well-formed rule",
  fpr_budget: "Doesn't flag too many new normal customers",
  regression_no_loss: "Still catches every attack the old rules caught",
  regression_benign: "Doesn't flag more lookalike normal customers",
  holdout_recall_gain: "Catches more unseen attacks than before",
};

export const ShieldIcon = (
  <svg aria-hidden="true" viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.4">
    <path d="M8 1.5 13 3.5v4c0 3.2-2.2 5.6-5 7-2.8-1.4-5-3.8-5-7v-4z" strokeLinejoin="round" />
  </svg>
);

export function percent(n: number, d: number) {
  if (!d) return "—";
  const x = (n / d) * 100;
  return `${x < 10 ? Number(x.toFixed(1)) : Math.round(x)}%`;
}

function cell(n: number, d: number) {
  return `${n} / ${d} · ${percent(n, d)}`;
}

function gate(report: EvaluationReport, name: string): GateResult | undefined {
  return report.gate_results.find((g) => g.name === name);
}

// One honest sentence pair from the gates: what was gained, and what it cost.
function GateSummary({ report }: { report: EvaluationReport }) {
  const failed = report.gate_results.filter((g) => !g.passed);
  if (failed.length) {
    return (
      <div className="rounded-[2px] border-l-2 border-coral bg-red-panel p-5 text-[15px]">
        <p className="text-coral">Not eligible for approval: {failed.length} safety check{failed.length === 1 ? "" : "s"} failed.</p>
        <ul className="mt-1.5 space-y-0.5 text-muted">
          {failed.map((g) => <li key={g.name}>{GATES[g.name] ?? g.name}{g.detail && ` — ${g.detail}`}</li>)}
        </ul>
      </div>
    );
  }
  const gain = gate(report, "holdout_recall_gain")?.numerator ?? 0;
  const newFp = gate(report, "fpr_budget")?.numerator ?? 0;
  const kept = gate(report, "regression_no_loss");
  const headline = gain > 0 && newFp <= 0
    ? "Material gain with no added customer friction."
    : gain > 0
      ? `${gain} more attacks caught, with ${newFp} more customers flagged — within the budget.`
      : "Passes every safety check.";
  return (
    <div className="flex gap-3 rounded-[2px] border-l-2 border-mint bg-green-panel p-5 text-[15px]">
      <span className="mt-0.5 text-mint">✓</span>
      <div>
        <p className="text-ink">{headline}</p>
        {kept && kept.denominator > 0 && (
          <p className="text-muted">
            All {kept.denominator} regression-set attacks the current rules caught are still caught.
          </p>
        )}
      </div>
    </div>
  );
}

// An honest limitation, not an error: amber, never red.
function StillMissed({ missed, total, breakdown }: { missed: number; total: number; breakdown?: MissReason[] }) {
  const rows = [...(breakdown ?? [])].sort((a, b) => b.count - a.count);
  return (
    <div className="border-t border-line pt-6">
      <p className="label-caps mb-1 text-amber">What the missed attacks did</p>
      <h3 className="text-[20px] text-ink">Still missed: <span className="tabular-nums">{missed} of {total}</span> attacks</h3>
      {missed > 0 && (
        <>
          {breakdown === undefined ? (
            <p className="mt-2 text-[15px] text-muted">Breakdown not available yet.</p>
          ) : (
            <ul className="mt-4 space-y-3">
              {rows.map((m) => (
                <li key={m.reason} className="text-[15px]">
                  <div className="mb-1.5 flex justify-between gap-2">
                    <span className="text-ink">{m.label}</span>
                    <span className="tabular-nums text-amber">{m.count}</span>
                  </div>
                  <div className="h-1.5 bg-amber-panel">
                    <div className="h-1.5 bg-amber" style={{ width: `${(m.count / missed) * 100}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-4 text-[15px] text-muted">Consider a follow-up rule for these patterns.</p>
        </>
      )}
    </div>
  );
}

export default function ScorecardStep({ report, onEvaluate, loading }: {
  report: EvaluationReport | null;
  onEvaluate: () => void;
  loading: boolean;
}) {
  if (!report) {
    return (
      <StepCard id="step-evaluate" label="Held-out evaluation" title="Test the fix on unseen data"
        subtitle="The fix is scored on attacks and customers neither AI has seen."
        action={<button onClick={onEvaluate} disabled={loading} className={BUTTON_PRIMARY}>Run evaluation</button>} />
    );
  }

  const before = report.baseline_confusion.final_holdout;
  const after = report.candidate_confusion.final_holdout;
  const passed = report.gate_results.filter((g) => g.passed).length;
  const net = after && before ? after.tp - before.tp : null;
  const ROW = "border-b border-line";
  return (
    <StepCard id="scorecard" label={`Held-out evaluation · ${report.attack_n} attacks / ${report.benign_n} customers`}
      title="Performance scorecard" action={<Chip tone="muted" icon={ShieldIcon}>Deterministic test</Chip>}>
      <div className="space-y-6 border-t border-line pt-4">
        {before && after && (
          <table className="w-full text-left text-[16px]">
            <thead className="label-caps text-muted">
              <tr className={ROW}>
                <th className="py-3 pr-3 font-normal">Measure</th>
                <th className="py-3 pr-3 font-normal">Current</th>
                <th className="py-3 font-normal">With proposal</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              <tr className={ROW}>
                <td className="py-4 pr-3 text-ink">Attacks caught</td>
                <td className="py-4 pr-3 text-ink">{cell(before.tp, before.tp + before.fn)}</td>
                <td className={`py-4 text-[18px] ${after.tp > before.tp ? "text-mint" : "text-ink"}`}>{cell(after.tp, after.tp + after.fn)}</td>
              </tr>
              <tr className={ROW}>
                <td className="py-4 pr-3 text-ink">False positives</td>
                <td className="py-4 pr-3 text-ink">{cell(before.fp, before.fp + before.tn)}</td>
                <td className={`py-4 text-[18px] ${after.fp < before.fp ? "text-mint" : after.fp > before.fp ? "text-coral" : "text-ink"}`}>
                  {cell(after.fp, after.fp + after.tn)}
                </td>
              </tr>
              <tr className={ROW}>
                <td className="py-4 pr-3 text-ink">Net new attacks caught</td>
                <td className="py-4 pr-3 text-muted">—</td>
                <td className={`py-4 text-[18px] ${net !== null && net > 0 ? "text-mint" : "text-ink"}`}>
                  {net === null ? "—" : `${net > 0 ? "+" : ""}${net}`}
                </td>
              </tr>
            </tbody>
          </table>
        )}

        <GateSummary report={report} />

        <details className="group text-[15px]">
          <summary className="cursor-pointer text-muted hover:text-ink">
            Safety checks: <span className="tabular-nums">{passed} of {report.gate_results.length}</span> passed
          </summary>
          <ul className="mt-3 space-y-1.5">
            {report.gate_results.map((g) => (
              <li key={g.name} className="flex gap-2">
                <span className={g.passed ? "text-mint" : "text-coral"}>{g.passed ? "✓" : "✗"}</span>
                <span className="text-ink">{GATES[g.name] ?? g.name}{g.detail && <span className="text-muted"> — {g.detail}</span>}</span>
              </li>
            ))}
          </ul>
        </details>

        {after && <StillMissed missed={report.attack_n - after.tp} total={report.attack_n} breakdown={report.missed_breakdown} />}

        <p className="text-[13px] text-muted">All numbers are computed by deterministic code on data neither agent saw — not by an AI.</p>
      </div>
    </StepCard>
  );
}
