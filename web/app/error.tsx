"use client";

import { useEffect } from "react";

// Last-resort fallback so a rendering bug never leaves a blank screen or a stack trace.
export default function Error({ error, retry }: { error: unknown; retry: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="flex min-h-screen w-full items-center justify-center bg-slate-50 p-6 text-slate-900">
      <div role="alert" className="max-w-lg rounded-xl border-2 border-red-300 bg-red-50 p-6 text-center">
        <p className="text-lg font-semibold text-red-900">Something went wrong while showing this page.</p>
        <p className="mt-1 text-sm text-red-800">Try again. If it keeps happening, reload the page and create a new lab.</p>
        <button onClick={() => retry()} className="mt-4 rounded-lg bg-red-600 px-4 py-2 text-white">
          Try again
        </button>
      </div>
    </main>
  );
}
