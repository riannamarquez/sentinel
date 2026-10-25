import type { World } from "../api";
import StepCard, { BUTTON_PRIMARY, BUTTON_SECONDARY } from "./StepCard";

const INPUT = "mt-1.5 w-28 rounded-[2px] border border-line bg-page px-3 py-2 text-[15px] tabular-nums text-ink focus:border-lavender focus:outline-none";

export default function SetupCard({ seed, accounts, onSeedChange, onAccountsChange, onCreate, loading, created, world, compact = false }: {
  seed: number;
  accounts: number;
  onSeedChange: (v: number) => void;
  onAccountsChange: (v: number) => void;
  onCreate: () => void;
  loading: boolean;
  created: boolean;
  world: World | null;
  compact?: boolean;   // once a round is under way: a quiet card for starting over
}) {
  return (
    <StepCard id="step-setup" label={compact ? "Lab" : "Step 1 · Synthetic bank"}
      title={compact ? undefined : "Create a fake bank"}
      subtitle={compact ? undefined : "Generates a synthetic credit union with normal customer activity."}>
      {world && (
        <p className="mb-5 text-[15px] text-muted">
          Community Credit Union:{" "}
          <span className="tabular-nums text-ink">{world.accounts.toLocaleString()}</span> accounts ·{" "}
          <span className="tabular-nums text-ink">{world.customers.toLocaleString()}</span> customers ·{" "}
          <span className="tabular-nums text-ink">{world.transactions.toLocaleString()}</span> transactions
        </p>
      )}
      <div className="flex flex-wrap items-end gap-4">
        <label className="flex flex-col text-sm text-muted">
          Seed
          <input type="number" value={seed} onChange={(e) => onSeedChange(Number(e.target.value))} className={INPUT} />
        </label>
        <label className="flex flex-col text-sm text-muted">
          Accounts
          <input type="number" value={accounts} onChange={(e) => onAccountsChange(Number(e.target.value))} className={INPUT} />
        </label>
        <button onClick={onCreate} disabled={loading} className={created ? BUTTON_SECONDARY : BUTTON_PRIMARY}>
          {loading && !created ? "Creating…" : created ? "Create a new lab" : "Create lab"}
        </button>
      </div>
    </StepCard>
  );
}
