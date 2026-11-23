import { get } from "@/lib/api";
import type { Asset, CrewItem, CrewPlanDocument, DamageQueue, ModelEvaluation } from "./types";

export const crewsApi = {
  crews: () => get<CrewItem[]>("/api/crews"),
  plan: () => get<CrewPlanDocument>("/api/crews/plan"),
  damage: () => get<DamageQueue>("/api/damage/queue"),
  assets: () => get<Asset[]>("/api/assets?domain=water"),
  ladiEvaluation: () => get<ModelEvaluation>("/api/models/ladi_reference/evaluation"),
};
