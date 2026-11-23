-- WP-14a (orchestrator-approved additive K1 change): the gateway's `test` purpose is a valid `llm_call` row.
ALTER TABLE llm_call DROP CONSTRAINT llm_call_purpose_check;
ALTER TABLE llm_call ADD CONSTRAINT llm_call_purpose_check
    CHECK (purpose IN ('spike', 'dev', 'eval', 'redteam', 'record', 'demo', 'test'));
