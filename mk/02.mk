# Contracts targets; they only wrap the typer CLI (K20).
SGW_CONTRACTS := uv run sgw

.PHONY: contracts contracts-check numbers test-contracts
contracts: ## Regenerate contract artefacts (JSON Schema, OpenAPI, TS, SQL domains, vectors, fixtures)
	$(SGW_CONTRACTS) contracts

contracts-check: ## Fail on drift between contracts and generated artefacts
	$(SGW_CONTRACTS) contracts-check

numbers: ## Generate numbers.tex, numbers_gen.py, numbers/policies TS and audit literal values
	$(SGW_CONTRACTS) numbers --tex --py --ts --audit

test-contracts: ## Contract tests (set SGW_TEST_DATABASE_URL for the K1 database tests)
	uv run pytest tests/contracts -q
	pnpm -C web exec vitest run src/contracts
