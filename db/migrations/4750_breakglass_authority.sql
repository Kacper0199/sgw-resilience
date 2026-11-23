-- WP-09b: break-glass is a second, explicit path to an execution token (PLAN section 2: IC alone, mandatory
-- reason, co-sign by the second function within 24 h, auto-flag in after-action). The 4500 token trigger is
-- replaced, not bypassed: a token is issued for an approved proposal whose current version and hash carry
-- either an approval from every required function by distinct non-proposers, or a break-glass row bound to
-- that same version and hash. Break-glass rows are evidence: one per proposal version, opened only while
-- the proposal is undecided and unexpired (and was not proposed by the IC), never deleted, and they only gain a co-signature (by a holder of a second required
-- function who is neither the IC nor the proposer). SQLSTATE 42501 -> 403, 09000 -> 412.

CREATE OR REPLACE FUNCTION execution_token_enforce() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    p proposal%ROWTYPE;
    signed integer;
    signers integer;
BEGIN
    SELECT * INTO p FROM proposal WHERE proposal_id = NEW.proposal_id FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'token for unknown proposal %', NEW.proposal_id USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF NEW.proposal_version <> p.proposal_version OR NEW.action_hash <> p.action_hash THEN
        RAISE EXCEPTION 'token for proposal % is not bound to its current version and hash', p.proposal_id
            USING ERRCODE = 'triggered_action_exception';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF NEW.token_id <> OLD.token_id OR NEW.proposal_id <> OLD.proposal_id
           OR NEW.proposal_version <> OLD.proposal_version OR NEW.action_hash <> OLD.action_hash
           OR NEW.expires_at <> OLD.expires_at OR OLD.burned_at IS NOT NULL OR NEW.burned_at IS NULL THEN
            RAISE EXCEPTION 'execution tokens only gain burned_at, once' USING ERRCODE = 'insufficient_privilege';
        END IF;
        IF p.state <> 'approved' THEN
            RAISE EXCEPTION 'proposal % is %, not approved', p.proposal_id, p.state
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.burned_at IS NOT NULL THEN
        RAISE EXCEPTION 'a token is issued unburned' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p.state <> 'approved' THEN
        RAISE EXCEPTION 'proposal % is %, not approved', p.proposal_id, p.state
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF EXISTS (
        SELECT 1 FROM break_glass b
        WHERE b.proposal_id = p.proposal_id AND b.proposal_version = p.proposal_version
          AND b.action_hash = p.action_hash
    ) THEN
        RETURN NEW;
    END IF;
    SELECT count(DISTINCT a.function), count(DISTINCT a.approver_id) INTO signed, signers
    FROM approval a
    WHERE a.proposal_id = p.proposal_id AND a.proposal_version = p.proposal_version
      AND a.action_hash = p.action_hash AND a.decision = 'approve' AND a.voided_at IS NULL
      AND a.approver_id <> p.proposed_by AND a.function = ANY (p.required_functions);
    IF signed <> cardinality(p.required_functions) OR signers < cardinality(p.required_functions) THEN
        RAISE EXCEPTION 'proposal % lacks an approval from every required function by distinct people',
            p.proposal_id USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END
$$;

CREATE UNIQUE INDEX break_glass_one_per_version ON break_glass (proposal_id, proposal_version);

CREATE OR REPLACE FUNCTION break_glass_enforce() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    p proposal%ROWTYPE;
    ic app_user%ROWTYPE;
    co app_user%ROWTYPE;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'break-glass rows are evidence and are never deleted' USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT * INTO p FROM proposal WHERE proposal_id = NEW.proposal_id FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'break-glass for unknown proposal %', NEW.proposal_id USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF p.tier <> 'T3' THEN
            RAISE EXCEPTION 'break-glass applies to T3 only' USING ERRCODE = 'insufficient_privilege';
        END IF;
        IF NEW.proposal_version <> p.proposal_version OR NEW.action_hash <> p.action_hash THEN
            RAISE EXCEPTION 'stale break-glass for proposal %', p.proposal_id USING ERRCODE = 'triggered_action_exception';
        END IF;
        IF p.state IN ('approved', 'rejected', 'withdrawn', 'expired', 'executed') THEN
            RAISE EXCEPTION 'proposal % is %; break-glass needs an undecided proposal', p.proposal_id, p.state
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        IF p.expires_at IS NOT NULL AND NEW.used_at >= p.expires_at THEN
            RAISE EXCEPTION 'proposal % expired at %; break-glass cannot open it', p.proposal_id, p.expires_at
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        IF NEW.ic_id = p.proposed_by THEN
            RAISE EXCEPTION 'the IC cannot break-glass their own proposal' USING ERRCODE = 'insufficient_privilege';
        END IF;
        SELECT * INTO ic FROM app_user WHERE user_id = NEW.ic_id;
        IF NOT FOUND OR NOT ic.break_glass_eligible OR NOT ('command' = ANY (ic.functions)) THEN
            RAISE EXCEPTION 'user % is not break-glass eligible', NEW.ic_id USING ERRCODE = 'insufficient_privilege';
        END IF;
        IF NEW.cosigned_by IS NOT NULL OR NEW.cosigned_at IS NOT NULL OR NOT NEW.flagged THEN
            RAISE EXCEPTION 'break-glass opens unsigned and flagged for after-action'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.proposal_id <> OLD.proposal_id OR NEW.ic_id <> OLD.ic_id OR NEW.reason <> OLD.reason
       OR NEW.used_at <> OLD.used_at OR NEW.proposal_version <> OLD.proposal_version
       OR NEW.action_hash <> OLD.action_hash OR NEW.cosign_due <> OLD.cosign_due
       OR NEW.flagged <> OLD.flagged OR OLD.cosigned_by IS NOT NULL
       OR NEW.cosigned_by IS NULL OR NEW.cosigned_at IS NULL THEN
        RAISE EXCEPTION 'break-glass rows only gain a co-signature, once' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.cosigned_at < NEW.used_at THEN
        RAISE EXCEPTION 'a co-signature cannot precede the break-glass' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.cosigned_by = p.proposed_by THEN
        RAISE EXCEPTION 'the proposer cannot co-sign a break-glass on their own proposal'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT * INTO co FROM app_user WHERE user_id = NEW.cosigned_by;
    IF NOT FOUND OR NOT co.can_approve OR NOT EXISTS (
        SELECT 1 FROM unnest(p.required_functions) f
        WHERE f <> 'command' AND f = ANY (co.functions)
    ) THEN
        RAISE EXCEPTION 'co-signer % does not hold the second required function', NEW.cosigned_by
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END
$$;

DROP TRIGGER break_glass_enforce_write ON break_glass;
CREATE TRIGGER break_glass_enforce_write
    BEFORE INSERT OR UPDATE OR DELETE ON break_glass
    FOR EACH ROW EXECUTE FUNCTION break_glass_enforce();

CREATE TRIGGER break_glass_no_truncate
    BEFORE TRUNCATE ON break_glass
    FOR EACH STATEMENT EXECUTE FUNCTION audit_event_reject_change();

-- An approved envelope is immutable; it exists only for an approved (or executed) T3 proposal and expires
-- with `valid_until`. A changed plan is a new proposal (outside bounds T3, O-04).
CREATE FUNCTION envelope_enforce() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    p proposal%ROWTYPE;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'an approved envelope is immutable (% rejected)', TG_OP USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT * INTO p FROM proposal WHERE proposal_id = NEW.proposal_id FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'envelope for unknown proposal %', NEW.proposal_id USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF p.tier <> 'T3' OR p.state NOT IN ('approved', 'executed') THEN
        RAISE EXCEPTION 'an envelope needs an approved T3 proposal (% is % %)', p.proposal_id, p.tier, p.state
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF jsonb_typeof(NEW.bounds) <> 'object' OR NEW.bounds = '{}'::jsonb THEN
        RAISE EXCEPTION 'envelope bounds must be a non-empty object' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER envelope_enforce_write
    BEFORE INSERT OR UPDATE OR DELETE ON envelope
    FOR EACH ROW EXECUTE FUNCTION envelope_enforce();

CREATE TRIGGER envelope_no_truncate
    BEFORE TRUNCATE ON envelope
    FOR EACH STATEMENT EXECUTE FUNCTION audit_event_reject_change();
