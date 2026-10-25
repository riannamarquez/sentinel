import type { Bypass, Rule } from "../api";
import type { AttackChain } from "./attackChain";
import { FEATURES, formatFeature, OPERATORS } from "./format";

const HOUR = 3600;

// One account holding the stolen money: from when it arrived to when the account sent it on.
export type HoldBar = { account: string; label: string; startH: number; endH: number; heldH: number };

// A rule's time limit, in hours. Most rules look back `window_hours`; the hop-count rule instead
// only counts a hop held under `hold_hours`, which is the number a long hold has to beat.
export type RuleLimit = { ruleId: string; hours: number; label: string };

export function hoursText(h: number) {
  return h < 1 ? `${Math.round(h * 60)} min` : `${Number(h.toFixed(1))} h`;
}

function hourWord(h: number) {
  return `${Number(h.toFixed(1))}-hour`;
}

function listText(items: string[]) {
  return items.length <= 1 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

export function timeline(chain: AttackChain) {
  const t0 = Math.min(...chain.hops.map((h) => h.txs[0].timestamp));
  const tEnd = Math.max(...chain.hops.flatMap((h) => h.txs.map((t) => t.timestamp)));
  const bars: HoldBar[] = chain.hops
    .filter((h) => chain.owned.has(h.from) && h.waitedSeconds !== null)
    .map((h) => {
      const endH = (h.txs[0].timestamp - t0) / HOUR;
      const heldH = h.waitedSeconds! / HOUR;
      return { account: h.from, label: chain.labels.get(h.from) ?? h.from, startH: endH - heldH, endH, heldH };
    });
  return { bars, totalH: (tEnd - t0) / HOUR };
}

export function ruleTimeLimits(rules: Rule[]): RuleLimit[] {
  const out: RuleLimit[] = [];
  for (const r of rules) {
    const hop = r.all_of.find((c) => c.feature_key === "short_hold_hop_count");
    if (hop) {
      const hours = hop.params?.hold_hours ?? 24;   // the registry default, as in describeRule
      out.push({ ruleId: r.rule_id, hours, label: `${r.rule_id} counts holds under ${hoursText(hours)}` });
      continue;
    }
    const windows = r.all_of.map((c) => c.window_hours).filter((w): w is number => typeof w === "number");
    if (windows.length) {
      const hours = Math.max(...windows);
      out.push({ ruleId: r.rule_id, hours, label: `${r.rule_id} watches ${hoursText(hours)}` });
    }
  }
  return out.sort((a, b) => a.hours - b.hours);
}

export function windowFor(rules: Rule[] | null, ruleId: string, featureKey: string) {
  return rules?.find((r) => r.rule_id === ruleId)?.all_of.find((c) => c.feature_key === featureKey)?.window_hours ?? null;
}

/** One plain-English sentence on why no rule fired, built only from the data. */
export function silenceSentence(bars: HoldBar[], limits: RuleLimit[], bypass: Bypass): string {
  if (bars.length && limits.length) {
    const held = bars.map((b) => b.heldH);
    const [lo, hi] = [Math.min(...held), Math.max(...held)];
    const longest = Math.max(...limits.map((l) => l.hours));
    if (lo > longest) {
      const range = Number(lo.toFixed(1)) === Number(hi.toFixed(1))
        ? `${Number(lo.toFixed(1))} hours`
        : `${Number(lo.toFixed(1))}–${Number(hi.toFixed(1))} hours`;
      const who = bars.length === 1 ? "The account" : "Each account";
      const hours = listText([...new Set(limits.map((l) => l.hours))].map(hourWord));
      return `${who} held the money ${range} — ${lo >= 2 * longest ? "far " : ""}longer than the ${hours} time limits the rules check — so no account ever looked suspicious.`;
    }
  }

  // Otherwise explain rule by rule, from the check that never fired.
  const reasons = bypass.why_it_worked.flatMap((rule) => {
    const c = rule.conditions.find((x) => x.held);
    if (!c) return [];
    const name = FEATURES[c.feature_key] ?? c.feature_key;
    const reached = formatFeature(c.feature_key, c.closest_value);
    const needed = c.feature_key === "new_device_before_transfer"
      ? `must be ${formatFeature(c.feature_key, c.threshold)}`
      : `fires at ${OPERATORS[c.operator] ?? c.operator} ${formatFeature(c.feature_key, c.threshold)}`;
    return [`${rule.rule_id}: ${name.toLowerCase()} only reached ${reached} (${needed})`];
  });
  return reasons.length
    ? `No rule fired because each one had a check the attack never met — ${reasons.join("; ")}.`
    : "No rule fired on any transfer in this attack.";
}
