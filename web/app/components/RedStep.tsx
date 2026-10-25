import type { RedRun } from "../api";
import AttackTimeline from "./AttackTimeline";
import { analyzeChain } from "./attackChain";
import { ruleTimeLimits, silenceSentence, timeline, windowFor, type HoldBar } from "./bypassExplain";
import { dollars, FEATURES, formatFeature, OPERATORS } from "./format";
import StepCard from "./StepCard";

const YES_NO_FEATURES = new Set(["new_device_before_transfer"]);

// "$0 received in the window" looks wrong when the account plainly received money; it means the
// money arrived before the window started. Only claim that when every hold really was longer.
function windowNote(featureKey: string, closest: number, window: number | null, bars: HoldBar[]) {
  if (featureKey !== "velocity_in_amount" || closest !== 0 || window === null || !bars.length) return null;
  if (!bars.every((b) => b.heldH > window)) return null;
  return `Money arrived more than ${window} h before it left, so the ${window}-hour window never saw both.`;
}

export default function RedStep({ redRun, onRun, loading }: {
  redRun: RedRun | null;
  onRun: () => void;
  loading: boolean;
}) {
  const bypass = redRun?.bypass;
  const chain = bypass ? analyzeChain(bypass) : null;
  const { bars, totalH } = chain ? timeline(chain) : { bars: [], totalH: 0 };
  const limits = redRun?.rules ? ruleTimeLimits(redRun.rules) : null;

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

          <div>
            <h3 className="mb-1 font-semibold">Why it got through</h3>
            <p className="mb-3 text-base text-slate-800">{silenceSentence(bars, limits ?? [], bypass)}</p>
            {bars.length > 0 && <AttackTimeline bars={bars} totalH={totalH} limits={limits} />}
          </div>

          <div className="rounded-lg border bg-slate-50 px-3 py-2">
            <p className="text-sm text-slate-600"><span className="font-semibold">Red&apos;s plan:</span> {bypass.rationale}</p>
          </div>

          <div>
            <h3 className="mb-1 font-semibold">Why every rule stayed silent</h3>
            <p className="mb-2 text-sm text-slate-500">
              A rule only fires when all of its checks are met. Highlighted rows are the checks the attack never tripped.
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
                  rule.conditions.map((c, i) => {
                    const note = windowNote(c.feature_key, c.closest_value,
                      windowFor(redRun.rules, rule.rule_id, c.feature_key), bars);
                    return (
                      <tr key={`${rule.rule_id}-${i}`}
                        className={`border-b align-top ${c.held ? "bg-amber-50 text-amber-950" : ""}`}>
                        <td className="py-2 pr-4 font-mono">{i === 0 ? rule.rule_id : ""}</td>
                        <td className="py-2 pr-4">{FEATURES[c.feature_key] ?? c.feature_key}</td>
                        <td className="py-2 pr-4">
                          {YES_NO_FEATURES.has(c.feature_key)
                            ? `Must be: ${formatFeature(c.feature_key, c.threshold)}`
                            : `${OPERATORS[c.operator] ?? c.operator} ${formatFeature(c.feature_key, c.threshold)}`}
                        </td>
                        <td className="py-2">
                          {formatFeature(c.feature_key, c.closest_value)}
                          {note && <p className="mt-0.5 text-xs text-amber-800">{note}</p>}
                        </td>
                      </tr>
                    );
                  }),
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </StepCard>
  );
}
