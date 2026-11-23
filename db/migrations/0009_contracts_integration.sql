-- K1 v1.1 additions (D-053): critical-path dependencies, commitments, integration tokens and webhooks.

CREATE TABLE decision_dependency (
    decision_case_id text NOT NULL REFERENCES decision_case (decision_case_id),
    prerequisite_id  text NOT NULL REFERENCES decision_case (decision_case_id),
    reason           text NOT NULL,
    PRIMARY KEY (decision_case_id, prerequisite_id),
    CHECK (decision_case_id <> prerequisite_id)
);
CREATE INDEX decision_dependency_prereq_idx ON decision_dependency (prerequisite_id);

CREATE TABLE commitment (
    commitment_id    text PRIMARY KEY,
    decision_case_id text NOT NULL REFERENCES decision_case (decision_case_id),
    proposal_id      text NOT NULL REFERENCES proposal (proposal_id),
    promised_by_utc  timestamptz NOT NULL,
    projected_utc    timestamptz,
    state            sgw_commitment_state NOT NULL DEFAULT 'on_track',
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE commitment_milestone (
    commitment_id text NOT NULL REFERENCES commitment (commitment_id),
    seq           smallint NOT NULL,
    name          text NOT NULL,
    due_utc       timestamptz NOT NULL,
    met_utc       timestamptz,
    PRIMARY KEY (commitment_id, seq)
);

CREATE TABLE api_token (
    token_id     text PRIMARY KEY,
    name         text NOT NULL,
    token_hash   text NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    scopes       sgw_api_scope[] NOT NULL CHECK (cardinality(scopes) > 0),
    created_by   text NOT NULL REFERENCES app_user (user_id),
    created_at   timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL,
    revoked_at   timestamptz,
    last_used_at timestamptz
);

CREATE TABLE webhook_subscription (
    subscription_id text PRIMARY KEY,
    url             text NOT NULL CHECK (url ~ '^https://'),
    event_types     text[] NOT NULL CHECK (event_types <@ ARRAY['ClockBreached', 'CommitmentCreated',
                                                                 'CommitmentDrifted', 'DecisionApproved']::text[]),
    secret_ref      text NOT NULL,
    secret_hint     text NOT NULL CHECK (char_length(secret_hint) = 4),
    token_id        text NOT NULL REFERENCES api_token (token_id),
    active          boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE webhook_delivery (
    delivery_id     text PRIMARY KEY,
    subscription_id text NOT NULL REFERENCES webhook_subscription (subscription_id),
    event_id        uuid NOT NULL REFERENCES event (event_id),
    state           sgw_webhook_delivery_state NOT NULL DEFAULT 'pending',
    attempts        integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz,
    last_status     integer,
    signed_at       timestamptz,
    UNIQUE (subscription_id, event_id)
);
CREATE INDEX webhook_delivery_due_idx ON webhook_delivery (state, next_attempt_at);
