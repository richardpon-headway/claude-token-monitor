import { useState } from "react";

/** Tiny SVG sparkline. Two modes:
 *
 *  - mode="bars" (default) — one bar per data point. Older bars at low
 *    alpha, latest brighter. Quota reference lines at integer multiples
 *    of `quota` within the y-range.
 *  - mode="cumulative" — designed for the "today" tile. Renders TWO
 *    layers in one SVG with INDEPENDENT y-scales:
 *      * hourly bars at the bottom, scaled to the peak hour (so bars
 *        retain their own intensity proportions)
 *      * cumulative running-total line + area on top, scaled to a
 *        multiple of `quota` chosen so the line never reaches the top
 *        (lineMax = (floor(total/quota) + 1) * quota). The dashed
 *        quota lines mark each integer multiple — the line crossing
 *        a quota line means "you've hit Nx the daily floor"
 *
 *  The svg is `width="100%" height="100%"` with `preserveAspectRatio="none"`,
 *  so it stretches to whatever container the caller positions it in. */

const VB_WIDTH = 100;
const VB_HEIGHT = 100;
const BAR_FILL = "rgba(16, 185, 129, 0.22)";       // emerald-500 / 22%
const BAR_FILL_LAST = "rgba(16, 185, 129, 0.45)";  // emerald-500 / 45%
const AREA_FILL = "rgba(16, 185, 129, 0.18)";
const AREA_STROKE = "rgba(16, 185, 129, 0.85)";
const QUOTA_STROKE = "rgba(161, 161, 170, 0.35)";  // zinc-400 / 35%

export function Sparkline({
  data,
  mode = "bars",
  quota,
  tooltipFor,
  className,
}: {
  data: number[];
  mode?: "bars" | "cumulative";
  quota?: number;
  /** Called per bar to produce a hover tooltip string. Rendered as a
   *  styled overlay (matches the activity-chart tooltip), not a native
   *  <title>, so it appears instantly with no OS delay. */
  tooltipFor?: (value: number, index: number) => string;
  className?: string;
}) {
  const [hovered, setHovered] = useState<number | null>(null);
  if (data.length === 0) return null;

  // Map the cursor's x-position within the SVG to a bar index. We use
  // mousemove on the SVG (instead of per-rect onMouseEnter) so narrow
  // bars don't require pixel-perfect aim.
  const handleMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const idx = Math.min(
      data.length - 1,
      Math.max(0, Math.floor((x / rect.width) * data.length)),
    );
    setHovered(idx);
  };

  return (
    <div className={className} style={{ position: "relative" }}>
      <svg
        width="100%"
        height="100%"
        viewBox={`0 0 ${VB_WIDTH} ${VB_HEIGHT}`}
        role="img"
        aria-label="trend"
        preserveAspectRatio="none"
        onMouseMove={tooltipFor ? handleMove : undefined}
        onMouseLeave={() => setHovered(null)}
      >
        {mode === "bars"
          ? renderBars(data, quota, hovered)
          : renderCumulative(data, quota)}
      </svg>
      {tooltipFor && hovered !== null && (
        <div
          className="absolute top-1 right-1 rounded border border-zinc-700 bg-zinc-950/90 px-2 py-1 text-xs text-zinc-200 pointer-events-none whitespace-nowrap shadow-lg"
        >
          {tooltipFor(data[hovered], hovered)}
        </div>
      )}
    </div>
  );
}

// --- bars mode -----------------------------------------------------------

function renderBars(
  data: number[],
  quota?: number,
  hovered?: number | null,
) {
  const max = Math.max(...data, 1);
  const gap = 0.5;
  const barW = Math.max(
    (VB_WIDTH - gap * (data.length - 1)) / data.length,
    0.1,
  );
  return (
    <>
      {quotaLines(max, quota)}
      {data.map((v, i) => {
        const h = Math.max((v / max) * VB_HEIGHT, v > 0 ? 1 : 0);
        // Hovered bar gets the brighter "last bar" emphasis fill so the
        // user can see which bar the tooltip refers to.
        const isHighlighted =
          (hovered === i) || (hovered == null && i === data.length - 1);
        return (
          <rect
            key={i}
            x={i * (barW + gap)}
            y={VB_HEIGHT - h}
            width={barW}
            height={h}
            fill={isHighlighted ? BAR_FILL_LAST : BAR_FILL}
          />
        );
      })}
    </>
  );
}

// --- cumulative mode -----------------------------------------------------

function renderCumulative(data: number[], quota?: number) {
  // Hourly bars at their own scale so they remain visually proportional
  // to the peak hour (otherwise they'd be tiny against the daily quota).
  const barMax = Math.max(...data, 1);
  const gap = 0.5;
  const barW = Math.max(
    (VB_WIDTH - gap * (data.length - 1)) / data.length,
    0.1,
  );

  // Cumulative running sums prepended with 0 so the line starts at the
  // bottom-left at hour 0.
  const cum = data.reduce<number[]>(
    (acc, v) => [...acc, (acc[acc.length - 1] ?? 0) + v],
    [0],
  );
  const total = cum[cum.length - 1];

  // Independent y-scale for the line: pick lineMax such that there's
  // always at least one quota line ABOVE the line's current end.
  let lineMax: number;
  if (quota && quota > 0) {
    const completed = Math.floor(total / quota);
    lineMax = (completed + 1) * quota;
  } else {
    lineMax = Math.max(total, 1);
  }

  const n = cum.length;
  const stepX = VB_WIDTH / (n - 1);
  const points = cum.map((v, i) => ({
    x: i * stepX,
    y: VB_HEIGHT - (v / lineMax) * VB_HEIGHT,
  }));
  const linePath = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`)
    .join(" ");
  const areaPath = `${linePath} L ${VB_WIDTH} ${VB_HEIGHT} L 0 ${VB_HEIGHT} Z`;

  return (
    <>
      {/* quota lines tied to the line's scale (the line's question is
          'how many quotas have I burned today'). */}
      {quotaLines(lineMax, quota)}
      {/* hourly bars beneath, at their own scale. Render first so the
          line/area overlay them. */}
      {data.map((v, i) => {
        const h = Math.max((v / barMax) * VB_HEIGHT, v > 0 ? 1 : 0);
        return (
          <rect
            key={`b${i}`}
            x={i * (barW + gap)}
            y={VB_HEIGHT - h}
            width={barW}
            height={h}
            fill={BAR_FILL}
          />
        );
      })}
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

// --- shared --------------------------------------------------------------

function quotaLines(yMax: number, quota: number | undefined) {
  if (!quota || quota <= 0) return null;
  const maxMultiple = Math.min(Math.floor(yMax / quota), 8);
  const lines: React.ReactNode[] = [];
  for (let k = 1; k <= maxMultiple; k++) {
    const y = VB_HEIGHT - ((k * quota) / yMax) * VB_HEIGHT;
    lines.push(
      <line
        key={`q${k}`}
        x1={0}
        x2={VB_WIDTH}
        y1={y}
        y2={y}
        stroke={QUOTA_STROKE}
        strokeWidth={0.5}
        strokeDasharray="1.5 1.5"
        vectorEffect="non-scaling-stroke"
      />,
    );
  }
  return <>{lines}</>;
}
