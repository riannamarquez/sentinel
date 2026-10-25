import { ShieldIcon } from "./ScorecardStep";
import StepCard from "./StepCard";

// What each party is given, per sentinel/api/app.py: Red gets the current rules and the synthetic
// bank, Blue gets Red's bypass trace and the current rules, and only the evaluator sees the holdout.
const PARTIES = [
  { mark: "R", name: "Red agent", sees: "Current rules and synthetic bank only", tone: "border-coral/60 bg-red-panel text-coral" },
  { mark: "B", name: "Blue agent", sees: "Attack path and current rules only", tone: "border-lavender/60 bg-lavender-panel text-lavender" },
  { mark: null, name: "Evaluator", sees: "Held-out attacks and customers", tone: "border-line bg-card-raised text-ink" },
];

export default function TestIntegrity() {
  return (
    <StepCard id="test-integrity" label="Test integrity" title="What the agents could see">
      <ul className="grid gap-5 border-t border-line pt-6 sm:grid-cols-3">
        {PARTIES.map((p) => (
          <li key={p.name} className="flex gap-3">
            <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-[2px] border text-[18px] ${p.tone}`}>
              {p.mark ?? ShieldIcon}
            </span>
            <div>
              <p className="text-[16px] text-ink">{p.name}</p>
              <p className="text-[14px] leading-snug text-muted">{p.sees}</p>
            </div>
          </li>
        ))}
      </ul>
    </StepCard>
  );
}
