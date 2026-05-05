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
        <section className="mb-6 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          <Tile label="today (local)" b={windows.today_local} />
          <Tile label="last 7d (local)" b={windows.last_7d_local} />
          <Tile label="last 30d (local)" b={windows.last_30d_local} />
          <Tile label="last 7d UTC" b={windows.last_7d_utc} muted />
          <Tile label="last 30d UTC" b={windows.last_30d_utc} muted />
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

function Tile({
  label,
  b,
  muted = false,
}: {
  label: string;
  b: { output: number; input: number; messages: number; spark: number[] };
  muted?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border border-zinc-800 ${
        muted ? "bg-zinc-900/40" : "bg-zinc-900"
      } px-4 py-3`}
    >
      <div className="text-xs uppercase tracking-wide text-zinc-500">
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">
        {fmt(b.output)}
      </div>
      <div className="mt-1 text-xs text-zinc-500 tabular-nums">
        {fmt(b.messages)} msgs · {fmt(b.input)} input
      </div>
      {b.spark.length > 0 && (
        <div className="mt-2 w-full">
          <Sparkline data={b.spark} height={24} />
        </div>
      )}
    </div>
  );
}
