import { NODE_LABEL } from "./labels";
import type { RunView, ToolCall } from "./types";

export interface Delegation {
  id: string;
  name: string;
  task: string;
  status: "waiting" | "running" | "done";
  tools: ToolCall[];
  findings: { evidenceIds: string[]; citationIds: string[] } | null;
}

const statusOf = (run: RunView, node: string): Delegation["status"] =>
  run.nodes.find((n) => n.node === node)?.status ?? (run.status === "running" ? "waiting" : "done");

/**
 * The copilot graph has two model-driven specialists. Their cards show the task each was given, the tools the
 * investigator called and what it found, all read from the run's own frames.
 */
export function copilotDelegations(run: RunView): Delegation[] {
  const answer = run.answer;
  return [
    {
      id: "route_intent",
      name: "Read the question",
      task: "Finds what you asked and which assets or decisions it mentions.",
      status: statusOf(run, "route_intent"),
      tools: [],
      findings: null,
    },
    {
      id: "investigate",
      name: "Look things up",
      task: run.question ?? "Searches platform data and procedures, and cites them.",
      status: statusOf(run, "investigate"),
      tools: run.tools,
      findings: answer ? { evidenceIds: answer.evidenceIds, citationIds: answer.citationIds } : null,
    },
  ];
}

export const stepsLabel = (run: RunView): string => {
  const done = run.nodes.filter((n) => n.status === "done").length;
  return `${done} of ${run.nodes.length || Object.keys(NODE_LABEL).length} steps`;
};
