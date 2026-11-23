import type { WireRun, WireStep } from "./wire";

const T0 = Date.parse("2024-09-27T03:20:00Z");
const at = (ms: number) => new Date(T0 + ms).toISOString();

type Seed = Partial<WireStep> & Pick<WireStep, "kind" | "node">;

const step = (seq: number, ms: number, s: Seed): WireStep => ({
  seq,
  at: at(ms),
  model: null,
  mode: null,
  decision: null,
  tokens_in: 0,
  tokens_out: 0,
  cost_usd_micros: 0,
  latency_ms: null,
  ...s,
});

const SONNET = "claude-sonnet-5-5";
const HAIKU = "claude-haiku-4-5";

/** `tokens_in` counts the cached input too (K3: "input tokens incl. cache reads and writes"); `cache_read_tokens` is the cached part of it. */
/** The multi-agent copilot run of AX §2 as `GET /api/runs/{id}` is expected to serve it: plan, three workers, synthesis, checks. */
export function multiAgentRun(runId: string): WireRun {
  const steps: WireStep[] = [
    step(1, 0, { kind: "graph_step", node: "load_context", latency_ms: 14 }),
    step(2, 20, {
      kind: "llm_call",
      node: "route_intent",
      model: HAIKU,
      mode: "replay",
      tokens_in: 742,
      tokens_out: 52,
      latency_ms: 690,
    }),
    step(3, 710, { kind: "graph_step", node: "route_intent", latency_ms: 700 }),
    step(4, 720, { kind: "graph_step", node: "plan", latency_ms: 1090 }),
    step(5, 730, {
      kind: "llm_call",
      node: "ask_plan",
      model: HAIKU,
      mode: "replay",
      tokens_in: 1180,
      tokens_out: 146,
      cache_read_tokens: 640,
      latency_ms: 1060,
    }),
    step(6, 1820, { kind: "worker", node: "ask_worker_water", worker: "water", latency_ms: 6240 }),
    step(7, 1830, {
      kind: "tool_call",
      node: "get_water_status",
      worker: "water",
      tool: "get_water_status",
      status: "ok",
      args: { zone: "PS-17" },
      latency_ms: 180,
    }),
    step(8, 2010, {
      kind: "tool_call",
      node: "list_anomalies",
      worker: "water",
      tool: "list_anomalies",
      status: "ok",
      args: { asset: "PS-17" },
      latency_ms: 240,
    }),
    step(9, 2260, {
      kind: "llm_call",
      node: "ask_worker_water",
      worker: "water",
      model: SONNET,
      mode: "replay",
      tokens_in: 2310,
      tokens_out: 388,
      cache_read_tokens: 1640,
      latency_ms: 5700,
    }),
    step(10, 1820, { kind: "worker", node: "ask_worker_grid_crews", worker: "grid_crews", latency_ms: 5180 }),
    step(11, 1840, {
      kind: "tool_call",
      node: "get_crews",
      worker: "grid_crews",
      tool: "get_crews",
      status: "ok",
      args: { yard: "STG-AIK-SANDHILL-YARD" },
      latency_ms: 310,
    }),
    step(12, 2150, {
      kind: "tool_call",
      node: "get_etr",
      worker: "grid_crews",
      tool: "get_etr",
      status: "ok",
      args: { feeder: "FDR-2207" },
      latency_ms: 120,
    }),
    step(13, 2280, {
      kind: "llm_call",
      node: "ask_worker_grid_crews",
      worker: "grid_crews",
      model: SONNET,
      mode: "replay",
      tokens_in: 2640,
      tokens_out: 351,
      cache_read_tokens: 1640,
      latency_ms: 4600,
    }),
    step(14, 1820, { kind: "worker", node: "ask_worker_policy", worker: "policy", latency_ms: 3310 }),
    step(15, 1840, {
      kind: "tool_call",
      node: "search_procedures",
      worker: "policy",
      tool: "search_procedures",
      status: "ok",
      args: { query: "boil-water notice" },
      latency_ms: 420,
    }),
    step(16, 2270, {
      kind: "tool_call",
      node: "get_readiness",
      worker: "policy",
      tool: "get_readiness",
      status: "refused",
      latency_ms: 4,
    }),
    step(17, 2280, {
      kind: "llm_call",
      node: "ask_worker_policy",
      worker: "policy",
      model: SONNET,
      mode: "replay",
      tokens_in: 1920,
      tokens_out: 214,
      cache_read_tokens: 1280,
      latency_ms: 2850,
    }),
    step(18, 8060, { kind: "graph_step", node: "gather", latency_ms: 6 }),
    step(19, 8070, { kind: "graph_step", node: "synthesise", latency_ms: 2940 }),
    step(20, 8080, {
      kind: "llm_call",
      node: "ask_synth",
      model: SONNET,
      mode: "replay",
      tokens_in: 4280,
      tokens_out: 412,
      cache_read_tokens: 3100,
      latency_ms: 2900,
    }),
    step(21, 11020, { kind: "graph_step", node: "verify", decision: "pass", latency_ms: 38 }),
    step(22, 11060, { kind: "graph_step", node: "finalise", decision: "pass", latency_ms: 12 }),
    step(23, 11075, { kind: "graph_step", node: "link", latency_ms: 9 }),
    step(24, 11090, { kind: "graph_step", node: "respond", latency_ms: 4 }),
    step(25, 11095, { kind: "graph_step", node: "audit", latency_ms: 21 }),
  ];
  const calls = steps.filter((s) => s.kind === "llm_call");
  return {
    run: {
      run_id: runId,
      thread_id: "THR-0001",
      graph: "copilot",
      graph_version: "copilot@2",
      user_id: "ops_dm_01",
      run_mode: "replay",
      status: "done",
      started_at: at(0),
      ended_at: at(11120),
      duration_ms: 11120,
      llm_calls: calls.length,
      billed_calls: 0,
      tokens_in: calls.reduce((n, c) => n + c.tokens_in, 0),
      tokens_out: calls.reduce((n, c) => n + c.tokens_out, 0),
      cost_usd_micros: 0,
      nodes: calls.map((c) => c.node),
      models: [HAIKU, SONNET],
      tainted: false,
      classification: "C1",
      trace_id: null,
      trace_url: null,
    },
    steps,
  };
}

/** The same run answered live: billed calls and a failed check, to show the other states. */
export function liveFailedRun(runId: string): WireRun {
  const base = multiAgentRun(runId);
  const steps = base.steps.map((s) => {
    if (s.kind === "llm_call") {
      const sonnet = s.model === SONNET;
      return { ...s, mode: "live", cost_usd_micros: sonnet ? 11_400 : 900 };
    }
    return s.node === "verify" ? { ...s, decision: "fail" } : s;
  });
  return {
    run: {
      ...base.run,
      run_mode: "live",
      billed_calls: steps.filter((s) => s.kind === "llm_call").length,
      cost_usd_micros: steps.reduce((n, s) => n + s.cost_usd_micros, 0),
    },
    steps,
  };
}
