import { humanize } from "@/features/health/format";
import { nodeLabel } from "../../agent-panel/labels";
import { CHECK_LABEL, PHASE_LABEL, toolFace, workerLabel } from "./labels";
import type { CallMode, CheckRow, Lane, LlmCall, Phase, ToolRow, Totals, Trace } from "./model";
import type { WireRun, WireStep } from "./wire";

const PHASE_OF: Record<string, string> = {
  load_context: "question",
  route_intent: "question",
  plan: "plan",
  ask_plan: "plan",
  synthesise: "answer",
  ask_synth: "answer",
  respond: "answer",
  verify: "checks",
  finalise: "checks",
  link: "links",
};
const HIDDEN_NODES = new Set(["gather", "audit"]);
const CHECK_NODES = new Set(["verify", "finalise"]);
const WORKER_NODE = "ask_worker_";
const FAILED_DECISIONS = new Set(["fail", "deny", "refused"]);

const sum = (values: (number | null)[]): number | null => {
  const known = values.filter((v): v is number => v !== null);
  return known.length === 0 ? null : known.reduce((a, b) => a + b, 0);
};

function callMode(mode: string | null): CallMode | null {
  if (!mode) return null;
  if (mode.includes("cache")) return "cached";
  if (mode.includes("replay")) return "replay";
  if (mode === "live" || mode === "record") return "live";
  return "other";
}

const toLlm = (s: WireStep): LlmCall => ({
  seq: s.seq,
  model: s.model,
  mode: callMode(s.mode),
  tokensIn: s.tokens_in,
  tokensOut: s.tokens_out,
  cacheRead: s.cache_read_tokens ?? 0,
  costMicros: s.cost_usd_micros,
  ms: s.latency_ms,
});

function toTool(s: WireStep): ToolRow {
  const tool = s.tool ?? s.node;
  const face = toolFace(tool);
  const args = Object.values(s.args ?? {}).slice(0, 2);
  return {
    seq: s.seq,
    verb: face.verb,
    tag: face.tag ?? null,
    arg: args.length > 0 ? args.join(", ") : null,
    outcome:
      s.status === "refused" || s.decision === "deny" ? "refused" : s.status === "error" ? "error" : "ok",
    ms: s.latency_ms,
  };
}

const workerOf = (s: WireStep): string | null =>
  s.worker ?? (s.node.startsWith(WORKER_NODE) ? s.node.slice(WORKER_NODE.length) : null);

function phaseOf(node: string): { id: string; label: string } {
  const id = PHASE_OF[node] ?? node;
  return { id, label: PHASE_LABEL[id] ?? nodeLabel(node) };
}

function emptyLane(worker: string): Lane {
  return {
    worker,
    label: workerLabel(worker),
    outcome: "ok",
    fallback: false,
    ms: null,
    llm: [],
    tools: [],
  };
}

function finishLane(lane: Lane, stepMs: number | null): Lane {
  const own = stepMs ?? sum([...lane.llm.map((l) => l.ms), ...lane.tools.map((t) => t.ms)]);
  return { ...lane, ms: own };
}

/** One reader of the run detail: the steps become the phases of the graph, the workers in lanes, and the totals. */
export function adaptTrace(run: WireRun): Trace {
  const steps = [...run.steps].sort((a, b) => a.seq - b.seq);
  const phases = new Map<string, Phase>();
  const lanes = new Map<string, Lane>();
  const laneMs = new Map<string, number | null>();
  const phase = (id: string, label: string): Phase => {
    let p = phases.get(id);
    if (!p) {
      p = { id, label, ms: null, llm: [], tools: [], lanes: [], checks: [] };
      phases.set(id, p);
    }
    return p;
  };
  const lane = (worker: string): Lane => {
    let l = lanes.get(worker);
    if (!l) {
      l = emptyLane(worker);
      lanes.set(worker, l);
      phase("workers", PHASE_LABEL.workers ?? "Specialists");
    }
    return l;
  };
  const stepMs = new Map<string, number | null>();

  for (const s of steps) {
    const worker = workerOf(s);
    if (worker !== null) {
      const l = lane(worker);
      if (s.kind === "llm_call") l.llm.push(toLlm(s));
      else if (s.kind === "tool_call") l.tools.push(toTool(s));
      else {
        laneMs.set(worker, s.latency_ms);
        if (s.status === "error") l.outcome = "error";
        if (s.decision === "fallback") l.fallback = true;
      }
      continue;
    }
    if (HIDDEN_NODES.has(s.node) && s.kind !== "tool_call") continue;
    const { id, label } = phaseOf(s.node);
    const p = phase(id, label);
    if (s.kind === "llm_call") p.llm.push(toLlm(s));
    else if (s.kind === "tool_call") p.tools.push(toTool(s));
    else {
      if (CHECK_NODES.has(s.node)) {
        const passed = !FAILED_DECISIONS.has(s.decision ?? "") && s.status !== "error";
        p.checks.push({ seq: s.seq, label: CHECK_LABEL[s.node] ?? humanize(s.node), passed });
      }
      if (s.latency_ms !== null) stepMs.set(id, (stepMs.get(id) ?? 0) + s.latency_ms);
    }
  }

  const workers = phases.get("workers");
  if (workers) {
    workers.lanes = [...lanes.values()].map((l) => finishLane(l, laneMs.get(l.worker) ?? null));
    const longest = Math.max(0, ...workers.lanes.map((l) => l.ms ?? 0));
    workers.ms = longest > 0 ? longest : null;
  }
  for (const p of phases.values()) {
    if (p.id === "workers") continue;
    p.ms = stepMs.get(p.id) ?? sum([...p.llm.map((l) => l.ms), ...p.tools.map((t) => t.ms)]);
  }

  const ordered = [...phases.values()]
    .filter(hasContent)
    .sort((a, b) => firstSeq(steps, a) - firstSeq(steps, b));
  return {
    runId: run.run.run_id,
    status: run.run.status,
    graph: run.run.graph,
    startedAt: run.run.started_at,
    phases: ordered,
    totals: totalsOf(run, steps, ordered),
  };
}

const hasContent = (p: Phase): boolean =>
  p.ms !== null || p.llm.length + p.tools.length + p.lanes.length + p.checks.length > 0;

function firstSeq(steps: WireStep[], p: Phase): number {
  const mine = (s: WireStep) =>
    p.id === "workers" ? workerOf(s) !== null : workerOf(s) === null && phaseOf(s.node).id === p.id;
  return steps.find(mine)?.seq ?? Number.MAX_SAFE_INTEGER;
}

function totalsOf(run: WireRun, steps: WireStep[], phases: Phase[]): Totals {
  const calls = steps.filter((s) => s.kind === "llm_call");
  const checks = phases.flatMap((p) => p.checks);
  const modes = [...new Set(calls.map((c) => callMode(c.mode)).filter((m): m is CallMode => m !== null))];
  return {
    ms: run.run.duration_ms,
    llmCalls: run.run.llm_calls,
    tokensIn: run.run.tokens_in,
    tokensOut: run.run.tokens_out,
    cacheRead: calls.reduce((n, c) => n + (c.cache_read_tokens ?? 0), 0),
    costMicros: run.run.cost_usd_micros,
    billed: run.run.billed_calls > 0,
    modes,
    checksPassed: checks.filter((c: CheckRow) => c.passed).length,
    checksTotal: checks.length,
  };
}
