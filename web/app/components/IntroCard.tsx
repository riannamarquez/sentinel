"use client";

import { useSyncExternalStore } from "react";
import { BUTTON_SECONDARY } from "./StepCard";

const listeners = new Set<() => void>();
// In memory only, so the card is back on every page load (for user testing and demos).
let memory = false;

function readDismissed() {
  return memory;
}

function setDismissed(dismissed: boolean) {
  memory = dismissed;
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

// Shown during prerender too, matching the client's first render: no flash, no hydration mismatch.
export function useIntroDismissed() {
  const dismissed = useSyncExternalStore(subscribe, readDismissed, () => false);
  return [dismissed, setDismissed] as const;
}

const POINTS = [
  { title: "The problem", text: "Fraud rules are built from past attacks, so new tactics can slip through." },
  {
    title: "How Sentinel works",
    text: "Red (an AI attacker) looks for a gap in the rules. Blue (an AI defender) proposes a fix. Plain code tests the fix on data neither AI has seen.",
  },
  { title: "Your role", text: "Review the evidence, then approve or reject the fix." },
];

export default function IntroCard({ onDismiss }: { onDismiss: () => void }) {
  return (
    <section id="intro" className="scroll-mt-28 rounded-[3px] border border-lavender/40 bg-lavender-panel/60 p-7">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <p className="label-caps mb-2 text-lavender">Methodology</p>
          <h2 className="text-[26px] leading-tight text-ink">What you&apos;re looking at</h2>
        </div>
        <button onClick={onDismiss} className={BUTTON_SECONDARY}>Got it</button>
      </div>
      <ol className="space-y-3">
        {POINTS.map((p, i) => (
          <li key={p.title} className="flex gap-4 text-[15px] leading-snug text-muted">
            <span className="tabular-nums text-lavender">{String(i + 1).padStart(2, "0")}</span>
            <span><span className="text-ink">{p.title}.</span> {p.text}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
