import type { NoRegretVerdict } from "@/contracts/vocab.gen";

export const QUANTILES = ["q0025", "q0100", "q0250", "q0500", "q0750", "q0900", "q0975"] as const;
export type QuantileKey = (typeof QUANTILES)[number];

/** One county's peak outage fan, customers out at the storm's peak. Not in the K3 contract yet. */
export interface CountyFan extends Record<QuantileKey, number> {
  fips: string;
  name: string;
  customers: number;
  mean: number;
  /** The county's highest customers out in the outage feed by the scenario clock. */
  observed_peak?: number | null;
}

/** The outage feed at the scenario clock, for forecast vs actual. */
export interface ObservedOutages {
  as_of: string;
  customers_out_now: number;
  peak_customers_out: number;
  peak_at_utc: string;
}

export interface ActionShare {
  action_id: string;
  label: string;
  decision_case_ids: string[];
  share_ppm: number;
  members_needed: number;
  members: number;
}

/** `GET /api/forecasts/outages/counties?advisory=`: the A2 county fans of one advisory. */
export interface CountyForecast {
  advisory_label: string;
  issued_utc: string;
  next_advisory_utc: string | null;
  model_version: string;
  members: number;
  trained_on: string[];
  counties: CountyFan[];
  actions: ActionShare[];
  observed?: ObservedOutages | null;
}

export interface PlanDiffAction {
  action_id: string;
  label: string;
  decision_case_ids: string[];
  share_ppm: [number | null, number];
  crossed_act_now_threshold: boolean;
  rule: string;
  /** The open decision of the action's case, as Decisions lists it; null or absent when none is open. */
  proposal_id?: string | null;
  /** The Timing Decisions shows for that case. */
  timing?: NoRegretVerdict | null;
}

export interface PlanDiffCounty {
  fips: string;
  name: string;
  p50_out: [number, number];
  p90_out: [number, number];
  p_ppm: [number, number];
  band: [string, string];
}

/** `GET /api/forecasts/outages/plan-diff?to=`: what changed between an advisory and the one before it. */
export interface PlanDiff {
  scenario: string;
  from_advisory: string;
  to_advisory: string;
  footprint_mean_out: [number, number];
  footprint_p90_out_sum: [number, number];
  asset_band_changes: number;
  act_now_threshold_ppm: number;
  counties: PlanDiffCounty[];
  actions: PlanDiffAction[];
}

export interface WhatIfCell {
  customer_hours: number;
  customers_affected: number;
  delta_customer_hours_pct: number;
  hours_peak_to_90pct: number | null;
  peak_customers_out: number;
  levers: Record<string, number>;
}

/** `GET /api/whatif`: the precomputed grid, narrowed to the baseline and the named scenarios. */
export interface WhatIf {
  scenario: string;
  label: string;
  metric_notes: Record<string, string>;
  baseline: WhatIfCell;
  scenarios: (WhatIfCell & { id: string; title: string })[];
}

export interface K17Row {
  metric: string;
  value: number;
  unit: string;
  n: number;
  split: string;
  label: string;
  baseline_name: string | null;
  baseline_value: number | null;
  direction: "lower_is_better" | "higher_is_better";
  passed: boolean | null;
}

export interface K17Report {
  name: string;
  schema_version: number;
  created_at: string;
  code_version: string;
  command: string;
  metrics: K17Row[];
}
