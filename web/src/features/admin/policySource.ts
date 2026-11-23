import type { PolicyParam } from "./types";

const SOURCE: Record<string, string> = {
  policy_approval_ttl_t1_min: "SGW default: how long a signature stays valid",
  policy_approval_ttl_t2_min: "SGW default: how long a signature stays valid",
  policy_approval_ttl_t3_min: "SGW default: how long a signature stays valid",
  policy_audit_retention_years: "SGW policy: audit records are kept for 7 years",
  policy_break_glass_cosign_hours: "SGW decision: co-sign window for emergency approval",
  policy_c3_aggregation_assets: "SGW policy: when grouped asset data counts as sensitive",
  policy_ce_weight_hospital: "SGW policy: weight of a hospital when customers are counted",
  policy_commitment_drift_tolerance_min:
    "SGW policy: one quarter-hour, the reporting step of the operations systems",
  policy_decision_elevated_within_min: "SGW policy: one advisory cycle (6 hours)",
  policy_decision_severe_within_min: "SGW policy: the last hour before a decision is due",
  policy_envelope_pct: "SGW decision: example limit of 20% more or fewer crews per site",
  policy_equity_weight: "SGW decision: weight for equity when customers are counted",
  policy_etr_restore_fraction_pct: "SGW policy: share of affected customers that must be restored",
  policy_learning_credibility_prior_n: "SGW policy: how much history counts when plans are tuned",
  policy_learning_min_change_min: "SGW policy: smallest change when plans are tuned",
  policy_learning_rounding_min: "SGW policy: plan times round to a quarter-hour",
  policy_no_regret_act_now_ppm: "SGW default: share of scenarios that must agree before 'Act now'",
  policy_pre_landfall_breach_p: "SGW assumption: chance of low pressure that triggers action",
  policy_saa_cvar_alpha: "SGW assumption: which part of the worst cases the plan guards against",
  policy_saa_cvar_weight: "SGW assumption: how much the worst cases count in the plan",
  policy_saa_tail_spend_quantile: "SGW assumption: size of the early mutual-aid request",
  policy_small_staging_customer_limit: "SGW policy: largest staging a single team may approve",
  policy_staging_home_share_min: "SGW assumption: share of crews that stay at home yards",
  policy_staging_site_cap_persons: "SGW assumption: placeholder until the logistics site list is in",
  policy_webhook_tolerance_s: "SGW default: how far apart clocks may be for outbound messages",
};

const GROUP: [RegExp, string][] = [
  [/^policy_evidence_age_/, "SGW policy: how old evidence may be before a decision"],
  [/^policy_heat_/, "SGW assumption: heat rule for transformers"],
  [/^policy_transformer_hot_spot_/, "SGW assumption: transformer temperature alarm level"],
  [/^policy_water_continuity_/, "SGW assumption: water network model setting"],
  [/^policy_wildfire_/, "SGW assumption: wildfire trigger"],
];

const developerText =
  /\bWP-\d|P-\d\d-\d\d|planner-handoff|project fact base|Contract default|DESIGN\.md|\.yaml|\bRESOLUTION\b|\bPLAN section|BE-UI|\bPA DC|\bPS DC/i;

/** The source of a policy setting in plain words; internal work-package and document references stay out of the screen. */
export function plainPolicySource(p: PolicyParam): string {
  const known = SOURCE[p.key] ?? GROUP.find(([re]) => re.test(p.key))?.[1];
  if (known) return known;
  if (!developerText.test(p.source)) return p.source;
  return p.source.startsWith("assumed") ? "SGW assumption" : "SGW policy";
}
