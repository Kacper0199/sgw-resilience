-- K1 ops, ML and AI tables. `llm_call` is the union of PA K1 and AI 5.3 columns (X-10).

CREATE TABLE pipeline_run (
    run_id           text PRIMARY KEY,
    asset            text NOT NULL,
    status           text NOT NULL CHECK (status IN ('running', 'success', 'failed', 'partial')),
    started_at       timestamptz NOT NULL,
    finished_at      timestamptz,
    rows_in          integer NOT NULL DEFAULT 0,
    rows_out         integer NOT NULL DEFAULT 0,
    rows_quarantined integer NOT NULL DEFAULT 0,
    watermarks       jsonb NOT NULL DEFAULT '{}'::jsonb,
    error            text,
    code_version     text NOT NULL,
    trace_id         text
);

CREATE TABLE dq_check (
    check_id   text PRIMARY KEY,
    run_id     text REFERENCES pipeline_run (run_id),
    asset      text NOT NULL,
    name       text NOT NULL,
    severity   text NOT NULL CHECK (severity IN ('warn', 'error')),
    passed     boolean NOT NULL,
    observed   text NOT NULL,
    freshness_limit_s integer,
    checked_at timestamptz NOT NULL
);

CREATE TABLE adapter_health (
    source_id         text PRIMARY KEY,
    feed_mode         sgw_feed_mode NOT NULL,
    last_success_at   timestamptz,
    ingest_lag_s      integer,
    product_age_s     integer,
    error_rate_ppm    integer NOT NULL DEFAULT 0 CHECK (error_rate_ppm BETWEEN 0 AND 1000000),
    freshness_limit_s integer NOT NULL,
    updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE VIEW feed_health AS
SELECT source_id, feed_mode, last_success_at, ingest_lag_s, product_age_s, error_rate_ppm, freshness_limit_s,
       (ingest_lag_s IS NULL OR ingest_lag_s > 2 * freshness_limit_s) AS stale
FROM adapter_health;

CREATE TABLE model_version (
    model_id      text PRIMARY KEY,
    name          text NOT NULL,
    version       text NOT NULL,
    mlflow_run_id text,
    alias         text,
    data_hash     text NOT NULL,
    metrics       jsonb NOT NULL DEFAULT '{}'::jsonb,
    eval_report   text,
    UNIQUE (name, version)
);

CREATE TABLE agent_run (
    run_id        text PRIMARY KEY,
    thread_id     text NOT NULL,
    user_id       text NOT NULL,
    graph         text NOT NULL,
    graph_version text NOT NULL,
    run_mode      sgw_run_mode NOT NULL,
    status        text NOT NULL CHECK (status IN ('running', 'paused', 'done', 'error', 'cancelled')),
    tokens_in     integer NOT NULL DEFAULT 0,
    tokens_out    integer NOT NULL DEFAULT 0,
    cost_usd_micros bigint NOT NULL DEFAULT 0,
    tainted       boolean NOT NULL DEFAULT false,
    classification sgw_classification NOT NULL DEFAULT 'C1',
    trace_id      text,
    started_at    timestamptz NOT NULL DEFAULT now(),
    ended_at      timestamptz
);

CREATE TABLE llm_call (
    call_id                     text PRIMARY KEY,
    ts                          timestamptz NOT NULL,
    mode                        text NOT NULL CHECK (mode IN ('live', 'record', 'replay')),
    billed                      boolean NOT NULL,
    purpose                     text NOT NULL CHECK (purpose IN ('spike', 'dev', 'eval', 'redteam', 'record', 'demo')),
    wave                        text,
    run_id                      text,
    node                        text NOT NULL,
    prompt_version              text,
    model                       text NOT NULL,
    effort                      sgw_effort,
    batch                       boolean NOT NULL DEFAULT false,
    route                       text,
    classes                     sgw_classification[] NOT NULL DEFAULT '{}',
    decision                    text CHECK (decision IN ('allow', 'deny', 'redact')),
    input_tokens                integer NOT NULL DEFAULT 0,
    cache_creation_input_tokens integer NOT NULL DEFAULT 0,
    cache_read_input_tokens     integer NOT NULL DEFAULT 0,
    output_tokens               integer NOT NULL DEFAULT 0,
    stop_reason                 text,
    latency_ms                  integer,
    cost_usd_micros             bigint NOT NULL DEFAULT 0,
    request_hash                text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    payload_hash                text
);
CREATE INDEX llm_call_run_idx ON llm_call (run_id);
CREATE INDEX llm_call_wave_purpose_idx ON llm_call (wave, purpose, node);
