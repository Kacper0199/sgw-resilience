# Envelope rule (package sgw.envelope), O-04 and PLAN section 2: a re-optimisation whose every parameter is
# a whole number inside the inclusive bounds of an approved, unexpired envelope is T1; any value outside,
# any parameter without a bound or an expired envelope makes it T3. Mirrors sgw.approval.envelope.assess.
package sgw.envelope

cfg := data.sgw.governance.envelope

bounds := input.envelope.bounds

default expired := false

expired if input.context.now_ns > input.envelope.valid_until_ns

unknown contains k if {
	some k, _ in input.params
	not bounds[k]
}

within(v, b) if {
	is_number(v)
	floor(v) == v
	v >= b.min
	v <= b.max
}

outside contains k if {
	some k, v in input.params
	b := bounds[k]
	not within(v, b)
}

default inside := false

inside if {
	not expired
	count(unknown) == 0
	count(outside) == 0
}

tier := cfg.inside_tier if inside

else := cfg.outside_tier

assessment := {
	"tier": tier,
	"outside": sort(outside),
	"unknown": sort(unknown),
	"expired": expired,
}
