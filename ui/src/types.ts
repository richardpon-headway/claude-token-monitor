// Mirrors the daemon's JSON response shapes (snake_case from Python dataclasses).

export interface DayBucket {
  output: number;
  input: number;
  messages: number;
  /** Per-bucket output tokens for the tile sparkline. Length depends on
   *  the window: 24 hourly buckets for today, 7 daily for 7d, 30 for 30d. */
  spark: number[];
}

export interface Windows {
  today_local: DayBucket;
  today_utc: DayBucket;
  last_7d_local: DayBucket;
  last_30d_local: DayBucket;
  last_7d_utc: DayBucket;
  last_30d_utc: DayBucket;
}

export interface ProjectRow {
  project: string;
  sessions: number;
  output: number;
  input: number;
  messages: number;
  last_at: string | null;
  sample_prompts: string[];
}

export interface Segment {
  output: number;
  input: number;
  messages: number;
  last_at: string | null;
}

export interface SessionRow {
  session_id: string;
  project: string;
  output: number;
  input: number;
  messages: number;
  started_at: string | null;
  last_at: string | null;
  early_user_prompts: string[];
  topic_id: string | null; // dominant topic
  segments: Record<string, Segment>;
}

export interface TopicRow {
  topic_id: string;
  sessions: number;
  output: number;
  input: number;
  messages: number;
  last_at: string | null;
  label: string;
  summary: string | null;
  sample_prompts: string[];
}

export type GroupBy = "topic" | "session" | "project";
export type RangeKey = "1h" | "4h" | "1d" | "7d" | "30d";

export type GroupRow = TopicRow | SessionRow | ProjectRow;

export interface GroupsResponse {
  by: GroupBy;
  rows: GroupRow[];
}

export interface TimeseriesBucket {
  t: string;
  output: number;
}

export interface TimeseriesResponse {
  range: RangeKey;
  granularity: "minute" | "10min" | "hour" | "4hour" | "day";
  buckets: TimeseriesBucket[];
}
