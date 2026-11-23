-- WP-07 ingest: index for the transactional outbox on `job` (kind 'ledger.append', state 'queued') in the
-- relay's claim order, and a sequence for pipeline run ids (no count(*) race between runners).

CREATE INDEX job_ledger_outbox_queued_idx
    ON job (created_at, (CASE WHEN payload->>'ord' ~ '^[0-9]{1,9}$' THEN (payload->>'ord')::int END), job_id)
    WHERE kind = 'ledger.append' AND state = 'queued';

CREATE SEQUENCE pipeline_run_seq AS bigint;
