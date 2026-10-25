import type { ReactNode } from "react";

export type Tone = "coral" | "lavender" | "muted" | "mint";

const LABEL_TONE: Record<Tone, string> = {
  coral: "text-coral",
  lavender: "text-lavender",
  muted: "text-muted",
  mint: "text-mint",
};

// Outlined uppercase chip: "VALID RULE", "SLIPPED THROUGH", "DETERMINISTIC TEST", …
export function Chip({ tone = "lavender", icon, children }: { tone?: Tone; icon?: ReactNode; children: ReactNode }) {
  const styles: Record<Tone, string> = {
    lavender: "border-lavender/60 bg-lavender-panel text-lavender",
    coral: "border-coral/60 bg-red-panel text-coral",
    mint: "border-mint/60 bg-green-panel text-mint",
    muted: "border-line bg-card-raised text-muted",
  };
  return (
    <span className={`label-caps inline-flex shrink-0 items-center gap-1.5 rounded-[2px] border px-2.5 py-1 ${styles[tone]}`}>
      {icon}
      {children}
    </span>
  );
}

// The card every step and panel sits in. `id` is the auto-scroll target.
export default function StepCard({ id, label, labelTone = "muted", labelIcon, title, subtitle, note, action, children, className = "" }: {
  id: string;
  label?: string;           // small uppercase section label
  labelTone?: Tone;
  labelIcon?: ReactNode;
  title?: ReactNode;        // serif heading
  subtitle?: ReactNode;
  note?: ReactNode;         // a quiet extra line under the subtitle
  action?: ReactNode;       // button or chip on the right
  children?: ReactNode;
  className?: string;
}) {
  return (
    <section id={id} className={`scroll-mt-28 rounded-[3px] border border-line bg-card p-7 ${className}`}>
      {(label || title || action) && (
        <div className={`flex items-start justify-between gap-4 ${children ? "mb-5" : ""}`}>
          <div className="min-w-0">
            {label && (
              <p className={`label-caps mb-2 flex items-center gap-2 ${LABEL_TONE[labelTone]}`}>{labelIcon}{label}</p>
            )}
            {title && <h2 className="text-[28px] leading-tight text-ink">{title}</h2>}
            {subtitle && <p className="mt-1.5 text-[15px] leading-snug text-muted">{subtitle}</p>}
            {note}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

// Button styles, so every step's buttons look the same.
export const BUTTON_PRIMARY =
  "inline-flex items-center justify-center gap-2 rounded-[2px] bg-lavender px-5 py-2.5 text-[15px] font-medium text-page transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40";
export const BUTTON_SECONDARY =
  "inline-flex items-center justify-center gap-2 rounded-[2px] border border-line px-5 py-2.5 text-[15px] text-ink transition hover:border-muted disabled:cursor-not-allowed disabled:opacity-40";
export const BUTTON_ATTACK =
  "inline-flex items-center justify-center gap-2 rounded-[2px] border border-coral/70 bg-red-panel px-5 py-2.5 text-[15px] text-coral transition hover:brightness-125 disabled:cursor-not-allowed disabled:opacity-40";
