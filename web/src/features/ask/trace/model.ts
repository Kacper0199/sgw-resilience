export type Outcome = "ok" | "refused" | "error";
export type CallMode = "replay" | "live" | "cached" | "other";

export interface LlmCall {
  seq: number;
  model: string | null;
  mode: CallMode | null;
  tokensIn: number;
  tokensOut: number;
  cacheRead: number;
  costMicros: number;
  ms: number | null;
}

export interface ToolRow {
  seq: number;
  verb: string;
  tag: string | null;
  arg: string | null;
  outcome: Outcome;
  ms: number | null;
}

export interface Lane {
  worker: string;
  label: string;
  outcome: Outcome;
  fallback: boolean;
  ms: number | null;
  llm: LlmCall[];
  tools: ToolRow[];
}

export interface CheckRow {
  seq: number;
  label: string;
  passed: boolean;
}

export interface Phase {
  id: string;
  label: string;
  ms: number | null;
  llm: LlmCall[];
  tools: ToolRow[];
  lanes: Lane[];
  checks: CheckRow[];
}

export interface Totals {
  ms: number | null;
  llmCalls: number;
  tokensIn: number;
  tokensOut: number;
  cacheRead: number;
  costMicros: number;
  billed: boolean;
  modes: CallMode[];
  checksPassed: number;
  checksTotal: number;
}

export interface Trace {
  runId: string;
  status: "running" | "paused" | "done" | "error" | "cancelled";
  graph: string;
  startedAt: string;
  phases: Phase[];
  totals: Totals;
}
