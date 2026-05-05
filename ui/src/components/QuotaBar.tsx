/** Today's output as a percentage of the workday-pro-rated quota floor.
 *
 *  The bar auto-extends past 100%: scaleMax is the next 100% increment
 *  above current usage (so at 105% the track shows up to 200%; at 244%
 *  it shows up to 300%). Vertical tick marks land at every 100%
 *  increment within the scale, so you can read exactly how many
 *  quotas you're at by where the bar's right edge sits relative to
 *  the ticks.
 *
 *  Color: emerald < 80%, amber < 100%, red ≥ 100%. */

const WORKDAY_FLOOR = 233_333; // 5M / 30 / (5/7) per plan-16

export function QuotaBar({ todayOutput }: { todayOutput: number }) {
  const pct = (todayOutput / WORKDAY_FLOOR) * 100;
  // ε so exactly 100/200/300% nudges to the next bracket and the
  // current-quota tick stays visible to the LEFT of the bar's edge.
  const scaleMax = Math.max(100, Math.ceil((pct + 0.0001) / 100) * 100);
  const barWidth = (pct / scaleMax) * 100;

  // Tick positions for each 1×, 2×, ..., (scaleMax/100 - 1)× boundary.
  const ticks: number[] = [];
  for (let k = 100; k < scaleMax; k += 100) {
    ticks.push((k / scaleMax) * 100);
  }

  const color =
    pct > 100 ? "bg-red-500"
    : pct > 80 ? "bg-amber-400"
    : "bg-emerald-500";
  const pctColor =
    pct > 100 ? "text-red-400"
    : pct > 80 ? "text-amber-300"
    : "text-emerald-400";

  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className="text-zinc-400">Today</span>
        <span className="tabular-nums">
          <span className="font-semibold text-zinc-100">
            {todayOutput.toLocaleString()}
          </span>
          <span className="text-zinc-500"> / {WORKDAY_FLOOR.toLocaleString()} </span>
          <span className={pctColor}>({pct.toFixed(0)}%)</span>
        </span>
      </div>
      <div className="relative h-1.5 w-full">
        {/* track + colored bar — rounded ends, clips overflow */}
        <div className="absolute inset-0 rounded-full bg-zinc-800 overflow-hidden">
          <div
            className={`h-full transition-all ${color}`}
            style={{ width: `${barWidth}%` }}
          />
        </div>
        {/* tick marks — 2px wide, extend 3px above and below the track
            so they read as deliberate quota markers, not edges of the bar */}
        {ticks.map((leftPct, i) => (
          <div
            key={i}
            className="absolute w-0.5 -translate-x-1/2 bg-zinc-100/70"
            style={{ left: `${leftPct}%`, top: -3, bottom: -3 }}
            aria-hidden
          />
        ))}
      </div>
    </div>
  );
}
