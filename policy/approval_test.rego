# Table-driven tests for package sgw.approval. Expected tiers and functions come from data.sgw.tiers (the
# generated K8 tier table), so a change to PLAN section 2 changes the expectations, not this file.
package sgw.approval_test

import data.sgw.approval

rules := data.sgw.tiers.rules

proposal_input(action, proposer) := {
	"action": "propose",
	"subject": {"user_id": proposer, "functions": ["operations"], "can_approve": true, "on_shift": true},
	"proposal": {
		"action_type": action,
		"proposed_by": proposer,
		"requested_by": null,
		"initiator_kind": kind(proposer),
		"target_ids": ["STG-AIK-SANDHILL-YARD"],
	},
	"facts": {"customers_affected": 0},
	"context": {"degraded_mode": "M0", "now_ns": 0},
}

kind(proposer) := "system_rule" if startswith(proposer, "system:")

kind(proposer) := "agent" if proposer == "agent"

kind(proposer) := "person" if {
	not startswith(proposer, "system:")
	proposer != "agent"
}

t3_input(approvals, subject, function) := {
	"action": "approve",
	"subject": subject,
	"proposal": {
		"action_type": "preposition_crews",
		"proposed_by": "ops_dm_01",
		"requested_by": null,
		"initiator_kind": "person",
		"target_ids": ["STG-AIK-SANDHILL-YARD", "STG-RCH-MILLPOND-YARD"],
		"tier": "T3",
		"required_functions": ["command", "logistics"],
		"state": "proposed",
		"expires_at_ns": 2000,
	},
	"context": {"degraded_mode": "M0", "now_ns": 1000},
	"approval": {"decision": "approve", "function": function, "evidence_oldest_age_s": 60},
	"approvals": approvals,
}

ic := {"user_id": "ic_01", "functions": ["command"], "can_approve": true, "on_shift": true}

logistics := {"user_id": "log_01", "functions": ["logistics"], "can_approve": true, "on_shift": true}

proposer := {"user_id": "ops_dm_01", "functions": ["operations"], "can_approve": true, "on_shift": true}

dual := {"user_id": "dual_01", "functions": ["command", "logistics"], "can_approve": true, "on_shift": true}

ic_signed := [{"approver_id": "ic_01", "function": "command", "decision": "approve"}]

test_every_tier_row_classifies_as_the_table if {
	every action, r in rules {
		c := approval.classification with input as proposal_input(action, r.proposers[0])
		c.tier == r.tier
		c.required_functions == r.approver_functions
		c.escalators == []
	}
}

test_every_listed_proposer_may_propose if {
	every action, r in rules {
		every who in r.proposers {
			d := approval.propose with input as proposal_input(action, who)
			d.allow
		}
	}
}

test_unlisted_proposer_is_denied if {
	every action in object.keys(rules) {
		d := approval.propose with input as proposal_input(action, "exec_01")
		"proposer_not_allowed" in d.deny
	}
}

test_person_must_propose_as_self if {
	inp := json.patch(proposal_input("preposition_crews", "ops_dm_01"), [{"op": "replace", "path": "/subject/user_id", "value": "ops_dm_02"}])
	d := approval.propose with input as inp
	"proposer_is_not_subject" in d.deny
}

test_agent_drafts_for_a_user_where_the_table_allows_agents if {
	inp := json.patch(proposal_input("sitrep_draft", "ic_01"), [{"op": "replace", "path": "/proposal/initiator_kind", "value": "agent"}])
	d := approval.propose with input as inp
	d.allow
	crews := json.patch(proposal_input("preposition_crews", "ic_01"), [{"op": "replace", "path": "/proposal/initiator_kind", "value": "agent"}])
	"proposer_not_allowed" in approval.propose.deny with input as crews
}

test_unknown_action_is_t4_and_denied if {
	d := approval.propose with input as proposal_input("open_breaker", "ops_dm_01")
	d.classification.tier == "T4"
	"unknown_action_type" in d.deny
	"tier_t4_prohibited" in d.deny
	not d.allow
}

escalation_cases contains [action, flag] if {
	some action, r in rules
	r.tier == "T2"
	some flag in data.sgw.tiers.escalation.flags
}

test_any_flag_raises_t2_to_t3_with_escalated_functions if {
	count(escalation_cases) > 0
	every pair in escalation_cases {
		inp := json.patch(proposal_input(pair[0], rules[pair[0]].proposers[0]), [{"op": "add", "path": sprintf("/facts/%s", [pair[1]]), "value": true}])
		c := approval.classification with input as inp
		c.tier == "T3"
		c.base_tier == "T2"
		c.required_functions == rules[pair[0]].escalated_functions
		c.escalators == [pair[1]]
	}
}

test_customer_and_target_limits_escalate_t2 if {
	limit := data.sgw.tiers.escalation.customer_limit
	at_limit := json.patch(proposal_input("stage_crews_small", "ops_dm_01"), [{"op": "replace", "path": "/facts/customers_affected", "value": limit}])
	below := json.patch(proposal_input("stage_crews_small", "ops_dm_01"), [{"op": "replace", "path": "/facts/customers_affected", "value": limit - 1}])
	targets := [sprintf("STG-%d", [i]) | some i in numbers.range(0, data.sgw.tiers.escalation.target_limit)]
	many := json.patch(proposal_input("stage_crews_small", "ops_dm_01"), [{"op": "replace", "path": "/proposal/target_ids", "value": targets}])
	c1 := approval.classification with input as at_limit
	c2 := approval.classification with input as below
	c3 := approval.classification with input as many
	c1.tier == "T3"
	c1.escalators == ["customers_ge_limit"]
	c2.tier == "T2"
	c3.tier == "T3"
	c3.escalators == ["targets_gt_limit"]
}

test_degraded_mode_only_raises if {
	t2 := json.patch(proposal_input("set_event_type", "ops_dm_01"), [{"op": "replace", "path": "/context/degraded_mode", "value": "M2"}])
	t1 := json.patch(proposal_input("sitrep_draft", "agent"), [{"op": "replace", "path": "/context/degraded_mode", "value": "M2"}])
	t3 := json.patch(proposal_input("boil_water_notice", "system:rule:bwa_pressure_loss"), [{"op": "replace", "path": "/context/degraded_mode", "value": "M2"}])
	c2 := approval.classification with input as t2
	c1 := approval.classification with input as t1
	c3 := approval.classification with input as t3
	c2.tier == "T3"
	c2.required_functions == ["command", "operations"]
	c1.tier == "T1"
	c3.tier == "T3"
	c3.required_functions == ["water_operations", "compliance"]
}

test_sec16_initiator_cannot_approve_own_proposal if {
	d := approval.approve with input as t3_input([], proposer, "operations")
	"self_approval" in d.deny
	not d.allow
}

test_sec16_agent_counts_as_initiator_for_requesting_user if {
	inp := json.patch(t3_input([], ic, "command"), [
		{"op": "replace", "path": "/proposal/initiator_kind", "value": "agent"},
		{"op": "replace", "path": "/proposal/requested_by", "value": "ic_01"},
	])
	d := approval.approve with input as inp
	"initiator_approval" in d.deny
}

test_sec17_same_person_cannot_sign_twice if {
	d2 := approval.approve with input as t3_input([{"approver_id": "dual_01", "function": "command", "decision": "approve"}], dual, "logistics")
	"approver_already_signed" in d2.deny
	not d2.complete
}

test_sec17_two_people_same_function_stays_pending if {
	ic2 := {"user_id": "ic_02", "functions": ["command"], "can_approve": true, "on_shift": true}
	d := approval.approve with input as t3_input(ic_signed, ic2, "command")
	"function_already_signed" in d.deny
	not d.complete
}

test_t3_first_signature_leaves_one_function if {
	d := approval.approve with input as t3_input([], ic, "command")
	d.allow
	not d.complete
	d.remaining_functions == ["logistics"]
}

test_t3_valid_pair_completes if {
	d := approval.approve with input as t3_input(ic_signed, logistics, "logistics")
	d.allow
	d.complete
	d.remaining_functions == []
}

test_function_must_be_held_and_required if {
	d1 := approval.approve with input as t3_input([], ic, "logistics")
	"function_not_held" in d1.deny
	ops := {"user_id": "ops_dm_02", "functions": ["operations"], "can_approve": true, "on_shift": true}
	d2 := approval.approve with input as t3_input([], ops, "operations")
	"function_not_required" in d2.deny
}

test_non_approver_and_off_shift_are_denied if {
	planner := {"user_id": "plan_etr_01", "functions": ["command"], "can_approve": false, "on_shift": true}
	tired := {"user_id": "ic_01", "functions": ["command"], "can_approve": true, "on_shift": false}
	d1 := approval.approve with input as t3_input([], planner, "command")
	d2 := approval.approve with input as t3_input([], tired, "command")
	"not_an_approver" in d1.deny
	"off_shift" in d2.deny
}

test_state_expiry_and_evidence_age_deny if {
	closed := json.patch(t3_input([], ic, "command"), [{"op": "replace", "path": "/proposal/state", "value": "approved"}])
	late := json.patch(t3_input([], ic, "command"), [{"op": "replace", "path": "/context/now_ns", "value": 2000}])
	stale := json.patch(t3_input([], ic, "command"), [{"op": "replace", "path": "/approval/evidence_oldest_age_s", "value": data.sgw.tiers.evidence_age_limit_s.T3 + 1}])
	"not_reviewable" in approval.approve.deny with input as closed
	"expired" in approval.approve.deny with input as late
	"evidence_too_old" in approval.approve.deny with input as stale
}

test_missing_expiry_and_age_do_not_deny if {
	inp := json.patch(t3_input([], ic, "command"), [
		{"op": "replace", "path": "/proposal/expires_at_ns", "value": null},
		{"op": "replace", "path": "/approval/evidence_oldest_age_s", "value": null},
	])
	d := approval.approve with input as inp
	d.allow
}

test_t3_with_one_function_is_denied if {
	inp := json.patch(t3_input([], ic, "command"), [{"op": "replace", "path": "/proposal/required_functions", "value": ["command", "command"]}])
	"t3_needs_two_functions" in approval.approve.deny with input as inp
}

test_t0_t1_and_t4_have_no_approval if {
	every t in ["T0", "T1", "T4"] {
		inp := json.patch(t3_input([], ic, "command"), [{"op": "replace", "path": "/proposal/tier", "value": t}])
		"no_approval_tier" in approval.approve.deny with input as inp
	}
}

test_reject_is_checked_like_approve_and_never_completes if {
	inp := json.patch(t3_input(ic_signed, logistics, "logistics"), [{"op": "replace", "path": "/approval/decision", "value": "reject"}])
	d := approval.approve with input as inp
	d.allow
	not d.complete
	bad := json.patch(inp, [{"op": "replace", "path": "/approval/decision", "value": "maybe"}])
	"bad_decision" in approval.approve.deny with input as bad
}

test_t2_needs_one_non_proposer if {
	ops2 := {"user_id": "ops_dm_02", "functions": ["operations"], "can_approve": true, "on_shift": true}
	inp := json.patch(t3_input([], ops2, "operations"), [
		{"op": "replace", "path": "/proposal/action_type", "value": "stage_crews_small"},
		{"op": "replace", "path": "/proposal/tier", "value": "T2"},
		{"op": "replace", "path": "/proposal/required_functions", "value": ["operations"]},
	])
	d := approval.approve with input as inp
	d.complete
	own := json.patch(inp, [{"op": "replace", "path": "/subject/user_id", "value": "ops_dm_01"}])
	"self_approval" in approval.approve.deny with input as own
}

zone_input(action, proposer, facts) := object.union(proposal_input(action, proposer), {"facts": facts})

test_field_resource_order_is_t2_logistics_from_a_zone_rule if {
	some proposer in ["system:rule:zone_hospital_tanker", "system:rule:zone_fuel_dispatch", "system:rule:zone_fuel_reroute", "system:rule:zone_mobile_generator"]
	d := approval.propose with input as zone_input("field_resource_order", proposer, {"customers_affected": 0})
	d.allow
	d.classification.tier == "T2"
	d.classification.required_functions == ["logistics"]
}

test_field_resource_order_to_a_critical_facility_escalates_to_command_and_logistics if {
	facts := {"customers_affected": 0, "critical_facility": true}
	d := approval.propose with input as zone_input("field_resource_order", "system:rule:zone_hospital_tanker", facts)
	d.classification.tier == "T3"
	d.classification.required_functions == ["command", "logistics"]
	d.classification.escalators == ["critical_facility"]
}

test_exercise_injects_propose_the_inject_action_types if {
	some action in ["set_event_type", "mutual_aid_request", "stage_crews_small", "cross_domain_priority", "field_resource_order", "work_order_draft"]
	d := approval.propose with input as zone_input(action, "system:rule:exercise_inject", {"customers_affected": 0})
	d.allow
}

test_exercise_injects_never_issue_or_lift_a_boil_water_notice if {
	some action in ["boil_water_notice", "lift_boil_water_notice", "publish_global_etr", "policy_change"]
	d := approval.propose with input as zone_input(action, "system:rule:exercise_inject", {"customers_affected": 0})
	not d.allow
	"proposer_not_allowed" in d.deny
}

test_field_resource_order_is_not_proposed_by_a_person if {
	d := approval.propose with input as zone_input("field_resource_order", "log_01", {"customers_affected": 0})
	not d.allow
	"proposer_not_allowed" in d.deny
}

test_lift_boil_water_notice_is_t3_water_operations_and_compliance if {
	d := approval.propose with input as zone_input("lift_boil_water_notice", "system:rule:bwa_lift_clean_samples", {"customers_affected": 0})
	d.allow
	d.classification.tier == "T3"
	d.classification.required_functions == ["water_operations", "compliance"]
}

test_lift_boil_water_notice_needs_the_lift_rule if {
	d := approval.propose with input as zone_input("lift_boil_water_notice", "system:rule:bwa_pressure_loss", {"customers_affected": 0})
	not d.allow
}

test_zone_rules_reuse_priority_notice_and_work_order if {
	prio := approval.propose with input as zone_input("cross_domain_priority", "system:rule:zone_restoration_order", {"customers_affected": 0})
	prio.allow
	prio.classification.required_functions == ["command", "water_operations"]
	wo := approval.propose with input as zone_input("work_order_draft", "system:rule:ami_dark_section", {"customers_affected": 0})
	wo.allow
	wo.classification.tier == "T1"
}

test_field_resource_order_logistics_signer_completes if {
	inp := {
		"action": "approve",
		"subject": logistics,
		"proposal": {
			"action_type": "field_resource_order",
			"proposed_by": "system:rule:zone_hospital_tanker",
			"requested_by": null,
			"initiator_kind": "system_rule",
			"target_ids": ["WTK-CORDGRASS-2"],
			"tier": "T2",
			"required_functions": ["logistics"],
			"state": "proposed",
			"expires_at_ns": 2000,
		},
		"context": {"degraded_mode": "M0", "now_ns": 1000},
		"approval": {"decision": "approve", "function": "logistics", "evidence_oldest_age_s": 60},
		"approvals": [],
	}
	d := approval.approve with input as inp
	d.allow
	d.complete
}
