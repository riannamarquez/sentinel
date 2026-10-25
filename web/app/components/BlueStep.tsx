"use client";

import { useState } from "react";
import type { BlueSource, PatchRun } from "../api";
import { describeRule } from "./format";
import { ruleTitle, specCells } from "./ruleSpec";
import StepCard, { BUTTON_PRIMARY, Chip } from "./StepCard";

export const SparkleIcon = (
  <svg aria-hidden="true" viewBox="0 0 16 16" className="h-4 w-4" fill="currentColor">
    <path d="M6 1.5 7.2 5 10.5 6 7.2 7 6 10.5 4.8 7 1.5 6 4.8 5zM12 8.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z" />
  </svg>
);

const CheckIcon = (
  <svg aria-hidden="true" viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="m3 8.5 3 3 7-7" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const SOURCE_LABEL: Record<BlueSource, string> = { llm_live: "LLM live", llm_replay: "LLM replay", fixture: "fixture" };

export default function BlueStep({ patchRun, selectedPatchId, onAsk, loading }: {
  patchRun: PatchRun | null;
  selectedPatchId: string | null;   // the valid patch the round goes on with
  onAsk: () => void;
  loading: boolean;
}) {
  const [showLogic, setShowLogic] = useState(false);
  const selected = patchRun?.patches.find((p) => p.patch.patch_id === selectedPatchId) ?? null;
  const others = patchRun?.patches.filter((p) => p !== selected) ?? [];

  if (!patchRun) {
    return (
      <StepCard id="step-blue" label="Blue agent proposal" labelTone="lavender" labelIcon={SparkleIcon}
        title="Ask Blue to close the gap" subtitle="Blue proposes a rule change to close the gap Red found."
        action={<button onClick={onAsk} disabled={loading} className={BUTTON_PRIMARY}>Ask Blue for a fix</button>} />
    );
  }

  return (
    <StepCard id="step-blue" label="Blue agent proposal" labelTone="lavender" labelIcon={SparkleIcon}
      title={selected ? ruleTitle(selected.patch) : "No valid proposal"}
      note={patchRun.source && (
        <div className="mt-3"><Chip tone={patchRun.source === "fixture" ? "muted" : "lavender"}>Blue: {SOURCE_LABEL[patchRun.source]}</Chip></div>
      )}
      action={selected ? <Chip icon={CheckIcon}>Valid rule</Chip> : <Chip tone="coral">Rejected</Chip>}>
      {patchRun.state === "failed" && (
        <p className="mb-5 rounded-[2px] border-l-2 border-coral bg-red-panel p-4 text-[15px] text-coral">
          Blue couldn&apos;t propose a valid fix. Every suggestion below was rejected before testing.
        </p>
      )}

      {selected?.patch.all_of && (
        <div className="border-t border-line pt-6">
          <p className="text-[19px] leading-relaxed text-ink">{describeRule(selected.patch.all_of)}</p>
          <dl className="mt-6 grid grid-cols-2 border border-line sm:grid-cols-4">
            {specCells(selected.patch.all_of).map((cell, i) => (
              <div key={`${cell.label}-${i}`} className="border-line p-4 [&:not(:last-child)]:border-r max-sm:[&:nth-child(2n)]:border-r-0 max-sm:[&:nth-child(n+3)]:border-t">
                <dt className="text-[13px] text-muted">{cell.label}</dt>
                <dd className="mt-1.5 text-[18px] tabular-nums text-ink">{cell.value}</dd>
              </div>
            ))}
          </dl>
          {selected.patch.rationale && (
            <p className="mt-5 text-[15px] leading-snug text-muted">
              <span className="text-lavender">Blue&apos;s reasoning:</span> {selected.patch.rationale}
            </p>
          )}
          <button onClick={() => setShowLogic((v) => !v)} aria-expanded={showLogic}
            className="mt-5 inline-flex items-center gap-1.5 text-[15px] text-lavender hover:underline">
            View rule logic <span className={`transition ${showLogic ? "rotate-90" : ""}`}>›</span>
          </button>
          {showLogic && (
            <pre className="mt-3 overflow-x-auto rounded-[2px] border border-line bg-page p-4 font-mono text-[13px] leading-relaxed text-muted">
              {JSON.stringify(selected.patch, null, 2)}
            </pre>
          )}
        </div>
      )}

      {others.length > 0 && (
        <div className="mt-6 border-t border-line pt-5">
          <p className="label-caps mb-3 text-muted">Other proposals</p>
          <ul className="space-y-3">
            {others.map(({ patch, valid, error }) => (
              <li key={patch.patch_id} className="text-[15px]">
                <div className="flex flex-wrap items-center gap-2">
                  <Chip tone={valid ? "lavender" : "coral"}>{valid ? "Valid" : "Rejected"}</Chip>
                  <span className="text-ink">{ruleTitle(patch)}</span>
                </div>
                {patch.all_of && <p className="mt-1 text-muted">{describeRule(patch.all_of)}</p>}
                {error && <p className="mt-1 text-sm text-coral">{error}</p>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </StepCard>
  );
}
