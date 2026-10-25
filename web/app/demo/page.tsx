"use client";

import Link from "next/link";
import { useState } from "react";
import capture from "./capture.json";
import "./demo.css";

const stages = [
  { name: "Build the bank", actor: "Simulator", title: "Start with a safe, synthetic bank.", explanation: "Create normal customer activity and known fraud examples. Every account, transaction and dollar in this walkthrough is simulated.", handoff: "A reproducible world → the current fraud detector" },
  { name: "Find the blind spot", actor: "Current rules · v1", title: "Fast fraud is caught. Slow fraud slips through.", explanation: "The baseline checks three examples against the same rules. This establishes the weakness before either agent proposes a change.", handoff: "The current rules and their limits → Red" },
  { name: "Red attacks", actor: "Red · Attacker", title: "Move the money slowly enough to avoid an alarm.", explanation: "Red spaces transfers across mule accounts. Each short-window rule stays silent, even though the complete path reveals suspicious movement.", handoff: "Successful attack + rule-by-rule evidence → Blue" },
  { name: "Blue proposes", actor: "Blue · Defender", title: "Look at the whole chain, not just one account.", explanation: "Blue proposes R4: flag a chain of at least 4 transfers within 72 hours, with each hop holding funds under 24 hours and forwarding at least 40%.", handoff: "A validated rule proposal → independent evaluation" },
  { name: "Code evaluates", actor: "Deterministic evaluator", title: "Does the fix catch more fraud without more false alarms?", explanation: "The evaluator runs the current and proposed rules on identical held-out attacks and normal households. The agents do not calculate these scores.", handoff: "Measured results + safety gates → you" },
  { name: "You decide", actor: "Human reviewer", title: "A proposal becomes active only with your approval.", explanation: "Review the evidence, then choose a branch. Approval activates v2 in this recorded lab. Rejection keeps v1. Neither agent can make this decision.", handoff: "Your decision → versioned detector and audit event" },
  { name: "Rechallenge", actor: "Fresh independent attack", title: "Close the loop with an attack the agents did not use.", explanation: "A fresh slow-chain attack is tested against the detector selected by your decision. The stored audit trail preserves the entire round.", handoff: "New evidence → the next testing round" },
];
const money = (cents: number) => (cents / 100).toLocaleString("en-US", { style: "currency", currency: "USD" });

export default function Demo() {
  const [step, setStep] = useState(0);
  const [decision, setDecision] = useState<"approve" | "reject" | null>(null);
  const [evidence, setEvidence] = useState(false);
  const data = capture[decision ?? "approve"];
  const stage = stages[step];
  const before = data.report.baseline_confusion.final_holdout;
  const after = data.report.candidate_confusion.final_holdout;
  const bypass = data.red.bypass;
  const passed = data.report.eligible_for_approval;
  const version = step === 6 && decision === "approve" ? 2 : 1;

  function restart() { setStep(0); setDecision(null); setEvidence(false); }

  return (
    <main className="demo-page">
      <header className="demo-header">
        <Link href="/" className="demo-brand">SENTINEL <span>/ Workflow demo</span></Link>
        <span className="demo-tag">SYNTHETIC DATA · RECORDED RUN</span>
        <Link href="/">Open interactive lab ↗</Link>
      </header>
      <div className="demo-intro">
        <p className="label-caps text-muted">Attack → repair → test → human decision</p>
        <h1>Watch a fraud rule get stronger.</h1>
        <p>A complete, seven-step walkthrough. Fixture agents propose; real evaluator code scores; you choose the outcome.</p>
      </div>
      <nav aria-label="Demo stages" className="demo-stages">
        {stages.map((s, i) => <button key={s.name} aria-current={step === i ? "step" : undefined} disabled={i === 6 && !decision} onClick={() => setStep(i)}><span>{String(i + 1).padStart(2, "0")}</span>{s.name}</button>)}
      </nav>
      <section className="demo-scene" aria-label={`Step ${step + 1}: ${stage.name}`}>
        <div className="demo-narration" aria-live="polite">
          <p className={`label-caps ${step === 2 ? "text-coral" : step === 3 ? "text-lavender" : "text-muted"}`}>{stage.actor} · Step {step + 1} / 7</p>
          <h2>{stage.title}</h2>
          <p>{stage.explanation}</p>
          <div className="demo-handoff"><span className="label-caps">What moves forward</span><p>{stage.handoff}</p></div>
          <div className="demo-version">Active detector <strong>v{version}</strong><span>{step === 3 || step === 4 || step === 5 ? "R4 is only a proposal" : "Versioned rules"}</span></div>
        </div>
        <div className="demo-visual">
          {step === 0 && <><p className="label-caps text-muted">Community Credit Union · Seed 7</p><div className="demo-stats">{Object.entries(data.lab.world).map(([name, value]) => <div key={name}><strong>{value.toLocaleString()}</strong><span>{name}</span></div>)}</div><div className="demo-callout">Same seed. Same bank. Reproducible evidence.</div></>}
          {step === 1 && <><p className="label-caps text-muted">Three baseline checks · Detector v1</p>{data.baseline.results.map((r, i) => <div className="demo-result" key={r.scenario_id}><div><strong>{["Fast mule ring", "Slow mule chain", "Legitimate lookalike"][i]}</strong><p>{["Many rapid transfers", "Money waits between transfers", "Normal customer behavior"][i]}</p></div><span className={i === 1 ? "text-coral" : "text-lavender"}>{r.alert ? `Caught · ${r.triggered_rule_ids.join(", ")}` : i === 1 ? "Missed" : "Correctly clear"}</span></div>)}<div className="demo-callout">The gap: the rules inspect short windows; the attack stretches across hours.</div></>}
          {step === 2 && <><div className="demo-money"><strong>{money(bypass.moved_cents)}</strong><span>moved without an alarm · goal {money(bypass.objective_cents)}</span></div><ol className="demo-chain">{bypass.scenario.transactions.map((t, i) => <li key={t.transaction_id}><span>{i + 1}</span><div><strong>{t.from_id} → {t.to_id}</strong><p>{money(t.amount_cents)} · +{((t.timestamp - bypass.scenario.transactions[0].timestamp) / 3600).toFixed(1)}h</p></div></li>)}</ol><div className="demo-callout">R1, R2 and R3 stay silent. Red hands this trace to Blue.</div></>}
          {step === 3 && <><p className="label-caps text-lavender">Proposed rule change</p><div className="demo-rule"><span>KEEP</span><strong>R1 + R2 + R3</strong><p>Existing protections stay in place.</p></div><div className="demo-rule added"><span>+ ADD R4</span><strong>Follow the money across accounts</strong><p>4+ transfers · 72-hour window<br />Each hold &lt; 24h · Each carry ≥ 40%</p></div><div className="demo-callout">Proposal validated. Detector v1 is still active.</div></>}
          {step === 4 && <><table className="demo-table"><caption>Held-out evaluation · {data.report.attack_n} attacks / {data.report.benign_n} normal households</caption><thead><tr><th>Measure</th><th>v1</th><th>v1 + R4</th></tr></thead><tbody><tr><th>Attacks caught</th><td>{before.tp}/{data.report.attack_n}</td><td className="text-lavender">{after.tp}/{data.report.attack_n}</td></tr><tr><th>Normal households flagged</th><td>{before.fp}/{data.report.benign_n}</td><td>{after.fp}/{data.report.benign_n}</td></tr><tr><th>Attacks still missed</th><td>{before.fn}</td><td>{after.fn}</td></tr></tbody></table><div className="demo-gates">{data.report.gate_results.map(g => <div key={g.name}><span>{g.passed ? "✓" : "✕"} {g.name.replaceAll("_", " ")}</span><small>{g.detail}</small></div>)}</div></>}
          {step === 5 && <><p className="label-caps text-muted">Decision checkpoint</p><div className="demo-money"><strong>{after.tp - before.tp} more attacks caught</strong><span>{after.fp - before.fp} additional normal households flagged</span></div><div className="demo-callout">{passed ? "All safety gates passed. The proposal is eligible for approval." : "A safety gate failed. Approval is blocked."}</div><div className="demo-decisions"><button className="review-button review-button-primary" disabled={!passed} onClick={() => { setDecision("approve"); setStep(6); }}>Approve → activate v2</button><button className="review-button review-button-secondary" onClick={() => { setDecision("reject"); setStep(6); }}>Reject → keep v1</button></div><p className="demo-footnote">This chooses a recorded branch. It does not change your live lab.</p></>}
          {step === 6 && <><p className="label-caps text-muted">Decision: {decision === "approve" ? "approved" : "rejected"} · v{data.approval.active_version} active</p><div className="demo-outcome"><span className={data.approval.rechallenge?.alert ? "text-lavender" : "text-coral"}>{data.approval.rechallenge?.alert ? "Caught." : "Missed."}</span><p>{data.approval.rechallenge?.alert ? `The fresh attack triggers ${data.approval.rechallenge.triggered_rule_ids.join(", ")}. The approved defense closes this gap.` : "The same blind spot remains because the proposed defense was rejected."}</p></div><div className="demo-callout">{after.fn} of {data.report.attack_n} held-out attacks still evade the proposed rules. This fix improves coverage; it does not catch everything.</div><button className="review-button review-button-secondary" onClick={() => setEvidence(!evidence)} aria-expanded={evidence}>{evidence ? "Hide" : "Show"} recorded audit trail</button>{evidence && <ol className="demo-audit">{data.run.events.map(e => <li key={e.event_id}><span>{e.actor}</span> {e.action}</li>)}</ol>}</>}
        </div>
      </section>
      <footer className="demo-controls"><button className="review-button review-button-secondary" onClick={restart}>Restart demo</button><span aria-live="polite">{step + 1} of 7 · {stage.name}</span><div><button className="review-button review-button-secondary" disabled={step === 0} onClick={() => setStep(step - 1)}>← Back</button>{step < 5 && <button className="review-button review-button-primary" onClick={() => setStep(step + 1)}>Next: {stages[step + 1].name} →</button>}{step === 6 && <button className="review-button review-button-primary" onClick={() => setStep(5)}>Try the other decision</button>}</div></footer>
      <p className="demo-provenance">Offline replay of real seed-7 API results · Red and Blue use fixed fixture proposals · Metrics come from the deterministic evaluator · No live model calls</p>
    </main>
  );
}
