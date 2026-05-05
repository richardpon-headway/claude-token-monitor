import { useMemo } from "react";
import {
  Bar,
  BarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { RangeKey, TimeseriesResponse } from "../types";

/** Pads the buckets so missing time slices render as zeros. Daemon only
 *  returns slices with activity; UI fills the gaps so the chart has a
 *  continuous left-to-right time axis. */
function padBuckets(
  buckets: TimeseriesResponse["buckets"],
  range: RangeKey,
  granularity: TimeseriesResponse["granularity"],
  tz: "local" | "utc" = "local",
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

  // Anchor the rightmost bucket to midnight + N*widthMs in the chosen
  // timezone. The daemon aggregates per-tz on its side so this match is
  // what keeps lookups from missing for hour/4hour buckets. For widthMin
  // in {1, 60, 240, 1440} (all factors of 1440) the alignment also stays
  // correct across day boundaries when walking backward.
  const dayStartMs =
    tz === "utc"
      ? Date.UTC(
          now.getUTCFullYear(),
          now.getUTCMonth(),
          now.getUTCDate(),
        )
      : (() => {
          const d = new Date(now);
          d.setHours(0, 0, 0, 0);
          return d.getTime();
        })();
  const msSinceMidnight = now.getTime() - dayStartMs;
  const nowBucketMs =
    dayStartMs + Math.floor(msSinceMidnight / widthMs) * widthMs;
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

function formatTickMinute(ts: number, tz: "local" | "utc"): string {
  const d = new Date(ts);
  return tz === "utc"
    ? `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`
    : `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function formatTickDay(ts: number, tz: "local" | "utc"): string {
  const d = new Date(ts);
  return tz === "utc"
    ? `${d.getUTCMonth() + 1}/${d.getUTCDate()}`
    : `${d.getMonth() + 1}/${d.getDate()}`;
}

export function LiveChart({
  data,
  range,
  tz = "local",
}: {
  data: TimeseriesResponse;
  range: RangeKey;
  tz?: "local" | "utc";
}) {
  const padded = useMemo(
    () => padBuckets(data.buckets, range, data.granularity, tz),
    [data.buckets, range, data.granularity, tz],
  );
  const isMinute = data.granularity === "minute";
  // Sub-day granularities show clock time on ticks; day-or-coarser show M/D.
  const tickFormatter = (ts: number) =>
    isMinute ? formatTickMinute(ts, tz) : formatTickDay(ts, tz);

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
                const opts: Intl.DateTimeFormatOptions = tz === "utc"
                  ? { timeZone: "UTC" }
                  : {};
                return isMinute
                  ? d.toLocaleString(undefined, opts) + (tz === "utc" ? " UTC" : "")
                  : d.toLocaleDateString(undefined, opts) + (tz === "utc" ? " UTC" : "");
              }}
              formatter={(v: number) => [v.toLocaleString(), "output tokens"]}
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
