-- WP-37 integration API and webhooks: encrypted signing secrets with a rotation overlap, delivery attempts,
-- the fan-out cursor, and the ledger position a subscription starts after.

ALTER TABLE webhook_subscription
    ADD COLUMN after_seq   bigint NOT NULL DEFAULT 0 CHECK (after_seq >= 0),
    ADD COLUMN disabled_at timestamptz,
    ADD COLUMN disabled_reason text;
CREATE INDEX webhook_subscription_token_idx ON webhook_subscription (token_id);

ALTER TABLE webhook_delivery
    ADD COLUMN created_at   timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN delivered_at timestamptz,
    ADD COLUMN last_error   text CHECK (char_length(last_error) <= 300),
    ADD CONSTRAINT webhook_delivery_attempts_nonneg CHECK (attempts >= 0);
CREATE INDEX webhook_delivery_subscription_idx ON webhook_delivery (subscription_id, created_at);

CREATE TABLE webhook_secret (
    subscription_id text NOT NULL REFERENCES webhook_subscription (subscription_id),
    slot            smallint NOT NULL CHECK (slot >= 1),
    nonce           bytea NOT NULL CHECK (octet_length(nonce) = 12),
    ciphertext      bytea NOT NULL,
    secret_hint     text NOT NULL CHECK (char_length(secret_hint) = 4),
    created_at      timestamptz NOT NULL,
    retires_at      timestamptz,
    PRIMARY KEY (subscription_id, slot),
    CHECK (retires_at IS NULL OR retires_at >= created_at)
);

CREATE TABLE webhook_attempt (
    delivery_id  text NOT NULL REFERENCES webhook_delivery (delivery_id),
    attempt      integer NOT NULL CHECK (attempt >= 1),
    attempted_at timestamptz NOT NULL,
    status       integer,
    error        text CHECK (char_length(error) <= 300),
    duration_ms  integer NOT NULL CHECK (duration_ms >= 0),
    PRIMARY KEY (delivery_id, attempt)
);

CREATE TABLE integration_cursor (
    name       text PRIMARY KEY,
    last_seq   bigint NOT NULL DEFAULT 0 CHECK (last_seq >= 0),
    updated_at timestamptz NOT NULL DEFAULT now()
);
