# Tests for package sgw.egress. `base` is an input the policy allows; each case changes one field.
package sgw.egress_test

import data.sgw.egress

base := {
	"route": "R1",
	"node": "narrate_brief",
	"model": "claude-sonnet-5-5",
	"classes": ["C0", "C1"],
	"pseudonymized": false,
	"betas": [],
	"tool_types": [],
	"source_types": [],
	"detectors": {"canary_hits": 0, "secret_hits": 0},
	"node_rule": {
		"models": ["claude-sonnet-5-5"],
		"class_ceiling": "C1",
		"betas": ["context-1m"],
		"tool_types": ["web_search_20260209"],
		"source_types": ["image.base64"],
	},
}

denies(inp) := d if {
	d := egress.decision.deny with input as inp
}

test_base_allowed if {
	egress.decision.allow with input as base
	egress.decision.policy_version == "egress-v1" with input as base
	count(denies(base)) == 0
}

test_c3_and_above_denied_on_r1_and_r2 if {
	every c in ["C3", "C3-N", "C4", "CX"] {
		every r in ["R1", "R2"] {
			inp := object.union(base, {"route": r, "classes": ["C1", c]})
			"class_not_allowed_on_route" in denies(inp)
			not egress.decision.allow with input as inp
		}
	}
}

test_c2_denied_on_r1 if {
	"class_not_allowed_on_route" in denies(object.union(base, {"classes": ["C2"]}))
}

test_c2_on_r2_needs_pseudonymization if {
	rule := object.union(base.node_rule, {"class_ceiling": "C2"})
	inp := object.union(base, {"route": "R2", "classes": ["C2"], "node_rule": rule})
	denies(inp) == ["class_requires_pseudonymization"]
	count(denies(object.union(inp, {"pseudonymized": true}))) == 0
	denies(object.remove(inp, ["pseudonymized"])) == ["class_requires_pseudonymization"]
}

test_unclassified_denied if {
	"unclassified_payload" in denies(object.union(base, {"classes": []}))
	"unclassified_payload" in denies(object.union(base, {"classes": "C1"}))
	"unclassified_payload" in denies(object.remove(base, ["classes"]))
}

test_unknown_label_denied if {
	"unknown_class_label" in denies(object.union(base, {"classes": ["C9"]}))
}

test_unknown_route_denied if {
	"route_unknown" in denies(object.union(base, {"route": "R3"}))
}

test_detectors if {
	"canary_detected" in denies(object.union(base, {"detectors": {"canary_hits": 1, "secret_hits": 0}}))
	"secret_detected" in denies(object.union(base, {"detectors": {"canary_hits": 0, "secret_hits": 2}}))
	"detectors_missing" in denies(object.remove(base, ["detectors"]))
	"detectors_missing" in denies(object.union(object.remove(base, ["detectors"]), {"detectors": {"canary_hits": 0}}))
}

test_node_rule if {
	"node_not_configured" in denies(object.remove(base, ["node_rule"]))
	"route_unknown" in denies(object.remove(base, ["route"]))
	"node_not_configured" in denies(object.union(base, {"node_rule": null}))
	"node_not_configured" in denies(object.union(base, {"node_rule": object.union(base.node_rule, {"models": []})}))
	"model_not_allowed" in denies(object.union(base, {"model": "claude-opus-5-5"}))
	"node_ceiling_invalid" in denies(object.union(base, {"node_rule": object.union(base.node_rule, {"class_ceiling": "C7"})}))
}

test_partial_rule_and_input_fail_closed if {
	sparse := {"class_ceiling": "C1"}
	"node_not_configured" in denies(object.union(object.remove(base, ["node_rule"]), {"node_rule": {}}))
	d := denies(object.union(object.remove(base, ["node_rule"]), {"node_rule": sparse, "betas": ["b"], "tool_types": ["t"]}))
	"node_not_configured" in d
	"beta_not_allowed" in d
	"tool_type_not_allowed" in d
	"model_not_allowed" in denies(object.remove(base, ["model"]))
	"node_ceiling_invalid" in denies(object.union(object.remove(base, ["node_rule"]), {"node_rule": {"models": ["m"]}}))
}

test_class_above_node_ceiling if {
	rule := object.union(base.node_rule, {"class_ceiling": "C0"})
	denies(object.union(base, {"node_rule": rule})) == ["class_above_node_ceiling"]
}

test_betas_and_tools_from_the_node_rule if {
	count(denies(object.union(base, {"betas": ["context-1m"], "tool_types": ["web_search_20260209"]}))) == 0
	"beta_not_allowed" in denies(object.union(base, {"betas": ["mcp-client-2025-11-20"]}))
	"tool_type_not_allowed" in denies(object.union(base, {"tool_types": ["code_execution_20260521"]}))
}

test_source_types_from_the_node_rule if {
	count(denies(object.union(base, {"source_types": ["image.base64"]}))) == 0
	"source_type_not_allowed" in denies(object.union(base, {"source_types": ["document.base64"]}))
	"source_type_not_allowed" in denies(object.union(base, {"source_types": ["document.url"]}))
}
