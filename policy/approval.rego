# K8 approval policy (package sgw.approval). Tiers, approver functions, proposers and thresholds are read
# from data.sgw.tiers, generated from the K8 tier table (PLAN section 2) by sgw.approval.policy_data; this
# file holds rules only. The server builds `input`; tiers and escalators are never taken from a client or
# a model. Every decision is a deny-list: an empty list allows, anything undefined denies.
package sgw.approval

tiers := data.sgw.tiers

rule := tiers.rules[input.proposal.action_type]

default base_tier := "T4"

base_tier := rule.tier

escalators contains "customers_ge_limit" if {
	is_number(input.facts.customers_affected)
	input.facts.customers_affected >= tiers.escalation.customer_limit
}

escalators contains "targets_gt_limit" if {
	count(input.proposal.target_ids) > tiers.escalation.target_limit
}

escalators contains flag if {
	some flag in tiers.escalation.flags
	input.facts[flag] == true
}

escalators contains "degraded_mode" if {
	is_string(input.context.degraded_mode)
	input.context.degraded_mode != tiers.escalation.normal_degraded_mode
}

escalated if {
	base_tier == "T2"
	count(escalators) > 0
}

tier := "T3" if escalated

else := base_tier

default required_functions := []

required_functions := rule.escalated_functions if escalated

else := rule.approver_functions if rule

classification := {
	"tier": tier,
	"base_tier": base_tier,
	"required_functions": required_functions,
	"escalators": sort(escalators),
	"policy_version": tiers.policy_version,
}

# ---- propose -------------------------------------------------------------------------------------------

proposer_allowed if input.proposal.proposed_by in rule.proposers

proposer_allowed if {
	input.proposal.initiator_kind == "agent"
	"agent" in rule.proposers
}

propose_deny contains "unknown_action_type" if not rule

propose_deny contains "tier_t4_prohibited" if tier == "T4"

propose_deny contains "proposer_not_allowed" if {
	rule
	not proposer_allowed
}

propose_deny contains "proposer_is_not_subject" if {
	input.proposal.initiator_kind == "person"
	input.proposal.proposed_by != input.subject.user_id
}

propose := {
	"allow": count(propose_deny) == 0,
	"deny": sort(propose_deny),
	"classification": classification,
}

# ---- approve or reject ---------------------------------------------------------------------------------

decision_kinds := {"approve", "reject"}

approving if input.approval.decision == "approve"

approve_deny contains "bad_decision" if not input.approval.decision in decision_kinds

approve_deny contains "not_reviewable" if not input.proposal.state in tiers.reviewable_states

approve_deny contains "no_approval_tier" if not input.proposal.tier in tiers.approval_tiers

approve_deny contains "t3_needs_two_functions" if {
	input.proposal.tier == "T3"
	count({f | some f in input.proposal.required_functions}) != 2
}

approve_deny contains "expired" if {
	is_number(input.proposal.expires_at_ns)
	input.context.now_ns >= input.proposal.expires_at_ns
}

approve_deny contains "self_approval" if input.subject.user_id == input.proposal.proposed_by

approve_deny contains "initiator_approval" if input.subject.user_id == input.proposal.requested_by

approve_deny contains "not_an_approver" if not input.subject.can_approve == true

approve_deny contains "off_shift" if input.subject.on_shift == false

approve_deny contains "function_not_held" if not input.approval.function in input.subject.functions

approve_deny contains "function_not_required" if not input.approval.function in input.proposal.required_functions

approve_deny contains "function_already_signed" if {
	some a in input.approvals
	a.function == input.approval.function
}

approve_deny contains "approver_already_signed" if {
	some a in input.approvals
	a.approver_id == input.subject.user_id
}

approve_deny contains "evidence_too_old" if {
	is_number(input.approval.evidence_oldest_age_s)
	input.approval.evidence_oldest_age_s > tiers.evidence_age_limit_s[input.proposal.tier]
}

signed_functions contains a.function if {
	some a in input.approvals
	a.decision == "approve"
}

signed_functions contains input.approval.function if approving

signers contains a.approver_id if {
	some a in input.approvals
	a.decision == "approve"
}

signers contains input.subject.user_id if approving

remaining_functions contains f if {
	some f in input.proposal.required_functions
	not f in signed_functions
}

default complete := false

complete if {
	approving
	count(approve_deny) == 0
	count(remaining_functions) == 0
	count(signers) >= count({f | some f in input.proposal.required_functions})
	not input.proposal.proposed_by in signers
	not input.proposal.requested_by in signers
}

approve := {
	"allow": count(approve_deny) == 0,
	"deny": sort(approve_deny),
	"complete": complete,
	"remaining_functions": sort(remaining_functions),
}
