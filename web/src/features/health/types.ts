import type { components } from "@/contracts/api.gen";

export type FeedHealthItem = components["schemas"]["FeedHealthItem"];
export type PipelineRun = components["schemas"]["PipelineRunOut"];
export type DqCheck = components["schemas"]["DqCheckOut"];
export type ModelCard = components["schemas"]["ModelCard"];
export type ControlState = components["schemas"]["ControlState"];
export type AiConfig = components["schemas"]["AiConfig"];
export type AiNodeConfig = components["schemas"]["AiNodeConfig"];
export type KillLevel = components["schemas"]["KillLevel"];
export type DegradedMode = components["schemas"]["DegradedMode"];

/** `GET /api/pipeline/assets` (untyped in K3 v1.1; shape from `sgw.ops.health.lineage`). */
export interface PipelineAsset {
  name: string;
  description: string;
  upstream: string[];
  downstream: string[];
  freshness_limit_s: number | null;
  last_run: {
    run_id: string;
    status: PipelineRun["status"];
    started_at: string;
    finished_at: string | null;
    rows_in: number;
    rows_out: number;
    rows_quarantined: number;
    dq: { checks: number; errors: number; warnings: number };
    skipped?: boolean;
    replay?: boolean;
  } | null;
}

/** One K17 evaluation row. */
export interface EvalRow {
  metric: string;
  value: number;
  unit: string;
  n: number;
  split: string;
  label: string;
  baseline_name: string | null;
  baseline_value: number | null;
  threshold: number | null;
  direction: "higher_is_better" | "lower_is_better";
  passed: boolean | null;
}

/**
 * `GET /api/models/{name}/evaluation`. The live route nests the report under `eval_report`; the WP-20 and WP-26
 * mocks return the report itself, so both shapes are read.
 */
export interface ModelEvaluation {
  name: string;
  serving?: { model_id: string; version: string; alias: string | null; data_hash: string };
  eval_report?: {
    name: string | null;
    created_at: string | null;
    code_version: string | null;
    metrics: EvalRow[];
  };
  metrics?: EvalRow[];
  created_at?: string;
  card?: Record<string, unknown> | null;
}

export type CapabilityKey =
  | "view_dashboards"
  | "create_proposals"
  | "approve_and_execute"
  | "agent_runs"
  | "llm_calls"
  | "free_form_plans"
  | "ingest_external"
  | "pipeline_runs"
  | "manual_workflow"
  | "crew_into_hazard_proposals";

/** `GET /api/control/capabilities`. */
export interface Capabilities {
  kill_level: KillLevel;
  degraded_mode: DegradedMode;
  control_readable: boolean;
  capabilities: Record<CapabilityKey, boolean>;
  active_signals: {
    signal: string;
    source: string;
    detail: string | null;
    floor: DegradedMode;
    since: string | null;
    exit: string;
  }[];
  pending_restore: {
    restore_id: string;
    from_level: KillLevel;
    to_level: KillLevel;
    requested_by: string;
    requested_function: string;
    requested_at: string;
    expires_at: string;
  } | null;
  mode_ladder: { mode: DegradedMode; name: string; available: string; disabled: string }[];
}

/** `GET /api/llm/usage` (platform, command and executive only). */
export interface LlmUsage {
  group_by: string[];
  rows: ({ [group: string]: string | number | null } & UsageTotals)[];
  total: UsageTotals & { last_call_at: string | null };
}

export interface UsageTotals {
  calls: number;
  billed_calls: number;
  replay_calls: number;
  denied_calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
}

export type RunStatus = "running" | "completed" | "failed" | "cancelled" | "waiting_approval";

/** `GET /api/runs`. */
export interface AgentRun {
  run_id: string;
  thread_id: string | null;
  graph: string;
  node: string | null;
  status: RunStatus;
  run_mode: "live" | "replay" | "backfill" | "shadow" | "what_if";
  started_at: string;
  ended_at: string | null;
  duration_ms: number | null;
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd_micros: number | null;
  billed: boolean;
  error_code: string | null;
  trace_url: string | null;
}

export interface RunStep {
  seq: number;
  kind: "graph_step" | "llm_call";
  name: string;
  status: "ok" | "failed" | "denied" | "skipped";
  started_at: string;
  duration_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd_micros: number | null;
}

/** `GET /api/runs/{run_id}` (proposed for BE-UI3). */
export interface AgentRunDetail extends AgentRun {
  steps: RunStep[];
}
