-- G1-BE: the owner's rating of a copilot run (`POST /api/threads/{t}/runs/{r}/feedback`), one row per run;
-- a new rating replaces the old one. C1: the note is the user's own words about the answer.

CREATE TABLE agent_run_feedback (
    run_id     text PRIMARY KEY REFERENCES agent_run (run_id) ON DELETE CASCADE,
    user_id    text NOT NULL,
    rating     text NOT NULL CHECK (rating IN ('up', 'down')),
    note       text CHECK (note IS NULL OR length(note) <= 2000),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sgw_app') THEN
        GRANT SELECT, INSERT, UPDATE ON agent_run_feedback TO sgw_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sgw_readonly') THEN
        GRANT SELECT ON agent_run_feedback TO sgw_readonly;
    END IF;
END
$$;
