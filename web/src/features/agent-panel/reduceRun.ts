import type { WireFrame } from "@/contracts/wire.gen";
import { REFERENCE_KINDS } from "../ask/references";
import { toSourceCite, type WireCitation } from "./citations";
import { wireExtras } from "./extras";
import { nodeLabel, toolVerb } from "./labels";
import { plainToolArg } from "./ToolChip";
import type {
  AnswerArtifact,
  AnswerPath,
  LogEntry,
  NodeState,
  Reference,
  RunView,
  SitrepDraft,
  ToolCall,
  ToolStatus,
} from "./types";

export const emptyRun = (
  runId: string,
  threadId: string,
  graph: string,
  question: string | null,
): RunView => ({
  runId,
  threadId,
  graph,
  status: "running",
  question,
  startedAt: null,
  endedAt: null,
  scenarioTime: null,
  nodes: [],
  tools: [],
  log: [],
  answer: null,
  draft: null,
  alerts: [],
  error: null,
  lastEventId: null,
});

const PATHS: readonly AnswerPath[] = ["llm", "m2", "not_in_documents", "guide"];
const str = (v: unknown): string | null => (typeof v === "string" ? v : null);
const strings = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];

const REASONS = [
  "llm_unavailable",
  "model_not_in_documents",
  "out_of_scope",
  "step_cap",
  "checks_failed",
] as const;

function wireCitations(v: unknown): WireCitation[] {
  if (!Array.isArray(v)) return [];
  return v.filter(
    (c): c is WireCitation =>
      typeof c === "object" && c !== null && typeof (c as WireCitation).n === "number" && "citation_id" in c,
  );
}

function wireReferences(v: unknown): Reference[] {
  if (!Array.isArray(v)) return [];
  return v.filter(
    (r): r is Reference =>
      typeof r === "object" &&
      r !== null &&
      REFERENCE_KINDS.includes((r as Reference).kind) &&
      typeof (r as Reference).id === "string" &&
      typeof (r as Reference).label === "string",
  );
}

function toAnswer(p: Record<string, unknown>, at: string): AnswerArtifact {
  const path = PATHS.find((x) => x === p.path) ?? null;
  return {
    text: str(p.text) ?? "",
    path,
    reason: REASONS.find((x) => x === p.reason) ?? null,
    citations: wireCitations(p.citation_details).map(toSourceCite),
    citationIds: strings(p.citations),
    evidenceIds: strings(p.evidence_ids),
    references: wireReferences(p.references),
    extras: wireExtras(p),
    tainted: p.tainted === true,
    writeAttempts: typeof p.write_attempts === "number" ? p.write_attempts : 0,
    at,
  };
}

function toDraft(p: Record<string, unknown>): SitrepDraft {
  const slots =
    p.slots && typeof p.slots === "object"
      ? (p.slots as Record<string, string>)
      : ({} as Record<string, string>);
  return {
    tier: str(p.tier) ?? "T1",
    promotion: str(p.promotion) ?? "by a person",
    path: str(p.path) ?? "llm",
    rendered: str(p.rendered) ?? "",
    slots,
    tainted: p.tainted === true,
  };
}

function upsertNode(nodes: NodeState[], node: string, status: NodeState["status"], at: string): NodeState[] {
  const i = nodes.findIndex((n) => n.node === node);
  if (i === -1)
    return [...nodes, { node, status, startedAt: at, endedAt: status === "done" ? at : undefined }];
  return nodes.map((n, k) => (k === i ? { ...n, status, endedAt: status === "done" ? at : n.endedAt } : n));
}

/** Pure fold of one K4 run frame into the view of a run. Unknown frames and heartbeats change nothing. */
export function reduceRunFrame(run: RunView, frame: WireFrame, sseId?: string): RunView {
  const p = (frame.payload ?? {}) as Record<string, unknown>;
  const at = frame.ts;
  const seq = frame.seq;
  const entry = (e: Omit<LogEntry, "seq" | "at">): LogEntry[] => [...run.log, { seq, at, ...e }];
  const next: RunView = { ...run, lastEventId: sseId ?? run.lastEventId };

  switch (frame.type) {
    case "run_start":
      return {
        ...next,
        startedAt: at,
        scenarioTime: frame.scenario_time ?? run.scenarioTime,
        status: "running",
      };
    case "agent_start":
    case "agent_end":
    case "step": {
      const node = str(p.node);
      if (!node) return next;
      const done = frame.type === "agent_end" || p.status === "end" || p.status === "resumed";
      const kind = frame.type === "step" ? "step" : "agent";
      return {
        ...next,
        nodes: upsertNode(run.nodes, node, done ? "done" : "running", at),
        log: done ? entry({ node, kind, label: nodeLabel(node), detail: null, status: "done" }) : run.log,
      };
    }
    case "tool_start": {
      const tool = str(p.tool) ?? "tool";
      const call = typeof p.call === "number" ? p.call : run.tools.length;
      const args = (p.args && typeof p.args === "object" ? p.args : {}) as Record<string, unknown>;
      const tools: ToolCall[] = [
        ...run.tools.filter((t) => t.call !== call),
        { call, tool, args, status: "running" },
      ];
      return { ...next, tools };
    }
    case "tool_end": {
      const call = typeof p.call === "number" ? p.call : -1;
      const status: ToolStatus = p.status === "refused" || p.status === "error" ? p.status : "ok";
      const found = p.status === "empty" ? { empty: true } : {};
      const tools = run.tools.map((t) => (t.call === call ? { ...t, status, ...found } : t));
      const hit = tools.find((t) => t.call === call);
      return {
        ...next,
        tools,
        log: entry({
          node: null,
          kind: "tool",
          label: toolVerb(hit?.tool ?? "tool"),
          detail: hit ? plainToolArg(hit.args) || null : null,
          status,
        }),
      };
    }
    case "artifact": {
      if (p.kind === "message" && p.role === "user")
        return { ...next, question: run.question ?? str(p.text) };
      if (p.kind === "message" && p.role === "assistant") {
        return {
          ...next,
          answer: toAnswer(p, at),
          log: entry({
            node: "respond",
            kind: "artifact",
            label: "Answer ready",
            detail: null,
            status: "done",
          }),
        };
      }
      if (p.kind === "sitrep_draft") {
        return {
          ...next,
          draft: toDraft(p),
          log: entry({
            node: "sitrep_draft",
            kind: "artifact",
            label: "Draft saved",
            detail: null,
            status: "done",
          }),
        };
      }
      if (p.kind === "security_alert") {
        return { ...next, alerts: [...run.alerts, str(p.reason) ?? str(p.code) ?? "security alert"] };
      }
      return next;
    }
    case "run_end": {
      const cancelled = p.status === "cancelled";
      return {
        ...next,
        status: cancelled ? "cancelled" : "done",
        endedAt: at,
        log: entry({
          node: null,
          kind: "end",
          label: cancelled ? "Stopped" : "Done",
          detail: null,
          status: "done",
        }),
      };
    }
    case "run_paused":
      return { ...next, status: "paused", endedAt: at };
    case "run_error": {
      const message = str(p.message) ?? str(p.error) ?? "Couldn't finish";
      return {
        ...next,
        status: "error",
        endedAt: at,
        error: message,
        log: entry({ node: null, kind: "error", label: "Failed", detail: message, status: "error" }),
      };
    }
    default:
      return next;
  }
}

export const isTerminal = (run: RunView): boolean => run.status !== "running";
