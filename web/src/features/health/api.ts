import { get, post } from "@/lib/api";
import { type LiveRun, type LiveRunDetail, toAgentRun, toAgentRunDetail } from "./adaptRuns";
import type {
  AgentRun,
  AgentRunDetail,
  AiConfig,
  Capabilities,
  ControlState,
  DegradedMode,
  DqCheck,
  FeedHealthItem,
  KillLevel,
  LlmUsage,
  ModelCard,
  ModelEvaluation,
  PipelineAsset,
  PipelineRun,
} from "./types";

export const healthApi = {
  feeds: () => get<FeedHealthItem[]>("/api/feeds/health"),
  assets: () => get<PipelineAsset[]>("/api/pipeline/assets"),
  runs: () => get<PipelineRun[]>("/api/pipeline/runs?limit=20"),
  checks: () => get<DqCheck[]>("/api/dq/checks?limit=200"),
  models: () => get<ModelCard[]>("/api/models"),
  evaluation: (name: string) => get<ModelEvaluation>(`/api/models/${encodeURIComponent(name)}/evaluation`),
  aiConfig: () => get<AiConfig>("/api/admin/ai-config"),
  usage: () => get<LlmUsage>("/api/llm/usage?group_by=model"),
  agentRuns: async (): Promise<AgentRun[]> => (await get<LiveRun[]>("/api/runs?limit=50")).map(toAgentRun),
  agentRun: async (id: string): Promise<AgentRunDetail> =>
    toAgentRunDetail(await get<LiveRunDetail>(`/api/runs/${encodeURIComponent(id)}`)),
  capabilities: () => get<Capabilities>("/api/control/capabilities"),
  setKill: (kill_level: KillLevel, reason: string) =>
    post<ControlState>("/api/control/kill", { kill_level, reason }),
  setMode: (degraded_mode: DegradedMode, reason: string) =>
    post<ControlState>("/api/control/mode", { degraded_mode, reason }),
};
