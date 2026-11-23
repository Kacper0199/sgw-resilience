import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMe } from "@/auth/useSession";
import { ApiError, api, type Me } from "@/lib/api";
import { healthApi } from "./api";
import type { DegradedMode, KillLevel } from "./types";

const LIVE = 30_000;

export const useFeeds = () =>
  useQuery({ queryKey: ["health", "feeds"], queryFn: healthApi.feeds, refetchInterval: LIVE });
export const useAssets = () => useQuery({ queryKey: ["health", "assets"], queryFn: healthApi.assets });
export const usePipelineRuns = () =>
  useQuery({ queryKey: ["health", "pipeline-runs"], queryFn: healthApi.runs });
export const useChecks = () => useQuery({ queryKey: ["health", "dq"], queryFn: healthApi.checks });
export const useModels = () => useQuery({ queryKey: ["models"], queryFn: healthApi.models });

export const useEvaluations = (names: string[]) =>
  useQueries({
    queries: names.map((name) => ({
      queryKey: ["models", name, "evaluation"],
      queryFn: () => healthApi.evaluation(name),
      staleTime: 300_000,
      retry: false,
    })),
  });

/** The person is not allowed to read it (403) or the route is not there yet (404): a quiet note, not an error. */
export const isNotShown = (error: unknown): boolean =>
  error instanceof ApiError && (error.status === 403 || error.status === 404);

const USAGE_FUNCTIONS = new Set(["platform", "command", "executive"]);

/** The server decides; these only avoid a request that is certain to be refused (and a console error for it). */
export const canSeeAiConfig = (me: Me | null | undefined): boolean =>
  me?.function === "platform" || me?.roles.includes("platform_admin") === true;
export const canSeeUsage = (me: Me | null | undefined): boolean =>
  me !== null && me !== undefined && USAGE_FUNCTIONS.has(me.function);

export function useAiConfig() {
  const me = useMe();
  const allowed = canSeeAiConfig(me.data);
  const query = useQuery({
    queryKey: ["admin", "ai-config"],
    queryFn: healthApi.aiConfig,
    retry: false,
    enabled: allowed,
  });
  return Object.assign(query, { allowed });
}

export function useUsage() {
  const me = useMe();
  const allowed = canSeeUsage(me.data);
  const query = useQuery({
    queryKey: ["health", "llm-usage"],
    queryFn: healthApi.usage,
    retry: false,
    enabled: allowed,
  });
  return Object.assign(query, { allowed });
}
export const useAgentRuns = () =>
  useQuery({
    queryKey: ["health", "agent-runs"],
    queryFn: healthApi.agentRuns,
    retry: false,
    refetchInterval: LIVE,
  });
export const useAgentRun = (id: string | null) =>
  useQuery({
    queryKey: ["health", "agent-runs", id],
    queryFn: () => healthApi.agentRun(id as string),
    enabled: id !== null,
    retry: false,
  });
export const useCapabilities = () =>
  useQuery({ queryKey: ["control", "capabilities"], queryFn: healthApi.capabilities, refetchInterval: LIVE });

export type ControlRequest =
  | { kind: "kill"; level: KillLevel; reason: string; password?: string }
  | { kind: "mode"; mode: DegradedMode; reason: string; password?: string };

export function useControl() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (req: ControlRequest) => {
      if (req.password) await api.stepUp(req.password);
      return req.kind === "kill"
        ? healthApi.setKill(req.level, req.reason)
        : healthApi.setMode(req.mode, req.reason);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["control"] }),
  });
}
