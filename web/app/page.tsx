"use client";

import { useState } from "react";

type World = { customers: number; accounts: number; transactions: number; edges: number };
type BaselineResult = {
  scenario_id: string;
  alert: boolean;
  triggered_rule_ids: string[];
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

export default function Home() {
  const [seed, setSeed] = useState(7);
  const [accounts, setAccounts] = useState(200);
  const [labId, setLabId] = useState<string | null>(null);
  const [world, setWorld] = useState<World | null>(null);
  const [baseline, setBaseline] = useState<BaselineResult[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function createLab() {
    setLoading(true);
    setError(null);
    setBaseline(null);
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

      {error && <p className="text-red-600">{error}</p>}
    </main>
  );
}