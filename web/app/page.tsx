"use client";

import Image from "next/image";
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
import StepCard from "./components/StepCard";
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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<StepError | null>(null);
  // The run whose rechallenge is being polled; cleared when the round is reset so stale polls stop.
  const pollingRun = useRef<string | null>(null);
  // A fresh object each time, so asking for the same target twice still scrolls.
  const [scrollTarget, setScrollTarget] = useState<{ id: string } | null>(null);

  // Scroll to the next step once it has rendered, unless it's already comfortably on screen.
  useEffect(() => {
    if (!scrollTarget) return;
    const el = document.getElementById(scrollTarget.id);
    if (!el) return;
    const { top } = el.getBoundingClientRect();
    if (top < 100 || top > window.innerHeight * 0.6) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [scrollTarget]);

  // Runs one step. On failure, the error is pinned to that step with a way to re-run it.
  async function run(step: Step, retry: () => void, action: () => Promise<void>) {
    setLoading(true);
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

  return (
    <main className="min-h-screen w-full bg-page text-ink">
      <header className="sticky top-0 z-20 border-b border-line bg-page/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1760px] flex-wrap items-center gap-x-6 gap-y-3 px-8 py-4 lg:px-12">
          <div className="flex items-center gap-3">
            <Image src="/sentinel-logo.png" alt="" width={868} height={662} priority className="h-8 w-auto" />
            <span className="text-[22px] tracking-[0.3em] text-ink">SENTINEL</span>
          </div>
          <span className="hidden h-8 w-px bg-line md:block" />
          <span className="label-caps rounded-[2px] border border-lavender/60 bg-lavender-panel px-3 py-1.5 text-lavender">
            Synthetic environment
          </span>
          <span className="text-[16px] text-muted">
            Community Credit Union <span className="mx-2 opacity-60">/</span>
            <span className="tabular-nums">Seed {labSeed === null ? "—" : String(labSeed).padStart(2, "0")}</span>
          </span>
          <div className="ml-auto flex items-center gap-7 text-[16px]">
            <button onClick={openMethodology} className="text-ink underline decoration-muted underline-offset-[6px] hover:decoration-lavender">
              Methodology
            </button>
            <span className="flex items-center gap-2 text-ink">
              <span className={`h-2.5 w-2.5 rounded-full ${activeVersion ? "bg-mint" : "bg-muted"}`} />
              {activeVersion ? <span className="tabular-nums">Detector v{activeVersion} active</span> : "No lab yet"}
            </span>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-[1760px] px-8 pb-16 lg:px-12">
        {/* Title area */}
        <div className="flex flex-wrap items-end justify-between gap-6 border-b border-line pb-8 pt-10">
          <div>
            <p className="label-caps flex items-center gap-2 text-muted">
              <span className={`h-2 w-2 rounded-full ${complete ? "bg-mint" : "bg-lavender"}`} />
              <span className="tabular-nums">{status}</span>
            </p>
            <h1 className="mt-3 text-[56px] leading-[1.05] text-ink">Rule change review</h1>
            <p className="mt-4 text-[19px] text-muted">
              Review Blue&apos;s proposed response to an attack discovered by Red, scored against held-out data.
            </p>
          </div>
          {completedAt && (
            <div className="text-right">
              <p className="text-[15px] text-muted">Completed</p>
              <p className="mt-1 text-[17px] tabular-nums text-ink">{completedAt}</p>
            </div>
          )}
        </div>

        {/* Tabs */}
        <nav className="mb-8 flex gap-10 border-b border-line">
          {(["review", "evidence"] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)} aria-current={tab === t ? "page" : undefined}
              className={`-mb-px flex items-center gap-2 border-b-2 py-4 text-[17px] ${
                tab === t ? "border-lavender text-ink" : "border-transparent text-muted hover:text-ink"}`}>
              {t === "review" ? "Review" : "Evidence log"}
              {t === "evidence" && runRecord && (
                <span className="rounded-full bg-card-raised px-2 py-0.5 text-[14px] tabular-nums text-muted">{runRecord.events.length}</span>
              )}
            </button>
          ))}
        </nav>

        {tab === "evidence" ? (
          <EvidenceLog events={runRecord?.events ?? null} runId={runId} />
        ) : (
          <div className="grid gap-8 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1.6fr)_minmax(0,1fr)]">
            {/* Left: Red's finding */}
            <div className="space-y-6">
              {redRun?.bypass ? (
                <NetworkMap labId={labId} runId={runId} bypass={redRun.bypass} baseRules={redRun.rules}
                  patch={evaluatedPatch} candidateReady={!!report} approval={approval}
                  otherCustomers={world?.customers ?? null} onRerun={runRed} loading={loading} />
              ) : baseline ? (
                <RedStep redRun={redRun} onRun={runRed} loading={loading} />
              ) : (
                <StepCard id="step-red" label="Red agent finding" labelTone="coral" title="Attack path"
                  subtitle="Red's attack appears here after the baseline test." />
              )}
              {errorFor("red")}
            </div>

            {/* Center: setup, then Blue's proposal and the evaluation */}
            <div className="space-y-6">
              {!introDismissed && <IntroCard onDismiss={() => setIntroDismissed(true)} />}
              {!roundUnderway && (
                <>
                  <SetupCard seed={seed} accounts={accounts} onSeedChange={setSeed} onAccountsChange={setAccounts}
                    onCreate={createLab} loading={loading} created={!!labId} world={world} />
                  {errorFor("setup")}
                  {labId && <BaselineStep results={baseline} onRun={runBaseline} loading={loading} />}
                  {errorFor("baseline")}
                </>
              )}
              {roundUnderway && redRun && (
                <>
                  <BlueStep patchRun={patchRun} selectedPatchId={patchId} onAsk={askBlue} loading={loading} />
                  {errorFor("blue")}
                  {patchId && <ScorecardStep report={report} onEvaluate={evaluate} loading={loading} />}
                  {errorFor("evaluate")}
                  <WhyItGotThrough redRun={redRun} />
                </>
              )}
              {redRun && <TestIntegrity />}
              {roundUnderway && (
                <>
                  <SetupCard compact seed={seed} accounts={accounts} onSeedChange={setSeed} onAccountsChange={setAccounts}
                    onCreate={createLab} loading={loading} created={!!labId} world={world} />
                  {errorFor("setup")}
                </>
              )}
            </div>

            {/* Right: the human decision, pinned */}
            <aside className="space-y-6 xl:sticky xl:top-28 xl:max-h-[calc(100vh-8rem)] xl:self-start xl:overflow-y-auto">
              <ApprovalStep report={report} approval={approval} onDecide={decide} loading={loading} />
              {errorFor("decide")}
            </aside>
          </div>
        )}
      </div>
    </main>
  );
}
