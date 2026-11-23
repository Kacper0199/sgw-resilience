-- WP-38 commitment watch and learning loop (D-053, D-054). Side tables next to the K1 `commitment` and
-- `commitment_milestone` rows: how each milestone is observed, the drift log, and the after-action
-- policy-change proposals. A policy-change proposal never carries an `applied` state: the learning loop
-- proposes, people decide through the approval flow, and the lead-time policy file changes only by a commit.

CREATE TABLE commitment_milestone_plan (
    commitment_id    text NOT NULL,
    seq              smallint NOT NULL,
    lead_key         text,
    remaining_min    integer NOT NULL CHECK (remaining_min >= 0),
    signal           jsonb NOT NULL CHECK (signal ? 'type'),
    met_event_id     uuid,
    PRIMARY KEY (commitment_id, seq),
    FOREIGN KEY (commitment_id, seq) REFERENCES commitment_milestone (commitment_id, seq)
);

CREATE TABLE commitment_drift (
    commitment_id    text NOT NULL REFERENCES commitment (commitment_id),
    seq              integer NOT NULL CHECK (seq >= 1),
    detected_at      timestamptz NOT NULL,
    state            sgw_commitment_state NOT NULL,
    reason           text NOT NULL CHECK (reason IN ('milestone_late', 'input_changed')),
    milestone_seq    smallint,
    promised_by_utc  timestamptz NOT NULL,
    projected_utc    timestamptz NOT NULL,
    drift_min        integer NOT NULL,
    tolerance_min    integer NOT NULL CHECK (tolerance_min >= 0),
    reopened         boolean NOT NULL DEFAULT false,
    proposal_version integer,
    note             text NOT NULL DEFAULT '',
    PRIMARY KEY (commitment_id, seq)
);

CREATE TABLE policy_change_proposal (
    change_id          text PRIMARY KEY,
    policy_key         text NOT NULL CHECK (policy_key IN ('lead_times')),
    tier               sgw_tier NOT NULL CHECK (tier = 'T2'),
    required_functions sgw_approval_function[] NOT NULL CHECK (cardinality(required_functions) >= 1),
    state              text NOT NULL DEFAULT 'proposed'
        CHECK (state IN ('proposed', 'in_review', 'approved', 'rejected', 'withdrawn', 'superseded')),
    proposed_by        text NOT NULL CHECK (proposed_by LIKE 'system:%'),
    incident_id        text NOT NULL,
    policy_version     text NOT NULL,
    method             jsonb NOT NULL,
    evidence           jsonb NOT NULL CHECK (jsonb_typeof(evidence) = 'array' AND jsonb_array_length(evidence) >= 1),
    current_values     jsonb NOT NULL,
    proposed_values    jsonb NOT NULL,
    evidence_hash      text NOT NULL CHECK (evidence_hash ~ '^[0-9a-f]{64}$'),
    approval_proposal_id text REFERENCES proposal (proposal_id),
    created_at         timestamptz NOT NULL,
    UNIQUE (policy_key, incident_id, evidence_hash)
);
