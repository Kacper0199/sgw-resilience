# Commitment watch and learning loop: thin wrappers around `uv run sgw commitments` (K20).
SGW ?= uv run sgw
COMMITMENT_DB ?= sgw_wp38
SCENARIO ?= helene

.PHONY: commitments-replay commitments-after-action test-commitments

commitments-replay: ## Seeded PS-17 commitment drifts in the helene_micro replay and reopens (COMMITMENT_DB=<seeded db>)
	$(SGW) commitments replay-ps17 --database $(COMMITMENT_DB)

commitments-after-action: ## Actual vs assumed lead times and the T2 proposal (SCENARIO=helene, COMMITMENT_DB= to write the row)
	$(SGW) commitments after-action --scenario $(SCENARIO) $(if $(COMMITMENT_DB),--database $(COMMITMENT_DB))

test-commitments: ## Commitment watch and learning-loop tests (DB tests need SGW_TEST_DATABASE_URL)
	uv run pytest tests/unit/models/commitments -q
