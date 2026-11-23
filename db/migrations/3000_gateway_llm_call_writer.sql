-- WP-14a: the LLM gateway writes K1 `llm_call` rows through a role that may only insert them.
-- Roles are cluster objects created by the stack (initdb / scripts/ci_db_setup.py, like sgw_app): the NOLOGIN
-- group `sgw_llm_writer` and the gateway's login role `sgw_gateway IN ROLE sgw_llm_writer`. Migrations run as
-- a non-superuser database owner without CREATEROLE, so this file only grants on its own objects, and only
-- when the group exists. `llm_call` becomes append-only for every role: spend rows are evidence (SC-15).

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sgw_llm_writer') THEN
        EXECUTE format('GRANT CONNECT ON DATABASE %I TO sgw_llm_writer', current_database());
        GRANT USAGE ON SCHEMA public TO sgw_llm_writer;
        GRANT INSERT ON llm_call TO sgw_llm_writer;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sgw_app') THEN
        REVOKE UPDATE, DELETE, TRUNCATE ON llm_call FROM sgw_app;
    END IF;
END
$$;

CREATE INDEX llm_call_ts_idx ON llm_call (ts DESC);

CREATE FUNCTION llm_call_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'llm_call is append-only' USING ERRCODE = '42501';
END
$$;

CREATE TRIGGER llm_call_no_update_delete
    BEFORE UPDATE OR DELETE ON llm_call
    FOR EACH ROW EXECUTE FUNCTION llm_call_append_only();

CREATE TRIGGER llm_call_no_truncate
    BEFORE TRUNCATE ON llm_call
    FOR EACH STATEMENT EXECUTE FUNCTION llm_call_append_only();
