import type { BaselineResult } from "../api";
import StepCard from "./StepCard";

// Plain-English names for the three example cases the backend scores.
const CASES: Record<string, { label: string; isFraud: boolean; blurb: string }> = {
  fast_ring: { label: "Fast mule ring", isFraud: true, blurb: "Stolen money hops quickly through several accounts." },
  slow_chain: { label: "Slow mule chain", isFraud: true, blurb: "Same idea, but each hop waits hours before moving on." },
  salaried_relay: { label: "Normal customer", isFraud: false, blurb: "A salaried person moving their own paycheck around." },
};

function caseInfo(id: string) {
  const key = Object.keys(CASES).find((k) => id.includes(k));
  return key ? CASES[key] : { label: id, isFraud: true, blurb: "" };
}

export default function BaselineStep({ results, onRun, loading }: {
  results: BaselineResult[] | null;
  onRun: () => void;
  loading: boolean;
}) {
  return (
    <StepCard id="step-baseline" title="2. Test the current fraud rules" action={
      <button onClick={onRun} disabled={loading}
        className="rounded-lg bg-slate-900 px-4 py-2 text-white disabled:opacity-50">
        Run baseline
      </button>
    }>
      {results && (
        <div className="grid gap-4 md:grid-cols-3">
          {results.map((r) => {
            const info = caseInfo(r.scenario_id);
            const good = info.isFraud ? r.alert : !r.alert;
            const badge = info.isFraud ? (r.alert ? "Caught" : "Missed") : r.alert ? "False alarm" : "Not flagged";
            return (
              <div key={r.scenario_id}
                className={`rounded-lg border-2 p-4 ${good ? "border-emerald-300 bg-emerald-50" : "border-red-300 bg-red-50"}`}>
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <h3 className="font-semibold">{info.label}</h3>
                  <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold ${good ? "bg-emerald-200 text-emerald-900" : "bg-red-200 text-red-900"}`}>
                    {good ? "✓" : "✗"} {badge}
                  </span>
                </div>
                <p className="text-sm text-slate-600">{info.blurb}</p>
                <p className="mt-2 text-xs text-slate-500">
                  Rules triggered: {r.triggered_rule_ids.length ? r.triggered_rule_ids.join(", ") : "none"}
                </p>
              </div>
            );
          })}
        </div>
      )}
    </StepCard>
  );
}
