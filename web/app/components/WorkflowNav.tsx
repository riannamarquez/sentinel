export type WorkflowItem = { title: string; detail: string; target: string; enabled: boolean };

export default function WorkflowNav({ items, current, complete, onNavigate }: {
  items: WorkflowItem[]; current: number; complete: boolean; onNavigate: (id: string) => void;
}) {
  return (
    <nav className="workflow-nav" aria-label="Experiment steps">
      <p className="label-caps mb-5 px-3 text-muted">The workflow</p>
      <ol>
        {items.map((item, index) => {
          const number = index + 1;
          const done = complete || number < current;
          const active = !complete && number === current;
          return (
            <li key={item.title}>
              <button disabled={!item.enabled} onClick={() => onNavigate(item.target)} aria-current={active ? "step" : undefined}
                className={number === 3 ? "red-step" : number === 4 ? "blue-step" : ""}>
                <span className="step-number" aria-hidden="true">{done ? "✓" : String(number).padStart(2, "0")}</span>
                <span className="min-w-0">
                  <span className={`block text-[13px] ${active || done ? "text-ink" : "text-muted"}`}>{item.title}</span>
                  <span className="step-description mt-1 block text-[11px] text-muted">{item.detail}</span>
                  <span className="sr-only">{done ? ", complete" : active ? ", current step" : ", upcoming"}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      <div className="workflow-note mt-8 border-t border-line px-3 pt-5">
        <p className="label-caps text-ink">Guided experiment</p>
        <p className="mt-2 text-[12px] leading-relaxed text-muted">The agents work within each stage. You advance the workflow and control approval.</p>
      </div>
    </nav>
  );
}
