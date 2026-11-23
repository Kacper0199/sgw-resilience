import type { components } from "@/contracts/api.gen";
import type { AgentRun, AgentRunDetail, RunStatus, RunStep } from "./types";

export type LiveRun = components["schemas"]["AgentRunSummary"];
export type LiveRunDetail = components["schemas"]["AgentRunDetail"];
type LiveStep = components["schemas"]["AgentRunStep"];

const STATUS: Record<LiveRun["status"], RunStatus> = {
  running: "running",
  paused: "waiting_approval",
  done: "completed",
  error: "failed",
  cancelled: "cancelled",
};

export const toAgentRun = (r: LiveRun): AgentRun => ({
  run_id: r.run_id,
  thread_id: r.thread_id,
  graph: r.graph,
  node: null,
  status: STATUS[r.status],
  run_mode: r.run_mode,
  started_at: r.started_at,
  ended_at: r.ended_at,
  duration_ms: r.duration_ms,
  llm_calls: r.llm_calls,
  input_tokens: r.tokens_in,
  output_tokens: r.tokens_out,
  cost_usd_micros: r.cost_usd_micros,
  billed: r.billed_calls > 0,
  error_code: null,
  trace_url: r.trace_url,
});

const toStep = (s: LiveStep): RunStep => ({
  seq: s.seq,
  kind: s.kind === "llm_call" ? "llm_call" : "graph_step",
  name: s.node,
  status: s.decision === "deny" ? "denied" : "ok",
  started_at: s.at ?? "",
  duration_ms: s.latency_ms,
  input_tokens: s.kind === "llm_call" ? s.tokens_in : null,
  output_tokens: s.kind === "llm_call" ? s.tokens_out : null,
  cost_usd_micros: s.kind === "llm_call" ? s.cost_usd_micros : null,
});

export const toAgentRunDetail = (d: LiveRunDetail): AgentRunDetail => ({
  ...toAgentRun(d.run),
  steps: d.steps.map(toStep),
});

const LIVE_STATUS: Record<RunStatus, LiveRun["status"]> = {
  running: "running",
  waiting_approval: "paused",
  completed: "done",
  failed: "error",
  cancelled: "cancelled",
};

/** The inverse of `toAgentRun`, for the MSW mock only: it keeps one fixture file and serves the live shape. */
export const toLiveRun = (r: AgentRun): LiveRun => ({
  run_id: r.run_id,
  thread_id: r.thread_id ?? "",
  graph: r.graph,
  graph_version: `${r.graph}@1`,
  user_id: "ops_dm_01",
  run_mode: r.run_mode,
  status: LIVE_STATUS[r.status],
  started_at: r.started_at,
  ended_at: r.ended_at,
  duration_ms: r.duration_ms,
  llm_calls: r.llm_calls,
  billed_calls: r.billed ? r.llm_calls : 0,
  tokens_in: r.input_tokens,
  tokens_out: r.output_tokens,
  cost_usd_micros: r.cost_usd_micros ?? 0,
  nodes: r.node ? [r.node] : [],
  models: [],
  tainted: false,
  classification: "C1",
  trace_id: null,
  trace_url: r.trace_url,
});

export const toLiveStep = (s: RunStep): LiveStep => ({
  seq: s.seq,
  kind: s.kind,
  node: s.name,
  at: s.started_at,
  model: null,
  mode: null,
  decision: s.status === "denied" ? "deny" : null,
  tokens_in: s.input_tokens ?? 0,
  tokens_out: s.output_tokens ?? 0,
  cost_usd_micros: s.cost_usd_micros ?? 0,
  latency_ms: s.duration_ms,
});
