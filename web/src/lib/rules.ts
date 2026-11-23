const RULE_NAME: Record<string, string> = {
  "rule.sc_service_pressure_normal": "Normal service pressure",
  "rule.sc_service_pressure_heavy_flow": "Heavy-flow service pressure",
  "rule.sc_bwa_pressure_loss": "Advisory after pressure loss",
  "rule.sc_bwa_pre_landfall": "Advisory before landfall",
  "rule.sc_bwn_confirmed": "Notice after a confirmed threat",
  "rule.sc_bwa_regulator_notice": "Tell the state regulator",
  "rule.sc_bwa_written_release": "Written release",
  "rule.sc_bwa_lift_pressure_loss": "Lift after pressure loss",
  "rule.sc_bwn_lift_two_sets": "Lift after positive samples",
  "rule.sc_bwa_lift_pre_hurricane": "Lift a pre-hurricane advisory",
  "rule.sc_bwa_lift_concurrence": "Lift with regulator agreement",
  "rule.ga_bwa_pressure_loss": "Advisory after pressure loss",
  "rule.ga_bwa_regulator_notice": "Tell the state regulator",
  "rule.ga_bwa_release": "Release the notice",
  "rule.ga_bwa_rescission": "Lift the advisory",
};

const CLAUSE_RULE: Record<string, string> = {
  "SC-P1": "rule.sc_service_pressure_normal",
  "SC-P2": "rule.sc_service_pressure_heavy_flow",
  "SC-A1": "rule.sc_bwa_pressure_loss",
  "SC-A2": "rule.sc_bwa_pre_landfall",
  "SC-N1": "rule.sc_bwn_confirmed",
  "SC-C1": "rule.sc_bwa_regulator_notice",
  "SC-I1": "rule.sc_bwa_written_release",
  "SC-L1": "rule.sc_bwa_lift_pressure_loss",
  "SC-L2": "rule.sc_bwn_lift_two_sets",
  "SC-L3": "rule.sc_bwa_lift_pre_hurricane",
  "SC-L4": "rule.sc_bwa_lift_concurrence",
  "GA-P1": "rule.ga_bwa_pressure_loss",
  "GA-C1": "rule.ga_bwa_regulator_notice",
  "GA-I1": "rule.ga_bwa_release",
  "GA-L1": "rule.ga_bwa_rescission",
};

const sentence = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** "rule.sc_bwa_pre_landfall" reads as "Advisory before landfall"; an unknown rule reads as its own words. */
export function ruleName(ruleId: string): string {
  return RULE_NAME[ruleId] ?? sentence(ruleId.replace(/^rule\.(?:sc|ga)_/, "").replaceAll("_", " "));
}

/** A water-rule clause ("SC-A2") by the name of the rule it carries. */
export const clauseName = (clauseId: string): string => ruleName(CLAUSE_RULE[clauseId] ?? clauseId);

/**
 * A basis citation as a plain label with the clause kept for a tooltip:
 * "rule.sc_service_pressure_normal: SC R.61-58.7.E(7) 25 psi normal operation" is "Normal service pressure" with
 * "SC R.61-58.7.E(7) 25 psi normal operation" as the clause; "SOP-WTR-4.2" is "Standard procedure".
 */
export function plainCitation(citation: string): { label: string; clause: string } {
  const rule = /^(rule\.[a-z0-9_]+):\s*(.*)$/i.exec(citation);
  if (rule) return { label: ruleName(rule[1] ?? ""), clause: rule[2] ?? citation };
  if (/^SOP-/i.test(citation)) return { label: "Standard procedure", clause: citation };
  return { label: citation, clause: citation };
}
