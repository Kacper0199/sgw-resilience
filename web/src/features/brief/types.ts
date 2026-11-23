import type { ApprovalFunction, Tier, UiSeverity } from "@/contracts/vocab.gen";

/** The four numbers on the Brief. The server supplies both views; the page only picks which to show. */
export interface BriefNumber {
  key: "customers_out" | "critical_facilities" | "water_zones_advisory" | "crews";
  label: string;
  unit: string;
  actual: { value: number; as_of: string; detail: string | null; source_id: string } | null;
  forecast: { p50: number; low: number | null; high: number | null; basis: string; source_id: string } | null;
}

export interface BriefClock {
  proposal_id: string;
  decision_case_id: string | null;
  title: string;
  tier: Tier;
  severity: UiSeverity;
  decide_by_utc: string;
  effective_decide_by_utc: string;
  waiting_for: ApprovalFunction[];
  signed: ApprovalFunction[];
}

export interface FunctionLine {
  function: ApprovalFunction;
  sentence: string;
}

export interface SitrepNumber {
  label: string;
  value: string;
  source_id: string;
}

export interface SitrepDoc {
  run_id: string;
  as_of_utc: string;
  tier: Tier;
  path: string | null;
  text: string;
  numbers: SitrepNumber[];
  created_at: string;
  promoted_by: string | null;
  promoted_at: string | null;
}

export type StatusWord = "Normal" | "Watch" | "Warning" | "Emergency" | "Restoring";

export interface Brief {
  as_of: string;
  status: { word: StatusWord; severity: UiSeverity; reason: string };
  last_advisory: { label: string; issued_utc: string; next_utc: string | null } | null;
  numbers: BriefNumber[];
  open_t3: BriefClock[];
  functions: FunctionLine[];
  caveat: string;
  sitrep: { current: SitrepDoc | null; draft: SitrepDoc | null; promote_by: ApprovalFunction[] };
  footer: string;
}
