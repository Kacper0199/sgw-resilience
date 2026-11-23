-- K1 least privilege for the ledger: the application role may read and append events but never rewrite or
-- delete them. Only the relay appends (outbox pattern, WP-07); resets run as the owner.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sgw_app') THEN
        REVOKE UPDATE, DELETE, TRUNCATE ON event FROM sgw_app;
    END IF;
END
$$;
