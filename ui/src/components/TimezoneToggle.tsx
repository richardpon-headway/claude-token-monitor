import { useMemo } from "react";

export type Tz = "local" | "utc";

const OPTIONS: Tz[] = ["local", "utc"];

/** Best-effort short timezone abbreviation (e.g. "PDT") for the local
 *  zone, derived via Intl. Returns "" if the platform doesn't expose a
 *  timeZoneName part. */
function useLocalTzAbbreviation(): string {
  return useMemo(() => {
    try {
      const parts = new Intl.DateTimeFormat("en-US", {
        timeZoneName: "short",
      }).formatToParts(new Date());
      return parts.find((p) => p.type === "timeZoneName")?.value ?? "";
    } catch {
      return "";
    }
  }, []);
}

export function TimezoneToggle({
  value,
  onChange,
}: {
  value: Tz;
  onChange: (v: Tz) => void;
}) {
  const localAbbr = useLocalTzAbbreviation();
  return (
    <div className="inline-flex rounded-md border border-zinc-800 bg-zinc-900 p-0.5">
      {OPTIONS.map((o) => {
        const active = o === value;
        const label =
          o === "local" && localAbbr ? `local · ${localAbbr}` : o;
        return (
          <button
            key={o}
            onClick={() => onChange(o)}
            className={`px-2.5 py-1 text-xs uppercase rounded transition-colors ${
              active
                ? "bg-zinc-800 text-zinc-100"
                : "text-zinc-400 hover:text-zinc-200"
            }`}
            aria-pressed={active}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
