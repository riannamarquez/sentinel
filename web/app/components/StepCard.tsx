import type { ReactNode } from "react";

// The white card every step sits in. `id` is the auto-scroll target.
export default function StepCard({ id, title, subtitle, action, children }: {
  id: string;
  title: string;
  subtitle?: string;
  action?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-24 rounded-xl border bg-white p-6 shadow-sm">
      <div className={`flex items-center justify-between gap-4 ${children ? "mb-4" : ""}`}>
        <div>
          <h2 className="text-lg font-semibold">{title}</h2>
          {subtitle && <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
