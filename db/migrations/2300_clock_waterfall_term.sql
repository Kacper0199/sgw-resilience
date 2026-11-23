-- WP-12 clocks: the basis waterfall behind each decision case (O-03) and the clock state that K1
-- `decision_case` does not hold (effective P10/P90, verdict basis, derived and missed flags).
-- Waterfall rows in display order: the consequence anchor (unit epoch_s), additive model or rule terms of the
-- nearest-rank member at each quantile (with the term's own P10-P90 as context), an optional
-- `ensemble_nonadditivity` row (bookkeeping, never a driver), the action lead time (negative) and the
-- critical-path adjustment. Rows are replaced as a set whenever the clock service recomputes the case.

CREATE TABLE clock_waterfall_term (
    decision_case_id text NOT NULL REFERENCES decision_case (decision_case_id) ON DELETE CASCADE,
    ord              smallint NOT NULL CHECK (ord >= 0),
    label            text NOT NULL CHECK (length(label) > 0),
    term_kind        text NOT NULL
        CHECK (term_kind IN ('anchor', 'term', 'ensemble_nonadditivity', 'lead_time', 'critical_path')),
    basis            jsonb,
    unit             text NOT NULL CHECK (unit IN ('min', 'epoch_s')),
    p10              double precision NOT NULL,
    p50              double precision NOT NULL,
    p90              double precision NOT NULL,
    context_p10      double precision,
    context_p90      double precision,
    computed_by      text NOT NULL,
    updated_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (decision_case_id, ord),
    CHECK (basis IS NULL OR (basis ? 'basis_id' AND basis ? 'basis_version' AND basis ? 'kind'))
);

CREATE TABLE clock_case_state (
    decision_case_id            text PRIMARY KEY REFERENCES decision_case (decision_case_id) ON DELETE CASCADE,
    effective_decide_by_p10_utc timestamptz NOT NULL,
    effective_decide_by_p90_utc timestamptz NOT NULL,
    verdict_basis_utc           timestamptz,
    bound_by_case_id            text,
    slack_min                   double precision,
    derived                     boolean NOT NULL DEFAULT false,
    missed                      boolean NOT NULL DEFAULT false,
    computed_by                 text NOT NULL,
    updated_at                  timestamptz NOT NULL DEFAULT now(),
    CHECK (effective_decide_by_p10_utc <= effective_decide_by_p90_utc)
);
