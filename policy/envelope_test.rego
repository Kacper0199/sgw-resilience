package sgw.envelope_test

import data.sgw.envelope

env := {"bounds": {"crews_at_a": {"min": 8, "max": 12}, "crews_at_b": {"min": 4, "max": 6}}, "valid_until_ns": 5000}

cases := [
	{"params": {"crews_at_a": 10, "crews_at_b": 5}, "now": 1000, "tier": "T1", "outside": [], "unknown": [], "expired": false},
	{"params": {"crews_at_a": 8, "crews_at_b": 6}, "now": 5000, "tier": "T1", "outside": [], "unknown": [], "expired": false},
	{"params": {"crews_at_a": 7}, "now": 1000, "tier": "T3", "outside": ["crews_at_a"], "unknown": [], "expired": false},
	{"params": {"crews_at_a": 13, "crews_at_b": 3}, "now": 1000, "tier": "T3", "outside": ["crews_at_a", "crews_at_b"], "unknown": [], "expired": false},
	{"params": {"crews_at_a": 10.5}, "now": 1000, "tier": "T3", "outside": ["crews_at_a"], "unknown": [], "expired": false},
	{"params": {"crews_at_a": true}, "now": 1000, "tier": "T3", "outside": ["crews_at_a"], "unknown": [], "expired": false},
	{"params": {"crews_at_c": 1}, "now": 1000, "tier": "T3", "outside": [], "unknown": ["crews_at_c"], "expired": false},
	{"params": {"crews_at_a": 10}, "now": 5001, "tier": "T3", "outside": [], "unknown": [], "expired": true},
	{"params": {}, "now": 1000, "tier": "T1", "outside": [], "unknown": [], "expired": false},
]

test_envelope_table if {
	every c in cases {
		a := envelope.assessment with input as {"envelope": env, "params": c.params, "context": {"now_ns": c.now}}
		a.tier == c.tier
		a.outside == c.outside
		a.unknown == c.unknown
		a.expired == c.expired
	}
}
