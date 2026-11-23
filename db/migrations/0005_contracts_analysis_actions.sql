-- K1 analysis and action tables, with K16 clock fields, envelope and break-glass (O-03, O-04).

CREATE TABLE snapshot (
    snapshot_id    text PRIMARY KEY,
    kind           text NOT NULL,
    as_of          timestamptz NOT NULL,
    engine_version text NOT NULL,
    hash           text NOT NULL CHECK (hash ~ '^[0-9a-f]{64}$'),
    output         jsonb NOT NULL
);

CREATE TABLE snapshot_input (
    snapshot_id text NOT NULL REFERENCES snapshot (snapshot_id),
    event_id    uuid NOT NULL REFERENCES event (event_id),
    PRIMARY KEY (snapshot_id, event_id)
);

CREATE TABLE risk (
    snapshot_id     text NOT NULL REFERENCES snapshot (snapshot_id),
    entity_id       text NOT NULL,
    level           text NOT NULL CHECK (level IN ('county', 'h3', 'asset')),
    region_id       text,
    domain          sgw_domain,
    p_ppm           integer NOT NULL CHECK (p_ppm BETWEEN 0 AND 1000000),
    band            sgw_risk_band NOT NULL,
    expected_impact integer NOT NULL DEFAULT 0 CHECK (expected_impact >= 0),
    attribution     jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (snapshot_id, entity_id)
);

CREATE TABLE anomaly (
    anomaly_id    text PRIMARY KEY,
    entity_id     text NOT NULL,
    region_id     text,
    domain        sgw_domain,
    detected_at   timestamptz NOT NULL,
    score_ppm     integer NOT NULL CHECK (score_ppm BETWEEN 0 AND 1000000),
    anomaly_class text NOT NULL,
    status        text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'acknowledged', 'dismissed'))
);

CREATE TABLE decision_case (
    decision_case_id        text PRIMARY KEY,
    step                    sgw_decision_step NOT NULL,
    title                   text NOT NULL,
    region_id               text NOT NULL,
    domain                  sgw_domain NOT NULL,
    clock_kind              sgw_clock_kind NOT NULL,
    consequence_utc         timestamptz NOT NULL,
    consequence_p10_utc     timestamptz NOT NULL,
    consequence_p90_utc     timestamptz NOT NULL,
    consequence_basis       jsonb NOT NULL,
    action_lead_time_min    integer NOT NULL CHECK (action_lead_time_min >= 0),
    lead_time_basis         jsonb NOT NULL,
    decide_by_utc           timestamptz NOT NULL,
    decide_by_p10_utc       timestamptz NOT NULL,
    decide_by_p90_utc       timestamptz NOT NULL,
    effective_decide_by_utc timestamptz NOT NULL,
    on_critical_path        boolean NOT NULL DEFAULT false,
    no_regret_share_ppm     integer CHECK (no_regret_share_ppm BETWEEN 0 AND 1000000),
    no_regret_verdict       sgw_no_regret_verdict NOT NULL DEFAULT 'n/a',
    next_advisory_utc       timestamptz,
    if_late                 text NOT NULL,
    snapshot_id             text REFERENCES snapshot (snapshot_id),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    CHECK (consequence_p10_utc <= consequence_utc AND consequence_utc <= consequence_p90_utc),
    CHECK (decide_by_p10_utc <= decide_by_utc AND decide_by_utc <= decide_by_p90_utc),
    CHECK (decide_by_utc = consequence_utc - make_interval(mins => action_lead_time_min)),
    CHECK (effective_decide_by_utc <= decide_by_utc),
    CHECK (no_regret_verdict = 'n/a' OR (no_regret_share_ppm IS NOT NULL AND next_advisory_utc IS NOT NULL))
);

CREATE TABLE proposal (
    proposal_id      text PRIMARY KEY,
    decision_case_id text NOT NULL REFERENCES decision_case (decision_case_id),
    incident_id      text NOT NULL,
    action_type      sgw_action_type NOT NULL,
    params           jsonb NOT NULL,
    targets          text[] NOT NULL,
    risk_band        sgw_risk_band NOT NULL,
    preconditions    jsonb NOT NULL DEFAULT '{}'::jsonb,
    tier             sgw_tier NOT NULL,
    required_functions sgw_approval_function[] NOT NULL DEFAULT '{}',
    escalators       text[] NOT NULL DEFAULT '{}',
    state            sgw_proposal_state NOT NULL DEFAULT 'draft',
    proposal_version integer NOT NULL DEFAULT 1 CHECK (proposal_version >= 1),
    action_hash      text NOT NULL CHECK (action_hash ~ '^[0-9a-f]{64}$'),
    policy_version   text NOT NULL,
    snapshot_id      text REFERENCES snapshot (snapshot_id),
    evidence_ids     text[] NOT NULL DEFAULT '{}',
    initiator_kind   sgw_initiator_kind NOT NULL,
    proposed_by      text NOT NULL,
    run_id           text,
    region_id        text NOT NULL,
    domain           sgw_domain NOT NULL,
    rationale        text NOT NULL DEFAULT '',
    expires_at       timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CHECK (tier NOT IN ('T2', 'T3') OR cardinality(required_functions) >= 1),
    CHECK (tier <> 'T3' OR (cardinality(required_functions) = 2
                            AND required_functions[1] IS DISTINCT FROM required_functions[2]))
);
CREATE INDEX proposal_state_idx ON proposal (state);
CREATE INDEX proposal_case_idx ON proposal (decision_case_id);

CREATE TABLE proposal_delta (
    proposal_id text NOT NULL REFERENCES proposal (proposal_id),
    version     integer NOT NULL,
    seq         integer NOT NULL,
    material    boolean NOT NULL,
    change      jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (proposal_id, version, seq)
);

CREATE TABLE approval (
    approval_id           text PRIMARY KEY,
    proposal_id           text NOT NULL REFERENCES proposal (proposal_id),
    proposal_version      integer NOT NULL,
    action_hash           text NOT NULL CHECK (action_hash ~ '^[0-9a-f]{64}$'),
    approver_id           text NOT NULL REFERENCES app_user (user_id),
    function              sgw_approval_function NOT NULL,
    decision              sgw_approval_decision NOT NULL,
    reason_code           text,
    note                  text,
    snapshot_id_seen      text,
    evidence_oldest_age_s integer CHECK (evidence_oldest_age_s >= 0),
    signature             text,
    voided_at             timestamptz,
    voided_by_version     integer,
    created_at            timestamptz NOT NULL DEFAULT now(),
    UNIQUE (proposal_id, proposal_version, function),
    UNIQUE (proposal_id, proposal_version, approver_id)
);

CREATE TABLE envelope (
    envelope_id text PRIMARY KEY,
    proposal_id text NOT NULL UNIQUE REFERENCES proposal (proposal_id),
    bounds      jsonb NOT NULL,
    valid_until timestamptz NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE break_glass (
    break_glass_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    proposal_id    text NOT NULL REFERENCES proposal (proposal_id),
    ic_id          text NOT NULL REFERENCES app_user (user_id),
    proposal_version integer NOT NULL,
    action_hash    text NOT NULL CHECK (action_hash ~ '^[0-9a-f]{64}$'),
    reason         text NOT NULL CHECK (char_length(btrim(reason)) >= 10),
    used_at        timestamptz NOT NULL,
    cosign_due     timestamptz NOT NULL,
    cosigned_by    text REFERENCES app_user (user_id),
    cosigned_at    timestamptz,
    flagged        boolean NOT NULL DEFAULT true,
    CHECK (cosign_due = used_at + interval '24 hours'),
    CHECK (cosigned_by IS NULL OR cosigned_by <> ic_id)
);

CREATE TABLE execution_token (
    token_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_id text NOT NULL UNIQUE REFERENCES proposal (proposal_id),
    action_hash text NOT NULL,
    expires_at  timestamptz NOT NULL,
    burned_at   timestamptz
);

CREATE TABLE effect (
    effect_id   text PRIMARY KEY,
    proposal_id text NOT NULL REFERENCES proposal (proposal_id),
    channel     text NOT NULL,
    state       sgw_effect_state NOT NULL DEFAULT 'queued',
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- "Authority is a DB row": approvals and break-glass are checked against the current proposal row and the
-- approver's seeded functions inside the database, whatever the API does. SQLSTATE 42501 maps to HTTP 403,
-- 09000 (stale version or hash) to HTTP 412.
CREATE FUNCTION approval_enforce() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    p proposal%ROWTYPE;
    u app_user%ROWTYPE;
BEGIN
    SELECT * INTO p FROM proposal WHERE proposal_id = NEW.proposal_id FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'approval for unknown proposal %', NEW.proposal_id USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF NEW.proposal_version <> p.proposal_version OR NEW.action_hash <> p.action_hash THEN
        RAISE EXCEPTION 'stale approval: proposal % is at version % with hash %', p.proposal_id,
            p.proposal_version, p.action_hash USING ERRCODE = 'triggered_action_exception';
    END IF;
    IF NEW.approver_id = p.proposed_by THEN
        RAISE EXCEPTION 'the proposer cannot approve their own proposal' USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT * INTO u FROM app_user WHERE user_id = NEW.approver_id;
    IF NOT FOUND OR NOT u.can_approve THEN
        RAISE EXCEPTION 'user % may not approve', NEW.approver_id USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NOT (NEW.function = ANY (u.functions)) THEN
        RAISE EXCEPTION 'user % does not hold function %', NEW.approver_id, NEW.function
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NOT (NEW.function = ANY (p.required_functions)) THEN
        RAISE EXCEPTION 'function % is not required for proposal %', NEW.function, p.proposal_id
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER approval_enforce_insert
    BEFORE INSERT ON approval
    FOR EACH ROW EXECUTE FUNCTION approval_enforce();

CREATE FUNCTION break_glass_enforce() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    p proposal%ROWTYPE;
    ic app_user%ROWTYPE;
    co app_user%ROWTYPE;
BEGIN
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
        SELECT * INTO ic FROM app_user WHERE user_id = NEW.ic_id;
        IF NOT FOUND OR NOT ic.break_glass_eligible OR NOT ('command' = ANY (ic.functions)) THEN
            RAISE EXCEPTION 'user % is not break-glass eligible', NEW.ic_id USING ERRCODE = 'insufficient_privilege';
        END IF;
    ELSE
        IF NEW.proposal_id <> OLD.proposal_id OR NEW.ic_id <> OLD.ic_id OR NEW.reason <> OLD.reason
           OR NEW.used_at <> OLD.used_at OR NEW.proposal_version <> OLD.proposal_version
           OR NEW.action_hash <> OLD.action_hash OR OLD.cosigned_by IS NOT NULL THEN
            RAISE EXCEPTION 'break-glass rows only gain a co-signature, once' USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    IF NEW.cosigned_by IS NOT NULL THEN
        SELECT * INTO co FROM app_user WHERE user_id = NEW.cosigned_by;
        IF NOT FOUND OR NOT co.can_approve OR NOT EXISTS (
            SELECT 1 FROM unnest(p.required_functions) f
            WHERE f <> 'command' AND f = ANY (co.functions)
        ) THEN
            RAISE EXCEPTION 'co-signer % does not hold the second required function', NEW.cosigned_by
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER break_glass_enforce_write
    BEFORE INSERT OR UPDATE ON break_glass
    FOR EACH ROW EXECUTE FUNCTION break_glass_enforce();
