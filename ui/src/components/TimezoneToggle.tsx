export type Tz = "local" | "utc";

const OPTIONS: Tz[] = ["local", "utc"];

export function TimezoneToggle({
  value,
  onChange,
}: {
  value: Tz;
  onChange: (v: Tz) => void;
}) {
  return (
    <div className="inline-flex rounded-md border border-zinc-800 bg-zinc-900 p-0.5">
      {OPTIONS.map((o) => {
        const active = o === value;
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
            {o}
          </button>
        );
      })}
    </div>
  );
}
