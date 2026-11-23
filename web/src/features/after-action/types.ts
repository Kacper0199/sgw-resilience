import type { components } from "@/contracts/api.gen";

export type AuditVerifyResult = components["schemas"]["AuditVerifyResult"];
export type AuditEvent = components["schemas"]["AuditEventOut"];

export type ClockOutcome = "met" | "missed" | "open" | "unverifiable";
export type CosignStatus =
  | "cosigned_on_time"
  | "cosigned_late"
  | "overdue_unsigned"
  | "awaiting_cosign"
  | "unverifiable";

export interface ChainCheck {
  ok: boolean;
  checked_to_seq: number;
  first_bad_seq: number | null;
  signed_head_seq: number | null;
  trusted_to_seq: number;
  problems: string[];
}

export interface ClockResult {
  decision_case_id: string;
  step: string;
  title: string;
  effective_decide_by: string;
  decided_at: string | null;
  decided_by: "approval" | "break_glass" | null;
  proposal_id: string | null;
  outcome: ClockOutcome;
  margin_min: number | null;
  proposed?: boolean;
}

export interface BreakGlassUse {
  break_glass_id: number;
  proposal_id: string;
  title: string | null;
  ic_id: string;
  tier: string;
  reason: string;
  reason_code: string | null;
  used_at: string;
  cosign_due: string;
  cosigned_by: string | null;
  cosigned_at: string | null;
  status: CosignStatus;
  table_agrees: boolean;
}

export interface TimelineEntry {
  seq: number;
  occurred_at: string;
  kind: string;
  actor_id: string;
  subject: string;
}

export interface ScoreMetric {
  metric: string;
  value: number;
  unit: string;
  n: number;
  baseline_value: number | null;
  baseline_name: string | null;
  direction: "higher_is_better" | "lower_is_better";
  passed: boolean | null;
}

export interface ScoreEstimate {
  estimate_id: string;
  region_id: string;
  scope: "global" | "region";
  as_of_utc: string;
  actual_utc: string | null;
  p50_error_h: number | null;
  abs_error_h: number | null;
  analog_abs_error_h: number | null;
  in_p25_p75: boolean | null;
  in_p10_p90: boolean | null;
}

export interface Scorecard {
  name: string;
  label: string;
  actual_label: string;
  metrics: ScoreMetric[];
  estimates: ScoreEstimate[];
}

export interface InterruptionRecord {
  area_id: string;
  area_kind: string;
  county_code: string | null;
  started_at: string;
  restored_at: string;
  duration_h: number;
  customers_interrupted: number;
  max_gust_ms: number;
  cause: string;
  report_required: boolean;
}

export interface ScReport {
  citation: string;
  source_note: string;
  label: string;
  threshold_h: number;
  event_name: string;
  filed: false;
  system: InterruptionRecord;
  /** Every affected county restored by the review time; `report_required` marks those over the threshold. */
  counties: InterruptionRecord[];
  filer_notes?: string[];
  markdown: string;
}

/** `GET /api/after-action`: the after-action review plus the ETR scorecard and the SC 103-314 draft. */
export interface AfterAction {
  as_of: string;
  chain: ChainCheck;
  clocks: ClockResult[];
  break_glass: BreakGlassUse[];
  timeline: TimelineEntry[];
  scorecard: Scorecard | null;
  sc_report: ScReport | null;
}

/** `POST /api/audit/tamper-demo`: the verifier run on an altered in-memory copy. */
export interface TamperDemo {
  tampered_seq: number;
  untrusted_from_seq: number | null;
  result: AuditVerifyResult;
}
