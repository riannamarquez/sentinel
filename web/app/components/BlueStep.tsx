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
      subtitle="Blue proposes a rule change to close the gap Red found." action={
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
