import { useMemo } from "react";
import {
  Bar,
  BarChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { RangeKey, TimeseriesResponse } from "../types";

const WORKDAY_FLOOR = 233_333;
const MINUTES_PER_DAY = 24 * 60;

/** Per-bucket workday-floor reference value. The floor is "tokens per
 *  workday"; scale it by the bucket width to compare against per-bucket
 *  output. */
function floorForBucket(granularity: TimeseriesResponse["granularity"]): number {
  switch (granularity) {
    case "minute": return WORKDAY_FLOOR / MINUTES_PER_DAY;
    case "hour":   return WORKDAY_FLOOR / 24;
    case "4hour":  return WORKDAY_FLOOR / 6;
    case "day":    return WORKDAY_FLOOR;
  }
}

/** Pads the buckets so missing time slices render as zeros. Daemon only
 *  returns slices with activity; UI fills the gaps so the chart has a
 *  continuous left-to-right time axis. */
function padBuckets(
  buckets: TimeseriesResponse["buckets"],
  range: RangeKey,
  granularity: TimeseriesResponse["granularity"],
): { t: string; output: number; ts: number }[] {
  const have = new Map<number, number>(
    buckets.map((b) => [Math.floor(new Date(b.t).getTime() / 60_000), b.output]),
  );
  const now = new Date();
  const out: { t: string; output: number; ts: number }[] = [];

  // Each granularity is just "how many minutes wide is one bar?"
  const bucketWidthMin: Record<TimeseriesResponse["granularity"], number> = {
    minute: 1,
    hour: 60,
    "4hour": 240,
    day: 1440,
  };
  const widthMin = bucketWidthMin[granularity];
  const widthMs = widthMin * 60_000;

  // Total bars in the view
  const totalBars: Record<RangeKey, number> = {
    "1h": 60,
    "4h": 240,
    "1d": 1440,
    "7d": 7 * 24,        // 168 hour-bars
    "30d": 30 * 6,       // 180 four-hour-bars
  };
  const total = totalBars[range];

  // Anchor the rightmost bucket on now (rounded DOWN to bucket boundary).
  const nowBucketMs = Math.floor(now.getTime() / widthMs) * widthMs;
  const startMs = nowBucketMs - (total - 1) * widthMs;

  for (let i = 0; i < total; i++) {
    const ts = startMs + i * widthMs;
    const minuteKey = Math.floor(ts / 60_000);
    out.push({
      t: new Date(ts).toISOString(),
      output: have.get(minuteKey) ?? 0,
      ts,
    });
  }
  return out;
}

function pad(n: number): string { return String(n).padStart(2, "0"); }

function formatTickMinute(ts: number): string {
  const d = new Date(ts);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function formatTickDay(ts: number): string {
  const d = new Date(ts);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

export function LiveChart({
  data,
  range,
}: {
  data: TimeseriesResponse;
  range: RangeKey;
}) {
  const padded = useMemo(
    () => padBuckets(data.buckets, range, data.granularity),
    [data.buckets, range, data.granularity],
  );
  const isMinute = data.granularity === "minute";
  const floor1x = floorForBucket(data.granularity);
  const floor2x = floor1x * 2;
  // Sub-day granularities show clock time on ticks; day-or-coarser show M/D.
  const tickFormatter = isMinute ? formatTickMinute : formatTickDay;

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3">
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={padded}
            margin={{ top: 4, right: 8, left: 0, bottom: 4 }}
            barCategoryGap={1}
          >
            <XAxis
              dataKey="ts"
              type="category"
              tickFormatter={(ts) => tickFormatter(Number(ts))}
              tick={{ fill: "#71717a", fontSize: 11 }}
              tickLine={{ stroke: "#3f3f46" }}
              axisLine={{ stroke: "#3f3f46" }}
              minTickGap={28}
              interval="preserveStartEnd"
            />
            <YAxis
              tick={{ fill: "#71717a", fontSize: 11 }}
              tickLine={{ stroke: "#3f3f46" }}
              axisLine={{ stroke: "#3f3f46" }}
              tickFormatter={(v: number) => abbr(v)}
              width={48}
            />
            <Tooltip
              cursor={{ fill: "#27272a", opacity: 0.5 }}
              contentStyle={{
                background: "#18181b",
                border: "1px solid #3f3f46",
                borderRadius: 6,
                color: "#e4e4e7",
                fontSize: 12,
              }}
              labelFormatter={(ts: number | string) => {
                const d = new Date(Number(ts));
                return isMinute ? d.toLocaleString() : d.toLocaleDateString();
              }}
              formatter={(v: number) => [v.toLocaleString(), "output tokens"]}
            />
            <ReferenceLine
              y={floor1x}
              stroke="#3f3f46"
              strokeDasharray="3 3"
              label={{ value: "1× floor", fill: "#71717a", fontSize: 10, position: "right" }}
            />
            <ReferenceLine
              y={floor2x}
              stroke="#52525b"
              strokeDasharray="3 3"
              label={{ value: "2× floor", fill: "#71717a", fontSize: 10, position: "right" }}
            />
            <Bar
              dataKey="output"
              fill="#10b981"
              isAnimationActive={false}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function abbr(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}k`;
  return String(n);
}
