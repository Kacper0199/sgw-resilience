-- WP-28a control plane: degraded-mode signals, kill-switch authority and the two-function restore.
-- "Authority is a DB row": the database refuses approvals, execution tokens and effects while a kill level
-- is set or a signal that blocks execution is active; agent runs from K2; ingestion and new proposals from
-- K3. The control row always exists and cannot be deleted; a missing row reads as K1 (fail closed). The
-- application role may change only the scenario columns of `control_state`; the kill level, the degraded
-- mode and restores change only through the SECURITY DEFINER functions below, and a kill level is lowered
-- only by `ops_restore_complete`, signed by two people from `command` and `compliance`, each with a live
-- stepped-up session. SQLSTATE 42501 maps to HTTP 403.

CREATE FUNCTION ops_kill_rank(level text) RETURNS integer
LANGUAGE sql IMMUTABLE AS $$ SELECT substr(level, 2)::integer $$;

CREATE FUNCTION ops_mode_rank(mode text) RETURNS integer
LANGUAGE sql IMMUTABLE AS $$ SELECT substr(mode, 2)::integer $$;

CREATE FUNCTION ops_kill_mode_floor(level text) RETURNS integer
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE level WHEN 'K2' THEN 2 WHEN 'K3' THEN 3 WHEN 'K4' THEN 4 ELSE 0 END
$$;

CREATE FUNCTION ops_current_kill() RETURNS integer
LANGUAGE sql STABLE AS $$
    SELECT coalesce((SELECT ops_kill_rank(kill_level) FROM control_state WHERE id = 1), 1)
$$;

INSERT INTO control_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

CREATE FUNCTION ops_control_no_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'the control row cannot be removed (% refused)', TG_OP USING ERRCODE = 'insufficient_privilege';
END
$$;

CREATE TRIGGER control_state_no_delete BEFORE DELETE ON control_state
    FOR EACH ROW EXECUTE FUNCTION ops_control_no_delete();
CREATE TRIGGER control_state_no_truncate BEFORE TRUNCATE ON control_state
    FOR EACH STATEMENT EXECUTE FUNCTION ops_control_no_delete();

CREATE TABLE ops_signal (
    signal           text PRIMARY KEY CHECK (signal ~ '^[a-z][a-z_]{1,39}$'),
    active           boolean NOT NULL DEFAULT false,
    floor_mode       sgw_degraded_mode NOT NULL DEFAULT 'M0',
    blocks_execution boolean NOT NULL DEFAULT false,
    source           text NOT NULL CHECK (source IN ('fault_flag', 'probe', 'manual')),
    detail           text NOT NULL DEFAULT '',
    fail_streak      integer NOT NULL DEFAULT 0 CHECK (fail_streak >= 0),
    ok_streak        integer NOT NULL DEFAULT 0 CHECK (ok_streak >= 0),
    since            timestamptz,
    updated_at       timestamptz NOT NULL DEFAULT now(),
    updated_by       text NOT NULL
);

CREATE TABLE ops_kill_role (
    role text PRIMARY KEY
);
INSERT INTO ops_kill_role (role) VALUES
    ('incident_commander'), ('duty_manager'), ('water_incident_lead'), ('executive');

CREATE TABLE ops_kill_restore (
    restore_id         text PRIMARY KEY CHECK (restore_id ~ '^RST-[0-9A-F]{12}$'),
    from_level         sgw_kill_level NOT NULL,
    to_level           sgw_kill_level NOT NULL,
    reason             text NOT NULL CHECK (char_length(btrim(reason)) >= 10),
    checklist          jsonb NOT NULL,
    requested_by       text NOT NULL REFERENCES app_user (user_id),
    requested_function sgw_approval_function NOT NULL,
    requested_at       timestamptz NOT NULL,
    expires_at         timestamptz NOT NULL,
    state              text NOT NULL DEFAULT 'pending'
                       CHECK (state IN ('pending', 'completed', 'cancelled', 'expired')),
    cosigned_by        text REFERENCES app_user (user_id),
    cosigned_function  sgw_approval_function,
    completed_at       timestamptz,
    completed_xid      xid8,
    CHECK (ops_kill_rank(to_level) < ops_kill_rank(from_level)),
    CHECK (expires_at > requested_at),
    CHECK (state <> 'completed' OR (cosigned_by IS NOT NULL AND cosigned_by <> requested_by
                                    AND cosigned_function IS DISTINCT FROM requested_function))
);
CREATE UNIQUE INDEX ops_kill_restore_one_pending ON ops_kill_restore ((true)) WHERE state = 'pending';

CREATE TABLE ops_voided_token (
    token_id  uuid PRIMARY KEY REFERENCES execution_token (token_id),
    voided_at timestamptz NOT NULL,
    reason    text NOT NULL
);

CREATE FUNCTION ops_restore_enforce() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    fn text;
    shift boolean;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.state <> 'pending' OR NEW.cosigned_by IS NOT NULL OR NEW.completed_at IS NOT NULL THEN
            RAISE EXCEPTION 'a restore starts pending with one signature' USING ERRCODE = 'insufficient_privilege';
        END IF;
        SELECT function, on_shift INTO fn, shift FROM app_user WHERE user_id = NEW.requested_by;
        IF fn IS NULL OR fn NOT IN ('command', 'compliance') OR NOT shift THEN
            RAISE EXCEPTION 'restore needs the command or compliance function on shift, not %', coalesce(fn, 'none')
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        NEW.requested_function := fn;
        IF ops_kill_rank(NEW.from_level) <> ops_current_kill() THEN
            RAISE EXCEPTION 'restore from % but the kill level is K%', NEW.from_level, ops_current_kill()
                USING ERRCODE = 'invalid_parameter_value';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.state <> 'pending' THEN
        RAISE EXCEPTION 'restore % is %, it cannot change', OLD.restore_id, OLD.state
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.restore_id <> OLD.restore_id OR NEW.from_level <> OLD.from_level OR NEW.to_level <> OLD.to_level
       OR NEW.reason <> OLD.reason OR NEW.checklist <> OLD.checklist OR NEW.requested_by <> OLD.requested_by
       OR NEW.requested_function <> OLD.requested_function OR NEW.requested_at <> OLD.requested_at
       OR NEW.expires_at <> OLD.expires_at THEN
        RAISE EXCEPTION 'a restore request is immutable once signed' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.state = 'completed' THEN
        SELECT function, on_shift INTO fn, shift FROM app_user WHERE user_id = NEW.cosigned_by;
        IF fn IS NULL OR fn NOT IN ('command', 'compliance') OR NOT shift THEN
            RAISE EXCEPTION 'the second restore signature needs command or compliance on shift, not %',
                coalesce(fn, 'none') USING ERRCODE = 'insufficient_privilege';
        END IF;
        IF NEW.cosigned_by = OLD.requested_by OR fn = OLD.requested_function::text THEN
            RAISE EXCEPTION 'restore needs two people from two functions (command and compliance)'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        IF OLD.expires_at <= now() THEN
            RAISE EXCEPTION 'restore % expired at %', OLD.restore_id, OLD.expires_at
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        IF ops_kill_rank(OLD.from_level) <> ops_current_kill() THEN
            RAISE EXCEPTION 'the kill level changed since restore % was requested', OLD.restore_id
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        NEW.cosigned_function := fn;
        NEW.completed_at := now();
        NEW.completed_xid := pg_current_xact_id();
        RETURN NEW;
    END IF;
    IF NEW.cosigned_by IS NOT NULL OR NEW.completed_xid IS NOT NULL THEN
        RAISE EXCEPTION 'only a completed restore carries a second signature'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER ops_kill_restore_enforce_write
    BEFORE INSERT OR UPDATE ON ops_kill_restore
    FOR EACH ROW EXECUTE FUNCTION ops_restore_enforce();

CREATE FUNCTION ops_control_enforce() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    signal_floor integer;
BEGIN
    IF NEW.kill_level IS DISTINCT FROM OLD.kill_level
       AND ops_kill_rank(NEW.kill_level) < ops_kill_rank(OLD.kill_level) THEN
        IF NOT EXISTS (
            SELECT 1 FROM ops_kill_restore r
            WHERE r.state = 'completed' AND r.completed_xid = pg_current_xact_id()
              AND r.from_level = OLD.kill_level AND r.to_level = NEW.kill_level
        ) THEN
            RAISE EXCEPTION 'lowering the kill level from % to % needs a restore signed by command and compliance',
                OLD.kill_level, NEW.kill_level USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    IF NEW.kill_level IS DISTINCT FROM OLD.kill_level OR NEW.degraded_mode IS DISTINCT FROM OLD.degraded_mode THEN
        SELECT coalesce(max(ops_mode_rank(floor_mode)), 0) INTO signal_floor FROM ops_signal WHERE active;
        IF ops_mode_rank(NEW.degraded_mode) < greatest(ops_kill_mode_floor(NEW.kill_level), signal_floor) THEN
            RAISE EXCEPTION 'degraded mode % is below the floor M% (kill level %, active signals)',
                NEW.degraded_mode, greatest(ops_kill_mode_floor(NEW.kill_level), signal_floor), NEW.kill_level
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER control_state_ops_enforce
    BEFORE UPDATE ON control_state
    FOR EACH ROW EXECUTE FUNCTION ops_control_enforce();

CREATE FUNCTION ops_execution_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    k integer := ops_current_kill();
    blocker text;
BEGIN
    IF k > 0 THEN
        RAISE EXCEPTION 'kill switch K% is set: no approvals, execution tokens or effects (%)', k, TG_TABLE_NAME
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT signal INTO blocker FROM ops_signal WHERE active AND blocks_execution ORDER BY signal LIMIT 1;
    IF blocker IS NOT NULL THEN
        RAISE EXCEPTION 'degraded (%): approvals, execution tokens and effects are denied (%)', blocker, TG_TABLE_NAME
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF TG_TABLE_NAME = 'execution_token' AND TG_OP = 'UPDATE' THEN
        IF EXISTS (SELECT 1 FROM ops_voided_token v WHERE v.token_id = NEW.token_id) THEN
            RAISE EXCEPTION 'execution token % was voided by the kill switch', NEW.token_id
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER approval_ops_guard BEFORE INSERT ON approval
    FOR EACH ROW EXECUTE FUNCTION ops_execution_guard();
CREATE TRIGGER execution_token_ops_guard BEFORE INSERT OR UPDATE ON execution_token
    FOR EACH ROW EXECUTE FUNCTION ops_execution_guard();
CREATE TRIGGER effect_ops_guard BEFORE INSERT ON effect
    FOR EACH ROW EXECUTE FUNCTION ops_execution_guard();

CREATE FUNCTION ops_kill_level_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    k integer := ops_current_kill();
    min_level integer := TG_ARGV[0]::integer;
BEGIN
    IF k >= min_level THEN
        IF TG_TABLE_NAME = 'job' THEN
            IF NOT (NEW.kind = 'ledger.append' AND coalesce(NEW.payload->>'origin', '') LIKE 'ingest:%') THEN
                RETURN NEW;
            END IF;
        END IF;
        RAISE EXCEPTION 'kill switch K% is set: % refused', k, TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER agent_run_ops_guard BEFORE INSERT ON agent_run
    FOR EACH ROW EXECUTE FUNCTION ops_kill_level_guard('2');
CREATE TRIGGER job_ingest_ops_guard BEFORE INSERT ON job
    FOR EACH ROW EXECUTE FUNCTION ops_kill_level_guard('3');
CREATE TRIGGER proposal_ops_guard BEFORE INSERT ON proposal
    FOR EACH ROW EXECUTE FUNCTION ops_kill_level_guard('3');

CREATE FUNCTION ops_session_stepped_up(p_user text, p_session text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT EXISTS (
        SELECT 1 FROM session s
        WHERE s.token_hash = p_session AND s.user_id = p_user AND s.expires_at > now()
          AND s.step_up_at IS NOT NULL AND s.step_up_at > now() - interval '5 minutes'
    )
$$;

CREATE FUNCTION ops_signal_floor() RETURNS integer
LANGUAGE sql STABLE AS $$
    SELECT coalesce(max(ops_mode_rank(floor_mode)), 0) FROM ops_signal WHERE active
$$;

CREATE FUNCTION ops_kill_trigger(p_user text, p_level text, p_reason text, p_at timestamptz) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    c control_state%ROWTYPE;
    new_mode text;
    approvals jsonb := '[]'::jsonb;
    tokens jsonb := '[]'::jsonb;
    runs jsonb := '[]'::jsonb;
    restores jsonb;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM app_user u
        WHERE u.user_id = p_user AND u.roles && ARRAY(SELECT role FROM ops_kill_role)
    ) THEN
        RAISE EXCEPTION 'user % may not trigger the kill switch', p_user USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF char_length(btrim(coalesce(p_reason, ''))) < 3 THEN
        RAISE EXCEPTION 'a kill switch trigger needs a reason' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    SELECT * INTO c FROM control_state WHERE id = 1 FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'the control row is missing' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF ops_kill_rank(p_level) <= ops_kill_rank(c.kill_level) THEN
        RAISE EXCEPTION 'trigger to % from %: only a higher level', p_level, c.kill_level
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    WITH x AS (
        UPDATE ops_kill_restore SET state = 'cancelled' WHERE state = 'pending' RETURNING restore_id
    ) SELECT coalesce(jsonb_agg(restore_id), '[]'::jsonb) INTO restores FROM x;
    IF c.kill_level = 'K0' THEN
        WITH x AS (
            UPDATE approval a SET voided_at = p_at FROM proposal p
            WHERE a.proposal_id = p.proposal_id AND a.voided_at IS NULL
              AND p.state IN ('proposed', 'in_review', 'approved', 'escalated')
            RETURNING a.approval_id
        ) SELECT coalesce(jsonb_agg(approval_id ORDER BY approval_id), '[]'::jsonb) INTO approvals FROM x;
        WITH x AS (
            INSERT INTO ops_voided_token (token_id, voided_at, reason)
            SELECT t.token_id, p_at, 'kill switch ' || p_level FROM execution_token t WHERE t.burned_at IS NULL
            ON CONFLICT (token_id) DO NOTHING RETURNING token_id
        ) SELECT coalesce(jsonb_agg(token_id::text ORDER BY token_id), '[]'::jsonb) INTO tokens FROM x;
    END IF;
    IF ops_kill_rank(p_level) >= 2 THEN
        WITH x AS (
            UPDATE agent_run SET status = 'cancelled', ended_at = p_at
            WHERE status IN ('running', 'paused') RETURNING run_id
        ) SELECT coalesce(jsonb_agg(run_id ORDER BY run_id), '[]'::jsonb) INTO runs FROM x;
    END IF;
    new_mode := 'M' || greatest(ops_mode_rank(c.degraded_mode), ops_kill_mode_floor(p_level), ops_signal_floor());
    UPDATE control_state SET kill_level = p_level, degraded_mode = new_mode, updated_by = ARRAY[p_user],
        updated_at = p_at WHERE id = 1;
    RETURN jsonb_build_object(
        'from', c.kill_level, 'to', p_level, 'mode_from', c.degraded_mode, 'mode_to', new_mode,
        'voided_approvals', approvals, 'voided_tokens', tokens, 'cancelled_agent_runs', runs,
        'cancelled_restores', restores
    );
END
$$;

CREATE FUNCTION ops_restore_expire() RETURNS SETOF text
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    UPDATE ops_kill_restore SET state = 'expired' WHERE state = 'pending' AND expires_at <= now()
    RETURNING restore_id
$$;

CREATE FUNCTION ops_restore_request(
    p_user text, p_session text, p_id text, p_to text, p_reason text, p_checklist jsonb
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    IF NOT ops_session_stepped_up(p_user, p_session) THEN
        RAISE EXCEPTION 'a restore signature needs a live stepped-up session of %', p_user
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    INSERT INTO ops_kill_restore (restore_id, from_level, to_level, reason, checklist, requested_by,
        requested_function, requested_at, expires_at)
    SELECT p_id, c.kill_level, p_to, p_reason, p_checklist, p_user, 'command', now(), now() + interval '15 minutes'
    FROM control_state c WHERE c.id = 1;
END
$$;

CREATE FUNCTION ops_restore_complete(p_user text, p_session text, p_id text, p_at timestamptz) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    c control_state%ROWTYPE;
    r ops_kill_restore%ROWTYPE;
    new_mode text;
BEGIN
    IF NOT ops_session_stepped_up(p_user, p_session) THEN
        RAISE EXCEPTION 'a restore signature needs a live stepped-up session of %', p_user
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT * INTO c FROM control_state WHERE id = 1 FOR UPDATE;
    UPDATE ops_kill_restore SET state = 'completed', cosigned_by = p_user
    WHERE restore_id = p_id AND state = 'pending' RETURNING * INTO r;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'no pending restore %', p_id USING ERRCODE = 'insufficient_privilege';
    END IF;
    new_mode := 'M' || greatest(ops_kill_mode_floor(r.to_level), ops_signal_floor());
    UPDATE control_state SET kill_level = r.to_level, degraded_mode = new_mode,
        updated_by = ARRAY[r.requested_by, p_user], updated_at = p_at WHERE id = 1;
    RETURN jsonb_build_object(
        'from', r.from_level, 'to', r.to_level, 'mode_from', c.degraded_mode, 'mode_to', new_mode,
        'requested_by', r.requested_by, 'requested_function', r.requested_function,
        'cosigned_by', r.cosigned_by, 'cosigned_function', r.cosigned_function
    );
END
$$;

CREATE FUNCTION ops_set_mode(p_actor text, p_mode text, p_at timestamptz) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    previous text;
BEGIN
    SELECT degraded_mode INTO previous FROM control_state WHERE id = 1 FOR UPDATE;
    IF previous IS DISTINCT FROM p_mode THEN
        UPDATE control_state SET degraded_mode = p_mode, updated_by = ARRAY[p_actor], updated_at = p_at
        WHERE id = 1;
    END IF;
    RETURN previous;
END
$$;

REVOKE ALL ON FUNCTION ops_kill_trigger(text, text, text, timestamptz), ops_restore_expire(),
    ops_restore_request(text, text, text, text, text, jsonb), ops_restore_complete(text, text, text, timestamptz),
    ops_set_mode(text, text, timestamptz), ops_session_stepped_up(text, text) FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sgw_app') THEN
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON control_state, ops_kill_role, ops_kill_restore, ops_voided_token
            FROM sgw_app;
        GRANT INSERT (id), UPDATE (scenario_clock, scenario_mode) ON control_state TO sgw_app;
        GRANT EXECUTE ON FUNCTION ops_kill_trigger(text, text, text, timestamptz), ops_restore_expire(),
            ops_restore_request(text, text, text, text, text, jsonb),
            ops_restore_complete(text, text, text, timestamptz), ops_set_mode(text, text, timestamptz),
            ops_session_stepped_up(text, text) TO sgw_app;
    END IF;
END
$$;
