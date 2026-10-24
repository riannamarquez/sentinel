"use client";

import { useState } from "react";

type World = { customers: number; accounts: number; transactions: number; edges: number };
type BaselineResult = {
  scenario_id: string;
  alert: boolean;
  triggered_rule_ids: string[];
};
type ConditionDiagnosis = {
  feature_key: string;
  operator: string;
  threshold: number;
  closest_value: number;
  held: boolean;
};
type Bypass = {
  bypass_id: string;
  scenario: { transactions: unknown[] };
  moved_cents: number;
  objective_cents: number;
  why_it_worked: { rule_id: string; conditions: ConditionDiagnosis[] }[];
  rationale: string;
};
type RedRun = { run_id: string; turns: number; bypass: Bypass | null };
type Condition = {
  feature_key: string;
  operator: string;
  threshold: number;
  window_hours?: number | null;
  params?: Record<string, number>;
};
type RulePatch = {
  patch_id: string;
  operation: "add" | "modify" | "disable";
  rule_id: string | null;
  all_of: Condition[] | null;
  rationale: string;
};
type PatchResult = { patch: RulePatch; valid: boolean; error: string | null };
type PatchRun = { state: string; patches: PatchResult[] };
type Confusion = { tp: number; fp: number; tn: number; fn: number };
type GateResult = { name: string; passed: boolean; detail: string };
type EvaluationReport = {
  report_id: string;
  benign_n: number;
  attack_n: number;
  baseline_confusion: Record<string, Confusion>;
  candidate_confusion: Record<string, Confusion>;
  gate_results: GateResult[];
  eligible_for_approval: boolean;
};

// Plain-English names for the three example cases the backend scores.
const CASES: Record<string, { label: string; isFraud: boolean; blurb: string }> = {
  fast_ring: { label: "Fast mule ring", isFraud: true, blurb: "Stolen money hops quickly through several accounts." },
  slow_chain: { label: "Slow mule chain", isFraud: true, blurb: "Same idea, but each hop waits hours before moving on." },
  salaried_relay: { label: "Normal customer", isFraud: false, blurb: "A salaried person moving their own paycheck around." },
};

function caseInfo(id: string) {
  const key = Object.keys(CASES).find((k) => id.includes(k));
  return key ? CASES[key] : { label: id, isFraud: true, blurb: "" };
}

// Plain-English names for the detector's feature keys.
const FEATURES: Record<string, string> = {
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
const OPERATORS: Record<string, string> = { ">=": "≥", ">": ">", "<=": "≤", "<": "<" };

function dollars(cents: number) {
  return `$${(cents / 100).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function formatFeature(key: string, value: number) {
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

function describeRule(all_of: Condition[]) {
  return `Alarm if ${all_of.map(describeCondition).join(", and ")}.`;
}

const GATES: Record<string, string> = {
  schema_valid: "The fix is a well-formed rule",
  fpr_budget: "Doesn't flag too many new normal customers",
  regression_no_loss: "Still catches every attack the old rules caught",
  regression_benign: "Doesn't flag more lookalike normal customers",
  holdout_recall_gain: "Catches more unseen attacks than before",
};

function fraction(n: number, d: number) {
  return `${n} / ${d} (${d ? Math.round((n / d) * 100) : 0}%)`;
}

const OPERATION_LABELS: Record<string, string> = { add: "+ New rule", modify: "Modify rule", disable: "Disable rule" };

export default function Home() {
  const [seed, setSeed] = useState(7);
  const [accounts, setAccounts] = useState(200);
  const [labId, setLabId] = useState<string | null>(null);
  const [world, setWorld] = useState<World | null>(null);
  const [baseline, setBaseline] = useState<BaselineResult[] | null>(null);
  const [redRun, setRedRun] = useState<RedRun | null>(null);
  const [patchRun, setPatchRun] = useState<PatchRun | null>(null);
  const [patchId, setPatchId] = useState<string | null>(null);
  const [report, setReport] = useState<EvaluationReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function createLab() {
    setLoading(true);
    setError(null);
    setBaseline(null);
    setRedRun(null);
    setPatchRun(null);
    setPatchId(null);
    setReport(null);
    try {
      const res = await fetch("/api/labs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ seed, account_count: accounts }),
      });
      if (!res.ok) throw new Error(`Create lab failed (${res.status})`);
      const data = await res.json();
      setLabId(data.lab_id);
      setWorld(data.world);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function runBaseline() {
    if (!labId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/labs/${labId}/baseline`, { method: "POST" });
      if (!res.ok) throw new Error(`Baseline failed (${res.status})`);
      const data = await res.json();
      setBaseline(data.results);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function runRed() {
    if (!labId) return;
    setLoading(true);
    setError(null);
    setPatchRun(null);
    setPatchId(null);
    setReport(null);
    try {
      const res = await fetch(`/api/labs/${labId}/red-runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!res.ok) throw new Error(`Red challenge failed (${res.status})`);
      const data = await res.json();
      setRedRun({ run_id: data.run_id, turns: data.turns, bypass: data.bypass });
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function askBlue() {
    if (!labId || !redRun?.bypass) return;
    setLoading(true);
    setError(null);
    setReport(null);
    try {
      const res = await fetch(`/api/labs/${labId}/patches`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: redRun.run_id, bypass_id: redRun.bypass.bypass_id }),
      });
      if (!res.ok) throw new Error(`Blue fix failed (${res.status})`);
      const data = await res.json();
      setPatchRun({ state: data.state, patches: data.patches });
      setPatchId(data.patches.find((p: PatchResult) => p.valid)?.patch.patch_id ?? null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function evaluate() {
    if (!labId || !redRun || !patchId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/labs/${labId}/evaluations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: redRun.run_id, patch_id: patchId }),
      });
      if (!res.ok) throw new Error(`Evaluation failed (${res.status})`);
      setReport(await res.json());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  const bypass = redRun?.bypass;
  const before = report?.baseline_confusion.final_holdout;
  const after = report?.candidate_confusion.final_holdout;

  return (
    <main className="min-h-screen bg-slate-50 p-8 text-slate-900">
      <header className="mb-8 flex items-center gap-3">
        <h1 className="text-3xl font-bold">Sentinel</h1>
        <span className="rounded bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-800">SYNTHETIC DATA</span>
      </header>

      {/* Step 1: Create lab */}
      <section className="mb-6 rounded-xl border bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-lg font-semibold">1. Create a fake bank</h2>
        <div className="flex flex-wrap items-end gap-4">
          <label className="flex flex-col text-sm">
            Seed
            <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))}
              className="mt-1 w-28 rounded border px-2 py-1" />
          </label>
          <label className="flex flex-col text-sm">
            Accounts
            <input type="number" value={accounts} onChange={(e) => setAccounts(Number(e.target.value))}
              className="mt-1 w-28 rounded border px-2 py-1" />
          </label>
          <button onClick={createLab} disabled={loading}
            className="rounded-lg bg-slate-900 px-4 py-2 text-white disabled:opacity-50">
            {loading && !labId ? "Creating…" : "Create lab"}
          </button>
        </div>
        {world && (
          <p className="mt-4 text-sm text-slate-600">
            Community Credit Union created: <b>{world.accounts}</b> accounts · <b>{world.customers}</b> customers ·{" "}
            <b>{world.transactions.toLocaleString()}</b> transactions
          </p>
        )}
      </section>

      {/* Step 2: Baseline */}
      {labId && (
        <section className="mb-6 rounded-xl border bg-white p-6 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold">2. Test the current fraud rules</h2>
            <button onClick={runBaseline} disabled={loading}
              className="rounded-lg bg-slate-900 px-4 py-2 text-white disabled:opacity-50">
              Run baseline
            </button>
          </div>

          {baseline && (
            <div className="grid gap-4 md:grid-cols-3">
              {baseline.map((r) => {
                const info = caseInfo(r.scenario_id);
                const good = info.isFraud ? r.alert : !r.alert;
                const badge = info.isFraud ? (r.alert ? "Caught" : "Missed") : r.alert ? "False alarm" : "Not flagged";
                return (
                  <div key={r.scenario_id}
                    className={`rounded-lg border-2 p-4 ${good ? "border-emerald-300 bg-emerald-50" : "border-red-300 bg-red-50"}`}>
                    <div className="mb-2 flex items-center justify-between">
                      <h3 className="font-semibold">{info.label}</h3>
                      <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${good ? "bg-emerald-200 text-emerald-900" : "bg-red-200 text-red-900"}`}>
                        {good ? "✓" : "✗"} {badge}
                      </span>
                    </div>
                    <p className="text-sm text-slate-600">{info.blurb}</p>
                    <p className="mt-2 text-xs text-slate-500">
                      Rules triggered: {r.triggered_rule_ids.length ? r.triggered_rule_ids.join(", ") : "none"}
                    </p>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      )}

      {/* Step 3: Red challenge */}
      {labId && baseline && (
        <section className="mb-6 rounded-xl border bg-white p-6 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold">3. Let Red try to sneak money past the rules</h2>
            <button onClick={runRed} disabled={loading}
              className="rounded-lg bg-red-600 px-4 py-2 text-white disabled:opacity-50">
              Start Red challenge
            </button>
          </div>

          {redRun && !bypass && (
            <p className="rounded-lg border-2 border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-900">
              Red tried {redRun.turns} times and couldn&apos;t get past the rules.
            </p>
          )}

          {bypass && (
            <div className="space-y-4">
              <div className="rounded-lg border-2 border-red-300 bg-red-50 p-4">
                <p className="text-2xl font-bold text-red-700">{dollars(bypass.moved_cents)} escaped undetected</p>
                <p className="mt-1 text-sm text-red-900">
                  Goal: {dollars(bypass.objective_cents)} · Succeeded on try {redRun.turns} ·{" "}
                  {bypass.scenario.transactions.length} transfers · no alarm fired
                </p>
              </div>

              <div className="rounded-lg border bg-slate-50 p-4">
                <h3 className="mb-1 text-sm font-semibold">Red&apos;s plan</h3>
                <p className="text-sm text-slate-700">{bypass.rationale}</p>
              </div>

              <div>
                <h3 className="mb-1 font-semibold">Why every rule stayed silent</h3>
                <p className="mb-2 text-xs text-slate-500">
                  A rule only fires when all of its checks are met. Red rows are checks the attack never tripped.
                </p>
                <table className="w-full text-left text-sm">
                  <thead className="border-b text-xs uppercase text-slate-500">
                    <tr>
                      <th className="py-2 pr-4">Rule</th>
                      <th className="py-2 pr-4">Check</th>
                      <th className="py-2 pr-4">Fires at</th>
                      <th className="py-2">Attack&apos;s closest</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bypass.why_it_worked.flatMap((rule) =>
                      rule.conditions.map((c, i) => (
                        <tr key={`${rule.rule_id}-${i}`}
                          className={`border-b ${c.held ? "bg-red-50 text-red-900" : ""}`}>
                          <td className="py-2 pr-4 font-mono text-xs">{i === 0 ? rule.rule_id : ""}</td>
                          <td className="py-2 pr-4">{FEATURES[c.feature_key] ?? c.feature_key}</td>
                          <td className="py-2 pr-4">
                            {OPERATORS[c.operator] ?? c.operator} {formatFeature(c.feature_key, c.threshold)}
                          </td>
                          <td className="py-2">{formatFeature(c.feature_key, c.closest_value)}</td>
                        </tr>
                      )),
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>
      )}

      {/* Step 4: Blue fix */}
      {labId && bypass && (
        <section className="mb-6 rounded-xl border bg-white p-6 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold">4. Ask Blue to close the gap</h2>
            <button onClick={askBlue} disabled={loading}
              className="rounded-lg bg-blue-600 px-4 py-2 text-white disabled:opacity-50">
              Ask Blue for a fix
            </button>
          </div>

          {patchRun?.state === "failed" && (
            <p className="mb-4 rounded-lg border-2 border-red-300 bg-red-50 p-4 text-sm text-red-900">
              Blue couldn&apos;t propose a valid fix. Every suggestion below was rejected before testing.
            </p>
          )}

          {patchRun && (
            <div className="grid gap-4 md:grid-cols-3">
              {patchRun.patches.map(({ patch, valid, error: patchError }) => (
                <div key={patch.patch_id}
                  className={`rounded-lg border-2 p-4 ${valid ? "border-blue-200 bg-blue-50" : "border-red-300 bg-red-50"}`}>
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <span className="text-sm font-semibold text-blue-900">
                      {OPERATION_LABELS[patch.operation] ?? patch.operation}
                      {patch.rule_id && patch.operation !== "add" ? ` ${patch.rule_id}` : ""}
                    </span>
                    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${valid ? "bg-emerald-200 text-emerald-900" : "bg-red-200 text-red-900"}`}>
                      {valid ? "✓ Valid" : `✗ ${patchError}`}
                    </span>
                  </div>
                  {patch.all_of && <p className="mb-2 font-medium">{describeRule(patch.all_of)}</p>}
                  <p className="text-sm text-slate-600">{patch.rationale}</p>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* Step 5: Evaluate */}
      {labId && patchId && (
        <section className="mb-6 rounded-xl border bg-white p-6 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold">5. Test the fix on unseen data</h2>
            <button onClick={evaluate} disabled={loading}
              className="rounded-lg bg-slate-900 px-4 py-2 text-white disabled:opacity-50">
              Evaluate on unseen data
            </button>
          </div>

          {report && before && after && (
            <div className="space-y-4">
              <table className="w-full text-left text-sm">
                <thead className="border-b text-xs uppercase text-slate-500">
                  <tr>
                    <th className="py-2 pr-4"></th>
                    <th className="py-2 pr-4">Current rules</th>
                    <th className="py-2">With Blue&apos;s fix</th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="border-b">
                    <td className="py-2 pr-4 font-medium">Attacks caught</td>
                    <td className="py-2 pr-4">{fraction(before.tp, before.tp + before.fn)}</td>
                    <td className={`py-2 ${after.tp > before.tp ? "font-semibold text-emerald-700" : ""}`}>
                      {fraction(after.tp, after.tp + after.fn)}
                    </td>
                  </tr>
                  <tr className="border-b">
                    <td className="py-2 pr-4 font-medium">Normal customers wrongly flagged</td>
                    <td className="py-2 pr-4">{fraction(before.fp, before.fp + before.tn)}</td>
                    <td className={`py-2 ${after.fp < before.fp ? "font-semibold text-emerald-700" : ""}`}>
                      {fraction(after.fp, after.fp + after.tn)}
                    </td>
                  </tr>
                </tbody>
              </table>

              <ul className="space-y-2">
                {report.gate_results.map((g) => (
                  <li key={g.name} className="flex gap-2 text-sm">
                    <span className={g.passed ? "text-emerald-600" : "text-red-600"}>{g.passed ? "✓" : "✗"}</span>
                    <span>
                      <span className="font-medium">{GATES[g.name] ?? g.name}</span>
                      {g.detail && <span className="text-slate-500"> — {g.detail}</span>}
                    </span>
                  </li>
                ))}
              </ul>

              <p className="text-xs text-slate-500">
                All numbers are computed by deterministic code on data neither agent saw — not by an AI.
              </p>
            </div>
          )}
        </section>
      )}

      {error && <p className="text-red-600">{error}</p>}
    </main>
  );
}