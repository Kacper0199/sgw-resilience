import { useQuery } from "@tanstack/react-query";
import { adminApi } from "./api";

const read = { retry: false } as const;

export const useUsers = () => useQuery({ queryKey: ["admin", "users"], queryFn: adminApi.users, ...read });
export const useRights = () => useQuery({ queryKey: ["admin", "rights"], queryFn: adminApi.rights, ...read });
export const useAiConfig = () =>
  useQuery({ queryKey: ["admin", "ai-config"], queryFn: adminApi.aiConfig, ...read });
/** Shares the cache key of the Water page, which reads the same route. */
export const usePolicies = () => useQuery({ queryKey: ["policies"], queryFn: adminApi.policies, ...read });
export const useIntegrations = () =>
  useQuery({ queryKey: ["admin", "integrations"], queryFn: adminApi.integrations, ...read });
export const useSystem = () => useQuery({ queryKey: ["admin", "system"], queryFn: adminApi.system, ...read });
