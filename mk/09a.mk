# Approvals targets: thin wrappers around `uv run sgw <cmd>` (K20).
SGW_09A ?= uv run sgw
SEED_DB ?= sgw

.PHONY: seed policy-test policy-data test-approval
seed: ## Load K18 users and the Helene T3 crew proposal into SEED_DB (default sgw)
	$(SGW_09A) seed --database $(SEED_DB)

policy-test: ## opa check, fmt and test (with coverage) for policy/*.rego
	$(SGW_09A) policy-test

policy-data: ## Regenerate policy/sgw/tiers/data.json from the K8 tier table
	$(SGW_09A) policy-data

test-approval: ## Approval unit and SEC-16/17/47 tests (DB and OPA tests need the local stack and docker)
	uv run pytest tests/unit/approval tests/security -q
