-- WP-38 learning loop: a policy change (updated lead times) is a T2 action approved by compliance (K8, migration 0013).
INSERT INTO authority_rule (action_type, tier, approver_functions, escalated_functions)
VALUES ('policy_change', 'T2', '{compliance}', '{}')
ON CONFLICT (action_type) DO NOTHING;
