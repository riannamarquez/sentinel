import { hoursText, type HoldBar, type RuleLimit } from "./bypassExplain";

const LANE_PX = 48;

function tickStep(totalH: number) {
  return totalH <= 36 ? 6 : totalH <= 96 ? 12 : 24;
}

// Swimlanes: one lane per account that held the stolen money, a red bar for each hold, thin
// connectors at each handoff, and each rule's time limit drawn to the same scale in green.
export default function AttackTimeline({ bars, totalH, limits }: {
  bars: HoldBar[];
  totalH: number;
  limits: RuleLimit[] | null;
}) {
  const step = tickStep(totalH);
  const axisH = Math.max(step, Math.ceil(totalH / step) * step);
  const pct = (h: number) => `${(h / axisH) * 100}%`;
  const ticks = Array.from({ length: axisH / step + 1 }, (_, i) => i * step);
  const firstStart = bars[0]?.startH ?? 0;

  return (
    <div className="rounded-lg border p-4">
      <div className="grid grid-cols-[7rem_minmax(0,1fr)] gap-x-3">
        {/* Rule time limits, starting where the first hold starts so the sizes compare directly */}
        {limits?.map((l) => (
          <div key={l.ruleId} className="contents">
            <div className="flex h-7 items-center text-xs font-medium text-emerald-800">{l.ruleId}</div>
            <div className="relative h-7">
              <div className="absolute top-1.5 h-4 rounded-sm border border-emerald-600 bg-emerald-200"
                style={{ left: pct(firstStart), width: `max(3px, ${pct(l.hours)})` }} />
              <span className="absolute top-1 whitespace-nowrap pl-2 text-xs text-emerald-800"
                style={{ left: `calc(${pct(firstStart)} + max(3px, ${pct(l.hours)}))` }}>
                {l.label}
              </span>
            </div>
          </div>
        ))}

        {bars.map((b, i) => {
          const width = ((b.endH - b.startH) / axisH) * 100;
          const inside = width >= 16;
          return (
            <div key={`${b.account}-${i}`} className="contents">
              <div className="flex items-center border-t text-sm font-semibold text-slate-800" style={{ height: LANE_PX }}>
                {b.label}
              </div>
              <div className="relative border-t" style={{ height: LANE_PX }}>
                {/* handoff connectors: down from this bar's end, and into the next bar's start */}
                {i > 0 && <div className="absolute top-0 h-1/2 w-0.5 bg-red-400" style={{ left: pct(b.startH) }} />}
                {i < bars.length - 1 && <div className="absolute top-1/2 h-1/2 w-0.5 bg-red-400" style={{ left: pct(b.endH) }} />}
                <div className="absolute top-1/2 flex h-6 -translate-y-1/2 items-center justify-center rounded bg-red-600 text-xs font-semibold text-white"
                  style={{ left: pct(b.startH), width: `max(3px, ${width}%)` }}>
                  {inside && `held ${hoursText(b.heldH)}`}
                </div>
                {!inside && (
                  <span className="absolute top-1/2 -translate-y-1/2 whitespace-nowrap pl-2 text-xs font-semibold text-red-700"
                    style={{ left: pct(b.endH) }}>
                    held {hoursText(b.heldH)}
                  </span>
                )}
              </div>
            </div>
          );
        })}

        {/* Axis */}
        <div className="border-t pt-1 text-xs text-slate-500">time</div>
        <div className="relative h-8 border-t">
          {ticks.map((h, i) => (
            <div key={h} className="absolute top-0" style={{ left: pct(h) }}>
              <div className="h-1.5 w-px bg-slate-400" />
              <span className={`absolute top-2 whitespace-nowrap text-xs text-slate-600 ${
                i === 0 ? "" : i === ticks.length - 1 ? "-translate-x-full" : "-translate-x-1/2"}`}>
                hour {h}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-600">
        <span className="flex items-center gap-1.5"><span className="inline-block h-3 w-5 rounded-sm bg-red-600" /> stolen money sitting in an account</span>
        <span className="flex items-center gap-1.5"><span className="inline-block h-3 w-5 rounded-sm border border-emerald-600 bg-emerald-200" /> a rule&apos;s time limit, to the same scale</span>
        {limits === null && <span>Rule time limits aren&apos;t available for this run.</span>}
      </div>
    </div>
  );
}
