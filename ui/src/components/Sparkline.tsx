/** Tiny SVG bar sparkline. Positioned-by-the-caller (defaults to width
 *  and height of 100% of the parent), with `preserveAspectRatio="none"`
 *  so bars stretch in both axes. Use as a tile background by giving
 *  the parent `relative` and the sparkline `absolute inset-0` (or a
 *  small inset like `inset-1` to leave a gap from the tile border).
 *
 *  Optional `quota` draws faint dashed horizontal reference lines at
 *  every integer multiple of the quota that falls inside the chart's
 *  y-range — so you can see at-a-glance how many "quotas" each bar
 *  represents (1×, 2×, 3×, etc.).
 *
 *  Colors: emerald at low alpha so the bars don't fight the text on top.
 *  Latest bar slightly brighter so the eye lands on "now". */
const VB_WIDTH = 100;
const VB_HEIGHT = 100;

export function Sparkline({
  data,
  quota,
  className,
}: {
  data: number[];
  quota?: number;
  className?: string;
}) {
  if (data.length === 0) return null;
  const max = Math.max(...data, 1);
  const gap = 0.5;
  const barW = Math.max(
    (VB_WIDTH - gap * (data.length - 1)) / data.length,
    0.1,
  );

  // Quota lines: y for each integer multiple of `quota` that falls
  // inside the chart's y-range. Limit to 8 to avoid stripey clutter.
  const quotaLines: number[] = [];
  if (quota && quota > 0) {
    const maxMultiple = Math.min(Math.floor(max / quota), 8);
    for (let k = 1; k <= maxMultiple; k++) {
      const y = VB_HEIGHT - ((k * quota) / max) * VB_HEIGHT;
      quotaLines.push(y);
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
      {/* quota reference lines drawn first so bars overlay them */}
      {quotaLines.map((y, i) => (
        <line
          key={`q${i}`}
          x1={0}
          x2={VB_WIDTH}
          y1={y}
          y2={y}
          stroke="rgba(161, 161, 170, 0.35)"
          strokeWidth={0.5}
          strokeDasharray="1.5 1.5"
          vectorEffect="non-scaling-stroke"
        />
      ))}
      {data.map((v, i) => {
        const h = Math.max((v / max) * VB_HEIGHT, v > 0 ? 1 : 0);
        const x = i * (barW + gap);
        const y = VB_HEIGHT - h;
        const isLast = i === data.length - 1;
        return (
          <rect
            key={i}
            x={x}
            y={y}
            width={barW}
            height={h}
            // emerald-500 at low alpha — keeps text readable on top.
            // Last bar at higher alpha so the eye lands on "now".
            fill={isLast ? "rgba(16, 185, 129, 0.45)" : "rgba(16, 185, 129, 0.22)"}
          />
        );
      })}
    </svg>
  );
}
