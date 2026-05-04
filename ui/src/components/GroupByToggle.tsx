import type { GroupBy } from "../types";

const OPTIONS: { value: GroupBy; label: string }[] = [
  { value: "topic", label: "Topic" },
  { value: "session", label: "Session" },
  { value: "project", label: "Project" },
];

export function GroupByToggle({
  value,
  onChange,
}: {
  value: GroupBy;
  onChange: (v: GroupBy) => void;
}) {
  return (
    <div
      role="tablist"
      className="inline-flex rounded-md border border-zinc-800 bg-zinc-900 p-0.5"
    >
      {OPTIONS.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(o.value)}
            className={`px-3 py-1 text-sm rounded transition-colors ${
              active
                ? "bg-zinc-800 text-zinc-100"
                : "text-zinc-400 hover:text-zinc-200"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
