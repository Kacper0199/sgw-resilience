-- Security fix H1 (audit of main aa6fd39): the runtime role could rewrite authority rows (0010 grants
-- UPDATE/DELETE on every table): lower a proposal's tier, empty its required functions, flip it to approved,
-- edit an approval's decision, make a user an approver, delete a burned token and reissue one.
--
-- 1. The runtime role (sgw_app, hence sgw_runtime) loses UPDATE/DELETE/TRUNCATE on every authority table and
--    INSERT on app_user. It keeps INSERT where a trigger already decides (proposal, approval,
--    execution_token, break_glass, envelope, effect, proposal_delta) and UPDATE (updated_at) on proposal,
--    which row locks (FOR UPDATE / FOR SHARE) need.
-- 2. The legitimate writes go through SECURITY DEFINER functions owned by the migration owner, each with
--    argument checks: set state, revise material, rationale, expiry, void, withdraw a signature, drop an
--    unburned token, burn a token, co-sign a break-glass.
-- 3. A BEFORE INSERT OR UPDATE trigger on proposal re-derives the tier and the required functions from
--    `authority_rule` (the K8 tier table as data: one row per action type, so a new action type needs one
--    row), refuses lowering, keeps identity columns fixed, ties material changes to a version bump and
--    checks authority for `approved` (signatures or a bound break-glass) and `executed` (a burned token).
--    It applies to every role, including the definer functions above.
-- 4. Approval rows can only gain a void mark.
-- SQLSTATE 42501 -> 403, 09000 -> 412.

CREATE TABLE authority_rule (
    action_type         text PRIMARY KEY,
    tier                sgw_tier NOT NULL,
    approver_functions  text[] NOT NULL DEFAULT '{}',
    escalated_functions text[] NOT NULL DEFAULT '{}',
    CHECK (tier NOT IN ('T2', 'T3') OR cardinality(approver_functions) >= 1),
    CHECK (cardinality(escalated_functions) = 0 OR (tier = 'T2' AND cardinality(escalated_functions) = 2))
);

INSERT INTO authority_rule (action_type, tier, approver_functions, escalated_functions) VALUES
    ('set_event_type', 'T2', '{command}', '{command,operations}'),
    ('preposition_crews', 'T3', '{command,logistics}', '{}'),
    ('mutual_aid_request', 'T3', '{command,logistics}', '{}'),
    ('reoptimise_within_envelope', 'T1', '{}', '{}'),
    ('stage_crews_small', 'T2', '{operations}', '{command,logistics}'),
    ('cross_domain_priority', 'T3', '{command,water_operations}', '{}'),
    ('boil_water_notice', 'T3', '{water_operations,compliance}', '{}'),
    ('publish_global_etr', 'T3', '{command,operations}', '{}'),
    ('work_order_draft', 'T1', '{}', '{}'),
    ('sitrep_draft', 'T1', '{}', '{}');

CREATE FUNCTION authority_tier_rank(t text) RETURNS integer
LANGUAGE sql IMMUTABLE AS $$
    SELECT array_position(ARRAY['T0', 'T1', 'T2', 'T3', 'T4'], t)
$$;

CREATE FUNCTION authority_sorted(a text[]) RETURNS text[]
LANGUAGE sql IMMUTABLE AS $$
    SELECT coalesce(array_agg(DISTINCT x ORDER BY x), '{}') FROM unnest(a) AS x
$$;

-- NULL when (action, tier, functions) is derivable from the rule, else the reason.
CREATE FUNCTION authority_tier_problem(p_action text, p_tier text, p_functions text[]) RETURNS text
LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public AS $$
DECLARE
    r authority_rule%ROWTYPE;
    want text[];
BEGIN
    IF cardinality(p_functions) <> cardinality(authority_sorted(p_functions)) THEN
        RETURN NULL;  -- duplicated functions: the table CHECKs refuse T3, and a T2 row can never be signed
    END IF;
    SELECT * INTO r FROM authority_rule WHERE action_type = p_action;
    IF NOT FOUND THEN
        RETURN format('no authority rule for action type %s', p_action);
    END IF;
    IF authority_tier_rank(p_tier) < authority_tier_rank(r.tier) THEN
        RETURN format('%s is %s by the tier table; %s is lower', p_action, r.tier, p_tier);
    END IF;
    IF p_tier = r.tier THEN
        want := r.approver_functions;
    ELSIF p_tier = 'T3' AND r.tier = 'T2' THEN
        want := r.escalated_functions;
    ELSE
        RETURN format('%s cannot be %s (rule tier %s)', p_action, p_tier, r.tier);
    END IF;
    IF authority_sorted(p_functions) <> authority_sorted(want) THEN
        RETURN format('%s at %s needs functions %s', p_action, p_tier, want);
    END IF;
    RETURN NULL;
END
$$;

CREATE FUNCTION authority_signed(p proposal) RETURNS boolean
LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $$
    SELECT (
        SELECT count(DISTINCT a.function) FROM approval a
        WHERE a.proposal_id = p.proposal_id AND a.proposal_version = p.proposal_version
          AND a.action_hash = p.action_hash AND a.decision = 'approve' AND a.voided_at IS NULL
          AND a.approver_id <> p.proposed_by AND a.function = ANY (p.required_functions)
    ) = cardinality(p.required_functions)
    AND (
        SELECT count(DISTINCT a.approver_id) FROM approval a
        WHERE a.proposal_id = p.proposal_id AND a.proposal_version = p.proposal_version
          AND a.action_hash = p.action_hash AND a.decision = 'approve' AND a.voided_at IS NULL
          AND a.approver_id <> p.proposed_by AND a.function = ANY (p.required_functions)
    ) >= cardinality(p.required_functions)
    OR EXISTS (
        SELECT 1 FROM break_glass b
        WHERE b.proposal_id = p.proposal_id AND b.proposal_version = p.proposal_version
          AND b.action_hash = p.action_hash
    )
$$;

CREATE FUNCTION proposal_authority_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
    problem text;
    material boolean;
BEGIN
    problem := authority_tier_problem(NEW.action_type, NEW.tier, NEW.required_functions::text[]);
    IF problem IS NOT NULL THEN
        RAISE EXCEPTION 'proposal %: %', NEW.proposal_id, problem USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.state NOT IN ('draft', 'proposed') THEN
            RAISE EXCEPTION 'a proposal starts as draft or proposed, not %', NEW.state
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.proposal_id <> OLD.proposal_id OR NEW.decision_case_id <> OLD.decision_case_id
       OR NEW.incident_id <> OLD.incident_id OR NEW.action_type <> OLD.action_type
       OR NEW.proposed_by <> OLD.proposed_by OR NEW.initiator_kind <> OLD.initiator_kind
       OR NEW.run_id IS DISTINCT FROM OLD.run_id OR NEW.created_at <> OLD.created_at
       OR NEW.region_id <> OLD.region_id OR NEW.domain <> OLD.domain THEN
        RAISE EXCEPTION 'proposal % identity fields are fixed', OLD.proposal_id USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF authority_tier_rank(NEW.tier) < authority_tier_rank(OLD.tier) THEN
        RAISE EXCEPTION 'proposal % tier cannot drop from % to %', OLD.proposal_id, OLD.tier, NEW.tier
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF OLD.state IN ('rejected', 'withdrawn', 'expired', 'executed') AND (
        NEW.state <> OLD.state OR NEW.proposal_version <> OLD.proposal_version
        OR NEW.action_hash <> OLD.action_hash) THEN
        RAISE EXCEPTION 'proposal % is % and final', OLD.proposal_id, OLD.state USING ERRCODE = 'insufficient_privilege';
    END IF;
    material := NEW.params IS DISTINCT FROM OLD.params OR NEW.targets IS DISTINCT FROM OLD.targets
        OR NEW.risk_band <> OLD.risk_band OR NEW.preconditions IS DISTINCT FROM OLD.preconditions
        OR NEW.tier <> OLD.tier OR NEW.required_functions IS DISTINCT FROM OLD.required_functions
        OR NEW.escalators IS DISTINCT FROM OLD.escalators OR NEW.action_hash <> OLD.action_hash
        OR NEW.policy_version <> OLD.policy_version;
    IF NEW.proposal_version NOT IN (OLD.proposal_version, OLD.proposal_version + 1) THEN
        RAISE EXCEPTION 'proposal % version moves by one at most', OLD.proposal_id USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF material AND (NEW.proposal_version <> OLD.proposal_version + 1 OR NEW.action_hash = OLD.action_hash) THEN
        RAISE EXCEPTION 'a material change of % needs a new version and action hash', OLD.proposal_id
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.proposal_version <> OLD.proposal_version AND NEW.state NOT IN ('draft', 'proposed') THEN
        RAISE EXCEPTION 'a new version of % starts as draft or proposed', OLD.proposal_id
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.state = 'approved' AND OLD.state <> 'approved' AND NOT authority_signed(NEW) THEN
        RAISE EXCEPTION 'proposal % lacks the signatures (or a bound break-glass) to be approved', OLD.proposal_id
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.state = 'executed' AND OLD.state <> 'executed' AND (OLD.state <> 'approved' OR NOT EXISTS (
        SELECT 1 FROM execution_token t
        WHERE t.proposal_id = NEW.proposal_id AND t.proposal_version = NEW.proposal_version
          AND t.action_hash = NEW.action_hash AND t.burned_at IS NOT NULL)) THEN
        RAISE EXCEPTION 'proposal % is executed only from approved with a burned token', OLD.proposal_id
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER proposal_authority_guard_write
    BEFORE INSERT OR UPDATE ON proposal
    FOR EACH ROW EXECUTE FUNCTION proposal_authority_guard();

CREATE FUNCTION approval_change_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF (to_jsonb(NEW) - 'voided_at' - 'voided_by_version') <> (to_jsonb(OLD) - 'voided_at' - 'voided_by_version')
       OR OLD.voided_at IS NOT NULL OR NEW.voided_at IS NULL THEN
        RAISE EXCEPTION 'approval rows only gain a void mark, once' USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER approval_change_guard_update
    BEFORE UPDATE ON approval
    FOR EACH ROW EXECUTE FUNCTION approval_change_guard();

-- ---- the legitimate writes ------------------------------------------------------------------------------

CREATE FUNCTION authority_set_state(p_id text, p_state text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    IF p_state IS NULL OR p_state NOT IN ('proposed', 'in_review', 'approved', 'rejected', 'withdrawn',
                                          'expired', 'escalated', 'executed') THEN
        RAISE EXCEPTION 'state % cannot be set', p_state USING ERRCODE = 'invalid_parameter_value';
    END IF;
    UPDATE proposal SET state = p_state, updated_at = now() WHERE proposal_id = p_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'proposal % not found', p_id USING ERRCODE = 'no_data_found';
    END IF;
END
$$;

CREATE FUNCTION authority_revise(p_id text, p_expected_version integer, p jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    r proposal;
BEGIN
    r := jsonb_populate_record(NULL::proposal, p);
    IF r.proposal_version IS DISTINCT FROM p_expected_version + 1 THEN
        RAISE EXCEPTION 'a revision of % moves to version %', p_id, p_expected_version + 1
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    UPDATE proposal SET params = r.params, targets = r.targets, risk_band = r.risk_band,
        preconditions = r.preconditions, tier = r.tier, required_functions = r.required_functions,
        escalators = r.escalators, state = r.state, proposal_version = r.proposal_version,
        action_hash = r.action_hash, policy_version = r.policy_version, evidence_ids = r.evidence_ids,
        rationale = r.rationale, expires_at = r.expires_at, updated_at = now()
    WHERE proposal_id = p_id AND proposal_version = p_expected_version;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'proposal % is not at version %', p_id, p_expected_version
            USING ERRCODE = 'triggered_action_exception';
    END IF;
END
$$;

CREATE FUNCTION authority_set_rationale(p_id text, p_rationale text) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    UPDATE proposal SET rationale = coalesce(p_rationale, ''), updated_at = now() WHERE proposal_id = p_id
$$;

CREATE FUNCTION authority_expire_due(p_now timestamptz) RETURNS SETOF text
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    UPDATE proposal SET state = 'expired', updated_at = now()
    WHERE state IN ('proposed', 'in_review') AND expires_at IS NOT NULL AND expires_at <= p_now
    RETURNING proposal_id
$$;

CREATE FUNCTION authority_void_approvals(p_id text, p_new_version integer) RETURNS SETOF text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM proposal WHERE proposal_id = p_id AND proposal_version = p_new_version) THEN
        RAISE EXCEPTION 'approvals of % are voided only by its current version', p_id
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN QUERY
        UPDATE approval SET voided_at = now(), voided_by_version = p_new_version
        WHERE proposal_id = p_id AND voided_at IS NULL AND proposal_version < p_new_version
        RETURNING approval_id;
END
$$;

CREATE FUNCTION authority_withdraw_approval(p_approval_id text, p_approver text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    DELETE FROM approval a USING proposal p
    WHERE a.approval_id = p_approval_id AND a.approver_id = p_approver AND a.decision = 'approve'
      AND a.voided_at IS NULL AND p.proposal_id = a.proposal_id AND p.proposal_version = a.proposal_version
      AND p.action_hash = a.action_hash AND p.state IN ('proposed', 'in_review');
    IF NOT FOUND THEN
        RAISE EXCEPTION 'approval % is not a live signature of % on an open proposal', p_approval_id, p_approver
            USING ERRCODE = 'insufficient_privilege';
    END IF;
END
$$;

CREATE FUNCTION authority_drop_unburned_token(p_id text) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    DELETE FROM execution_token WHERE proposal_id = p_id AND burned_at IS NULL
$$;

CREATE FUNCTION authority_burn_token(
    p_token uuid, p_id text, p_version integer, p_hash text, p_now timestamptz
) RETURNS text
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    UPDATE execution_token t SET burned_at = p_now
    FROM proposal p
    WHERE t.token_id = p_token AND t.proposal_id = p_id AND t.burned_at IS NULL AND t.expires_at > p_now
      AND p.proposal_id = t.proposal_id AND p.state = 'approved' AND p.proposal_version = p_version
      AND p.action_hash = p_hash AND t.action_hash = p.action_hash AND t.proposal_version = p.proposal_version
      AND authority_signed(p)
    RETURNING t.token_id::text
$$;

CREATE FUNCTION authority_cosign_break_glass(p_break_glass_id bigint, p_user text, p_at timestamptz)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    UPDATE break_glass SET cosigned_by = p_user, cosigned_at = p_at
    WHERE break_glass_id = p_break_glass_id AND cosigned_by IS NULL;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'break-glass % is unknown or already co-signed', p_break_glass_id
            USING ERRCODE = 'insufficient_privilege';
    END IF;
END
$$;

REVOKE ALL ON FUNCTION authority_set_state(text, text), authority_revise(text, integer, jsonb),
    authority_set_rationale(text, text), authority_expire_due(timestamptz),
    authority_void_approvals(text, integer), authority_withdraw_approval(text, text),
    authority_drop_unburned_token(text), authority_burn_token(uuid, text, integer, text, timestamptz),
    authority_cosign_break_glass(bigint, text, timestamptz) FROM PUBLIC;

REVOKE ALL ON authority_rule FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sgw_app') THEN
        REVOKE UPDATE, DELETE, TRUNCATE ON proposal, proposal_delta, approval, execution_token, effect,
            break_glass, envelope, app_user, authority_rule FROM sgw_app;
        REVOKE INSERT ON app_user, authority_rule FROM sgw_app;
        GRANT SELECT ON authority_rule TO sgw_app;
        GRANT UPDATE (updated_at) ON proposal TO sgw_app;
        GRANT EXECUTE ON FUNCTION authority_set_state(text, text), authority_revise(text, integer, jsonb),
            authority_set_rationale(text, text), authority_expire_due(timestamptz),
            authority_void_approvals(text, integer), authority_withdraw_approval(text, text),
            authority_drop_unburned_token(text), authority_burn_token(uuid, text, integer, text, timestamptz),
            authority_cosign_break_glass(bigint, text, timestamptz) TO sgw_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sgw_readonly') THEN
        GRANT SELECT ON authority_rule TO sgw_readonly;
    END IF;
END
$$;
