package sgw.dispatch_test

import data.sgw.dispatch

admin := {"user_id": "admin_01", "roles": ["platform_admin"], "functions": ["platform"], "can_approve": false, "on_shift": true}

ops := {"user_id": "ops_dm_01", "roles": ["duty_manager"], "functions": ["operations"], "can_approve": true, "on_shift": true}

logistics := {"user_id": "log_01", "roles": ["logistics_chief"], "functions": ["logistics"], "can_approve": true, "on_shift": true}

exec := {"user_id": "exec_01", "roles": ["executive"], "functions": ["executive"], "can_approve": false, "on_shift": true}

pending := {"state": "proposed", "proposed_by": "ops_dm_01", "required_function": "logistics"}

test_dispatchers_may_act if {
	every s in [ops, logistics] {
		dispatch.act.allow with input as {"subject": s}
	}
}

test_read_only_personas_and_the_platform_admin_may_not_act if {
	every s in [exec, admin] {
		d := dispatch.act with input as {"subject": s}
		not d.allow
		d.deny == ["role_not_allowed"]
	}
}

test_logistics_signs_unless_the_proposer_holds_logistics if {
	dispatch.propose.required_function == "logistics" with input as {"subject": ops}
	dispatch.propose.required_function == "operations" with input as {"subject": logistics}
}

test_propose_carries_the_policy_version if {
	d := dispatch.propose with input as {"subject": ops}
	d.allow
	d.policy_version == data.sgw.crew_dispatch.policy_version
}

test_propose_denied_for_a_reader if {
	d := dispatch.propose with input as {"subject": exec}
	d.deny == ["role_not_allowed"]
}

test_holder_of_every_signer_function_has_no_signer if {
	both := object.union(ops, {"functions": ["logistics", "operations"]})
	d := dispatch.propose with input as {"subject": both}
	not d.allow
	d.deny == ["no_signer_function"]
	d.required_function == null
}

test_logistics_signs_a_pending_assignment if {
	d := dispatch.sign with input as {"subject": logistics, "assignment": pending}
	d.allow
	d.deny == []
}

sign_cases := [
	{"want": "not_pending", "subject": logistics, "assignment": object.union(pending, {"state": "assigned"})},
	{"want": "self_sign", "subject": logistics, "assignment": object.union(pending, {"proposed_by": "log_01"})},
	{"want": "not_an_approver", "subject": object.union(logistics, {"can_approve": false}), "assignment": pending},
	{"want": "off_shift", "subject": object.union(logistics, {"on_shift": false}), "assignment": pending},
	{"want": "function_not_held", "subject": ops, "assignment": object.union(pending, {"proposed_by": "admin_01"})},
]

test_each_sign_rule_denies if {
	every c in sign_cases {
		d := dispatch.sign with input as {"subject": c.subject, "assignment": c.assignment}
		not d.allow
		c.want in d.deny
	}
}
