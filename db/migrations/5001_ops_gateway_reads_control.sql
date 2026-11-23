-- WP-28a: the LLM gateway reads the kill level and the degraded mode before every model call and refuses at
-- K2 or from M2 (SEC-60, STM 9.1). Its group role gets SELECT on the control row only.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sgw_llm_writer') THEN
        GRANT SELECT ON control_state TO sgw_llm_writer;
    END IF;
END
$$;
