import type { Condition, RulePatch } from "../api";
import { FEATURES, formatFeature, OPERATORS } from "./format";

// Rules have no name in the API, so the heading is copy picked by the rule's first feature.
const TITLES: Record<string, string> = {
  short_hold_hop_count: "Detect sustained pass-through chains",
  velocity_out_count: "Flag bursts of outgoing transfers",
  velocity_out_amount: "Flag large outflows in a short window",
  velocity_in_amount: "Flag large inflows in a short window",
  pass_through_ratio: "Flag money that passes straight through",
  new_device_before_transfer: "Flag transfers from new devices",
  transfer_amount: "Flag large single transfers",
  near_threshold_amount: "Flag transfers just under the reporting limit",
  min_hold_hours: "Flag money that barely stops",
};

export function ruleTitle(patch: RulePatch) {
  if (patch.operation === "disable") return `Disable ${patch.rule_id}`;
  const title = TITLES[patch.all_of?.[0]?.feature_key ?? ""] ?? "New detection rule";
  return patch.operation === "modify" ? `Change ${patch.rule_id}: ${title.toLowerCase()}` : title;
}

export type SpecCell = { label: string; value: string };

function op(c: Condition) {
  return OPERATORS[c.operator] ?? c.operator;
}

/** The spec grid: one cell per threshold, window or parameter in the rule's conditions. */
export function specCells(all_of: Condition[]): SpecCell[] {
  return all_of.flatMap((c): SpecCell[] => {
    const p = c.params ?? {};
    if (c.feature_key === "short_hold_hop_count") {
      return [
        { label: "Chain length", value: `${op(c)} ${c.threshold} accounts` },
        ...(c.window_hours ? [{ label: "Total window", value: `≤ ${c.window_hours} hours` }] : []),
        { label: "Hold per account", value: `< ${p.hold_hours ?? 24} hours` },
        { label: "Forwarded funds", value: `≥ ${p.min_carry_pct ?? 40}%` },
      ];
    }
    const name = FEATURES[c.feature_key] ?? c.feature_key;
    const cells: SpecCell[] = [{
      label: name,
      value: c.feature_key === "new_device_before_transfer"
        ? `Must be ${formatFeature(c.feature_key, c.threshold)}`
        : `${op(c)} ${formatFeature(c.feature_key, c.threshold)}`,
    }];
    if (c.window_hours) cells.push({ label: "Window", value: `≤ ${c.window_hours} hours` });
    if (p.n_hours) cells.push({ label: "Device lookback", value: `≤ ${p.n_hours} hours` });
    return cells;
  });
}
