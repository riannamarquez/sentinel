"use client";

import { useEffect } from "react";

// Last-resort fallback so a rendering bug never leaves a blank screen or a stack trace.
export default function Error({ error, retry }: { error: unknown; retry: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="flex min-h-screen w-full items-center justify-center bg-page p-6 text-ink">
      <div role="alert" className="max-w-lg rounded-[3px] border border-coral/50 border-l-2 border-l-coral bg-red-panel p-7 text-center">
        <p className="text-xl text-coral">Something went wrong while showing this page.</p>
        <p className="mt-2 text-[15px] text-muted">Try again. If it keeps happening, reload the page and create a new lab.</p>
        <button onClick={() => retry()}
          className="mt-5 rounded-[2px] border border-line px-5 py-2.5 text-[15px] text-ink hover:border-muted">
          Try again
        </button>
      </div>
    </main>
  );
}
