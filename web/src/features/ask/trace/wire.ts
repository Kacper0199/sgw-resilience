import type { components } from "@/contracts/api.gen";

type Step = components["schemas"]["AgentRunStep"];
type Detail = components["schemas"]["AgentRunDetail"];

export type WireStepKind = "graph_step" | "llm_call" | "worker" | "tool_call";

/**
 * `AgentRunStep` as the multi-agent graph is expected to send it (AX §3): the two new kinds and the optional fields
 * are additive. Replace this file with the generated type once K3 carries them; `adaptTrace.ts` is the only reader.
 */
export interface WireStep extends Omit<Step, "kind"> {
  kind: WireStepKind;
  worker?: string | null;
  tool?: string | null;
  status?: "ok" | "refused" | "error" | null;
  parent_seq?: number | null;
  cache_read_tokens?: number | null;
  args?: Record<string, string | number | boolean> | null;
}

export interface WireRun extends Omit<Detail, "steps"> {
  steps: WireStep[];
}
