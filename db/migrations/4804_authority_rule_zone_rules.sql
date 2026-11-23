-- R29 SX-1 zone rules (K8, migration 0014): the lift of a boil-water notice is T3 water operations +
-- compliance like the issue; a field resource order is T2 logistics and escalates to command + logistics
-- (sgw.approval.policy_data).
INSERT INTO authority_rule (action_type, tier, approver_functions, escalated_functions) VALUES
    ('lift_boil_water_notice', 'T3', '{water_operations,compliance}', '{}'),
    ('field_resource_order', 'T2', '{logistics}', '{command,logistics}')
ON CONFLICT (action_type) DO NOTHING;
