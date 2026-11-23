-- WP-14b: agent threads (K1 has `agent_run` but no thread table) and the LangGraph checkpoint tables of
-- langgraph-checkpoint-postgres 3.2 in schema `lg` (0001, 0008). The owner creates them here so the runtime
-- role never runs DDL; `lg.checkpoint_migrations` records the library's migrations 0-9 as applied, so the
-- saver's own `setup()` is never needed. Run frames stay in API memory, bounded.

CREATE TABLE agent_thread (
    thread_id  text PRIMARY KEY,
    user_id    text NOT NULL,
    module     text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX agent_run_thread_idx ON agent_run (thread_id, started_at DESC);

CREATE TABLE lg.checkpoint_migrations (
    v integer PRIMARY KEY
);

CREATE TABLE lg.checkpoints (
    thread_id            text NOT NULL,
    checkpoint_ns        text NOT NULL DEFAULT '',
    checkpoint_id        text NOT NULL,
    parent_checkpoint_id text,
    type                 text,
    checkpoint           jsonb NOT NULL,
    metadata             jsonb NOT NULL DEFAULT '{}',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

CREATE TABLE lg.checkpoint_blobs (
    thread_id     text NOT NULL,
    checkpoint_ns text NOT NULL DEFAULT '',
    channel       text NOT NULL,
    version       text NOT NULL,
    type          text NOT NULL,
    blob          bytea,
    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
);

CREATE TABLE lg.checkpoint_writes (
    thread_id     text NOT NULL,
    checkpoint_ns text NOT NULL DEFAULT '',
    checkpoint_id text NOT NULL,
    task_id       text NOT NULL,
    idx           integer NOT NULL,
    channel       text NOT NULL,
    type          text,
    blob          bytea NOT NULL,
    task_path     text NOT NULL DEFAULT '',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);

CREATE INDEX checkpoints_thread_id_idx ON lg.checkpoints (thread_id);
CREATE INDEX checkpoint_blobs_thread_id_idx ON lg.checkpoint_blobs (thread_id);
CREATE INDEX checkpoint_writes_thread_id_idx ON lg.checkpoint_writes (thread_id);

INSERT INTO lg.checkpoint_migrations (v) SELECT generate_series(0, 9);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sgw_app') THEN
        GRANT SELECT, INSERT, UPDATE ON agent_thread TO sgw_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON lg.checkpoints, lg.checkpoint_blobs, lg.checkpoint_writes
            TO sgw_app;
        GRANT SELECT ON lg.checkpoint_migrations TO sgw_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sgw_readonly') THEN
        GRANT SELECT ON agent_thread TO sgw_readonly;
    END IF;
END
$$;
