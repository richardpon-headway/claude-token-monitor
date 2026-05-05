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
const PER_MIN_FLOOR = WORKDAY_FLOOR / MINUTES_PER_DAY;

/** Number of minute buckets to render for each minute-granular range. */
const MINUTE_BUCKET_COUNT: Record<string, number> = {
  "1h": 60,
  "4h": 240,
  "1d": MINUTES_PER_DAY,
};

/** Pads the buckets so missing time slices render as zeros. Daemon only
 *  returns slices with activity; UI fills the gaps so the chart has a
 *  continuous left-to-right time axis. */
function padBuckets(
  buckets: TimeseriesResponse["buckets"],
  range: RangeKey,
  granularity: "minute" | "day",
): { t: string; output: number; ts: number }[] {
  const have = new Map(buckets.map((b) => [b.t, b.output]));
  const now = new Date();
  const out: { t: string; output: number; ts: number }[] = [];

  if (granularity === "minute") {
    const total = MINUTE_BUCKET_COUNT[range] ?? 60;
    // bucket key matches what the rollup emits: minute_iso() with seconds=0
    const start = new Date(now);
    start.setSeconds(0, 0);
    start.setMinutes(start.getMinutes() - (total - 1));
    for (let i = 0; i < total; i++) {
      const dt = new Date(start.getTime() + i * 60_000);
      // Daemon emits ISO with offset; we match by the exact key it returned
      // when present, otherwise emit a synthetic key with our own offset.
      const synthetic = isoMinute(dt);
      // Fallback match: linear scan if exact key not present (rare).
      let val = have.get(synthetic);
      if (val === undefined) {
        // try matching trimmed-to-minute UTC iso
        for (const [k, v] of have.entries()) {
          if (sameMinute(k, dt)) { val = v; break; }
        }
      }
      out.push({ t: synthetic, output: val ?? 0, ts: dt.getTime() });
    }
  } else {
    const days = range === "7d" ? 7 : 30;
    const today = new Date(now);
    today.setHours(0, 0, 0, 0);
    for (let i = days - 1; i >= 0; i--) {
      const dt = new Date(today.getTime() - i * 86400_000);
      const key = dt.toISOString().slice(0, 10); // YYYY-MM-DD
      out.push({
        t: key,
        output: have.get(key) ?? 0,
        ts: dt.getTime(),
      });
    }
  }
  return out;
}

function isoMinute(dt: Date): string {
  // Local time iso with offset, second-precision trimmed to :00
  const tzMin = -dt.getTimezoneOffset();
  const sign = tzMin >= 0 ? "+" : "-";
  const off = Math.abs(tzMin);
  const oh = String(Math.floor(off / 60)).padStart(2, "0");
  const om = String(off % 60).padStart(2, "0");
  return (
    `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}` +
    `T${pad(dt.getHours())}:${pad(dt.getMinutes())}:00${sign}${oh}:${om}`
  );
}
function sameMinute(iso: string, dt: Date): boolean {
  const a = new Date(iso).getTime();
  const b = dt.getTime();
  return Math.floor(a / 60_000) === Math.floor(b / 60_000);
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
  const floor1x = isMinute ? PER_MIN_FLOOR : WORKDAY_FLOOR;
  const floor2x = floor1x * 2;
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
