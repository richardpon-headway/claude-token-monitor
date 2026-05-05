/** Tiny SVG bar sparkline. No axes, no labels — the parent tile carries
 *  the headline number. Last bar is emphasized so the eye lands on "now".
 *  Muted zinc fill so the tile stays visually secondary to the chart. */
export function Sparkline({
  data,
  width = 100,
  height = 28,
}: {
  data: number[];
  width?: number;
  height?: number;
}) {
  if (data.length === 0) return null;
  const max = Math.max(...data, 1);
  const gap = 1;
  const barW = Math.max((width - gap * (data.length - 1)) / data.length, 0.5);

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="trend"
      preserveAspectRatio="none"
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
