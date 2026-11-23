import { get } from "@/lib/api";
import type { AdminUser, AiConfig, Integrations, PolicyParam, SystemInfo, UserRights } from "./types";

export const adminApi = {
  users: () => get<AdminUser[]>("/api/admin/users"),
  rights: () => get<UserRights[]>("/api/admin/approval-rights"),
  aiConfig: () => get<AiConfig>("/api/admin/ai-config"),
  policies: () => get<PolicyParam[]>("/api/policies"),
  integrations: () => get<Integrations>("/api/admin/integrations"),
  system: () => get<SystemInfo>("/api/admin/system"),
};
