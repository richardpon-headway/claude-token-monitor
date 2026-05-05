/** Tiny SVG sparkline. Two modes:
 *
 *  - mode="bars" (default) — one bar per data point. Older bars at low
 *    alpha, latest brighter, quota lines at integer multiples within
 *    the y-range.
 *  - mode="cumulative" — running-sum area chart. The line starts at
 *    zero, climbs through each cumulative value, and ends at the
 *    series total. Quota lines mark each multiple of `quota` so you
 *    can see at a glance whether the running total has crossed 1×,
 *    2×, 3× of the budget.
 *
 *  The svg is `width="100%" height="100%"` with `preserveAspectRatio="none"`,
 *  so it stretches to whatever container the caller positions it in. */

const VB_WIDTH = 100;
const VB_HEIGHT = 100;
const BAR_FILL = "rgba(16, 185, 129, 0.22)";       // emerald-500/22%
const BAR_FILL_LAST = "rgba(16, 185, 129, 0.45)";  // emerald-500/45%
const AREA_FILL = "rgba(16, 185, 129, 0.20)";
const AREA_STROKE = "rgba(16, 185, 129, 0.85)";
const QUOTA_STROKE = "rgba(161, 161, 170, 0.35)";  // zinc-400/35%

export function Sparkline({
  data,
  mode = "bars",
  quota,
  className,
}: {
  data: number[];
  mode?: "bars" | "cumulative";
  quota?: number;
  className?: string;
}) {
  if (data.length === 0) return null;

  // For cumulative mode, transform `data` into running sums prepended
  // with a 0 so the line starts at the bottom-left at hour 0.
  const series =
    mode === "cumulative"
      ? data.reduce<number[]>(
          (acc, v) => [...acc, (acc[acc.length - 1] ?? 0) + v],
          [0],
        )
      : data;
  const max = Math.max(...series, 1);

  // Quota reference lines (drawn first so the data overlays them).
  // Capped at 8 multiples to avoid stripey clutter.
  const quotaLines: number[] = [];
  if (quota && quota > 0) {
    const maxMultiple = Math.min(Math.floor(max / quota), 8);
    for (let k = 1; k <= maxMultiple; k++) {
      quotaLines.push(VB_HEIGHT - ((k * quota) / max) * VB_HEIGHT);
    }
  }

  return (
    <svg
      width="100%"
      height="100%"
      viewBox={`0 0 ${VB_WIDTH} ${VB_HEIGHT}`}
      role="img"
      aria-label="trend"
      preserveAspectRatio="none"
      className={className}
    >
      {quotaLines.map((y, i) => (
        <line
          key={`q${i}`}
          x1={0}
          x2={VB_WIDTH}
          y1={y}
          y2={y}
          stroke={QUOTA_STROKE}
          strokeWidth={0.5}
          strokeDasharray="1.5 1.5"
          vectorEffect="non-scaling-stroke"
        />
      ))}

      {mode === "bars"
        ? renderBars(data, max)
        : renderCumulative(series, max)}
    </svg>
  );
}

function renderBars(data: number[], max: number) {
  const gap = 0.5;
  const barW = Math.max(
    (VB_WIDTH - gap * (data.length - 1)) / data.length,
    0.1,
  );
  return data.map((v, i) => {
    const h = Math.max((v / max) * VB_HEIGHT, v > 0 ? 1 : 0);
    return (
      <rect
        key={i}
        x={i * (barW + gap)}
        y={VB_HEIGHT - h}
        width={barW}
        height={h}
        fill={i === data.length - 1 ? BAR_FILL_LAST : BAR_FILL}
      />
    );
  });
}

function renderCumulative(series: number[], max: number) {
  const n = series.length;
  if (n < 2) return null;
  const stepX = VB_WIDTH / (n - 1);
  const points = series.map((v, i) => ({
    x: i * stepX,
    y: VB_HEIGHT - (v / max) * VB_HEIGHT,
  }));
  const linePath = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`)
    .join(" ");
  const areaPath = `${linePath} L ${VB_WIDTH} ${VB_HEIGHT} L 0 ${VB_HEIGHT} Z`;
  return (
    <>
      <path d={areaPath} fill={AREA_FILL} />
      <path
        d={linePath}
        fill="none"
        stroke={AREA_STROKE}
        strokeWidth={1}
        vectorEffect="non-scaling-stroke"
      />
    </>
  );
}
