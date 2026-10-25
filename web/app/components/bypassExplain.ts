import type { Bypass, Rule } from "../api";
import { analyzeChain, escapedCents, type AttackChain } from "./attackChain";
import { FEATURES, formatFeature, OPERATORS, wholeDollars } from "./format";

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

// What changed between two of Red's attacks on the same lab, for the "How Red adapted" callout and
// the map's highlights. Only values that differ are listed.
export type ChangeKey = "hold" | "mules" | "splits" | "escaped";
export type Adaptation = { changes: { key: ChangeKey; text: string }[]; why: string | null };

function hoursWord(h: number) {
  const n = Number(h.toFixed(1));
  return `${n} ${n === 1 ? "hour" : "hours"}`;
}

function holdRange(bars: HoldBar[]) {
  if (!bars.length) return null;
  const held = bars.map((b) => b.heldH);
  const [lo, hi] = [Math.min(...held), Math.max(...held)];
  return Number(lo.toFixed(1)) === Number(hi.toFixed(1)) ? hoursWord(lo) : `${Number(lo.toFixed(1))}–${hoursWord(hi)}`;
}

function attackFigures(bypass: Bypass) {
  const chain = analyzeChain(bypass);
  const { bars } = timeline(chain);
  return {
    bars,
    hold: holdRange(bars),
    mules: [...chain.labels.values()].filter((l) => l.startsWith("Mule")).length,
    splits: Math.max(1, ...chain.hops.map((h) => h.txs.length)),
    escaped: escapedCents(chain),
  };
}

function splitText(n: number) {
  return n === 1 ? "one transfer per hop" : `up to ${n} transfers per hop`;
}

// Why Red changed: the rule time limit the old holds fell inside and the new holds clear, else a
// check of a rule the previous attack never faced that this attack stayed under.
function adaptationReason(prev: Bypass, next: Bypass, prevBars: HoldBar[], nextBars: HoldBar[], rules: Rule[] | null) {
  const isNew = (ruleId: string) =>
    next.detector_version > prev.detector_version && !prev.why_it_worked.some((w) => w.rule_id === ruleId);
  const who = (ruleId: string) => `${isNew(ruleId) ? "Blue's new rule" : "Rule"} ${ruleId}`;

  if (rules && prevBars.length && nextBars.length) {
    const prevMin = Math.min(...prevBars.map((b) => b.heldH));
    const nextMin = Math.min(...nextBars.map((b) => b.heldH));
    const crossed = ruleTimeLimits(rules)
      .filter((l) => prevMin < l.hours && nextMin >= l.hours)
      .sort((a, b) => Number(isNew(b.ruleId)) - Number(isNew(a.ruleId)) || b.hours - a.hours)[0];
    if (crossed) {
      const hop = rules.find((r) => r.rule_id === crossed.ruleId)?.all_of
        .some((c) => c.feature_key === "short_hold_hop_count");
      const what = hop ? `only flags money held under ${hoursWord(crossed.hours)}` : `only looks back ${hoursWord(crossed.hours)}`;
      return `${who(crossed.ruleId)} ${what}, so Red waited longer.`;
    }
  }

  const rule = next.why_it_worked.find((w) => isNew(w.rule_id) && w.conditions.some((c) => c.held));
  const c = rule?.conditions.find((x) => x.held);
  if (!rule || !c) return null;
  const name = (FEATURES[c.feature_key] ?? c.feature_key).toLowerCase();
  return `${who(rule.rule_id)} fires when ${name} is ${OPERATORS[c.operator] ?? c.operator} ${formatFeature(c.feature_key, c.threshold)}, so Red kept it at ${formatFeature(c.feature_key, c.closest_value)}.`;
}

/** How `next` differs from the attack before it, from the two scenarios and the rules `next` faced. */
export function adaptation(prev: Bypass, next: Bypass, rules: Rule[] | null): Adaptation {
  const a = attackFigures(prev);
  const b = attackFigures(next);
  const changes: Adaptation["changes"] = [];
  if (b.hold && a.hold && b.hold !== a.hold) {
    changes.push({ key: "hold", text: `Held money ${b.hold} per account (was ${a.hold})` });
  }
  if (b.mules !== a.mules) {
    changes.push({ key: "mules", text: `Used ${b.mules} mule ${b.mules === 1 ? "account" : "accounts"} (was ${a.mules})` });
  }
  if (b.splits !== a.splits) {
    changes.push({ key: "splits", text: `Sent ${splitText(b.splits)} (was ${splitText(a.splits)})` });
  }
  if (wholeDollars(b.escaped) !== wholeDollars(a.escaped)) {
    changes.push({ key: "escaped", text: `${wholeDollars(b.escaped)} escaped (was ${wholeDollars(a.escaped)})` });
  }
  return { changes, why: adaptationReason(prev, next, a.bars, b.bars, rules) };
}
