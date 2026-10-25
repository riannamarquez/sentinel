import type { RedRun } from "../api";
import { dollars, FEATURES, formatFeature, OPERATORS } from "./format";
import StepCard from "./StepCard";

export default function RedStep({ redRun, onRun, loading }: {
  redRun: RedRun | null;
  onRun: () => void;
  loading: boolean;
}) {
  const bypass = redRun?.bypass;
  return (
    <StepCard id="step-red" title="3. Let Red try to sneak money past the rules"
      subtitle="Red tries to move stolen money out without triggering any rule." action={
      <button onClick={onRun} disabled={loading}
        className="shrink-0 rounded-lg bg-red-600 px-4 py-2 text-white disabled:opacity-50">
        Start Red challenge
      </button>
    }>
      {redRun && !bypass && (
        <div className="rounded-lg border-2 border-emerald-300 bg-emerald-50 p-4 text-emerald-900">
          <p className="font-semibold">Red tried {redRun.turns} times and couldn&apos;t get past the rules.</p>
          <p className="mt-1 text-sm">The current rules held, so there&apos;s no gap for Blue to fix this round.</p>
        </div>
      )}

      {redRun && bypass && (
        <div id="red-result" className="scroll-mt-24 space-y-4">
          <div className="rounded-lg border-2 border-red-300 bg-red-50 p-4">
            <p className="text-2xl font-bold text-red-700">{dollars(bypass.moved_cents)} escaped undetected</p>
            <p className="mt-1 text-sm text-red-900">
              Goal: {dollars(bypass.objective_cents)} · Succeeded on try {redRun.turns} ·{" "}
              {bypass.scenario.transactions.length} transfers · no alarm fired
            </p>
          </div>

          <div className="rounded-lg border bg-slate-50 p-4">
            <h3 className="mb-1 text-sm font-semibold">Red&apos;s plan</h3>
            <p className="text-sm text-slate-700">{bypass.rationale}</p>
          </div>

          <div>
            <h3 className="mb-1 font-semibold">Why every rule stayed silent</h3>
            <p className="mb-2 text-xs text-slate-500">
              A rule only fires when all of its checks are met. Red rows are checks the attack never tripped.
            </p>
            <table className="w-full text-left text-sm">
              <thead className="border-b text-xs uppercase text-slate-500">
                <tr>
                  <th className="py-2 pr-4">Rule</th>
                  <th className="py-2 pr-4">Check</th>
                  <th className="py-2 pr-4">Fires at</th>
                  <th className="py-2">Attack&apos;s closest</th>
                </tr>
              </thead>
              <tbody>
                {bypass.why_it_worked.flatMap((rule) =>
                  rule.conditions.map((c, i) => (
                    <tr key={`${rule.rule_id}-${i}`}
                      className={`border-b ${c.held ? "bg-red-50 text-red-900" : ""}`}>
                      <td className="py-2 pr-4 font-mono text-xs">{i === 0 ? rule.rule_id : ""}</td>
                      <td className="py-2 pr-4">{FEATURES[c.feature_key] ?? c.feature_key}</td>
                      <td className="py-2 pr-4">
                        {OPERATORS[c.operator] ?? c.operator} {formatFeature(c.feature_key, c.threshold)}
                      </td>
                      <td className="py-2">{formatFeature(c.feature_key, c.closest_value)}</td>
                    </tr>
                  )),
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </StepCard>
  );
}
