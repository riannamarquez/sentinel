"use client";

import { useEffect, useState } from "react";
import * as api from "./api";
import ApprovalStep from "./components/ApprovalStep";
import BaselineStep from "./components/BaselineStep";
import BlueStep from "./components/BlueStep";
import ErrorBanner from "./components/ErrorBanner";
import IntroCard, { useIntroDismissed } from "./components/IntroCard";
import NetworkMap from "./components/NetworkMap";
import RedStep from "./components/RedStep";
import ScorecardStep, { Scorecard } from "./components/ScorecardStep";
import SetupCard from "./components/SetupCard";

type Step = "setup" | "baseline" | "red" | "blue" | "evaluate" | "decide";
type StepError = { step: Step; message: string; detail: string | null; retry: () => void };

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
  const [introDismissed, setIntroDismissed] = useIntroDismissed();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<StepError | null>(null);
  // A fresh object each time, so asking for the same target twice still scrolls.
  const [scrollTarget, setScrollTarget] = useState<{ id: string } | null>(null);

  // Scroll to the next step once it has rendered, unless it's already comfortably on screen
  // (the pinned right column usually is at projector width).
  useEffect(() => {
    if (!scrollTarget) return;
    const el = document.getElementById(scrollTarget.id);
    if (!el) return;
    const { top } = el.getBoundingClientRect();
    if (top < 80 || top > window.innerHeight * 0.6) el.scrollIntoView({ behavior: "smooth", block: "start" });
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

  function createLab() {
    setBaseline(null);
    setRedRun(null);
    setPatchRun(null);
    setPatchId(null);
    setReport(null);
    setApproval(null);
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
    setPatchRun(null);
    setPatchId(null);
    setReport(null);
    setApproval(null);
    return run("red", runRed, async () => {
      const result = await api.startRedRun(labId);
      setRedRun(result);
      setScrollTarget({ id: result.bypass ? "red-result" : "step-red" });
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
      setScrollTarget({ id: firstValid ? "step-evaluate" : "step-blue" });
    });
  }

  function evaluate() {
    if (!labId || !redRun || !patchId) return;
    setApproval(null);
    return run("evaluate", evaluate, async () => {
      setReport(await api.evaluatePatch(labId, redRun.run_id, patchId));
      setScrollTarget({ id: "scorecard" });
    });
  }

  function decide(decision: api.Decision) {
    if (!labId || !report) return;
    return run("decide", () => decide(decision), async () => {
      const result = await api.decide(labId, report.report_id, decision);
      setApproval(result);
      setActiveVersion(result.active_version);
      setScrollTarget({ id: "approval-result" });
    });
  }

  function errorFor(step: Step) {
    if (error?.step !== step) return null;
    return <ErrorBanner message={error.message} detail={error.detail} onRetry={error.retry} loading={loading} />;
  }

  return (
    <main className="min-h-screen w-full bg-slate-50 text-slate-900">
      <header className="sticky top-0 z-10 border-b bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1680px] items-center gap-4 px-6 py-4">
          <h1 className="text-3xl font-bold">Sentinel</h1>
          <span className="rounded bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-800">SYNTHETIC DATA</span>
          <span className="hidden text-xs text-slate-500 md:inline">
            Scope: one synthetic bank · &lsquo;Outside&rsquo; accounts belong to other institutions
          </span>
          <div className="ml-auto flex items-center gap-6 text-sm text-slate-600">
            <button onClick={() => { setIntroDismissed(false); setScrollTarget({ id: "intro" }); }}
              className="text-slate-500 underline underline-offset-2 hover:text-slate-900">
              How this works
            </button>
            <span>Seed <b className="text-slate-900">{labSeed ?? "—"}</b></span>
            <span>
              Active detector{" "}
              <b className="rounded bg-slate-900 px-2 py-0.5 text-white">{activeVersion ? `v${activeVersion}` : "—"}</b>
            </span>
          </div>
        </div>
      </header>

      <div className="mx-auto grid max-w-[1680px] gap-6 p-6 xl:grid-cols-[20rem_minmax(0,1fr)_26rem]">
        {/* Left: network map */}
        <aside className="xl:sticky xl:top-24 xl:self-start">
          <div className={`h-[32rem] overflow-hidden rounded-xl bg-white xl:h-[calc(100vh-7.5rem)] ${redRun?.bypass ? "border shadow-sm" : "border-2 border-dashed border-slate-300"}`}>
            <NetworkMap bypass={redRun?.bypass ?? null} redRan={!!redRun} rechallenge={approval?.rechallenge ?? null} />
          </div>
        </aside>

        {/* Center: the attack / repair sequence */}
        <div className="space-y-6">
          {!introDismissed && <IntroCard onDismiss={() => setIntroDismissed(true)} />}
          <SetupCard seed={seed} accounts={accounts} onSeedChange={setSeed} onAccountsChange={setAccounts}
            onCreate={createLab} loading={loading} created={!!labId} world={world} />
          {errorFor("setup")}
          {labId && <BaselineStep results={baseline} onRun={runBaseline} loading={loading} />}
          {errorFor("baseline")}
          {labId && baseline && <RedStep redRun={redRun} onRun={runRed} loading={loading} />}
          {errorFor("red")}
          {labId && redRun?.bypass && <BlueStep patchRun={patchRun} onAsk={askBlue} loading={loading} />}
          {errorFor("blue")}
          {labId && patchId && <ScorecardStep onEvaluate={evaluate} loading={loading} evaluated={!!report} />}
          {errorFor("evaluate")}
        </div>

        {/* Right: scorecard and decision, pinned once they exist */}
        <aside className="space-y-6 xl:sticky xl:top-24 xl:max-h-[calc(100vh-7.5rem)] xl:self-start xl:overflow-y-auto">
          {labId && report ? (
            <>
              <Scorecard report={report} />
              <ApprovalStep report={report} approval={approval} onDecide={decide} loading={loading} />
              {errorFor("decide")}
            </>
          ) : (
            <div className="hidden rounded-xl border-2 border-dashed border-slate-300 p-6 text-center text-sm text-slate-400 xl:block">
              The scorecard and approve/reject panel appear here after the fix is tested.
            </div>
          )}
        </aside>
      </div>
    </main>
  );
}
