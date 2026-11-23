# LLM egress policy (package sgw.egress), queried by services/llm_gateway before every model call, in
# every mode. The gateway builds `input` from the request it holds: declared data classes, the K14 rule of
# the calling node, beta headers, non-custom tool types and detector counts over the outbound body. Routes
# follow the threat model (R1 external API on standard terms, R2 external under zero retention). Every
# decision is a deny-list: an empty list allows; anything missing or malformed denies.
package sgw.egress

policy_version := "egress-v1"

class_rank := {"C0": 0, "C1": 1, "C2": 2, "C3": 3, "C3-N": 4, "C4": 5, "CX": 6}

routes := {
	"R1": {"allowed": {"C0", "C1"}, "pseudonymized_only": set()},
	"R2": {"allowed": {"C0", "C1", "C2"}, "pseudonymized_only": {"C2"}},
}

classes := {c | some c in input.classes}

route := routes[input.route]

rule := object.get(input, "node_rule", null)

detector(name) := object.get(input, ["detectors", name], null)

rule_list(name) := object.get(rule, name, []) if is_object(rule)

deny contains "unclassified_payload" if not is_array(object.get(input, "classes", null))

deny contains "unclassified_payload" if count(classes) == 0

deny contains "unknown_class_label" if {
	some c in classes
	not class_rank[c]
}

deny contains "route_unknown" if not routes[object.get(input, "route", "")]

deny contains "class_not_allowed_on_route" if {
	some c in classes
	class_rank[c]
	not c in route.allowed
}

deny contains "class_requires_pseudonymization" if {
	some c in classes
	c in route.pseudonymized_only
	object.get(input, "pseudonymized", false) != true
}

deny contains "detectors_missing" if not is_number(detector("canary_hits"))

deny contains "detectors_missing" if not is_number(detector("secret_hits"))

deny contains "canary_detected" if input.detectors.canary_hits > 0

deny contains "secret_detected" if input.detectors.secret_hits > 0

deny contains "node_not_configured" if not is_object(rule)

deny contains "node_not_configured" if count(rule_list("models")) == 0

deny contains "model_not_allowed" if {
	count(rule_list("models")) > 0
	not object.get(input, "model", null) in rule_list("models")
}

deny contains "node_ceiling_invalid" if {
	is_object(rule)
	not class_rank[object.get(rule, "class_ceiling", "")]
}

deny contains "class_above_node_ceiling" if {
	some c in classes
	class_rank[c] > class_rank[rule.class_ceiling]
}

deny contains "beta_not_allowed" if {
	some b in input.betas
	not b in rule_list("betas")
}

deny contains "tool_type_not_allowed" if {
	some t in input.tool_types
	not t in rule_list("tool_types")
}

deny contains "source_type_not_allowed" if {
	some t in input.source_types
	not t in rule_list("source_types")
}

decision := {
	"allow": count(deny) == 0,
	"deny": sort([r | some r in deny]),
	"policy_version": policy_version,
}
