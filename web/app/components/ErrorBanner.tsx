// The one red banner every failed step uses, with a button that re-runs that step.
export default function ErrorBanner({ message, detail, onRetry, loading }: {
  message: string;
  detail: string | null;
  onRetry: () => void;
  loading: boolean;
}) {
  return (
    <div role="alert" className="flex items-start justify-between gap-4 rounded-xl border-2 border-red-300 bg-red-50 p-4">
      <div className="min-w-0">
        <p className="font-semibold text-red-900">
          {/* `backticked` text in a message renders as code */}
          {message.split("`").map((part, i) =>
            i % 2 ? <code key={i} className="rounded bg-red-100 px-1 font-mono">{part}</code> : part)}
        </p>
        {detail && <p className="mt-1 break-words text-sm text-red-800">{detail}</p>}
      </div>
      <button onClick={onRetry} disabled={loading}
        className="shrink-0 rounded-lg bg-red-600 px-4 py-2 text-white disabled:opacity-50">
        {loading ? "Retrying…" : "Try again"}
      </button>
    </div>
  );
}
