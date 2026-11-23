-- R27 crew dispatch (D-100 Q-03 C): a person assigns a crew to an open decision or a staging yard; the
-- assignment waits for one signature from the function the dispatch policy names (sgw.dispatch). Crew status
-- itself stays in the ledger (K2 CrewStatus); this table holds only the assignment and its sign-off.
-- Reverse with: DROP TABLE crew_assignment;

CREATE TABLE crew_assignment (
    assignment_id     text PRIMARY KEY CHECK (assignment_id ~ '^ASG-[0-9A-F]{16}$'),
    crew_id           text NOT NULL CHECK (char_length(crew_id) BETWEEN 1 AND 64),
    target_kind       text NOT NULL CHECK (target_kind IN ('decision', 'yard')),
    target_id         text NOT NULL CHECK (char_length(target_id) BETWEEN 1 AND 64),
    state             text NOT NULL CHECK (state IN ('proposed', 'assigned', 'rejected', 'withdrawn', 'released')),
    required_function sgw_approval_function NOT NULL,
    proposed_by       text NOT NULL REFERENCES app_user (user_id),
    proposed_at       timestamptz NOT NULL,
    decided_by        text REFERENCES app_user (user_id),
    decided_at        timestamptz,
    closed_by         text REFERENCES app_user (user_id),
    closed_at         timestamptz,
    policy_version    text NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CHECK (decided_by IS NULL OR decided_by <> proposed_by),
    CHECK ((decided_by IS NULL) = (decided_at IS NULL)),
    CHECK ((closed_by IS NULL) = (closed_at IS NULL))
);

CREATE UNIQUE INDEX crew_assignment_one_active_idx ON crew_assignment (crew_id)
    WHERE state IN ('proposed', 'assigned');
CREATE INDEX crew_assignment_target_idx ON crew_assignment (target_kind, target_id, state);
CREATE INDEX crew_assignment_crew_idx ON crew_assignment (crew_id, proposed_at DESC);
