-- K7 additive change (orchestrator-approved, R13 W6-root for WP-38): action_type gains 'policy_change' so the
-- after-action lead-time proposal goes through the approval service (T2, compliance). The domain is
-- redefined in place; existing values keep their meaning.
ALTER DOMAIN sgw_action_type DROP CONSTRAINT sgw_action_type_check;
ALTER DOMAIN sgw_action_type ADD CONSTRAINT sgw_action_type_check
  CHECK (VALUE IN ('set_event_type', 'preposition_crews', 'reoptimise_within_envelope', 'stage_crews_small',
    'mutual_aid_request', 'cross_domain_priority', 'boil_water_notice', 'publish_global_etr', 'work_order_draft',
    'sitrep_draft', 'policy_change'));
