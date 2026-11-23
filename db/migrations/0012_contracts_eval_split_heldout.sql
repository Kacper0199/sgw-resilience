-- K7 additive change (orchestrator-approved, R09 WP-15 fix round): eval_split gains 'heldout' for the
-- held-out LLM item sets. The domain is redefined in place; existing values keep their meaning.
ALTER DOMAIN sgw_eval_split DROP CONSTRAINT sgw_eval_split_check;
ALTER DOMAIN sgw_eval_split ADD CONSTRAINT sgw_eval_split_check
  CHECK (VALUE IN ('dev', 'heldout_family_b', 'real_loso', 'ladi_reference', 'heldout'));
