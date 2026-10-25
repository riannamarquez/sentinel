import type { PatchRun } from "../api";
import { describeRule } from "./format";
import StepCard from "./StepCard";

const OPERATION_LABELS: Record<string, string> = { add: "+ New rule", modify: "Modify rule", disable: "Disable rule" };

export default function BlueStep({ patchRun, onAsk, loading }: {
  patchRun: PatchRun | null;
  onAsk: () => void;
  loading: boolean;
}) {
  return (
    <StepCard id="step-blue" title="4. Ask Blue to close the gap"
      subtitle="Blue proposes a rule change to close the gap Red found."
      note={
        // Blue's only inputs are Red's bypass trace and the current rules (blue.propose in sentinel/api/app.py).
        <p className="mt-1 flex items-start gap-1.5 text-xs text-slate-500">
          <svg aria-hidden="true" viewBox="0 0 16 16" className="mt-px h-3.5 w-3.5 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="8" cy="8" r="6.5" />
            <path d="M8 7.25v4M8 4.75v.01" strokeLinecap="round" />
          </svg>
          <span>What Blue can see: Red&apos;s attack path and the current rules — not other banks&apos; accounts, and not the hidden test data.</span>
        </p>
      } action={
      <button onClick={onAsk} disabled={loading}
        className="shrink-0 rounded-lg bg-blue-600 px-4 py-2 text-white disabled:opacity-50">
        Ask Blue for a fix
      </button>
    }>
      {patchRun?.state === "failed" && (
        <p className="mb-4 rounded-lg border-2 border-red-300 bg-red-50 p-4 text-sm text-red-900">
          Blue couldn&apos;t propose a valid fix. Every suggestion below was rejected before testing.
        </p>
      )}

      {patchRun && (
        <div className="grid gap-4">
          {patchRun.patches.map(({ patch, valid, error }) => (
            <div key={patch.patch_id}
              className={`rounded-lg border-2 p-4 ${valid ? "border-blue-200 bg-blue-50" : "border-red-300 bg-red-50"}`}>
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="text-sm font-semibold text-blue-900">
                  {OPERATION_LABELS[patch.operation] ?? patch.operation}
                  {patch.rule_id && patch.operation !== "add" ? ` ${patch.rule_id}` : ""}
                </span>
                <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${valid ? "bg-emerald-200 text-emerald-900" : "bg-red-200 text-red-900"}`}>
                  {valid ? "✓ Valid" : `✗ ${error}`}
                </span>
              </div>
              {patch.all_of && <p className="mb-2 font-medium">{describeRule(patch.all_of)}</p>}
              <p className="text-sm text-slate-600">{patch.rationale}</p>
            </div>
          ))}
        </div>
      )}
    </StepCard>
  );
}
