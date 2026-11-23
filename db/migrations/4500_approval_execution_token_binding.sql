-- WP-09a: the execution token is bound to proposal_version + action_hash and is single-use, enforced in the
-- database as well as in the service (defence in depth, PA DC-09 (6)). A token can only exist for an
-- approved proposal whose current version carries an approval for every required function, each by a
-- different person who is not the proposer; it can only gain burned_at, once, while the proposal still
-- has that version and hash. SQLSTATE 42501 maps to HTTP 403, 09000 (stale version or hash) to 412.

ALTER TABLE execution_token ADD COLUMN proposal_version integer NOT NULL CHECK (proposal_version >= 1);

CREATE FUNCTION execution_token_enforce() RETURNS trigger
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

CREATE TRIGGER execution_token_enforce_write
    BEFORE INSERT OR UPDATE ON execution_token
    FOR EACH ROW EXECUTE FUNCTION execution_token_enforce();
