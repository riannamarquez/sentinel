import type { Bypass, Transaction } from "../api";
import { dollars } from "./format";

// One arrow's worth of money: every transfer from one account to the next. Red can split a hop
// into several transfers to the same account, so a hop can hold more than one.
export type Hop = {
  key: string;
  from: string;
  to: string;
  txs: Transaction[];
  totalCents: number;
  waitedSeconds: number | null;   // since money last arrived in `from`; null if nothing arrived first
  attack: boolean;
};

export type AttackChain = {
  order: string[];                // accounts in the order they first appear, which is time order
  owned: Set<string>;             // accounts inside this bank
  labels: Map<string, string>;
  hops: Hop[];
};

// Names come from each account's role in the data, not from its ID: outside accounts that only
// send are the victim, outside accounts that only receive are the cash-out, and accounts inside
// this bank are numbered in the order the money reached them.
function accountLabels(order: string[], txs: Transaction[], owned: Set<string>) {
  const sends = new Set(txs.map((t) => t.from_id));
  const receives = new Set(txs.map((t) => t.to_id));
  const labels = new Map<string, string>();
  let inside = 0;
  for (const id of order) {
    if (owned.has(id)) labels.set(id, `Account ${++inside}`);
    else labels.set(id, !receives.has(id) ? "Victim (outside)" : !sends.has(id) ? "Cash-out (outside)" : `${id} (outside)`);
  }
  return labels;
}

export function analyzeChain(bypass: Bypass): AttackChain {
  // Same order the backend uses: time, then transaction ID.
  const txs = [...bypass.scenario.transactions].sort(
    (a, b) => a.timestamp - b.timestamp || a.transaction_id.localeCompare(b.transaction_id));
  const owned = new Set(bypass.scenario.owned_account_ids);

  const order: string[] = [];
  for (const t of txs) for (const id of [t.from_id, t.to_id]) if (!order.includes(id)) order.push(id);

  const groups = new Map<string, { first: number; txs: Transaction[] }>();
  txs.forEach((t, i) => {
    const key = `${t.from_id}->${t.to_id}`;
    const g = groups.get(key) ?? groups.set(key, { first: i, txs: [] }).get(key)!;
    g.txs.push(t);
  });

  const hops = [...groups].map(([key, g]): Hop => {
    const t = txs[g.first];
    const inflow = txs.slice(0, g.first).findLast((p) => p.to_id === t.from_id);
    return {
      key,
      from: t.from_id,
      to: t.to_id,
      txs: g.txs,
      totalCents: g.txs.reduce((sum, x) => sum + x.amount_cents, 0),
      waitedSeconds: inflow ? t.timestamp - inflow.timestamp : null,
      attack: g.txs.some((x) => x.ground_truth_label === "malicious"),
    };
  });

  return { order, owned, labels: accountLabels(order, txs, owned), hops };
}

function waitText(seconds: number) {
  const hours = seconds / 3600;
  if (hours < 1) {
    const minutes = Math.round(seconds / 60);
    return `${minutes} minute${minutes === 1 ? "" : "s"}`;
  }
  const rounded = Number(hours.toFixed(1));
  return `${rounded} hour${rounded === 1 ? "" : "s"}`;
}

function wholeDollars(cents: number) {
  return dollars(Math.round(cents / 100) * 100);
}

/**
 * The attack as a short plain-English story, built only from the chain. Returns null unless the
 * money followed one straight line (victim → inside accounts → cash-out), since the story can't
 * describe splits between different accounts honestly.
 */
export function attackStory(chain: AttackChain): string[] | null {
  const { hops, owned, labels } = chain;
  const first = hops[0];
  const last = hops[hops.length - 1];
  if (!first || hops.length < 2 || owned.has(first.from) || !owned.has(first.to) || owned.has(last.to)) return null;
  for (let i = 1; i < hops.length; i++) {
    if (hops[i].from !== hops[i - 1].to || !owned.has(hops[i].from) || hops[i].waitedSeconds === null) return null;
  }

  const insideCount = hops.length - 1;
  const name = (id: string) => labels.get(id) ?? id;
  const sentences = [
    `A criminal steals ${wholeDollars(first.totalCents)} from a victim.`,
    `Sending it straight to their own account would be traced immediately, so it moves through ${insideCount} account${insideCount === 1 ? "" : "s"} at this bank, one after another.`,
    `The stolen money lands in ${name(first.to)}.`,
  ];
  hops.slice(1).forEach((hop, i) => {
    const received = hops[i].totalCents;
    const share = hop.totalCents * 2 >= received ? "most of it" : "part of it";
    const split = hop.txs.length > 1 ? `, in ${hop.txs.length} transfers` : "";
    const waited = `${name(hop.from)} waits ${waitText(hop.waitedSeconds!)}, then sends`;
    sentences.push(hop === last
      ? `${waited} ${wholeDollars(hop.totalCents)}${split} out of the bank to the criminal (the “cashout”).`
      : `${waited} ${share} (${wholeDollars(hop.totalCents)}${split}) to ${name(hop.to)}.`);
  });
  return sentences;
}
