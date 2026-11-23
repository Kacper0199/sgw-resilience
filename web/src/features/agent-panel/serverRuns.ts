import type { components } from "@/contracts/api.gen";
import { emptyRun } from "./reduceRun";
import type { RunView, ToolStatus } from "./types";

/** `GET /api/threads/{id}/runs`: the owner's runs of one thread, newest first, so the Runs tab survives a reload. */
export type ThreadRun = components["schemas"]["ThreadRun"];

const TOOL_STATUS: Record<string, ToolStatus> = {
  ok: "ok",
  empty: "ok",
  running: "running",
  refused: "refused",
};

export function runViewOf(threadId: string, r: ThreadRun): RunView {
  const view = emptyRun(r.run_id, threadId, r.graph, r.question);
  return {
    ...view,
    status: r.status,
    startedAt: r.started_at,
    endedAt: r.ended_at,
    nodes: r.steps.map((s) => ({
      node: s.node,
      status: s.status,
      startedAt: s.at ?? r.started_at,
      endedAt: s.status === "done" ? (s.at ?? undefined) : undefined,
    })),
    tools: r.tool_calls.map((t, i) => ({
      call: i + 1,
      tool: t.tool,
      args: t.args ?? {},
      status: TOOL_STATUS[t.status] ?? "error",
      ...(t.status === "empty" ? { empty: true } : {}),
    })),
  };
}
