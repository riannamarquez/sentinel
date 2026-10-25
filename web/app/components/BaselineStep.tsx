import type { BaselineResult } from "../api";
import StepCard, { BUTTON_PRIMARY, Chip } from "./StepCard";

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
    <StepCard id="step-baseline" label="Step 2 · Baseline" title="Test the current fraud rules"
      subtitle="Checks three known cases against today's fraud rules."
      action={!results && <button onClick={onRun} disabled={loading} className={BUTTON_PRIMARY}>Run baseline</button>}>
      {results && (
        <div className="grid gap-3 sm:grid-cols-3">
          {results.map((r) => {
            const info = caseInfo(r.scenario_id);
            const good = info.isFraud ? r.alert : !r.alert;
            const badge = info.isFraud ? (r.alert ? "Caught" : "Missed") : r.alert ? "False alarm" : "Not flagged";
            return (
              <div key={r.scenario_id} className={`rounded-[2px] border border-line border-l-2 p-4 ${
                good ? "border-l-mint bg-green-panel/60" : "border-l-coral bg-red-panel/70"}`}>
                <div className="mb-2"><Chip tone={good ? "mint" : "coral"}>{good ? "✓" : "✗"} {badge}</Chip></div>
                <h3 className="text-[17px] text-ink">{info.label}</h3>
                <p className="mt-1 text-sm leading-snug text-muted">{info.blurb}</p>
                <p className="mt-2 text-xs text-muted">
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
