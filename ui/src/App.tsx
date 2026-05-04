import { useUsage } from "./hooks/useUsage";
import { useUsageStream } from "./hooks/useUsageStream";
import { QuotaBar } from "./components/QuotaBar";
import type { Windows } from "./types";

const fmt = (n: number) => n.toLocaleString();

export default function App() {
  const { refreshKey, live } = useUsageStream();
  const { data, error, loading } = useUsage<Windows>(
    "/api/usage/windows",
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

      {data && (
        <div className="mb-6 max-w-xl">
          <QuotaBar todayOutput={data.today_local.output} />
        </div>
      )}

      {error && (
        <div className="rounded border border-red-900 bg-red-950/50 px-3 py-2 text-sm text-red-200">
          fetch error: {error.message}
        </div>
      )}

      {loading && !data && (
        <div className="text-sm text-zinc-500">loading …</div>
      )}

      {data && (
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
          <Tile label="today (local)" b={data.today_local} />
          <Tile label="last 7d (local)" b={data.last_7d_local} />
          <Tile label="last 30d (local)" b={data.last_30d_local} />
          <Tile label="last 7d UTC" b={data.last_7d_utc} muted />
          <Tile label="last 30d UTC" b={data.last_30d_utc} muted />
        </section>
      )}
    </div>
  );
}

function Tile({
  label,
  b,
  muted = false,
}: {
  label: string;
  b: { output: number; input: number; messages: number };
  muted?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border border-zinc-800 ${
        muted ? "bg-zinc-900/40" : "bg-zinc-900"
      } px-4 py-3`}
    >
      <div className="text-xs uppercase tracking-wide text-zinc-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">
        {fmt(b.output)}
      </div>
      <div className="mt-1 text-xs text-zinc-500 tabular-nums">
        {fmt(b.messages)} msgs · {fmt(b.input)} input
      </div>
    </div>
  );
}
