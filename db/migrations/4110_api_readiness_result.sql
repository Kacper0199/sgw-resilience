-- R29 WA: results the owner of a pre-season readiness check records (ready, not ready, waived). The checks
-- and their work orders stay in the WP-22 fixture; the latest row per item overrides the work-order status at
-- the pre-season review the row names. Append-only: a new result is a new row.
-- Reverse with: DROP TABLE readiness_result;

CREATE TABLE readiness_result (
    result_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_id        text NOT NULL CHECK (char_length(item_id) BETWEEN 1 AND 128),
    status         text NOT NULL CHECK (status IN ('ready', 'not_ready', 'waived')),
    note           text NOT NULL CHECK (char_length(note) BETWEEN 3 AND 300),
    evidence_url   text CHECK (evidence_url IS NULL OR evidence_url ~ '^https?://\S+$' AND char_length(evidence_url) <= 500),
    owner_function sgw_approval_function NOT NULL,
    recorded_by    text NOT NULL REFERENCES app_user (user_id),
    reviewed_at    timestamptz NOT NULL,
    recorded_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX readiness_result_item_idx ON readiness_result (item_id, result_id DESC);
