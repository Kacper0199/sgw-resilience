-- K1 time and ledger tables. Hypertables only on observed_at (C-51); the ledger is an ordinary table.

CREATE TABLE event (
    event_id          uuid PRIMARY KEY,
    type              text NOT NULL,
    schema_version    integer NOT NULL CHECK (schema_version >= 1),
    source_id         text NOT NULL,
    feed_mode         sgw_feed_mode NOT NULL,
    run_mode          sgw_run_mode NOT NULL,
    event_time        timestamptz NOT NULL,
    issued_at         timestamptz,
    valid_at          timestamptz,
    received_at       timestamptz NOT NULL,
    known_at          timestamptz NOT NULL,
    scenario_known_at timestamptz NOT NULL,
    ledger_seq        bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    dedup_key         text NOT NULL UNIQUE,
    classification    sgw_classification NOT NULL,
    trust             sgw_trust NOT NULL,
    quality           sgw_quality NOT NULL DEFAULT 'good',
    coverage_ppm      integer NOT NULL DEFAULT 1000000 CHECK (coverage_ppm BETWEEN 0 AND 1000000),
    finality          sgw_finality NOT NULL DEFAULT 'confirmed',
    supersedes        uuid REFERENCES event (event_id),
    region_id         text,
    domain            sgw_domain,
    payload           jsonb NOT NULL
);
CREATE INDEX event_type_time_idx ON event (type, event_time);
CREATE INDEX event_scenario_known_idx ON event (scenario_known_at);

CREATE TABLE observation (
    source_id   text NOT NULL,
    tag         text NOT NULL,
    asset_id    text,
    region_id   text,
    domain      sgw_domain,
    observed_at timestamptz NOT NULL,
    known_at    timestamptz NOT NULL,
    value       double precision NOT NULL CHECK (value NOT IN ('NaN', 'Infinity', '-Infinity')),
    unit        text NOT NULL,
    quality     sgw_quality NOT NULL DEFAULT 'good',
    finality    sgw_finality NOT NULL DEFAULT 'confirmed',
    value_hash  text NOT NULL,
    UNIQUE (source_id, tag, observed_at, value_hash)
);
SELECT create_hypertable('observation', by_range('observed_at', INTERVAL '1 day'));

CREATE TABLE forecast (
    forecast_id   text PRIMARY KEY,
    model_version text NOT NULL,
    target        text NOT NULL,
    entity_id     text NOT NULL,
    region_id     text,
    domain        sgw_domain,
    issued_at     timestamptz NOT NULL,
    known_at      timestamptz NOT NULL,
    valid_at      timestamptz NOT NULL,
    quantiles     jsonb NOT NULL
);
CREATE INDEX forecast_lookup_idx ON forecast (target, entity_id, issued_at DESC);

CREATE TABLE job (
    job_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind         text NOT NULL,
    payload      jsonb NOT NULL,
    state        text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued', 'running', 'done', 'failed', 'dead')),
    locked_until timestamptz,
    lease_token  uuid,
    attempts     integer NOT NULL DEFAULT 0,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX job_ready_idx ON job (state, locked_until);

CREATE TABLE coverage_gap (
    gap_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id text NOT NULL,
    from_ts   timestamptz NOT NULL,
    to_ts     timestamptz NOT NULL CHECK (to_ts > from_ts),
    reason    text NOT NULL
);

CREATE TABLE quarantine (
    quarantine_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id     text NOT NULL,
    record        jsonb NOT NULL,
    reason        text NOT NULL,
    run_id        text,
    created_at    timestamptz NOT NULL DEFAULT now()
);
