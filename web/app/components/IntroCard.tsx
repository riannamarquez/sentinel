"use client";

import { useSyncExternalStore } from "react";

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
    <section id="intro" className="scroll-mt-24 rounded-xl border border-slate-200 bg-slate-100 p-6">
      <div className="mb-3 flex items-center justify-between gap-4">
        <h2 className="text-lg font-semibold">What you&apos;re looking at</h2>
        <button onClick={onDismiss}
          className="shrink-0 rounded-lg bg-slate-900 px-4 py-2 text-white">
          Got it
        </button>
      </div>
      <ol className="space-y-2">
        {POINTS.map((p, i) => (
          <li key={p.title} className="flex gap-3 text-sm text-slate-700">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-white text-xs font-bold text-slate-900">
              {i + 1}
            </span>
            <span><b className="text-slate-900">{p.title}:</b> {p.text}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
