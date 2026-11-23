-- K1 base: extensions, schemas and roles (WP-02, W0). Never edit after it is applied.
-- Runs as a superuser or as the database owner after a superuser created the extensions and, ideally, the
-- roles sgw_app and sgw_readonly (WP-03 bootstrap). IF NOT EXISTS makes the extension lines no-ops then;
-- role creation is skipped with a notice when the migrating role lacks CREATEROLE.
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS lg;

DO $$
DECLARE
    r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['sgw_app', 'sgw_readonly'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            BEGIN
                EXECUTE format('CREATE ROLE %I NOLOGIN', r);
            EXCEPTION WHEN insufficient_privilege THEN
                RAISE NOTICE 'role % not created (no CREATEROLE); grants to it are skipped', r;
            END;
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sgw_app') THEN
        GRANT USAGE ON SCHEMA public, lg TO sgw_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sgw_readonly') THEN
        GRANT USAGE ON SCHEMA public TO sgw_readonly;
    END IF;
END
$$;
