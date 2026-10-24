import type { EvaluationReport } from "../api";
import StepCard from "./StepCard";

const GATES: Record<string, string> = {
  schema_valid: "The fix is a well-formed rule",
  fpr_budget: "Doesn't flag too many new normal customers",
  regression_no_loss: "Still catches every attack the old rules caught",
  regression_benign: "Doesn't flag more lookalike normal customers",
  holdout_recall_gain: "Catches more unseen attacks than before",
};

function fraction(n: number, d: number) {
  return `${n} / ${d} (${d ? Math.round((n / d) * 100) : 0}%)`;
}

// Step 5 in the center column: just the button. The results pin to the right column as <Scorecard>.
export default function ScorecardStep({ onEvaluate, loading, evaluated }: {
  onEvaluate: () => void;
  loading: boolean;
  evaluated: boolean;
}) {
  return (
    <StepCard id="step-evaluate" title="5. Test the fix on unseen data" action={
      <button onClick={onEvaluate} disabled={loading}
        className="shrink-0 rounded-lg bg-slate-900 px-4 py-2 text-white disabled:opacity-50">
        Evaluate on unseen data
      </button>
    }>
      {evaluated && (
        <p className="text-sm text-slate-600">Results are in the scorecard. Approve or reject the fix there.</p>
      )}
    </StepCard>
  );
}

export function Scorecard({ report }: { report: EvaluationReport }) {
  const before = report.baseline_confusion.final_holdout;
  const after = report.candidate_confusion.final_holdout;
  return (
    <StepCard id="scorecard" title="Scorecard">
      <div className="space-y-4">
        {before && after && (
          <table className="w-full text-left text-sm">
            <thead className="border-b text-xs uppercase text-slate-500">
              <tr>
                <th className="py-2 pr-3"></th>
                <th className="py-2 pr-3">Current rules</th>
                <th className="py-2">With Blue&apos;s fix</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b">
                <td className="py-2 pr-3 font-medium">Attacks caught</td>
                <td className="py-2 pr-3">{fraction(before.tp, before.tp + before.fn)}</td>
                <td className={`py-2 ${after.tp > before.tp ? "font-semibold text-emerald-700" : ""}`}>
                  {fraction(after.tp, after.tp + after.fn)}
                </td>
              </tr>
              <tr className="border-b">
                <td className="py-2 pr-3 font-medium">Normal customers wrongly flagged</td>
                <td className="py-2 pr-3">{fraction(before.fp, before.fp + before.tn)}</td>
                <td className={`py-2 ${after.fp < before.fp ? "font-semibold text-emerald-700" : ""}`}>
                  {fraction(after.fp, after.fp + after.tn)}
                </td>
              </tr>
            </tbody>
          </table>
        )}

        <ul className="space-y-2">
          {report.gate_results.map((g) => (
            <li key={g.name} className="flex gap-2 text-sm">
              <span className={g.passed ? "text-emerald-600" : "text-red-600"}>{g.passed ? "✓" : "✗"}</span>
              <span>
                <span className="font-medium">{GATES[g.name] ?? g.name}</span>
                {g.detail && <span className="text-slate-500"> — {g.detail}</span>}
              </span>
            </li>
          ))}
        </ul>

        <p className="text-xs text-slate-500">
          All numbers are computed by deterministic code on data neither agent saw — not by an AI.
        </p>
      </div>
    </StepCard>
  );
}
