# Ingest, ledger relay, pipeline runs and DQ: thin wrappers around `uv run sgw replay` (K20).
SGW ?= uv run sgw
SCENARIO ?= helene_micro
REPLAY_DB ?=
REPLAY_ARGS ?=

.PHONY: replay replay-fresh test-ingest s11

replay: ## Replay a scenario through adapters, outbox, ledger relay and DQ (SCENARIO=helene_micro, REPLAY_DB=<db>)
	$(SGW) replay --scenario $(SCENARIO) $(if $(REPLAY_DB),--database $(REPLAY_DB)) $(REPLAY_ARGS)

replay-fresh: ## Same, after deleting the target's ledger and ingest tables (never use on the main database)
	$(SGW) replay --scenario $(SCENARIO) $(if $(REPLAY_DB),--database $(REPLAY_DB)) --fresh $(REPLAY_ARGS)

test-ingest: ## Ingest and pipeline tests, database tests included (needs the local stack)
	uv run pytest tests/unit/ingest tests/unit/pipeline tests/integration/ingest_relay -q

s11: ## Load check: 4 producers x 1,000 events through the outbox, gapless ledger, printed numbers
	uv run pytest tests/integration/ingest_relay/test_s11_relay.py -q -s
