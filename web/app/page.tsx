"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import * as api from "./api";
import ApprovalStep from "./components/ApprovalStep";
import BaselineStep from "./components/BaselineStep";
import BlueStep from "./components/BlueStep";
import ErrorBanner from "./components/ErrorBanner";
import EvidenceLog, { formatUtc } from "./components/EvidenceLog";
import IntroCard, { useIntroDismissed } from "./components/IntroCard";
import NetworkMap from "./components/NetworkMap";
import RedStep, { WhyItGotThrough } from "./components/RedStep";
import ScorecardStep from "./components/ScorecardStep";
import SetupCard from "./components/SetupCard";
import { BUTTON_SECONDARY } from "./components/StepCard";
import WorkflowNav from "./components/WorkflowNav";
import TestIntegrity from "./components/TestIntegrity";

type Step = "setup" | "baseline" | "red" | "blue" | "evaluate" | "decide";
type StepError = { step: Step; message: string; detail: string | null; retry: () => void };
type Tab = "review" | "evidence";

export default function Home() {
  const [seed, setSeed] = useState(7);
  const [accounts, setAccounts] = useState(200);
  const [labId, setLabId] = useState<string | null>(null);
  const [labSeed, setLabSeed] = useState<number | null>(null);
  const [activeVersion, setActiveVersion] = useState<number | null>(null);
  const [world, setWorld] = useState<api.World | null>(null);
  const [baseline, setBaseline] = useState<api.BaselineResult[] | null>(null);
  const [redRun, setRedRun] = useState<api.RedRun | null>(null);
  const [patchRun, setPatchRun] = useState<api.PatchRun | null>(null);
  const [patchId, setPatchId] = useState<string | null>(null);
  const [report, setReport] = useState<api.EvaluationReport | null>(null);
  const [approval, setApproval] = useState<api.Approval | null>(null);
  const [runRecord, setRunRecord] = useState<api.RunRecord | null>(null);
  const [tab, setTab] = useState<Tab>("review");
  const [introDismissed, setIntroDismissed] = useIntroDismissed();
  const [agentModes, setAgentModes] = useState<api.AgentModes | null>(null);
  const [loading, setLoading] = useState(false);
  const [runningStep, setRunningStep] = useState<Step | null>(null);
  const [error, setError] = useState<StepError | null>(null);
  // The run whose rechallenge is being polled; cleared when the round is reset so stale polls stop.
  const pollingRun = useRef<string | null>(null);
  // A fresh object each time, so asking for the same target twice still scrolls.
  const [scrollTarget, setScrollTarget] = useState<{ id: string } | null>(null);

  useEffect(() => {
    let active = true;
    api.getAgentModes().then((modes) => { if (active) setAgentModes(modes); }).catch(() => {});
    return () => { active = false; };
  }, []);

  // Scroll to the next step once it has rendered, unless it's already comfortably on screen.
  useEffect(() => {
    if (!scrollTarget) return;
    const el = document.getElementById(scrollTarget.id);
    if (!el) return;
    for (let parent = el.parentElement; parent; parent = parent.parentElement) {
      if (parent instanceof HTMLDetailsElement) parent.open = true;
    }
    const { top } = el.getBoundingClientRect();
    if (top < 100 || top > window.innerHeight * 0.6) {
      el.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "start" });
    }
  }, [scrollTarget]);

  // Runs one step. On failure, the error is pinned to that step with a way to re-run it.
  async function run(step: Step, retry: () => void, action: () => Promise<void>) {
    setLoading(true);
    setRunningStep(step);
    setError(null);
    try {
      await action();
    } catch (e) {
      const known = e instanceof api.ApiError;
      setError({
        step,
        message: known ? e.message : "Something went wrong in the page.",
        detail: known ? e.detail : null,
        retry,
      });
    } finally {
      setLoading(false);
      setRunningStep(null);
    }
  }

  // The run's audit trail, for the Evidence log and the status line. Read-only; a failure here
  // never blocks a step, the log just stays as it was.
  function refreshRun(runId: string) {
    api.getRun(runId).then(setRunRecord).catch(() => {});
  }

  function createLab() {
    pollingRun.current = null;
    setBaseline(null);
    setRedRun(null);
    setPatchRun(null);
    setPatchId(null);
    setReport(null);
    setApproval(null);
    setRunRecord(null);
    return run("setup", createLab, async () => {
      const lab = await api.createLab(seed, accounts);
      setLabId(lab.lab_id);
      setLabSeed(seed);
      setActiveVersion(lab.active_detector_version);
      setWorld(lab.world);
      setScrollTarget({ id: "step-baseline" });
    });
  }

  function runBaseline() {
    if (!labId) return;
    return run("baseline", runBaseline, async () => {
      setBaseline(await api.runBaseline(labId));
      setScrollTarget({ id: "step-red" });
    });
  }

  function runRed() {
    if (!labId) return;
    pollingRun.current = null;
    setRunRecord(null);
    setPatchRun(null);
    setPatchId(null);
    setReport(null);
    setApproval(null);
    return run("red", runRed, async () => {
      const result = await api.startRedRun(labId);
      setRedRun(result);
      refreshRun(result.run_id);
      setScrollTarget({ id: result.bypass ? "attack-path" : "step-red" });
    });
  }

  function askBlue() {
    if (!labId || !redRun?.bypass) return;
    const { run_id, bypass } = redRun;
    setReport(null);
    setApproval(null);
    return run("blue", askBlue, async () => {
      const result = await api.proposePatches(labId, run_id, bypass.bypass_id);
      const firstValid = result.patches.find((p) => p.valid)?.patch.patch_id ?? null;
      setPatchRun(result);
      setPatchId(firstValid);
      refreshRun(run_id);
      setScrollTarget({ id: firstValid ? "step-evaluate" : "step-blue" });
    });
  }

  function evaluate() {
    if (!labId || !redRun || !patchId) return;
    setApproval(null);
    return run("evaluate", evaluate, async () => {
      setReport(await api.evaluatePatch(labId, redRun.run_id, patchId));
      refreshRun(redRun.run_id);
      setScrollTarget({ id: "scorecard" });
    });
  }

  // The decision is saved before the rechallenge runs; poll the run until its result appears.
  async function pollRechallenge(runId: string) {
    pollingRun.current = runId;
    for (let i = 0; i < 60 && pollingRun.current === runId; i++) {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      try {
        const rechallenge = await api.getRechallenge(runId);
        if (rechallenge && pollingRun.current === runId) {
          setApproval((a) => a && { ...a, rechallenge, completion_pending: false });
          refreshRun(runId);
          return;
        }
      } catch {
        // A blip while the backend works; keep polling.
      }
    }
    if (pollingRun.current === runId) setApproval((a) => a && { ...a, completion_pending: false });
  }

  function decide(decision: api.Decision) {
    if (!labId || !report || !redRun) return;
    const runId = redRun.run_id;
    return run("decide", () => decide(decision), async () => {
      const result = await api.decide(labId, report.report_id, decision);
      setApproval(result);
      setActiveVersion(result.active_version);
      refreshRun(runId);
      setScrollTarget({ id: "approval-result" });
      if (result.completion_pending && !result.rechallenge) void pollRechallenge(runId);
    });
  }

  function errorFor(step: Step) {
    if (error?.step !== step) return null;
    return <ErrorBanner message={error.message} detail={error.detail} onRetry={error.retry} loading={loading} />;
  }

  function openMethodology() {
    setIntroDismissed(false);
    setTab("review");
    setScrollTarget({ id: "intro" });
  }

  // Where the round is, for the status line under the header.
  const runId = redRun?.run_id ?? null;
  const complete = runRecord?.state === "complete" || !!approval?.rechallenge;
  const status = complete ? `Simulation complete · Run ${runId}`
    : approval ? `Running the rechallenge · Run ${runId}`
      : report ? `Awaiting your decision · Run ${runId}`
        : patchId ? "Ready to evaluate Blue's proposal"
          : patchRun ? "Blue found no valid fix"
            : redRun?.bypass ? "Ready for Blue's proposal"
              : redRun ? "Rules held · Red found no gap"
                : baseline ? "Ready for the Red challenge"
                  : labId ? "Ready to run baseline"
                    : "Ready to create a lab";
  // The real completion time: the last audit event of a run the backend marks complete.
  const lastEvent = runRecord?.events.at(-1);
  const completedAt = runRecord?.state === "complete" && lastEvent ? formatUtc(lastEvent.timestamp, true) : null;
  const evaluatedPatch = patchRun?.patches.find((p) => p.patch.patch_id === report?.patch_id)?.patch ?? null;
  const roundUnderway = !!redRun?.bypass;
  const nextStep = complete
    ? { number: 6, title: "Round complete", detail: "Compare the attack before and after the fix, or run Red again.", target: "attack-path", action: "View attack" }
    : approval
      ? { number: 6, title: "Your decision is saved", detail: "A fresh attack is being tested. You do not need to approve again.", target: "approval-result", action: "View decision" }
      : report
        ? { number: 6, title: "Review the results and decide", detail: report.eligible_for_approval ? "The checks passed. Approve to activate the fix in this lab, or reject to keep the current rules." : "A safety check failed. Review the results; this proposal cannot be approved.", target: "step-approval", action: "Review decision" }
        : patchId
          ? { number: 5, title: "Independently test Blue’s proposal", detail: "Blue has suggested a rule. Deterministic code now tests it on unseen attacks and normal customers; neither agent decides whether it passes.", target: "step-evaluate", action: "Go to evaluation" }
          : patchRun
            ? { number: 4, title: "Blue found no valid proposal", detail: "Review the rejected proposals, then start another Red challenge if you want a new round.", target: "step-blue", action: "View proposals" }
            : redRun?.bypass
              ? { number: 4, title: "Hand Red’s finding to Blue", detail: "Red found a way past the rules. Ask the Blue agent to propose a fix; it will not change the active detector.", target: "step-blue", action: "Go to Blue" }
              : baseline
                ? { number: 3, title: redRun ? "Red found no gap this round" : "Start the Red challenge", detail: "Start Red below. It tests attacks against the current rules and can revise its approach across several turns.", target: "step-red", action: "Go to Red" }
                : labId
                  ? { number: 2, title: "Test the current rules", detail: "Run the baseline first to see what the detector already catches and misses.", target: "step-baseline", action: "Go to baseline" }
                  : { number: 1, title: "Start by creating a lab", detail: "This sets up the fake bank both agents will work with. Leave seed 7 and 200 accounts for your first walkthrough, then choose Create lab.", target: "step-setup", action: "Go to setup" };

  const runningSteps: Record<Step, { number: number; title: string }> = {
    setup: { number: 1, title: "Creating the synthetic bank" },
    baseline: { number: 2, title: "Checking the current fraud rules" },
    red: { number: 3, title: "Red is testing attack candidates" },
    blue: { number: 4, title: "Blue is testing and refining its proposal" },
    evaluate: { number: 5, title: "Independent tests are running" },
    decide: { number: 6, title: "Recording your decision and rechallenging" },
  };
  const visibleStep = runningStep ? {
    ...nextStep, ...runningSteps[runningStep],
    detail: "This step is running. The result will appear below; you do not need to click again.",
  } : nextStep;

  const workflowItems = [
    { title: "Create lab", detail: "Build the synthetic bank", target: "step-setup", enabled: true },
    { title: "Baseline", detail: "Check existing rules", target: "step-baseline", enabled: !!labId },
    { title: "Red agent", detail: "Find a way through", target: roundUnderway ? "attack-path" : "step-red", enabled: !!baseline },
    { title: "Blue agent", detail: "Propose a defense", target: "step-blue", enabled: roundUnderway },
    { title: "Independent test", detail: "Measure the proposal", target: report ? "scorecard" : "step-evaluate", enabled: !!patchId },
    { title: "Your decision", detail: "Approve or reject", target: "step-approval", enabled: !!report },
  ];

  return (
    <main className="min-h-screen w-full bg-page text-ink">
      <header className="review-header">
        <div className="review-shell review-header-inner">
          <div className="flex items-center gap-3">
            <Image src="/sentinel-logo.png" alt="" width={868} height={662} priority className="h-7 w-auto" />
            <span className="text-[16px] tracking-[0.2em]">SENTINEL</span>
          </div>
          <span className="label-caps border-l border-line pl-6 text-muted">Synthetic environment</span>
          <div className="ml-auto flex flex-wrap items-center gap-6 text-[12px]">
            <Link href="/demo" className="text-lavender hover:text-ink">Workflow demo ↗</Link>
            <button onClick={openMethodology} className="text-muted hover:text-ink">Methodology</button>
            <span className="flex items-center gap-2">
              {activeVersion && <span aria-hidden="true" className="live-signal" />}
              {activeVersion ? `Detector v${activeVersion} active` : "No lab yet"}
            </span>
          </div>
        </div>
      </header>

      <div className="review-shell">
        <div className="review-hero">
          <div>
            <p className="label-caps mb-5 text-muted">Red team / Blue team</p>
            <h1>Rule change review</h1>
            <p className="hero-copy mt-6">Red finds a weakness. Blue proposes a fix. Independent tests check it. You decide.</p>
          </div>
          <section aria-label="Who does what" className="team-board">
            <div className="team-unit">
              <span aria-hidden="true" className="team-avatar red">R</span>
              <div>
                <h2><span className="text-coral">Red agent</span> · Attacker</h2>
                <p>Tries synthetic attacks to find a gap in the bank&apos;s fraud rules.</p>
              </div>
            </div>
            <div className="team-handoff">Attack evidence → Proposed defense</div>
            <div className="team-unit">
              <span aria-hidden="true" className="team-avatar blue">B</span>
              <div>
                <h2><span className="text-lavender">Blue agent</span> · Defender</h2>
                <p>Proposes a fix, tests it on development data, and revises from the feedback. It cannot activate the fix.</p>
              </div>
            </div>
            <div className="team-human">
              <p className="label-caps text-ink">You · Reviewer</p>
              <p className="mt-2 text-[12px] leading-relaxed text-muted">Review the independent test results, then approve or reject Blue&apos;s proposal.</p>
            </div>
          </section>
        </div>

        <div className="review-facts">
          <span>Environment <strong className="ml-2">Community Credit Union</strong></span>
          <span>Seed <strong className="ml-2">{labSeed ?? "—"}</strong></span>
          {world && <span>Accounts <strong className="ml-2">{world.accounts.toLocaleString()}</strong></span>}
          <span>Mode <strong className="ml-2">Guided workflow</strong></span>
          {agentModes?.red_policy && <span>Red <strong className="ml-2">{agentModes.red_policy === 'llm' ? 'LLM agent' : agentModes.red_policy === 'heuristic' ? 'Heuristic search' : agentModes.red_policy}</strong></span>}
          {agentModes && <span>Blue <strong className="ml-2">{agentModes.llm === 'fixture' ? 'Fixture demo' : `${agentModes.llm} agent`}</strong></span>}
          {completedAt && <span>Completed <strong className="ml-2">{completedAt}</strong></span>}
        </div>

        <nav className="review-tabs" aria-label="Review views">
          {(["review", "evidence"] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)} aria-current={tab === t ? "page" : undefined} className="flex items-center gap-2">
              {t === "review" ? "Review" : "Evidence log"}
              {t === "evidence" && runRecord && <span className="font-mono text-[10px] text-muted">{runRecord.events.length}</span>}
            </button>
          ))}
        </nav>

        {tab === "evidence" ? (
          <div className="pb-16"><EvidenceLog events={runRecord?.events ?? null} runId={runId} /></div>
        ) : (
          <div className="workflow-layout">
            <WorkflowNav items={workflowItems} current={visibleStep.number} complete={complete && !loading}
              onNavigate={(id) => setScrollTarget({ id })} />
            <div className="workflow-content">
              <section aria-label="Next step" className="next-action">
                <div className="min-w-0 max-w-[58ch]">
                  <p className="label-caps mb-2 text-muted">{loading ? "In progress" : complete ? "Completed" : "Next"} · Step {visibleStep.number} of 6</p>
                  <h2>{visibleStep.title}</h2>
                  <p className="mt-2 text-[13px] leading-relaxed text-muted">{visibleStep.detail}</p>
                  <p className="mt-3 font-mono text-[10px] text-muted" role="status">{status}</p>
                </div>
                <button disabled={loading} className={BUTTON_SECONDARY} onClick={() => setScrollTarget({ id: nextStep.target })}>
                  {nextStep.action} <span aria-hidden="true">↓</span>
                </button>
              </section>

              {!introDismissed && <IntroCard onDismiss={() => setIntroDismissed(true)} />}
              {!roundUnderway && (
                <>
                  <SetupCard seed={seed} accounts={accounts} onSeedChange={setSeed} onAccountsChange={setAccounts}
                    onCreate={createLab} loading={loading} created={!!labId} world={world} />
                  {errorFor("setup")}
                  {labId && <BaselineStep results={baseline} onRun={runBaseline} loading={loading} />}
                  {errorFor("baseline")}
                  {baseline && <RedStep redRun={redRun} onRun={runRed} loading={loading} />}
                  {errorFor("red")}
                </>
              )}

              {roundUnderway && redRun?.bypass && (
                <>
                  <div className="agent-workspace">
                    <div className="min-w-0">
                      <NetworkMap labId={labId} runId={runId} bypass={redRun.bypass} baseRules={redRun.rules}
                        patch={evaluatedPatch} candidateReady={!!report} approval={approval}
                        otherCustomers={world?.customers ?? null} onRerun={runRed} loading={loading}
                        searchHistory={redRun.history} turns={redRun.turns} />
                      {errorFor("red")}
                    </div>
                    <div className="min-w-0">
                      <BlueStep patchRun={patchRun} selectedPatchId={patchId} onAsk={askBlue} loading={loading} />
                      {errorFor("blue")}
                    </div>
                  </div>
                  {patchId && <ScorecardStep report={report} onEvaluate={evaluate} loading={loading} />}
                  {errorFor("evaluate")}
                  {report && <ApprovalStep report={report} approval={approval} onDecide={decide} loading={loading} />}
                  {errorFor("decide")}
                  <details className="review-disclosure">
                    <summary>Attack analysis · Why did Red get through?</summary>
                    <WhyItGotThrough redRun={redRun} />
                  </details>
                  <details className="review-disclosure">
                    <summary>Test integrity · What could the agents see?</summary>
                    <TestIntegrity />
                  </details>
                  <details className="review-disclosure">
                    <summary>Lab settings and baseline results</summary>
                    <div className="grid gap-6">
                      <SetupCard compact seed={seed} accounts={accounts} onSeedChange={setSeed} onAccountsChange={setAccounts}
                        onCreate={createLab} loading={loading} created={!!labId} world={world} />
                      {errorFor("setup")}
                      <BaselineStep results={baseline} onRun={runBaseline} loading={loading} />
                    </div>
                  </details>
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
