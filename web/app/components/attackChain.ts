import type { Bypass, Transaction } from "../api";

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

// One transfer, numbered like the backend's per_hop (1-based, time-ordered).
export type TransferRow = { hopIndex: number; tx: Transaction; waitedSeconds: number | null };

export type AttackChain = {
  txs: Transaction[];             // time-ordered, the same order as the backend
  order: string[];                // accounts in the order they first appear, which is time order
  owned: Set<string>;             // accounts inside this bank
  labels: Map<string, string>;    // "Victim", "Source", "Mule 1"…, "Cash-out": one name everywhere
  hops: Hop[];
  transfers: TransferRow[];
  columns: string[][];            // accounts by how many hops the money took to reach them
};

// Names come from each account's role in the data, not from its ID: outside accounts that only
// send are the victim, outside accounts that only receive are the cash-out. Inside this bank, the
// first account the money reaches is the Source and the rest are mules, in the order reached.
function accountLabels(order: string[], txs: Transaction[], owned: Set<string>) {
  const sends = new Set(txs.map((t) => t.from_id));
  const receives = new Set(txs.map((t) => t.to_id));
  const labels = new Map<string, string>();
  let inside = 0;
  for (const id of order) {
    if (owned.has(id)) labels.set(id, inside++ === 0 ? "Source" : `Mule ${inside - 1}`);
    else labels.set(id, !receives.has(id) ? "Victim" : !sends.has(id) ? "Cash-out" : id);
  }
  return labels;
}

// Time since money last arrived in the sender before transfer i; null if nothing arrived first.
function waitedBefore(txs: Transaction[], i: number) {
  const inflow = txs.slice(0, i).findLast((p) => p.to_id === txs[i].from_id);
  return inflow ? txs[i].timestamp - inflow.timestamp : null;
}

export function analyzeChain(bypass: Bypass): AttackChain {
  // Same order the backend uses: time, then transaction ID.
  const txs = [...bypass.scenario.transactions].sort(
    (a, b) => a.timestamp - b.timestamp || a.transaction_id.localeCompare(b.transaction_id));
  const owned = new Set(bypass.scenario.owned_account_ids);

  const order: string[] = [];
  for (const t of txs) for (const id of [t.from_id, t.to_id]) if (!order.includes(id)) order.push(id);

  const groups = new Map<string, number[]>();
  txs.forEach((t, i) => {
    const key = `${t.from_id}->${t.to_id}`;
    groups.set(key, [...(groups.get(key) ?? []), i]);
  });
  const hops = [...groups].map(([key, idx]): Hop => {
    const t = txs[idx[0]];
    return {
      key,
      from: t.from_id,
      to: t.to_id,
      txs: idx.map((i) => txs[i]),
      totalCents: idx.reduce((sum, i) => sum + txs[i].amount_cents, 0),
      waitedSeconds: waitedBefore(txs, idx[0]),
      attack: idx.some((i) => txs[i].ground_truth_label === "malicious"),
    };
  });

  // Column = how many hops the money took to first reach the account, so split branches stack.
  const depth = new Map<string, number>();
  for (const h of hops) {
    if (!depth.has(h.from)) depth.set(h.from, 0);
    if (!depth.has(h.to)) depth.set(h.to, depth.get(h.from)! + 1);
  }
  const columns: string[][] = [];
  for (const id of order) (columns[depth.get(id) ?? 0] ??= []).push(id);

  return {
    txs, order, owned, labels: accountLabels(order, txs, owned), hops,
    transfers: txs.map((tx, i) => ({ hopIndex: i + 1, tx, waitedSeconds: waitedBefore(txs, i) })),
    columns: columns.filter(Boolean),
  };
}

// What reached cash-out: every transfer from this bank to another bank.
export function escapedCents(chain: AttackChain) {
  return chain.txs.filter((t) => chain.owned.has(t.from_id) && !chain.owned.has(t.to_id))
    .reduce((s, t) => s + t.amount_cents, 0);
}
