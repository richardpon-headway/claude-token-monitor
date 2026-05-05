/** Tiny SVG bar sparkline. Positioned-by-the-caller (defaults to width
 *  and height of 100% of the parent), with `preserveAspectRatio="none"`
 *  so bars stretch in both axes. Use as a tile background by giving
 *  the parent `relative` and the sparkline `absolute inset-0`.
 *
 *  Colors: emerald at low alpha so the bars don't fight the text on top.
 *  Latest bar slightly brighter so the eye lands on "now". */
const VB_WIDTH = 100;
const VB_HEIGHT = 100;

export function Sparkline({
  data,
  className,
}: {
  data: number[];
  className?: string;
}) {
  if (data.length === 0) return null;
  const max = Math.max(...data, 1);
  const gap = 0.5;
  const barW = Math.max(
    (VB_WIDTH - gap * (data.length - 1)) / data.length,
    0.1,
  );

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
