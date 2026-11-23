-- K1 audit: one global hash-chained stream, insert-only for the application role, and a trigger that
-- rejects UPDATE, DELETE and TRUNCATE for every role (DC-09 (8)).

CREATE TABLE audit_event (
    stream       text NOT NULL DEFAULT 'global',
    seq          bigint NOT NULL,
    event_key    text NOT NULL UNIQUE,
    occurred_at  timestamptz NOT NULL,
    actor_type   text NOT NULL CHECK (actor_type IN ('user', 'system', 'agent')),
    actor_id     text NOT NULL,
    kind         text NOT NULL,
    subject      text NOT NULL,
    payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    payload      jsonb NOT NULL,
    prev_hash    text NOT NULL CHECK (prev_hash ~ '^[0-9a-f]{64}$'),
    hash         text NOT NULL CHECK (hash ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (stream, seq)
);

CREATE TABLE audit_checkpoint (
    stream      text NOT NULL,
    seq         bigint NOT NULL,
    head_hash   text NOT NULL,
    signature   text NOT NULL,
    key_id      text NOT NULL,
    anchored_at timestamptz NOT NULL,
    PRIMARY KEY (stream, seq)
);

CREATE FUNCTION audit_event_reject_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_event is insert-only (% rejected)', TG_OP USING ERRCODE = 'insufficient_privilege';
END
$$;

CREATE TRIGGER audit_event_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_event
    FOR EACH ROW EXECUTE FUNCTION audit_event_reject_change();

CREATE TRIGGER audit_event_no_truncate
    BEFORE TRUNCATE ON audit_event
    FOR EACH STATEMENT EXECUTE FUNCTION audit_event_reject_change();

CREATE TRIGGER audit_checkpoint_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_checkpoint
    FOR EACH ROW EXECUTE FUNCTION audit_event_reject_change();

CREATE TRIGGER audit_checkpoint_no_truncate
    BEFORE TRUNCATE ON audit_checkpoint
    FOR EACH STATEMENT EXECUTE FUNCTION audit_event_reject_change();

REVOKE ALL ON audit_event, audit_checkpoint FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sgw_app') THEN
        GRANT SELECT, INSERT ON audit_event, audit_checkpoint TO sgw_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sgw_readonly') THEN
        GRANT SELECT ON audit_event, audit_checkpoint TO sgw_readonly;
    END IF;
END
$$;
