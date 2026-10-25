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
  { title: "Set up", text: "Create a synthetic bank, then run the baseline to see what its current fraud rules catch." },
  {
    title: "Run the agents",
    text: "Start Red to find an attack that slips through. Then ask Blue to propose a defense against it.",
  },
  { title: "Test and decide", text: "Run the independent evaluation. Review the results, then approve or reject Blue’s proposed rule." },
];

export default function IntroCard({ onDismiss }: { onDismiss: () => void }) {
  return (
    <section id="intro" className="review-intro scroll-mt-8">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <p className="label-caps mb-2 text-lavender">Methodology</p>
          <h2 className="text-ink">How to run this experiment</h2>
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
