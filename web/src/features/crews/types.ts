import type { components } from "@/contracts/api.gen";

export type CrewItem = components["schemas"]["CrewItem"];
export type Asset = components["schemas"]["Asset"];

export type PlanId = "P50" | "COA-A" | "COA-B" | "COA-C";

export interface PlanYard {
  home_groups: number;
  own_groups: number;
  mutual_aid_groups: number;
  persons: number;
}

export interface PlanOutcome {
  n: number;
  expected_customer_hours: number;
  p90_customer_hours: number;
  cvar90_customer_hours: number;
  expected_idle_early_mutual_aid_persons: number;
  expected_late_mutual_aid_persons: number;
}

export interface Bound {
  min: number;
  max: number;
}

export interface CrewPlan {
  plan_id: PlanId;
  title: string;
  trade_off: string;
  risk: string;
  early_mutual_aid_groups: number;
  early_mutual_aid_persons: number;
  own_groups_staged: number;
  committed_early_mutual_aid_usd_per_day: number;
  expected_cost: { total_mutual_aid_usd: number; total_mutual_aid_person_days: number };
  yards: Record<string, PlanYard>;
  out_of_sample: PlanOutcome;
  synthetic_truth_customer_hours: number;
  observed_scale_stress_customer_hours: number;
  params?: Record<string, number>;
  envelope?: {
    pct: number;
    bounds: Record<string, Bound>;
    rule: string;
    pinned_yards: string[];
    note: string;
  };
  resource_request_id?: string | null;
}

export interface ValueInterval {
  value: number;
  ci_low: number;
  ci_high: number;
  n: number;
}

export interface CrewPlanDocument {
  engine_version: string;
  scenario: string;
  advisory: string;
  issued_utc: string;
  landfall_utc: string;
  objective: string;
  size: { yards: number; clusters: number; scenarios: number; out_of_sample: number };
  crews: { own_groups: number; own_group_persons: number; mutual_aid_group_persons: number };
  planning_band_check: { synthetic_truth_requirement_over_p50: number; inside_planning_band: boolean };
  forecast_scale_band: { k_low: number; k_high: number; observed_scale_stress_k: number };
  staging_rules: { home_share_min: number; site_cap_persons: number; label: string };
  vss: { ev: ValueInterval; p50: ValueInterval };
  evpi: { in_sample: number; out_of_sample: number; out_of_sample_n: number };
  plans: CrewPlan[];
  recommendation: null;
  recommendation_note: string;
}

export interface DamageCase {
  case_id: string;
  case_rank: number;
  case_score: number;
  damage_state: "slight" | "moderate" | "extensive" | "complete";
  photo_ids: string[];
  photo_ranks: number[];
  section_id: string;
  status: string;
}

export interface DamagePhoto {
  image_id: string;
  rank: number;
  triage_score: number;
  signals: string[];
  suggested_actions: string[];
  human_only: string[];
  seeded_case_id: string | null;
  no_damage_control: boolean;
  section_id: string | null;
  source_url: string;
  status: string;
  tier: "slight" | "structural" | null;
  thumb_url: string | null;
}

export interface DamageQueue {
  cases: DamageCase[];
  rows: DamagePhoto[];
  total_photos: number;
  honest_miss: string;
  imagery_note: string;
  review_note: string;
  model_id: string;
  model_revision: string;
  seeded_order: {
    control_group_max_score: number;
    control_groups: number;
    ladder_discordant_pairs: number;
    ladder_pairs: number;
    structural_min_score: number;
    tier_violations: number;
    structural_above_all_control_groups: boolean;
  };
}

export interface EvalRow {
  metric: string;
  value: number;
  unit: string;
  n: number;
  label: string;
  baseline_name: string | null;
  baseline_value: number | null;
}

export interface ModelEvaluation {
  name: string;
  metrics: EvalRow[];
}
