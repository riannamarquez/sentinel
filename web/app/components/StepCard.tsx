import type { ReactNode } from "react";

export type Tone = "coral" | "lavender" | "muted" | "mint";
const LABEL_TONE: Record<Tone, string> = { coral: "text-coral", lavender: "text-lavender", muted: "text-muted", mint: "text-ink" };

export function Chip({ tone = "lavender", icon, children }: { tone?: Tone; icon?: ReactNode; children: ReactNode }) {
  return <span className="review-chip" data-tone={tone}>{icon}{children}</span>;
}

export default function StepCard({ id, label, labelTone = "muted", labelIcon, title, subtitle, note, action, children, className = "" }: {
  id: string; label?: string; labelTone?: Tone; labelIcon?: ReactNode; title?: ReactNode;
  subtitle?: ReactNode; note?: ReactNode; action?: ReactNode; children?: ReactNode; className?: string;
}) {
  return (
    <section id={id} data-tone={labelTone} className={`agent-panel ${className}`}>
      {(label || title || action) && (
        <div className={`panel-heading ${children ? "mb-5" : ""}`}>
          <div className="min-w-0">
            {label && <p className={`label-caps mb-3 flex items-center gap-2 ${LABEL_TONE[labelTone]}`}>{labelIcon}{label}</p>}
            {title && <h2>{title}</h2>}
            {subtitle && <p className="mt-3 text-[13px] leading-relaxed text-muted">{subtitle}</p>}
            {note}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export const BUTTON_PRIMARY = "review-button review-button-primary";
export const BUTTON_SECONDARY = "review-button review-button-secondary";
export const BUTTON_ATTACK = "review-button review-button-secondary review-button-red";
