import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { UsageList } from "./UsageList";
import type { ProjectRow, SessionRow, TopicRow } from "../types";

const topicRows: TopicRow[] = [
  { topic_id: "COR-100", label: "COR-100", sessions: 2, output: 100,
    input: 10, messages: 5, last_at: null, summary: null },
  { topic_id: "COR-200", label: "COR-200", sessions: 1, output: 500,
    input: 50, messages: 20, last_at: null, summary: null },
  { topic_id: "COR-300", label: "COR-300", sessions: 3, output: 250,
    input: 25, messages: 10, last_at: null, summary: null },
];

const projectRows: ProjectRow[] = [
  { project: "alpha", sessions: 1, output: 100, input: 0, messages: 1, last_at: null },
  { project: "beta", sessions: 1, output: 50, input: 0, messages: 1, last_at: null },
];

function getRowOrder(): string[] {
  const tbody = document.querySelector("tbody")!;
  const rows = within(tbody).queryAllByRole("row");
  return rows.map((r) => r.textContent ?? "");
}

describe("UsageList", () => {
  it("defaults to sorting by output desc", () => {
    render(<UsageList by="topic" rows={topicRows} />);
    const order = getRowOrder();
    expect(order[0]).toContain("COR-200"); // 500 (highest)
    expect(order[1]).toContain("COR-300"); // 250
    expect(order[2]).toContain("COR-100"); // 100
  });

  it("flips sort direction when the active header is clicked again", () => {
    render(<UsageList by="topic" rows={topicRows} />);
    fireEvent.click(screen.getByText("Output")); // active header — flips to asc
    const order = getRowOrder();
    expect(order[0]).toContain("COR-100"); // 100 (lowest)
    expect(order[2]).toContain("COR-200"); // 500 (highest)
  });

  it("switches sort key when a different header is clicked", () => {
    render(<UsageList by="topic" rows={topicRows} />);
    fireEvent.click(screen.getByText("Sessions")); // becomes active, dir=desc
    const order = getRowOrder();
    expect(order[0]).toContain("COR-300"); // 3 sessions
  });

  it("renders project columns when by=project", () => {
    render(<UsageList by="project" rows={projectRows} />);
    expect(screen.getByText("Project folder")).toBeInTheDocument();
    expect(screen.queryByText("Topic")).not.toBeInTheDocument();
  });

  it("shows the empty state when rows is empty", () => {
    render(<UsageList by="topic" rows={[]} />);
    expect(screen.getByText("no data yet")).toBeInTheDocument();
  });

  it("renders dominant topic only when session has a single segment", () => {
    const session: SessionRow = {
      session_id: "abc-1234", project: "headway",
      output: 100, input: 10, messages: 3,
      started_at: null, last_at: null, early_user_prompts: [],
      topic_id: "COR-144",
      segments: { "COR-144": { output: 100, input: 10, messages: 3, last_at: null } },
    };
    render(<UsageList by="session" rows={[session]} />);
    expect(screen.getByText("COR-144")).toBeInTheDocument();
    expect(screen.queryByText(/\+/)).not.toBeInTheDocument();
  });

  it("renders dominant + next when session has multiple segments", () => {
    const session: SessionRow = {
      session_id: "abc-1234", project: "headway",
      output: 200, input: 20, messages: 6,
      started_at: null, last_at: null, early_user_prompts: [],
      topic_id: "COR-144",
      segments: {
        "COR-144": { output: 130, input: 13, messages: 4, last_at: null },
        "COR-119": { output: 70, input: 7, messages: 2, last_at: null },
      },
    };
    render(<UsageList by="session" rows={[session]} />);
    expect(screen.getByText("COR-144")).toBeInTheDocument();
    expect(screen.getByText(/\+ COR-119/)).toBeInTheDocument();
  });

  it("renders the topic summary inline when present", () => {
    const rows: TopicRow[] = [
      { topic_id: "COR-144", label: "COR-144", sessions: 1, output: 100,
        input: 0, messages: 1, last_at: null,
        summary: "IA call webhook source of truth" },
    ];
    render(<UsageList by="topic" rows={rows} />);
    expect(screen.getByText(/IA call webhook source of truth/)).toBeInTheDocument();
  });

  it("renders only the topic id when summary is null", () => {
    const rows: TopicRow[] = [
      { topic_id: "COR-144", label: "COR-144", sessions: 1, output: 100,
        input: 0, messages: 1, last_at: null, summary: null },
    ];
    render(<UsageList by="topic" rows={rows} />);
    expect(screen.getByText("COR-144")).toBeInTheDocument();
    expect(screen.queryByText(/·/)).not.toBeInTheDocument();
  });

  it("renders +N more suffix when session has 3+ segments", () => {
    const session: SessionRow = {
      session_id: "abc-1234", project: "headway",
      output: 300, input: 30, messages: 9,
      started_at: null, last_at: null, early_user_prompts: [],
      topic_id: "COR-144",
      segments: {
        "COR-144": { output: 150, input: 15, messages: 4, last_at: null },
        "COR-119": { output: 100, input: 10, messages: 3, last_at: null },
        "COR-200": { output: 50,  input: 5,  messages: 2, last_at: null },
      },
    };
    render(<UsageList by="session" rows={[session]} />);
    expect(screen.getByText(/\+ COR-119/)).toBeInTheDocument();
    expect(screen.getByText(/\(\+1\)/)).toBeInTheDocument();
  });
});
