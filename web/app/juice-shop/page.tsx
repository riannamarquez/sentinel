"use client";

import Link from "next/link";
import { useState } from "react";
import capture from "./juice-capture.json";
import "../demo/demo.css";
import "./juice.css";

// --- the purple-team loop, told in seven steps -----------------------------
const stages = [
  { name: "The target", actor: "Recon", title: "A shop built to be broken.", explanation: "OWASP Juice Shop is a deliberately vulnerable web app used to train defenders. Sentinel points its Red and Blue agents at a copy running on localhost — never a system you don't own.", handoff: "A reachable target → the Red agent" },
  { name: "Red scans", actor: "Red · Attacker", title: "Five exploits, each one confirmed.", explanation: "Red fires one probe per known weakness and keeps only the attacks that actually fire. Every finding carries the exact request that triggered it, and maps to an OWASP Top 10 category.", handoff: "Confirmed findings + request evidence → Blue" },
  { name: "Trace the critical", actor: "Red · Attacker", title: "Log in as admin with no password.", explanation: "The login query is built by string concatenation, so an email of ' OR 1=1-- comments out the password check. Red proves it by getting a real auth token back — it confirms the hole, it doesn't loot the database.", handoff: "The captured bypass request → Blue" },
  { name: "Blue proposes", actor: "Blue · Defender", title: "Fix the code, and shield it right now.", explanation: "For each finding Blue answers twice: the real source-level fix you'd merge, and a compensating edge control it can enforce immediately — before anyone touches the source.", handoff: "A code fix + an active control per finding → the evaluator" },
  { name: "Code verifies", actor: "Deterministic replay", title: "Does the control actually stop the attack?", explanation: "Sentinel replays every finding's recorded request through Blue's now-active controls. A finding counts as mitigated only if the attack is really blocked. The agents don't grade themselves — the replay does.", handoff: "Verified results → you" },
  { name: "You decide", actor: "Human reviewer", title: "Controls go live only with your approval.", explanation: "Review the evidence, then choose. Approval deploys Blue's controls in this recorded lab; rejection leaves the app exposed. Neither agent can make this call.", handoff: "Your decision → a defended or exposed app" },
  { name: "Rechallenge", actor: "Fresh replay", title: "Re-run the critical attack through your choice.", explanation: "The same admin-bypass request is sent one more time, against the defense your decision selected. The loop closes with proof, not a promise.", handoff: "New evidence → the next round" },
];

type Finding = (typeof capture.findings)[number];
type Remediation = (typeof capture.remediations)[number];

const SEV_TONE: Record<string, string> = { critical: "text-coral", high: "text-coral", medium: "text-amber", low: "text-muted", info: "text-muted" };
const remById = Object.fromEntries(capture.remediations.map((r) => [r.finding_id, r])) as Record<string, Remediation>;
const mitigated = new Set(capture.mitigated_ids);
const critical = (capture.findings.find((f) => f.severity === "critical") ?? capture.findings[0]) as Finding;

function Diff({ before, after }: { before: string; after: string }) {
  return (
    <pre className="juice-diff">
      <span className="label-caps">code fix · before → after</span>
      {before.split("\n").map((l, i) => <span className="rm" key={"b" + i}>- {l || " "}</span>)}
      {after.split("\n").map((l, i) => <span className="add" key={"a" + i}>+ {l || " "}</span>)}
    </pre>
  );
}

export default function Demo() {
  const [step, setStep] = useState(0);
  const [decision, setDecision] = useState<"approve" | "reject" | null>(null);
  const [openId, setOpenId] = useState<string | null>(critical.id);

  const stage = stages[step];
  const defended = decision === "approve";
  const rem = remById[critical.id];

  function restart() { setStep(0); setDecision(null); setOpenId(critical.id); }

  return (
    <main className="demo-page">
      <header className="demo-header">
        <Link href="/" className="demo-brand">SENTINEL <span>/ Juice Shop · purple-team loop</span></Link>
        <span className="demo-tag">LOCAL TARGET · CONFIRMED EXPLOITS ONLY</span>
        <Link href="/">Open interactive lab ↗</Link>
      </header>

      <div className="demo-intro">
        <p className="label-caps text-muted">Scan → fix → verify → human decision</p>
        <h1>Watch a vulnerable app get defended.</h1>
        <p>Sentinel&apos;s Red agent attacks <a href="https://owasp.org/projects/juice-shop" target="_blank" rel="noopener" className="text-lavender">OWASP Juice Shop</a>; Blue ships a fix and an edge control for each hole; deterministic replay proves every attack is blocked. A seven-step walkthrough of the same red/blue loop, pointed at real web vulnerabilities.</p>
      </div>

      <nav aria-label="Demo stages" className="demo-stages">
        {stages.map((s, i) => (
          <button key={s.name} aria-current={step === i ? "step" : undefined} disabled={i === 6 && !decision} onClick={() => setStep(i)}>
            <span>{String(i + 1).padStart(2, "0")}</span>{s.name}
          </button>
        ))}
      </nav>

      <section className="demo-scene" aria-label={`Step ${step + 1}: ${stage.name}`}>
        <div className="demo-narration" aria-live="polite">
          <p className={`label-caps ${step === 1 || step === 2 ? "text-coral" : step === 3 ? "text-lavender" : "text-muted"}`}>{stage.actor} · Step {step + 1} / 7</p>
          <h2>{stage.title}</h2>
          <p>{stage.explanation}</p>
          <div className="demo-handoff"><span className="label-caps">What moves forward</span><p>{stage.handoff}</p></div>
          <div className="demo-version">
            App state <strong>{step >= 5 && decision ? (defended ? "defended" : "exposed") : "vulnerable"}</strong>
            <span>{step === 3 || step === 4 ? "controls proposed, not yet live" : "localhost only"}</span>
          </div>
        </div>

        <div className="demo-visual">
          {/* 0 — recon */}
          {step === 0 && <>
            <p className="label-caps text-muted">{capture.target} · juice-shop {capture.version}</p>
            <div className="demo-stats">
              <div><strong>{capture.counts.found}</strong><span>probes fired</span></div>
              <div><strong>{Object.keys(capture.counts.by_severity).length}</strong><span>severity tiers hit</span></div>
              <div><strong>4</strong><span>OWASP Top-10 classes</span></div>
              <div><strong>loopback</strong><span>scope enforced</span></div>
            </div>
            <div className="demo-callout">Same target, same probes, reproducible evidence. The client refuses any non-local host unless you explicitly authorise it.</div>
          </>}

          {/* 1 — findings list */}
          {step === 1 && <>
            <p className="label-caps text-muted">Confirmed findings · Red agent</p>
            <ol className="juice-findings">
              {capture.findings.map((f) => (
                <li key={f.id} className={openId === f.id ? "open" : ""}>
                  <button onClick={() => setOpenId(openId === f.id ? null : f.id)}>
                    <span className={`juice-sev ${f.severity}`}>{f.severity}</span>
                    <span className="juice-fname">{f.title}</span>
                    <span className="juice-cat">{f.category.split(" ")[0]}</span>
                  </button>
                  {openId === f.id && <p className="juice-fsum">{f.summary}</p>}
                </li>
              ))}
            </ol>
            <div className="demo-callout">1 critical, 2 high, 1 medium, 1 low — each is a live exploit, not a theoretical warning.</div>
          </>}

          {/* 2 — critical trace */}
          {step === 2 && <>
            <div className="demo-money"><strong className={SEV_TONE[critical.severity]}>{critical.title}</strong><span>{critical.category}</span></div>
            <pre className="juice-evidence">
              <span className="label-caps">captured request → response</span>
              {`${critical.evidence.method} ${critical.evidence.path}`}
              {critical.evidence.body ? "\n" + JSON.stringify(critical.evidence.body) : ""}
              <span className="resp">{`\n↳ ${critical.evidence.status_code}  ${critical.evidence.response_excerpt}`}</span>
            </pre>
            <div className="demo-callout">A 200 with an auth token is the proof. Red stops at confirmation and hands the trace to Blue.</div>
          </>}

          {/* 3 — blue proposes */}
          {step === 3 && <>
            <p className="label-caps text-lavender">Remediation · {rem.title}</p>
            <p className="juice-rationale">{rem.rationale}</p>
            <Diff before={rem.code_fix_before} after={rem.code_fix_after} />
            <div className="juice-control"><span className="label-caps">edge control, live now</span><strong>{rem.rule_name}</strong></div>
            <div className="demo-callout">Blue produced a fix + control for all {capture.counts.found} findings this way. The code is still vulnerable until it ships — the control defends in the meantime.</div>
          </>}

          {/* 4 — verify */}
          {step === 4 && <>
            <table className="demo-table">
              <caption>Replay · every finding&apos;s recorded request re-sent through Blue&apos;s controls</caption>
              <thead><tr><th>Finding</th><th>Control</th><th>Result</th></tr></thead>
              <tbody>
                {capture.findings.map((f) => {
                  const blocked = mitigated.has(f.id);
                  return <tr key={f.id}>
                    <th><span className={`juice-sev ${f.severity}`}>{f.severity}</span> {f.title}</th>
                    <td className="juice-mono">{remById[f.id]?.rule_name ?? "—"}</td>
                    <td className={blocked ? "text-lavender" : "text-coral"}>{blocked ? "✓ blocked" : "✗ residual"}</td>
                  </tr>;
                })}
              </tbody>
            </table>
            <div className="demo-callout">{capture.counts.mitigated} of {capture.counts.found} attacks re-blocked on replay · {capture.counts.residual} residual. The loop closes itself.</div>
          </>}

          {/* 5 — decision */}
          {step === 5 && <>
            <p className="label-caps text-muted">Decision checkpoint</p>
            <div className="demo-money"><strong>{capture.counts.mitigated} of {capture.counts.found} holes closed</strong><span>on verified replay, with 0 residual</span></div>
            <div className="demo-callout">All controls verified against Red&apos;s own requests. Deploying them defends the app immediately while the code fixes are merged.</div>
            <div className="demo-decisions">
              <button className="review-button review-button-primary" onClick={() => { setDecision("approve"); setStep(6); }}>Approve → deploy controls</button>
              <button className="review-button review-button-secondary" onClick={() => { setDecision("reject"); setStep(6); }}>Reject → leave exposed</button>
            </div>
            <p className="demo-footnote">This chooses a recorded branch. It does not change any live system.</p>
          </>}

          {/* 6 — rechallenge */}
          {step === 6 && <>
            <p className="label-caps text-muted">Rechallenge · {defended ? "controls deployed" : "no controls"}</p>
            <div className="demo-outcome">
              <span className={defended ? "text-lavender" : "text-coral"}>{defended ? "Blocked." : "Still in."}</span>
              <p>{defended
                ? `The admin-bypass request is caught by ${rem.rule_name} and rejected with a 403. The same attack that worked in step 3 now fails.`
                : "The bypass still returns an auth token. Nothing was deployed, so the blind spot is exactly where Red left it."}</p>
            </div>
            <div className="demo-callout">{defended
              ? `All ${capture.counts.found} controls stay active. Merge the code fixes to retire them.`
              : `${capture.counts.found} findings remain open. Re-run the decision to deploy Blue's verified controls.`}</div>
            <button className="review-button review-button-secondary" onClick={() => setStep(5)}>Try the other decision</button>
          </>}
        </div>
      </section>

      <footer className="demo-controls">
        <button className="review-button review-button-secondary" onClick={restart}>Restart demo</button>
        <span aria-live="polite">{step + 1} of 7 · {stage.name}</span>
        <div>
          <button className="review-button review-button-secondary" disabled={step === 0} onClick={() => setStep(step - 1)}>← Back</button>
          {step < 5 && <button className="review-button review-button-primary" onClick={() => setStep(step + 1)}>Next: {stages[step + 1].name} →</button>}
        </div>
      </footer>

      <p className="demo-provenance">Offline replay of a real Sentinel run against OWASP Juice Shop · Red reports only confirmed exploits · Mitigations verified by deterministic request replay · Run live with <span className="juice-mono">python run_demo.py --mode live</span></p>
    </main>
  );
}
