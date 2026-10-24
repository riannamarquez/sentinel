import type { World } from "../api";

export default function SetupCard({ seed, accounts, onSeedChange, onAccountsChange, onCreate, loading, created, world }: {
  seed: number;
  accounts: number;
  onSeedChange: (v: number) => void;
  onAccountsChange: (v: number) => void;
  onCreate: () => void;
  loading: boolean;
  created: boolean;
  world: World | null;
}) {
  return (
    <section id="step-setup" className="scroll-mt-24 rounded-xl border bg-white p-6 shadow-sm">
      <h2 className="mb-4 text-lg font-semibold">1. Create a fake bank</h2>
      <div className="flex flex-wrap items-end gap-4">
        <label className="flex flex-col text-sm">
          Seed
          <input type="number" value={seed} onChange={(e) => onSeedChange(Number(e.target.value))}
            className="mt-1 w-28 rounded border px-2 py-1" />
        </label>
        <label className="flex flex-col text-sm">
          Accounts
          <input type="number" value={accounts} onChange={(e) => onAccountsChange(Number(e.target.value))}
            className="mt-1 w-28 rounded border px-2 py-1" />
        </label>
        <button onClick={onCreate} disabled={loading}
          className="rounded-lg bg-slate-900 px-4 py-2 text-white disabled:opacity-50">
          {loading && !created ? "Creating…" : "Create lab"}
        </button>
      </div>
      {world && (
        <p className="mt-4 text-sm text-slate-600">
          Community Credit Union created: <b>{world.accounts}</b> accounts · <b>{world.customers}</b> customers ·{" "}
          <b>{world.transactions.toLocaleString()}</b> transactions
        </p>
      )}
    </section>
  );
}
