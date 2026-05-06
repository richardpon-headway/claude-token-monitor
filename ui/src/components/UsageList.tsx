import { useMemo, useState } from "react";
import type {
  GroupBy,
  GroupRow,
  ProjectRow,
  SessionRow,
  TopicRow,
} from "../types";

/** Activity-Monitor-style table. Columns adapt to group. Click headers to sort.
 *  Rows with activity in the last 5 minutes get a green-dot indicator. */

type SortDir = "asc" | "desc";
interface SortState { key: string; dir: SortDir }

const fmt = (n: number) => n.toLocaleString();

function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  const diff = (Date.now() - t) / 1000;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function isRecent(iso: string | null, withinSec = 300): boolean {
  if (!iso) return false;
  return (Date.now() - new Date(iso).getTime()) / 1000 < withinSec;
}

const isTopicRow = (r: GroupRow): r is TopicRow =>
  "topic_id" in r && "label" in r;
const isSessionRow = (r: GroupRow): r is SessionRow =>
  "session_id" in r && "early_user_prompts" in r;
const isProjectRow = (r: GroupRow): r is ProjectRow =>
  "project" in r && !("session_id" in r) && !("topic_id" in r);

function shortTopic(t: string): string {
  return t.startsWith("unclassified:") ? "—" : t;
}

/** Render a topic-group row's label + optional summary inline. */
function renderTopicCell(r: TopicRow): React.ReactNode {
  const tooltip = formatPromptsTooltip(r.sample_prompts);
  return (
    <span title={tooltip}>
      <span className={tooltip ? "underline decoration-dotted decoration-zinc-700 underline-offset-4" : ""}>
        {r.label}
      </span>
      {r.summary && (
        <span className="text-zinc-500"> · {r.summary}</span>
      )}
    </span>
  );
}

function renderProjectCell(r: ProjectRow): React.ReactNode {
  const tooltip = formatPromptsTooltip(r.sample_prompts);
  return (
    <span
      title={tooltip}
      className={tooltip ? "underline decoration-dotted decoration-zinc-700 underline-offset-4" : ""}
    >
      {r.project}
    </span>
  );
}

/** Compose a multi-line title string for a cell tooltip. Empty string
 *  means no tooltip — the title attribute is omitted in that case so
 *  rows without sample prompts don't render a 'no value' tooltip. */
function formatPromptsTooltip(prompts: string[] | undefined): string {
  if (!prompts || prompts.length === 0) return "";
  return (
    "Recent prompts:\n" +
    prompts.map((p) => `• ${p.slice(0, 200)}`).join("\n")
  );
}

/** Render a session row's topic column. Single-topic sessions show just
 *  the topic. Multi-topic sessions show the dominant + "+ next + N more"
 *  with a tooltip listing the full breakdown. */
function renderSessionTopic(r: SessionRow): React.ReactNode {
  const dominant = r.topic_id;
  if (!dominant) return <span className="text-zinc-500 text-xs">—</span>;
  const segs = r.segments || {};
  const others = Object.entries(segs)
    .filter(([k]) => k !== dominant)
    .sort((a, b) => b[1].output - a[1].output);
  const dominantText = shortTopic(dominant);
  if (others.length === 0) {
    return <span className="text-xs">{dominantText}</span>;
  }
  const tooltip = Object.entries(segs)
    .sort((a, b) => b[1].output - a[1].output)
    .map(([k, s]) => `${shortTopic(k)}: ${s.output.toLocaleString()}`)
    .join("\n");
  const next = shortTopic(others[0][0]);
  const more = others.length > 1 ? ` (+${others.length - 1})` : "";
  return (
    <span className="text-xs" title={tooltip}>
      {dominantText}
      <span className="text-zinc-500"> + {next}{more}</span>
    </span>
  );
}

interface ColumnDef {
  key: string;
  label: string;
  align?: "left" | "right";
  render: (r: GroupRow) => React.ReactNode;
  sortVal: (r: GroupRow) => number | string;
}

function topicColumns(): ColumnDef[] {
  return [
    {
      key: "label", label: "Topic", align: "left",
      render: (r) => isTopicRow(r) ? renderTopicCell(r) : "",
      sortVal: (r) => isTopicRow(r) ? r.label.toLowerCase() : "",
    },
    {
      key: "sessions", label: "Sessions", align: "right",
      render: (r) => isTopicRow(r) ? fmt(r.sessions) : "",
      sortVal: (r) => isTopicRow(r) ? r.sessions : 0,
    },
    {
      key: "output", label: "Output", align: "right",
      render: (r) => fmt(r.output),
      sortVal: (r) => r.output,
    },
    {
      key: "messages", label: "Messages", align: "right",
      render: (r) => fmt(r.messages),
      sortVal: (r) => r.messages,
    },
    {
      key: "last_at", label: "Last active", align: "right",
      render: (r) => relativeTime(r.last_at),
      sortVal: (r) => r.last_at ? new Date(r.last_at).getTime() : 0,
    },
  ];
}

function projectColumns(): ColumnDef[] {
  return [
    {
      key: "project", label: "Project folder", align: "left",
      render: (r) => isProjectRow(r) ? renderProjectCell(r) : "",
      sortVal: (r) => isProjectRow(r) ? r.project.toLowerCase() : "",
    },
    {
      key: "sessions", label: "Sessions", align: "right",
      render: (r) => isProjectRow(r) ? fmt(r.sessions) : "",
      sortVal: (r) => isProjectRow(r) ? r.sessions : 0,
    },
    {
      key: "output", label: "Output", align: "right",
      render: (r) => fmt(r.output),
      sortVal: (r) => r.output,
    },
    {
      key: "messages", label: "Messages", align: "right",
      render: (r) => fmt(r.messages),
      sortVal: (r) => r.messages,
    },
    {
      key: "last_at", label: "Last active", align: "right",
      render: (r) => relativeTime(r.last_at),
      sortVal: (r) => r.last_at ? new Date(r.last_at).getTime() : 0,
    },
  ];
}

function sessionColumns(): ColumnDef[] {
  return [
    {
      key: "session_id", label: "Session", align: "left",
      render: (r) => isSessionRow(r) ? (
        <span className="font-mono text-xs">{r.session_id.slice(0, 8)}…</span>
      ) : "",
      sortVal: (r) => isSessionRow(r) ? r.session_id : "",
    },
    {
      key: "project", label: "Project", align: "left",
      render: (r) => isSessionRow(r) ? (
        <span className="text-xs text-zinc-400 truncate max-w-[240px] inline-block align-bottom">
          {r.project}
        </span>
      ) : "",
      sortVal: (r) => isSessionRow(r) ? r.project.toLowerCase() : "",
    },
    {
      key: "topic_id", label: "Topic", align: "left",
      render: (r) => isSessionRow(r) ? renderSessionTopic(r) : "",
      sortVal: (r) => isSessionRow(r) ? (r.topic_id ?? "") : "",
    },
    {
      key: "first_prompt", label: "First prompt", align: "left",
      render: (r) => isSessionRow(r) && r.early_user_prompts.length > 0 ? (
        <span
          title={r.early_user_prompts[0]}
          className="text-xs text-zinc-400 truncate max-w-[280px] inline-block align-bottom"
        >
          {r.early_user_prompts[0]}
        </span>
      ) : <span className="text-zinc-600 text-xs">—</span>,
      sortVal: (r) => isSessionRow(r) && r.early_user_prompts.length > 0
        ? r.early_user_prompts[0].toLowerCase()
        : "",
    },
    {
      key: "output", label: "Output", align: "right",
      render: (r) => fmt(r.output),
      sortVal: (r) => r.output,
    },
    {
      key: "messages", label: "Turns", align: "right",
      render: (r) => fmt(r.messages),
      sortVal: (r) => r.messages,
    },
    {
      key: "last_at", label: "Last active", align: "right",
      render: (r) => relativeTime(r.last_at),
      sortVal: (r) => r.last_at ? new Date(r.last_at).getTime() : 0,
    },
  ];
}

export function UsageList({
  by,
  rows,
}: {
  by: GroupBy;
  rows: GroupRow[];
}) {
  const columns = useMemo(() => {
    if (by === "topic") return topicColumns();
    if (by === "project") return projectColumns();
    return sessionColumns();
  }, [by]);

  const [sort, setSort] = useState<SortState>({ key: "output", dir: "desc" });

  const sorted = useMemo(() => {
    const col = columns.find((c) => c.key === sort.key) ?? columns[0];
    const dir = sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const av = col.sortVal(a);
      const bv = col.sortVal(b);
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return 0;
    });
  }, [rows, columns, sort]);

  const onHeaderClick = (key: string) => {
    setSort((s) => s.key === key
      ? { key, dir: s.dir === "asc" ? "desc" : "asc" }
      : { key, dir: "desc" });
  };

  return (
    <div className="rounded-lg border border-zinc-800 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-zinc-900/60 text-zinc-400">
            <tr>
              <th className="w-6" />
              {columns.map((c) => {
                const active = c.key === sort.key;
                return (
                  <th
                    key={c.key}
                    className={`px-3 py-2 font-normal cursor-pointer select-none ${
                      c.align === "right" ? "text-right" : "text-left"
                    } ${active ? "text-zinc-200" : "hover:text-zinc-300"}`}
                    onClick={() => onHeaderClick(c.key)}
                  >
                    {c.label}
                    {active && (
                      <span className="ml-1 text-zinc-500">
                        {sort.dir === "asc" ? "▲" : "▼"}
                      </span>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/60">
            {sorted.map((r, i) => {
              const recent = isRecent(r.last_at);
              return (
                <tr
                  key={i}
                  className={`tabular-nums ${
                    recent ? "bg-emerald-950/20" : ""
                  } hover:bg-zinc-900/40`}
                >
                  <td className="px-2 py-1.5">
                    {recent && (
                      <span
                        className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-400"
                        aria-label="active in last 5 min"
                      />
                    )}
                  </td>
                  {columns.map((c) => (
                    <td
                      key={c.key}
                      className={`px-3 py-1.5 ${
                        c.align === "right" ? "text-right" : "text-left"
                      }`}
                    >
                      {c.render(r)}
                    </td>
                  ))}
                </tr>
              );
            })}
            {sorted.length === 0 && (
              <tr>
                <td
                  colSpan={columns.length + 1}
                  className="px-3 py-6 text-center text-zinc-500"
                >
                  no data yet
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
