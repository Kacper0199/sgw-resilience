-- Security fix H2 (audit of main aa6fd39): 4501 only checked that some burned token existed for the
-- proposal, so one burned token allowed many effect rows. An effect now names the token it spends: a unique
-- `token_id` with a foreign key to execution_token; the trigger requires that token to be burned and to
-- belong to the effect's proposal. Existing effects are backfilled from their proposal's token.

ALTER TABLE effect ADD COLUMN token_id uuid REFERENCES execution_token (token_id);

UPDATE effect e SET token_id = t.token_id
FROM execution_token t
WHERE t.proposal_id = e.proposal_id AND t.burned_at IS NOT NULL AND e.token_id IS NULL;

ALTER TABLE effect ADD CONSTRAINT effect_token_id_key UNIQUE (token_id);

CREATE OR REPLACE FUNCTION effect_enforce() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.proposal_id <> OLD.proposal_id OR NEW.token_id IS DISTINCT FROM OLD.token_id THEN
            RAISE EXCEPTION 'an effect keeps its proposal and token' USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.token_id IS NULL OR NOT EXISTS (
        SELECT 1 FROM execution_token t
        WHERE t.token_id = NEW.token_id AND t.proposal_id = NEW.proposal_id AND t.burned_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'effect for proposal % needs its own burned execution token', NEW.proposal_id
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END
$$;
