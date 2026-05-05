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

/** Decide whether a given timestamp deserves an x-axis tick, per range.
 *  The intent is to keep tick density readable AND ensure date labels
 *  land exactly at midnight in the chosen timezone. */
function isTickTime(
  ts: number,
  range: RangeKey,
  tz: "local" | "utc",
): boolean {
  const d = new Date(ts);
  const h = tz === "utc" ? d.getUTCHours() : d.getHours();
  const m = tz === "utc" ? d.getUTCMinutes() : d.getMinutes();
  switch (range) {
    case "1h":  return m % 15 === 0;
    case "4h":  return m === 0;
    case "1d":  return m === 0 && h % 4 === 0;
    case "7d":  return m === 0 && (h === 0 || h === 12);
    case "30d": return m === 0 && h === 0;
  }
}

/** Render a tick label. Midnight → "M/D"; otherwise "HH:MM" (or "HH:00"
 *  when the tick lands on the hour). Keeps date labels visually distinct
 *  from time-of-day labels. */
function smartTickLabel(ts: number, tz: "local" | "utc"): string {
  const d = new Date(ts);
  const h = tz === "utc" ? d.getUTCHours() : d.getHours();
  const m = tz === "utc" ? d.getUTCMinutes() : d.getMinutes();
  if (h === 0 && m === 0) {
    return tz === "utc"
      ? `${d.getUTCMonth() + 1}/${d.getUTCDate()}`
      : `${d.getMonth() + 1}/${d.getDate()}`;
  }
  return `${pad(h)}:${pad(m)}`;
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

  // Explicit tick positions: only "interesting" timestamps (midnights and
  // a handful of round hour marks per range). Time-scale axis (below)
  // honors arbitrary numeric tick values, so this works reliably.
  const ticks = useMemo(
    () =>
      padded
        .filter((p) => isTickTime(p.ts, range, tz))
        .map((p) => p.ts),
    [padded, range, tz],
  );

  // Extend the domain by half a bucket on each side. Recharts centers
  // each bar on its ts coordinate, so the leftmost/rightmost bars
  // would be half-clipped at the plot edges with a tight domain (the
  // left bar visibly overlapped the y-axis).
  const domain = useMemo<[number, number] | undefined>(() => {
    if (padded.length === 0) return undefined;
    const widthMin: Record<TimeseriesResponse["granularity"], number> = {
      minute: 1,
      hour: 60,
      "4hour": 240,
      day: 1440,
    };
    const halfWidthMs = (widthMin[data.granularity] * 60_000) / 2;
    return [
      padded[0].ts - halfWidthMs,
      padded[padded.length - 1].ts + halfWidthMs,
    ];
  }, [padded, data.granularity]);

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
              type="number"
              scale="time"
              domain={domain ?? ["dataMin", "dataMax"]}
              ticks={ticks}
              tickFormatter={(ts) => smartTickLabel(Number(ts), tz)}
              tick={{ fill: "#71717a", fontSize: 11 }}
              tickLine={{ stroke: "#3f3f46" }}
              axisLine={{ stroke: "#3f3f46" }}
              interval={0}
              allowDuplicatedCategory={false}
            />
            <YAxis
              tick={{ fill: "#71717a", fontSize: 11 }}
              tickLine={{ stroke: "#3f3f46" }}
              axisLine={{ stroke: "#3f3f46" }}
              tickFormatter={(v: number) => abbr(v)}
              width={48}
              // Small bottom padding so bars don't sit flush on the
              // x-axis line (which made them look like they were
              // overflowing past it).
              padding={{ bottom: 2, top: 4 }}
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
