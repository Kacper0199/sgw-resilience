import { get } from "@/lib/api";
import type { AnomalyItem, BwaAdvisory, BwaClause, ModelEvaluation, PolicyParam, WaterZone } from "./types";

export const waterApi = {
  zones: () => get<WaterZone[]>("/api/water/zones"),
  advisories: () => get<{ advisories: BwaAdvisory[]; forecasts_withheld?: boolean }>("/api/water/advisories"),
  rules: () => get<{ version: string; clauses: BwaClause[] }>("/api/water/rules"),
  anomalies: () => get<AnomalyItem[]>("/api/anomalies"),
  anomalyEvaluation: () => get<ModelEvaluation>("/api/models/anomaly_a7_a8/evaluation"),
  policies: () => get<PolicyParam[]>("/api/policies"),
};
