package sgw.breakglass_test

import data.sgw.breakglass

ic := {"user_id": "ic_01", "functions": ["command"], "break_glass_eligible": true, "on_shift": true}

open_t3 := {
	"tier": "T3",
	"state": "in_review",
	"proposed_by": "ops_dm_01",
	"required_functions": ["command", "logistics"],
	"expires_at_ns": 2000,
}

ok_bg := {"reason": "Feeder 12 failing, logistics chief unreachable", "existing": false}

now := {"now_ns": 1000}

test_ic_with_reason_on_open_t3_is_allowed if {
	d := breakglass.break_glass with input as {"subject": ic, "proposal": open_t3, "break_glass": ok_bg, "context": now}
	d.allow
	d.deny == []
}

deny_cases := [
	{"want": "not_break_glass_tier", "subject": ic, "proposal": object.union(open_t3, {"tier": "T2"}), "bg": ok_bg, "ctx": now},
	{"want": "reason_too_short", "subject": ic, "proposal": open_t3, "bg": {"reason": "  urgent   ", "existing": false}, "ctx": now},
	{"want": "reason_too_short", "subject": ic, "proposal": open_t3, "bg": {"existing": false}, "ctx": now},
	{"want": "not_eligible", "subject": object.union(ic, {"break_glass_eligible": false}), "proposal": open_t3, "bg": ok_bg, "ctx": now},
	{"want": "function_not_held", "subject": object.union(ic, {"functions": ["operations"]}), "proposal": open_t3, "bg": ok_bg, "ctx": now},
	{"want": "off_shift", "subject": object.union(ic, {"on_shift": false}), "proposal": open_t3, "bg": ok_bg, "ctx": now},
	{"want": "not_open", "subject": ic, "proposal": object.union(open_t3, {"state": "approved"}), "bg": ok_bg, "ctx": now},
	{"want": "expired", "subject": ic, "proposal": open_t3, "bg": ok_bg, "ctx": {"now_ns": 2000}},
	{"want": "ic_is_proposer", "subject": ic, "proposal": object.union(open_t3, {"proposed_by": "ic_01"}), "bg": ok_bg, "ctx": now},
	{"want": "already_used", "subject": ic, "proposal": open_t3, "bg": {"reason": ok_bg.reason, "existing": true}, "ctx": now},
]

test_each_break_glass_rule_denies if {
	every c in deny_cases {
		d := breakglass.break_glass with input as {"subject": c.subject, "proposal": c.proposal, "break_glass": c.bg, "context": c.ctx}
		not d.allow
		c.want in d.deny
	}
}

approved_t3 := object.union(open_t3, {"state": "approved"})

log := {"user_id": "log_01", "functions": ["logistics"], "can_approve": true, "on_shift": true}

bg_row := {"ic_id": "ic_01", "cosigned": false}

test_second_function_cosigns if {
	d := breakglass.cosign with input as {"subject": log, "proposal": approved_t3, "break_glass": bg_row}
	d.allow
	d.function == "logistics"
}

cosign_cases := [
	{"want": "not_an_approver", "subject": object.union(log, {"can_approve": false}), "proposal": approved_t3, "bg": bg_row},
	{"want": "off_shift", "subject": object.union(log, {"on_shift": false}), "proposal": approved_t3, "bg": bg_row},
	{"want": "cosigner_is_ic", "subject": object.union(log, {"user_id": "ic_01"}), "proposal": approved_t3, "bg": bg_row},
	{"want": "cosigner_is_proposer", "subject": object.union(log, {"user_id": "ops_dm_01"}), "proposal": approved_t3, "bg": bg_row},
	{"want": "no_second_function", "subject": object.union(log, {"functions": ["command"]}), "proposal": approved_t3, "bg": bg_row},
	{"want": "already_cosigned", "subject": log, "proposal": approved_t3, "bg": {"ic_id": "ic_01", "cosigned": true}},
	{"want": "not_cosignable", "subject": log, "proposal": open_t3, "bg": bg_row},
]

test_each_cosign_rule_denies if {
	every c in cosign_cases {
		d := breakglass.cosign with input as {"subject": c.subject, "proposal": c.proposal, "break_glass": c.bg}
		not d.allow
		c.want in d.deny
	}
}

test_no_second_function_has_empty_function if {
	d := breakglass.cosign with input as {"subject": object.union(log, {"functions": ["command"]}), "proposal": approved_t3, "break_glass": bg_row}
	d.function == ""
}
