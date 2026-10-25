import type { RedRun, TurnSource } from "../api";
import AttackTimeline from "./AttackTimeline";
import { analyzeChain } from "./attackChain";
import { ruleTimeLimits, silenceSentence, timeline, windowFor, type HoldBar } from "./bypassExplain";
import { FEATURES, formatFeature, OPERATORS } from "./format";
import StepCard, { BUTTON_ATTACK, Chip } from "./StepCard";

const YES_NO_FEATURES = new Set(["new_device_before_transfer"]);

// "$0 received in the window" looks wrong when the account plainly received money; it means the
// money arrived before the window started. Only claim that when every hold really was longer.
function windowNote(featureKey: string, closest: number, window: number | null, bars: HoldBar[]) {
  if (featureKey !== "velocity_in_amount" || closest !== 0 || window === null || !bars.length) return null;
  if (!bars.every((b) => b.heldH > window)) return null;
  return `Money arrived more than ${window} h before it left, so the ${window}-hour window never saw both.`;
}

const POLICY_LABEL: Record<string, string> = {
  llm: "LLM", heuristic_fallback: "heuristic fallback", heuristic: "heuristic", fixture: "fixture",
};

// Which policy produced Red's turns, so "is that the LLM?" has an answer on screen.
export function RedSource({ sources }: { sources: TurnSource[] }) {
  if (!sources.length) return null;
  const fallbacks = sources.filter((s) => s.policy === "heuristic_fallback");
  const policy = fallbacks.length ? "heuristic_fallback" : sources.every((s) => s.policy === "llm") ? "llm" : sources[0].policy;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[14px] text-muted">
      <Chip tone={fallbacks.length ? "coral" : policy === "llm" ? "lavender" : "muted"}>
        Red: {POLICY_LABEL[policy] ?? policy}
      </Chip>
      {fallbacks.length > 0 && (
        <span>
          {fallbacks.length} of {sources.length} turns fell back:{" "}
          {fallbacks.map((s) => `turn ${s.turn} (${(s.reason ?? "unknown").replace(/_/g, " ")})`).join(", ")}
        </span>
      )}
    </div>
  );
}

// Left column until Red finds a way through: the button, or the "rules held" result.
export default function RedStep({ redRun, onRun, loading }: {
  redRun: RedRun | null;
  onRun: () => void;
  loading: boolean;
}) {
  return (
    <StepCard id="step-red" label="Red agent finding" labelTone="coral" title="Red challenge"
      subtitle="Red tries to move stolen money out without triggering any rule.">
      {redRun && !redRun.bypass && (
        <div className="mb-5 rounded-[2px] border-l-2 border-mint bg-green-panel p-4">
          <p className="text-[16px] text-ink">Red tried {redRun.turns} times and couldn&apos;t get past the rules.</p>
          <p className="mt-1 text-[15px] text-muted">The current rules held, so there&apos;s no gap for Blue to fix this round.</p>
        </div>
      )}
      <button onClick={onRun} disabled={loading} className={`${BUTTON_ATTACK} w-full`}>
        {redRun ? "Run Red again" : "Start Red challenge"}
      </button>
    </StepCard>
  );
}

// Center column once Red got through: the swimlane and the per-rule checks.
export function WhyItGotThrough({ redRun }: { redRun: RedRun }) {
  const bypass = redRun.bypass!;
  const { bars, totalH } = timeline(analyzeChain(bypass));
  const limits = redRun.rules ? ruleTimeLimits(redRun.rules) : null;
  return (
    <StepCard id="red-result" label="Red agent finding · Timeline" labelTone="coral" title="Why no rule fired"
      subtitle={silenceSentence(bars, limits ?? [], bypass)}>
      <div className="space-y-6">
        {bars.length > 0 && <AttackTimeline bars={bars} totalH={totalH} limits={limits} />}

        <p className="text-[15px] text-muted"><span className="text-coral">Red&apos;s plan:</span> {bypass.rationale}</p>

        <div className="border-t border-line pt-5">
          <h3 className="text-[20px] text-ink">Why every rule stayed silent</h3>
          <p className="mb-3 mt-1 text-[15px] text-muted">
            A rule only fires when all of its checks are met. Highlighted rows are the checks the attack never tripped.
          </p>
          <table className="w-full text-left text-[15px]">
            <thead className="label-caps text-muted">
              <tr className="border-b border-line">
                <th className="py-2.5 pr-4 font-normal">Rule</th>
                <th className="py-2.5 pr-4 font-normal">Check</th>
                <th className="py-2.5 pr-4 font-normal">Fires at</th>
                <th className="py-2.5 font-normal">Attack&apos;s closest</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {bypass.why_it_worked.flatMap((rule) =>
                rule.conditions.map((c, i) => {
                  const note = windowNote(c.feature_key, c.closest_value,
                    windowFor(redRun.rules, rule.rule_id, c.feature_key), bars);
                  return (
                    <tr key={`${rule.rule_id}-${i}`}
                      className={`border-b border-line align-top ${c.held ? "bg-amber-panel text-ink" : "text-muted"}`}>
                      <td className="py-2.5 pl-2 pr-4">{i === 0 ? rule.rule_id : ""}</td>
                      <td className="py-2.5 pr-4">{FEATURES[c.feature_key] ?? c.feature_key}</td>
                      <td className="py-2.5 pr-4">
                        {YES_NO_FEATURES.has(c.feature_key)
                          ? `Must be: ${formatFeature(c.feature_key, c.threshold)}`
                          : `${OPERATORS[c.operator] ?? c.operator} ${formatFeature(c.feature_key, c.threshold)}`}
                      </td>
                      <td className={`py-2.5 pr-2 ${c.held ? "text-amber" : ""}`}>
                        {formatFeature(c.feature_key, c.closest_value)}
                        {note && <p className="mt-0.5 text-[13px] text-amber/90">{note}</p>}
                      </td>
                    </tr>
                  );
                }),
              )}
            </tbody>
          </table>
        </div>
      </div>
    </StepCard>
  );
}
