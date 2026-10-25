import { BUTTON_SECONDARY } from "./StepCard";

// The one error banner every failed step uses, with a button that re-runs that step.
export default function ErrorBanner({ message, detail, onRetry, loading }: {
  message: string;
  detail: string | null;
  onRetry: () => void;
  loading: boolean;
}) {
  return (
    <div role="alert" className="flex items-start justify-between gap-4 rounded-[3px] border border-coral/50 border-l-2 border-l-coral bg-red-panel p-5">
      <div className="min-w-0">
        <p className="text-[15px] text-coral">
          {/* `backticked` text in a message renders as code */}
          {message.split("`").map((part, i) =>
            i % 2 ? <code key={i} className="rounded-[2px] bg-page px-1 font-mono text-sm">{part}</code> : part)}
        </p>
        {detail && <p className="mt-1 break-words text-sm text-muted">{detail}</p>}
      </div>
      <button onClick={onRetry} disabled={loading} className={BUTTON_SECONDARY}>
        {loading ? "Retrying…" : "Try again"}
      </button>
    </div>
  );
}
