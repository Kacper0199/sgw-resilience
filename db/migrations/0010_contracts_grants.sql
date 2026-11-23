-- K1 privileges: the application role reads and writes everything except the audit tables, which stay
-- insert-only (0006). Later migrations inherit the default privileges.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sgw_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO sgw_app;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO sgw_app;
        REVOKE UPDATE, DELETE, TRUNCATE ON audit_event, audit_checkpoint FROM sgw_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sgw_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO sgw_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sgw_readonly') THEN
        GRANT SELECT ON ALL TABLES IN SCHEMA public TO sgw_readonly;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO sgw_readonly;
    END IF;
END
$$;
