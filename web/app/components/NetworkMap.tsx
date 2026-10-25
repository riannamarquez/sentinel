"use client";

import { useEffect, useState } from "react";
import * as api from "../api";
import { analyzeChain, type AttackChain } from "./attackChain";
import { describeFiring, dollars } from "./format";

type Cached = api.BypassReplay | { error: string };
type View = "base" | "candidate";

function wholeDollars(cents: number) {
  return dollars(Math.round(cents / 100) * 100);
}

function waitedText(seconds: number | null) {
  if (seconds === null) return "—";
  const h = seconds / 3600;
  return h < 1 ? `${Math.round(seconds / 60)}m` : `${Number(h.toFixed(1))}h`;
}

// "Caught at hop N by R4. Hop count reached 4 within 72 h." The reason comes from the fired rule's
// definition: the base rules, or the patch's rule for one the base rules don't have.
function caughtText(replay: api.BypassReplay, baseRules: api.Rule[] | null, patch: api.RulePatch | null) {
  const ruleId = replay.triggered_rule_ids[0];
  const patchDefines = patch?.all_of && (patch.operation === "add"
    ? !baseRules?.some((r) => r.rule_id === ruleId)
    : patch.rule_id === ruleId);
  const def = patchDefines ? patch!.all_of : baseRules?.find((r) => r.rule_id === ruleId)?.all_of;
  const by = replay.triggered_rule_ids.join(", ");
  return `Caught at hop ${replay.alert_hop_index} by ${by}.${def ? ` ${describeFiring(def)}.` : ""}`;
}

function Arrow({ numbers, never, stoppedBy }: { numbers: number[]; never: boolean; stoppedBy: string | null }) {
  const color = never ? "border-slate-400 text-slate-400" : "border-orange-600 text-orange-700";
  return (
    <div className="relative flex w-9 shrink-0 flex-col items-center self-center">
      <span className={`mb-0.5 rounded-full border bg-white px-1.5 text-xs font-semibold leading-4 ${color}`}>
        {numbers.length > 3 ? `${numbers[0]}–${numbers[numbers.length - 1]}` : numbers.join(",")}
      </span>
      <div className="flex w-full items-center">
        <div className={`h-0 flex-1 border-t-2 ${never ? "border-dashed" : ""} ${color}`} />
        <div className={`h-0 w-0 border-y-[5px] border-l-[7px] border-y-transparent ${
          never ? "border-l-slate-400" : "border-l-orange-600"}`} />
      </div>
      {stoppedBy && (
        <div className="absolute left-1/2 top-full z-10 flex -translate-x-1/2 flex-col items-center">
          <div className="h-3 w-px bg-emerald-600" />
          <span className="whitespace-nowrap rounded border border-emerald-600 bg-emerald-50 px-1.5 py-0.5 text-xs font-semibold text-emerald-800">
            Stopped here by {stoppedBy}
          </span>
        </div>
      )}
    </div>
  );
}

// One row, left to right in time order, wrapping when it runs out of room. Accounts the money
// reached after the same number of hops share a column, so split branches stack.
function ChainDiagram({ chain, replay, otherCustomers }: {
  chain: AttackChain;
  replay: api.BypassReplay | null;
  otherCustomers: number | null;
}) {
  const stopAt = replay?.alert ? replay.alert_hop_index : null;
  const source = chain.order.find((id) => chain.owned.has(id));
  return (
    <div className="flex flex-wrap items-start gap-y-4">
      {chain.columns.map((column, c) => (
        <div key={c} className="flex flex-col gap-2">
          {column.map((id) => {
            const incoming = chain.transfers.filter((t) => t.tx.to_id === id).map((t) => t.hopIndex);
            const never = stopAt !== null && incoming.length > 0 && incoming.every((n) => n > stopAt);
            const stopped = stopAt !== null && incoming.includes(stopAt);
            const inside = chain.owned.has(id);
            return (
              <div key={id} className={`flex items-start ${stopped ? "mb-9" : ""}`}>
                {c > 0 && <Arrow numbers={incoming} never={never}
                  stoppedBy={stopped ? replay!.triggered_rule_ids.join(", ") : null} />}
                <div className="flex flex-col items-center">
                  <div className={`min-w-[4.5rem] rounded-md border-2 px-2 py-1 text-center leading-tight ${
                    inside ? "border-orange-500 bg-orange-100 text-orange-950" : "border-dashed border-slate-400 bg-slate-100 text-slate-600"
                  } ${never && inside ? "opacity-40" : ""}`}>
                    <div className="text-[13px] font-semibold">{chain.labels.get(id)}</div>
                    <div className="text-xs opacity-75">{inside ? id : "other bank"}</div>
                  </div>
                  {id === source && otherCustomers !== null && (
                    <span title={`${otherCustomers} other customers, collapsed`}
                      className="mt-2 flex h-8 min-w-8 items-center justify-center rounded-full border border-slate-400 bg-white px-1 text-xs text-slate-600">
                      +{otherCustomers}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

function HopTable({ chain, replay }: { chain: AttackChain; replay: api.BypassReplay | null }) {
  const byTxn = new Map(replay?.per_hop.map((h) => [h.transaction_id, h]));
  const stopAt = replay?.alert ? replay.alert_hop_index : null;
  const name = (id: string) => chain.labels.get(id) ?? id;
  return (
    <table className="w-full text-left text-[13px]">
      <thead className="border-b text-xs text-slate-500">
        <tr>
          <th className="py-1.5 pr-2 font-medium">Hop</th>
          <th className="py-1.5 pr-2 font-medium">From → to</th>
          <th className="py-1.5 pr-2 font-medium">Amount</th>
          <th className="py-1.5 pr-2 font-medium">Waited</th>
          <th className="py-1.5 font-medium">Detector</th>
        </tr>
      </thead>
      <tbody>
        {chain.transfers.map(({ hopIndex, tx, waitedSeconds }) => {
          const hop = byTxn.get(tx.transaction_id);
          const index = hop?.hop_index ?? hopIndex;
          const never = stopAt !== null && index > stopAt;
          let detector = <span className="text-slate-400">…</span>;
          if (never) detector = <span>Never happens</span>;
          else if (hop && !hop.scored) detector = <span className="text-slate-400">Not scored (incoming)</span>;
          else if (hop && index === stopAt) {
            detector = (
              <span className="rounded bg-emerald-100 px-1.5 py-0.5 font-semibold text-emerald-800">
                {hop.rule_ids.join(", ")} fires — stopped
              </span>
            );
          } else if (hop) detector = <span>No rule fired</span>;
          return (
            <tr key={tx.transaction_id} className={`border-b align-top ${never ? "text-slate-400" : ""}`}>
              <td className="py-1.5 pr-2">{index}</td>
              <td className="py-1.5 pr-2">{name(tx.from_id)} → {name(tx.to_id)}</td>
              <td className="py-1.5 pr-2 tabular-nums">{wholeDollars(tx.amount_cents)}</td>
              <td className="py-1.5 pr-2 tabular-nums">{waitedText(waitedSeconds)}</td>
              <td className="py-1.5">{detector}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// The rechallenge is a fresh test attack from the backend, not Red's path, so the result is
// reported under the map rather than drawn onto any hop, and never called "like this one".
function RechallengeBanner({ rechallenge }: { rechallenge: api.Rechallenge }) {
  const fired = rechallenge.triggered_rule_ids.join(", ");
  return rechallenge.alert ? (
    <div className="rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-2 text-[13px] font-semibold text-emerald-900">
      ✓ The active rules caught a fresh test attack{fired && ` (fired: ${fired})`}
    </div>
  ) : (
    <div className="rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-[13px] font-semibold text-red-900">
      ✗ A fresh test attack still got through
    </div>
  );
}

export default function NetworkMap({ labId, runId, bypass, redRan, baseRules, patch, candidateReady, approval, otherCustomers }: {
  labId: string | null;
  runId: string | null;
  bypass: api.Bypass | null;
  redRan: boolean;
  baseRules: api.Rule[] | null;
  patch: api.RulePatch | null;          // the evaluated patch, for the caught reason
  candidateReady: boolean;              // a valid patch has been evaluated
  approval: api.Approval | null;
  otherCustomers: number | null;
}) {
  const [view, setView] = useState<View>("base");
  const [cache, setCache] = useState<Record<string, Cached>>({});
  // The candidate's label and version change once it's approved, so a decision starts a fresh cache entry.
  const baseKey = `${runId}:base`;
  const candidateKey = `${runId}:candidate:${approval?.decision ?? "open"}`;
  const shown: View = candidateReady ? view : "base";

  useEffect(() => {
    if (!labId || !runId || !bypass) return;
    const wanted: [string, View][] = [[baseKey, "base"]];
    if (candidateReady) wanted.push([candidateKey, "candidate"]);
    for (const [key, choice] of wanted) {
      if (cache[key]) continue;
      api.replayBypass(labId, runId, choice)
        .then((r) => setCache((c) => ({ ...c, [key]: r })))
        .catch((e) => setCache((c) => ({
          ...c, [key]: { error: e instanceof api.ApiError ? e.message : "Couldn't load the replay." } })));
    }
  }, [labId, runId, bypass, candidateReady, baseKey, candidateKey, cache]);

  if (!bypass) {
    return (
      <div className="flex h-full flex-col items-center justify-center p-6 text-center">
        <p className="font-semibold text-slate-500">Red&apos;s attack path</p>
        <p className="mt-1 text-sm text-slate-400">
          {redRan ? "Red didn't find a way past the rules, so there's no attack path to show." : "The attack path will appear here."}
        </p>
      </div>
    );
  }

  const chain = analyzeChain(bypass);
  const loaded = (key: string) => {
    const e = cache[key];
    return e && !("error" in e) ? e : null;
  };
  const shownKey = shown === "base" ? baseKey : candidateKey;
  const failed = cache[shownKey] && "error" in cache[shownKey] ? (cache[shownKey] as { error: string }).error : null;
  const replay = loaded(shownKey);
  const v1Label = loaded(baseKey)?.detector_label ?? `Detector v${bypass.detector_version}`;
  const v2Label = loaded(candidateKey)?.detector_label ?? `Detector v${bypass.detector_version + 1}`;
  // What reached cash-out: every transfer from this bank to an account at another bank.
  const reachedCents = chain.txs
    .filter((t) => chain.owned.has(t.from_id) && !chain.owned.has(t.to_id))
    .reduce((sum, t) => sum + t.amount_cents, 0);

  const toggle = (choice: View, label: string, disabled: boolean) => (
    <span title={disabled ? "Ask Blue for a fix first" : undefined}>
      <button onClick={() => setView(choice)} disabled={disabled} aria-pressed={shown === choice}
        className={`rounded-lg border px-2.5 py-1 text-[13px] font-medium disabled:cursor-not-allowed disabled:opacity-40 ${
          shown === choice ? "border-slate-900 bg-slate-900 text-white" : "border-slate-300 bg-white text-slate-700"}`}>
        {label}
      </button>
    </span>
  );

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold">Red&apos;s attack path</h2>
        <div className="flex flex-wrap gap-1.5">
          {toggle("base", v1Label, false)}
          {toggle("candidate", v2Label, !candidateReady)}
        </div>
      </div>

      {failed ? (
        <div className="flex items-center justify-between gap-2 rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-[13px] text-red-900">
          <span>{failed}</span>
          <button className="shrink-0 underline" onClick={() => setCache((c) => {
            const next = { ...c };
            delete next[shownKey];
            return next;
          })}>Try again</button>
        </div>
      ) : !replay ? (
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[13px] text-slate-500">Replaying the attack…</div>
      ) : replay.alert ? (
        <div className="rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-2 text-[13px] font-semibold text-emerald-800">
          🛡 {caughtText(replay, baseRules, patch)}
        </div>
      ) : (
        <div className="rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-[13px] font-semibold text-red-800">
          ⚠ Slipped through. {wholeDollars(reachedCents)} reached cash-out with no alert.
        </div>
      )}

      <ChainDiagram chain={chain} replay={replay} otherCustomers={otherCustomers} />

      <ul className="space-y-1 text-xs text-slate-600">
        <li className="flex flex-wrap items-center gap-1.5">
          <span className="inline-block h-3 w-3 rounded-sm border-2 border-orange-500 bg-orange-100" /> Our bank (source, mules)
          <span className="ml-3 inline-block h-3 w-3 rounded-sm border-2 border-dashed border-slate-400" /> Other bank
        </li>
        {otherCustomers !== null && (
          <li className="flex items-center gap-1.5">
            <span className="inline-block h-3 w-3 rounded-full border border-slate-400" /> {otherCustomers} other customers, collapsed
          </li>
        )}
        <li>Mule: an account used to pass stolen money along</li>
      </ul>

      <div>
        <p className="mb-1.5 text-xs text-slate-600">
          One attack: the same money moves through each account in turn. Amounts are per hop, not a running total.
        </p>
        <HopTable chain={chain} replay={replay} />
      </div>

      {approval?.rechallenge && <RechallengeBanner rechallenge={approval.rechallenge} />}
    </div>
  );
}
