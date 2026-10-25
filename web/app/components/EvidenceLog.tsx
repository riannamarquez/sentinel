import type { AuditEvent } from "../api";

// "enter:validate_patch" -> "Validate patch"; other actions get the same underscore cleanup.
function actionText(action: string) {
  const words = action.replace(/^enter:/, "").replace(/[_:]/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function formatUtc(seconds: number, withDate = false) {
  const d = new Date(seconds * 1000);
  const time = d.toLocaleTimeString("en-GB", { timeZone: "UTC", hour: "2-digit", minute: "2-digit", second: "2-digit" });
  if (!withDate) return `${time} UTC`;
  const date = d.toLocaleDateString("en-GB", { timeZone: "UTC", day: "numeric", month: "short", year: "numeric" });
  return `${date}, ${time.slice(0, 5)} UTC`;
}

export default function EvidenceLog({ events, runId }: { events: AuditEvent[] | null; runId: string | null }) {
  if (!runId) {
    return <p className="py-10 text-[15px] text-muted">The evidence log fills in once Red has run a challenge.</p>;
  }
  if (!events) return <p className="py-10 text-[15px] text-muted">Loading the audit trail…</p>;
  return (
    <section className="rounded-[3px] border border-line bg-card p-7">
      <p className="label-caps mb-2 text-muted">Audit trail · run {runId}</p>
      <h2 className="mb-5 text-[28px] text-ink">Evidence log</h2>
      <table className="w-full text-left text-[15px]">
        <thead className="label-caps text-muted">
          <tr className="border-b border-line">
            <th className="py-3 pr-4 font-normal">Time</th>
            <th className="py-3 pr-4 font-normal">Actor</th>
            <th className="py-3 pr-4 font-normal">Action</th>
            <th className="py-3 font-normal">Detector</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.event_id} className="border-b border-line">
              <td className="py-3 pr-4 tabular-nums text-muted">{formatUtc(e.timestamp)}</td>
              <td className={`py-3 pr-4 ${e.actor.includes("red") ? "text-coral" : e.actor.includes("blue") ? "text-lavender" : "text-ink"}`}>
                {e.actor}
              </td>
              <td className="py-3 pr-4 text-ink">{actionText(e.action)}</td>
              <td className="py-3 tabular-nums text-muted">
                {e.version_after ? `v${e.version_before} → v${e.version_after}` : e.version_before ? `v${e.version_before}` : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
