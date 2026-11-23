import type { components } from "@/contracts/api.gen";

export type WaterZone = components["schemas"]["WaterZone"];
export type AnomalyItem = components["schemas"]["AnomalyItem"];
export type PolicyParam = components["schemas"]["PolicyParam"];

/** One K17 evaluation row, as `GET /api/models/{name}/evaluation` returns it. */
export interface EvalRow {
  metric: string;
  value: number;
  unit: string;
  n: number;
  split: string;
  label: string;
  baseline_name: string | null;
  baseline_value: number | null;
  threshold: number | null;
  direction: "higher_is_better" | "lower_is_better";
  passed: boolean | null;
  ci_low: number | null;
  ci_high: number | null;
}

export interface ModelEvaluation {
  name: string;
  metrics: EvalRow[];
  caveats?: string[];
}

export interface BwaAssessment {
  advisory: string;
  issued_utc: string;
  power_loss_p_ppm: number;
  breach_given_loss_p_ppm: number;
  breach_p_ppm: number;
}

export interface BwaAdvisory {
  advisory_id: string;
  state: "SC" | "GA";
  zone_id: string;
  station_id: string;
  kind: "pre_landfall" | "pressure_loss";
  clause_ids: string[];
  policy_key: string;
  assessments: BwaAssessment[];
  sensitivity: { hookup_lag_min: number; breach_p_ppm: number }[];
  due_utc: string | null;
  status: "not_due" | "due" | "proposed" | "issued" | "lifted";
  proposal_id: string | null;
  decision_case_id: string | null;
  stage?: NoticeStage;
  clean_samples?: number | null;
  samples_needed?: number | null;
  lift_proposal_id?: string | null;
  lift_decision_case_id?: string | null;
}

/** Where a zone's notice stands, as the register reports it: due, issued, samples, lift_decision, lifted. */
export type NoticeStage = components["schemas"]["BwaAdvisory"]["stage"];

export interface BwaClause {
  clause_id: string;
  state: "SC" | "GA";
  summary: string;
  citation: string;
  sop: { doc_id: string; section: string } | null;
  label: string;
}

/** A zone as the API may send it: `pressure_history_psi_x10` (oldest first, last 6 h) is optional until the endpoint has it; no line is drawn without it. */
export type WaterZoneWithHistory = WaterZone & { pressure_history_psi_x10?: number[] | null };

export type WaterTab = "zones" | "plan" | "advisories";
