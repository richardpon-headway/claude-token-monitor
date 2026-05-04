/** Today's output as a percentage of the workday-pro-rated quota floor.
 *  Red when > 100%, amber when > 80%, otherwise emerald. */

const WORKDAY_FLOOR = 233_333; // 5M / 30 / (5/7) per plan-16

export function QuotaBar({ todayOutput }: { todayOutput: number }) {
  const pct = (todayOutput / WORKDAY_FLOOR) * 100;
  const clamped = Math.min(pct, 100);
  const over = pct > 100;
  const color =
    pct > 100 ? "bg-red-500"
    : pct > 80 ? "bg-amber-400"
    : "bg-emerald-500";

  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className="text-zinc-400">Today</span>
        <span className="tabular-nums">
          <span className="font-semibold text-zinc-100">
            {todayOutput.toLocaleString()}
          </span>
          <span className="text-zinc-500"> / {WORKDAY_FLOOR.toLocaleString()} </span>
          <span
            className={
              pct > 100 ? "text-red-400"
              : pct > 80 ? "text-amber-300"
              : "text-emerald-400"
            }
          >
            ({pct.toFixed(0)}%)
          </span>
        </span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-zinc-800 overflow-hidden">
        <div
          className={`h-full transition-all ${color}`}
          style={{ width: `${clamped}%` }}
        />
        {over && (
          <div className="h-0.5 -mt-2 w-full bg-red-500/40 animate-pulse" />
        )}
      </div>
    </div>
  );
}
