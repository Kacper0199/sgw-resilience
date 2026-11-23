-- WP-09a: an effect (the executed side of a proposal) exists only after its execution token was burned,
-- so nothing can be queued for execution without the approved, version-bound, single-use token (4500).

CREATE FUNCTION effect_enforce() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM execution_token t
        WHERE t.proposal_id = NEW.proposal_id AND t.burned_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'effect for proposal % without a burned execution token', NEW.proposal_id
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.proposal_id <> OLD.proposal_id THEN
        RAISE EXCEPTION 'an effect cannot move to another proposal' USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER effect_enforce_write
    BEFORE INSERT OR UPDATE ON effect
    FOR EACH ROW EXECUTE FUNCTION effect_enforce();
