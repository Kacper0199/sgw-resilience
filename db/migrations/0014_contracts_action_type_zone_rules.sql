-- K7 additive change (R29 SX-1, zone rules engine): action_type gains 'lift_boil_water_notice' (T3, the
-- mirror of the issue) and 'field_resource_order' (T2, tanker, fuel or mobile generator order). The domain is
-- redefined in place; existing values keep their meaning.
ALTER DOMAIN sgw_action_type DROP CONSTRAINT sgw_action_type_check;
ALTER DOMAIN sgw_action_type ADD CONSTRAINT sgw_action_type_check
  CHECK (VALUE IN ('set_event_type', 'preposition_crews', 'reoptimise_within_envelope', 'stage_crews_small',
    'mutual_aid_request', 'cross_domain_priority', 'boil_water_notice', 'lift_boil_water_notice',
    'field_resource_order', 'publish_global_etr', 'work_order_draft', 'sitrep_draft', 'policy_change'));
