import type { Condition } from "../api";

// Plain-English names for the detector's feature keys.
export const FEATURES: Record<string, string> = {
  velocity_out_count: "Transfers out in the window",
  velocity_out_amount: "Money sent out in the window",
  velocity_in_amount: "Money received in the window",
  new_device_before_transfer: "New device right before transfer",
  transfer_amount: "Size of a single transfer",
  near_threshold_amount: "Transfers just under the reporting limit",
  pass_through_ratio: "Share of incoming money passed on",
  min_hold_hours: "Shortest time money sat in an account (hours)",
  short_hold_hop_count: "Quick hops through accounts",
};
const AMOUNT_FEATURES = new Set(["velocity_out_amount", "velocity_in_amount", "transfer_amount"]);
export const OPERATORS: Record<string, string> = { ">=": "≥", ">": ">", "<=": "≤", "<": "<" };

export function dollars(cents: number) {
  return `$${(cents / 100).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

export function formatFeature(key: string, value: number) {
  if (AMOUNT_FEATURES.has(key)) return dollars(value);
  if (key === "pass_through_ratio") return `${Math.round(value * 100)}%`;
  if (key === "new_device_before_transfer") return value >= 1 ? "Yes" : "No";
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

// "4+", "more than 4", "at most 4", "under 4" depending on the operator.
function compare(op: string, v: string) {
  return { ">=": `${v}+`, ">": `more than ${v}`, "<=": `at most ${v}`, "<": `under ${v}` }[op] ?? `${op} ${v}`;
}

function describeCondition(c: Condition) {
  const p = c.params ?? {};
  const within = c.window_hours ? ` within ${c.window_hours} hours` : "";
  const t = c.threshold;
  switch (c.feature_key) {
    case "velocity_out_count":
      return `an account sends ${compare(c.operator, String(t))} transfers${within}`;
    case "velocity_out_amount":
      return `an account sends out ${compare(c.operator, dollars(t))}${within}`;
    case "velocity_in_amount":
      return `an account receives ${compare(c.operator, dollars(t))}${within}`;
    case "pass_through_ratio":
      return `an account passes on ${compare(c.operator, `${Math.round(t * 100)}%`)} of the money it received${within}`;
    case "new_device_before_transfer": {
      const hours = p.n_hours ?? 24;
      return c.operator.startsWith(">")
        ? `a new device logs in within ${hours} hours before the transfer`
        : `no new device logs in within ${hours} hours before the transfer`;
    }
    case "transfer_amount":
      return `a single transfer is ${compare(c.operator, dollars(t))}`;
    case "near_threshold_amount":
      return `an account makes ${compare(c.operator, String(t))} transfers just under the ${dollars(p.reporting_threshold_cents ?? 1_000_000)} reporting limit${within}`;
    case "min_hold_hours":
      return `money sits in an account for ${compare(c.operator, `${t} hours`)} before moving on${within}`;
    case "short_hold_hop_count":
      return `money passes through ${compare(c.operator, String(t))} accounts in a row${within}, each holding it under ${p.hold_hours ?? 24} hours and forwarding at least ${p.min_carry_pct ?? 40}%`;
    default:
      return `${c.feature_key} ${OPERATORS[c.operator] ?? c.operator} ${t}${within}`;
  }
}

export function describeRule(all_of: Condition[]) {
  return `Alarm if ${all_of.map(describeCondition).join(", and ")}.`;
}
