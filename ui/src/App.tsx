import { useState } from "react";
import { useUsage } from "./hooks/useUsage";
import { useUsageStream } from "./hooks/useUsageStream";
import { QuotaBar } from "./components/QuotaBar";
import { GroupByToggle } from "./components/GroupByToggle";
import { UsageList } from "./components/UsageList";
import { RangeSwitcher } from "./components/RangeSwitcher";
import { LiveChart } from "./components/LiveChart";
import { TimezoneToggle, type Tz } from "./components/TimezoneToggle";
import { Sparkline } from "./components/Sparkline";
import type {
  GroupBy,
  GroupsResponse,
  RangeKey,
  TimeseriesResponse,
  Windows,
} from "./types";

const fmt = (n: number) => n.toLocaleString();

export default function App() {
  const { refreshKey, live } = useUsageStream();
  const [groupBy, setGroupBy] = useState<GroupBy>("topic");
  const [range, setRange] = useState<RangeKey>("1h");
  const [tz, setTz] = useState<Tz>("local");

  const { data: windows } = useUsage<Windows>(
    "/api/usage/windows",
    refreshKey,
  );
  const { data: groups, error: groupsError } = useUsage<GroupsResponse>(
    `/api/usage/groups?by=${groupBy}`,
    refreshKey,
  );
  const { data: ts } = useUsage<TimeseriesResponse>(
    `/api/usage/timeseries?range=${range}&tz=${tz}`,
    refreshKey,
  );

  return (
    <div className="min-h-screen p-6">
      <header className="mb-6 flex items-start justify-between gap-6">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            claude-token-monitor
          </h1>
          <p className="text-sm text-zinc-400">
            live usage from ~/.claude/projects/
          </p>
        </div>
        <div className="text-xs text-zinc-500 flex items-center gap-1.5">
          <span
            className={`inline-block h-1.5 w-1.5 rounded-full ${
              live ? "bg-emerald-400" : "bg-zinc-600"
            }`}
            aria-label={live ? "live" : "polling"}
          />
          {live ? "live" : "polling"}
        </div>
      </header>

      {windows && (
        <div className="mb-6 max-w-xl">
          <QuotaBar todayOutput={windows.today_local.output} />
        </div>
      )}

      {windows && (
        <section className="mb-6 grid grid-cols-1 sm:grid-cols-3 gap-4">
          <Tile
            label="today"
            b={tz === "utc" ? windows.today_utc : windows.today_local}
            // Hourly bars only — no quota lines on a single-day window.
          />
          <Tile
            label="last 7d"
            b={tz === "utc" ? windows.last_7d_utc : windows.last_7d_local}
            quotaPerBucket={WORKDAY_FLOOR}
          />
          <Tile
            label="last 30d"
            b={tz === "utc" ? windows.last_30d_utc : windows.last_30d_local}
            quotaPerBucket={WORKDAY_FLOOR}
          />
        </section>
      )}

      <section className="mb-3 flex items-center justify-between">
        <h2 className="text-sm uppercase tracking-wide text-zinc-500">
          activity
        </h2>
        <div className="flex items-center gap-2">
          <RangeSwitcher value={range} onChange={setRange} />
          <TimezoneToggle value={tz} onChange={setTz} />
        </div>
      </section>

      {ts && (
        <div className="mb-6">
          <LiveChart data={ts} range={range} tz={tz} />
        </div>
      )}

      <section className="mb-3 flex items-center justify-between">
        <GroupByToggle value={groupBy} onChange={setGroupBy} />
        <span className="text-xs text-zinc-500">
          {groups ? `${groups.rows.length} ${groupBy}s` : ""}
        </span>
      </section>

      {groupsError && (
        <div className="mb-3 rounded border border-red-900 bg-red-950/50 px-3 py-2 text-sm text-red-200">
          fetch error: {groupsError.message}
        </div>
      )}

      {groups && <UsageList by={groupBy} rows={groups.rows} />}
    </div>
  );
}

const WORKDAY_FLOOR = 233_333; // tokens/workday — matches the QuotaBar constant

function Tile({
  label,
  b,
  muted = false,
  quotaPerBucket,
  sparkMode = "bars",
}: {
  label: string;
  b: { output: number; input: number; messages: number; spark: number[] };
  muted?: boolean;
  /** Per-bar quota for the dashed reference lines. */
  quotaPerBucket?: number;
  /** "bars" (default) for per-bucket bars; "cumulative" for a rising
   *  area chart of running sums. */
  sparkMode?: "bars" | "cumulative";
}) {
  return (
    <div
      className={`relative overflow-hidden rounded-lg border border-zinc-800 ${
        muted ? "bg-zinc-900/40" : "bg-zinc-900"
      } px-5 py-4`}
    >
      {b.spark.length > 0 && (
        <Sparkline
          data={b.spark}
          mode={sparkMode}
          quota={quotaPerBucket}
          className="absolute inset-1 pointer-events-none"
        />
      )}
      <div className="relative">
        <div className="text-xs uppercase tracking-wide text-zinc-500">
          {label}
        </div>
        <div className="mt-1 text-2xl font-semibold tabular-nums">
          {fmt(b.output)}
        </div>
        <div className="mt-1 text-xs text-zinc-500 tabular-nums">
          {fmt(b.messages)} msgs · {fmt(b.input)} input
        </div>
      </div>
    </div>
  );
}
