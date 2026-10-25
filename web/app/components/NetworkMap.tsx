"use client";

import { Fragment, useEffect, useState } from "react";
import * as api from "../api";
import { analyzeChain, type AttackChain } from "./attackChain";
import { ruleTimeLimits, silenceSentence, timeline } from "./bypassExplain";
import { describeFiring, dollars } from "./format";
import StepCard, { BUTTON_ATTACK, Chip } from "./StepCard";

type Cached = api.BypassReplay | { error: string };
type View = "base" | "candidate";

const ClockIcon = (
  <svg aria-hidden="true" viewBox="0 0 16 16" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.4">
    <circle cx="8" cy="8" r="6.5" />
    <path d="M8 4.5V8l2.5 1.5" strokeLinecap="round" />
  </svg>
);

function wholeDollars(cents: number) {
  return dollars(Math.round(cents / 100) * 100);
}

function holdText(seconds: number | null, caps = false) {
  if (seconds === null) return "—";
  const h = seconds / 3600;
  if (caps) return h < 1 ? `${Math.round(seconds / 60)} MIN` : `${Number(h.toFixed(1))} HOURS`;
  return h < 1 ? `${Math.round(seconds / 60)}m` : `${Number(h.toFixed(1))}h`;
}

// The fired rule's definition: the base rules, or the patch's rule for one the base rules don't have.
function firedReason(replay: api.BypassReplay, baseRules: api.Rule[] | null, patch: api.RulePatch | null) {
  const ruleId = replay.triggered_rule_ids[0];
  const patchDefines = patch?.all_of && (patch.operation === "add"
    ? !baseRules?.some((r) => r.rule_id === ruleId)
    : patch.rule_id === ruleId);
  const def = patchDefines ? patch!.all_of : baseRules?.find((r) => r.rule_id === ruleId)?.all_of;
  return def ? `${describeFiring(def)}.` : null;
}

// One account's figures: what it sent on (or, at the end of the chain, what it received) and how
// long it held the money before sending.
function accountFigures(chain: AttackChain, id: string) {
  const out = chain.txs.filter((t) => t.from_id === id);
  const sum = (ts: typeof out) => ts.reduce((s, t) => s + t.amount_cents, 0);
  const firstOut = chain.transfers.find((t) => t.tx.from_id === id);
  return {
    cents: out.length ? sum(out) : sum(chain.txs.filter((t) => t.to_id === id)),
    heldSeconds: firstOut?.waitedSeconds ?? null,
  };
}

// Vertical chain, one row per step of the relay; split branches sit side by side in the same row.
function Chain({ chain, replay }: { chain: AttackChain; replay: api.BypassReplay | null }) {
  const stopAt = replay?.alert ? replay.alert_hop_index : null;
  let n = 0;
  return (
    <ol>
      {chain.columns.map((column, c) => {
        const incoming = column.flatMap((id) => chain.transfers.filter((t) => t.tx.to_id === id));
        const numbers = incoming.map((t) => t.hopIndex);
        const never = stopAt !== null && numbers.length > 0 && numbers.every((x) => x > stopAt);
        const stopped = stopAt !== null && numbers.includes(stopAt);
        const sender = incoming[0]?.tx.from_id;
        const connector = sender && !chain.owned.has(sender) ? "TRANSFER" : `HELD ${holdText(incoming[0]?.waitedSeconds ?? null, true)}`;
        return (
          <Fragment key={c}>
            {c > 0 && (
              <li aria-hidden="true" className="relative ml-[3.25rem] flex h-11 items-center">
                <div className={`absolute left-4 top-0 h-full border-l ${never ? "border-dashed border-muted/60" : "border-coral/70"}`} />
                <span className={`absolute left-4 bottom-0 -translate-x-1/2 text-[9px] leading-none ${never ? "text-muted/60" : "text-coral/80"}`}>▼</span>
                <span className={`label-caps ml-8 tabular-nums ${never ? "text-muted/60" : "text-muted"}`}>
                  {never ? "Never happens" : connector}
                </span>
                {stopped && (
                  <span className="ml-3"><Chip tone="mint">Stopped here by {replay!.triggered_rule_ids.join(", ")}</Chip></span>
                )}
              </li>
            )}
            <li className={`flex gap-4 ${never ? "opacity-40" : ""}`}>
              <span className="w-9 pt-4 text-[15px] tabular-nums text-coral">{String(++n).padStart(2, "0")}</span>
              <div className="grid flex-1 gap-2" style={{ gridTemplateColumns: `repeat(${column.length}, minmax(0, 1fr))` }}>
                {column.map((id) => {
                  const inside = chain.owned.has(id);
                  const f = accountFigures(chain, id);
                  return (
                    <div key={id} className={`rounded-[2px] border px-4 py-3 ${inside ? "border-line bg-card-raised" : "border-dashed border-muted/50 bg-page/40"}`}>
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="text-[17px] text-ink">{chain.labels.get(id)}</span>
                        <span className="text-[16px] tabular-nums text-ink">{wholeDollars(f.cents)}</span>
                      </div>
                      <div className="mt-0.5 flex justify-between gap-2 text-[14px] text-muted">
                        <span>{inside ? `${id} · Our bank` : "Outside bank"}</span>
                        <span className="tabular-nums">{holdText(f.heldSeconds)}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </li>
          </Fragment>
        );
      })}
    </ol>
  );
}

// The rechallenge is a fresh test attack from the backend, not Red's path, so it's reported under
// the chain rather than drawn onto any hop, and never called "like this one".
function RechallengeBanner({ rechallenge }: { rechallenge: api.Rechallenge }) {
  const fired = rechallenge.triggered_rule_ids.join(", ");
  return rechallenge.alert ? (
    <p className="rounded-[2px] border-l-2 border-mint bg-green-panel px-4 py-3 text-[15px] text-mint">
      ✓ The active rules caught a fresh test attack{fired && ` (fired: ${fired})`}
    </p>
  ) : (
    <p className="rounded-[2px] border-l-2 border-coral bg-red-panel px-4 py-3 text-[15px] text-coral">
      ✗ A fresh test attack still got through
    </p>
  );
}

export default function NetworkMap({ labId, runId, bypass, baseRules, patch, candidateReady, approval, otherCustomers, onRerun, loading }: {
  labId: string | null;
  runId: string | null;
  bypass: api.Bypass;
  baseRules: api.Rule[] | null;
  patch: api.RulePatch | null;          // the evaluated patch, for the caught reason
  candidateReady: boolean;              // a valid patch has been evaluated
  approval: api.Approval | null;
  otherCustomers: number | null;
  onRerun: () => void;
  loading: boolean;
}) {
  const [view, setView] = useState<View>("base");
  const [cache, setCache] = useState<Record<string, Cached>>({});
  // The candidate's label and version change once it's approved, so a decision starts a fresh cache entry.
  const baseKey = `${runId}:base`;
  const candidateKey = `${runId}:candidate:${approval?.decision ?? "open"}`;
  const shown: View = candidateReady ? view : "base";

  useEffect(() => {
    if (!labId || !runId) return;
    const wanted: [string, View][] = [[baseKey, "base"]];
    if (candidateReady) wanted.push([candidateKey, "candidate"]);
    for (const [key, choice] of wanted) {
      if (cache[key]) continue;
      api.replayBypass(labId, runId, choice)
        .then((r) => setCache((c) => ({ ...c, [key]: r })))
        .catch((e) => setCache((c) => ({
          ...c, [key]: { error: e instanceof api.ApiError ? e.message : "Couldn't load the replay." } })));
    }
  }, [labId, runId, candidateReady, baseKey, candidateKey, cache]);

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

  // What reached cash-out (every transfer from this bank to another bank), as a share of what was stolen
  // (every transfer from another bank into this one).
  const reachedCents = chain.txs.filter((t) => chain.owned.has(t.from_id) && !chain.owned.has(t.to_id))
    .reduce((s, t) => s + t.amount_cents, 0);
  const stolenCents = chain.txs.filter((t) => !chain.owned.has(t.from_id) && chain.owned.has(t.to_id))
    .reduce((s, t) => s + t.amount_cents, 0);
  const share = stolenCents ? `${Number(((reachedCents / stolenCents) * 100).toFixed(1))}% of stolen funds` : null;
  const insideCount = chain.order.filter((id) => chain.owned.has(id)).length;
  const { bars } = timeline(chain);
  const why = silenceSentence(bars, baseRules ? ruleTimeLimits(baseRules) : [], bypass);

  const toggle = (choice: View, label: string, disabled: boolean) => (
    <span title={disabled ? "Ask Blue for a fix first" : undefined} className="min-w-0 flex-1">
      <button onClick={() => setView(choice)} disabled={disabled} aria-pressed={shown === choice}
        className={`w-full rounded-[2px] border px-3 py-2 text-[14px] disabled:cursor-not-allowed disabled:opacity-40 ${
          shown === choice ? "border-lavender bg-lavender-panel text-lavender" : "border-line text-muted hover:text-ink"}`}>
        {label}
      </button>
    </span>
  );

  return (
    <StepCard id="attack-path" label="Red agent finding" labelTone="coral"
      title={
        <span className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
          Attack path
          {!replay ? <Chip tone="muted">Replaying</Chip>
            : replay.alert ? <Chip tone="mint">Caught</Chip> : <Chip tone="coral">Slipped through</Chip>}
        </span>
      }
      subtitle={replay?.alert
        ? `${replay.detector_label} flags this ${insideCount}-account chain at hop ${replay.alert_hop_index} of ${chain.transfers.length}.`
        : `A ${insideCount}-account mule chain moved funds outside the bank without triggering a rule.`}>
      <div className="mb-5 flex gap-2">
        {toggle("base", v1Label, false)}
        {toggle("candidate", v2Label, !candidateReady)}
      </div>

      {/* Bleeds to the card edges, like the mockup's "Escaped undetected" block. */}
      <div className="-mx-7 mb-6">
        {failed ? (
          <div className="flex items-center justify-between gap-3 border-y border-coral/40 bg-red-panel px-7 py-5 text-[15px] text-coral">
            <span>{failed}</span>
            <button className="shrink-0 underline" onClick={() => setCache((c) => {
              const next = { ...c };
              delete next[shownKey];
              return next;
            })}>Try again</button>
          </div>
        ) : !replay ? (
          <div className="border-y border-line bg-card-raised px-7 py-6 text-[15px] text-muted">Replaying the attack…</div>
        ) : replay.alert ? (
          <div className="border-y border-mint/30 bg-green-panel px-7 py-6">
            <p className="label-caps text-mint">Caught by {replay.triggered_rule_ids.join(", ")}</p>
            <p className="mt-2 text-[44px] leading-none tabular-nums text-mint">{wholeDollars(reachedCents)}</p>
            <p className="mt-3 text-[15px] tabular-nums text-muted">
              flagged at hop {replay.alert_hop_index}{share && ` · ${share}`}
            </p>
            {firedReason(replay, baseRules, patch) && (
              <p className="mt-1 text-[15px] text-ink">{firedReason(replay, baseRules, patch)}</p>
            )}
          </div>
        ) : (
          <div className="border-y border-coral/30 bg-red-panel px-7 py-6">
            <p className="label-caps text-coral">Escaped undetected</p>
            <p className="mt-2 text-[44px] leading-none tabular-nums text-coral">{wholeDollars(reachedCents)}</p>
            {share && <p className="mt-3 text-[15px] tabular-nums text-muted">{share}</p>}
          </div>
        )}
      </div>

      <Chain chain={chain} replay={replay} />

      <div className="mt-6 flex gap-3 border-t border-line pt-5">
        <span className="mt-0.5 shrink-0 text-coral">{ClockIcon}</span>
        <div>
          <p className="text-[16px] text-ink">Why it worked</p>
          <p className="text-[15px] leading-snug text-muted">{why}</p>
        </div>
      </div>

      <ul className="mt-5 space-y-1.5 text-[13px] text-muted">
        <li className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span className="flex items-center gap-1.5"><span className="inline-block h-3 w-3 rounded-[1px] border border-line bg-card-raised" /> Our bank (source, mules)</span>
          <span className="flex items-center gap-1.5"><span className="inline-block h-3 w-3 rounded-[1px] border border-dashed border-muted/60" /> Other bank</span>
        </li>
        {otherCustomers !== null && (
          <li className="flex items-center gap-1.5">
            <span className="rounded-full border border-line px-1.5 tabular-nums">+{otherCustomers}</span> other customers, collapsed
          </li>
        )}
        <li>Mule: an account used to pass stolen money along</li>
      </ul>

      {approval?.rechallenge && <div className="mt-5"><RechallengeBanner rechallenge={approval.rechallenge} /></div>}

      <button onClick={onRerun} disabled={loading} className={`${BUTTON_ATTACK} mt-6 w-full`}>Run Red again</button>
    </StepCard>
  );
}
