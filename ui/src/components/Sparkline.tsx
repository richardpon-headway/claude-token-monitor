/** Tiny SVG bar sparkline. No axes, no labels — the parent tile carries
 *  the headline number. Last bar is emphasized so the eye lands on "now".
 *  Muted zinc fill so the tile stays visually secondary to the chart.
 *
 *  The SVG is `width="100%"` with `preserveAspectRatio="none"`, so bars
 *  stretch to fill the parent container's width. The viewBox uses a
 *  fixed internal coordinate system (100 wide), independent of the
 *  rendered pixel width. */
const VB_WIDTH = 100;

export function Sparkline({
  data,
  height = 28,
}: {
  data: number[];
  height?: number;
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
      height={height}
      viewBox={`0 0 ${VB_WIDTH} ${height}`}
      role="img"
      aria-label="trend"
      preserveAspectRatio="none"
      className="block"
    >
      {data.map((v, i) => {
        const h = Math.max((v / max) * height, v > 0 ? 1 : 0);
        const x = i * (barW + gap);
        const y = height - h;
        const isLast = i === data.length - 1;
        return (
          <rect
            key={i}
            x={x}
            y={y}
            width={barW}
            height={h}
            // muted zinc; last bar slightly brighter
            fill={isLast ? "#a1a1aa" : "#52525b"}
          />
        );
      })}
    </svg>
  );
}
