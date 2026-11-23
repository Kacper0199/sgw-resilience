import { FUNCTION_LABEL } from "@/auth/personas";
import type { ApprovalFunction } from "@/contracts/vocab.gen";
import type { ActionType } from "./types";

export const ACTION_LABEL: Record<ActionType, string> = {
  set_event_type: "Set the event type",
  preposition_crews: "Pre-stage crews",
  reoptimise_within_envelope: "Adjust the plan within pre-approved limits",
  stage_crews_small: "Stage a few crews",
  mutual_aid_request: "Request mutual aid",
  cross_domain_priority: "Set priority between power and water",
  boil_water_notice: "Issue a boil-water notice",
  lift_boil_water_notice: "Lift a boil-water notice",
  field_resource_order: "Order a tanker, fuel or generator",
  publish_global_etr: "Publish the global ETR",
  work_order_draft: "Draft a work order",
  sitrep_draft: "Draft a situation report",
  policy_change: "Change a policy setting",
};

export const functionLabel = (f: ApprovalFunction): string => FUNCTION_LABEL[f];

const humanise = (s: string): string => {
  const t = s.replaceAll("_", " ").replaceAll("-", " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
};

const WORD: Record<string, string> = { ttl: "expiry", ce: "CE", cosign: "co-sign" };
const DROP_LAST = new Set(["min", "pct", "hours", "years"]);

/** "policy_break_glass_cosign_hours" reads as "Break glass cosign"; the unit sits in the value column and the key in mono beside it. */
const TIER_WORDS: Record<string, string> = {
  t1: "one-person decisions",
  t2: "one-team decisions",
  t3: "two-team decisions",
};

const PLAIN_POLICY: Record<string, string> = {
  policy_c3_aggregation_assets: "Grouped asset data counts as sensitive from",
};

export const policyName = (key: string): string => {
  if (PLAIN_POLICY[key]) return PLAIN_POLICY[key];
  const tier = /_(t[123])_/.exec(key)?.[1];
  if (tier) return `${policyName(key.replace(`_${tier}_`, "_"))}, ${TIER_WORDS[tier]}`;
  const words = key.replace(/^policy_/, "").split("_");
  if (words.length > 1 && DROP_LAST.has(words[words.length - 1] ?? "")) words.pop();
  const text = words
    .map((w) => WORD[w] ?? (/^[tc]\d$/.test(w) ? w.toUpperCase() : w))
    .join(" ")
    .replace(/^break glass/, "emergency approval")
    .replace(/^envelope$/, "pre-approved limits")
    .replace(/^ce weight/i, "weighted customers");
  return text.charAt(0).toUpperCase() + text.slice(1);
};

export const ROLE_LABEL: Record<string, string> = {
  incident_commander: "Incident Commander",
  duty_manager: "Duty Manager",
  etr_specialist: "ETR Specialist",
  logistics_chief: "Logistics Section Chief",
  water_incident_lead: "Water Incident Lead",
  water_compliance_officer: "Water Compliance Officer",
  ml_data_owner: "Data and Models Owner",
  platform_admin: "Platform Administrator",
};
export const roleLabel = (r: string): string => ROLE_LABEL[r] ?? humanise(r);

export const EVENT_LABEL = (e: string): string => humanise(e.replaceAll(".", " "));

export const MODEL_LABEL = { sonnet: "Sonnet", haiku: "Haiku", opus: "Opus" } as const;
export const EFFORT_LABEL = {
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "Extra high",
  max: "Maximum",
} as const;

export const CLASS_LABEL: Record<string, string> = {
  C0: "Public (C0)",
  C1: "Operational (C1)",
  C2: "Sensitive (C2)",
};
export const classLabel = (c: string): string => CLASS_LABEL[c] ?? c;

export const isAdmin = (me: { function: string; roles: string[] } | null | undefined): boolean =>
  !!me && (me.function === "platform" || me.roles.includes("platform_admin"));
