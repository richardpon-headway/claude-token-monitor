import type { RangeKey } from "../types";

const OPTIONS: RangeKey[] = ["1h", "4h", "1d", "7d", "30d"];

export function RangeSwitcher({
  value,
  onChange,
}: {
  value: RangeKey;
  onChange: (v: RangeKey) => void;
}) {
  return (
    <div className="inline-flex rounded-md border border-zinc-800 bg-zinc-900 p-0.5">
      {OPTIONS.map((o) => {
        const active = o === value;
        return (
          <button
            key={o}
            onClick={() => onChange(o)}
            className={`px-2.5 py-1 text-xs rounded transition-colors ${
              active
                ? "bg-zinc-800 text-zinc-100"
                : "text-zinc-400 hover:text-zinc-200"
            }`}
          >
            {o}
          </button>
        );
      })}
    </div>
  );
}
