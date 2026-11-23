# LLM gateway targets: thin wrappers around `uv run sgw <cmd>` (K20).
SGW ?= uv run sgw
GATEWAY_PORT ?= 8100
ENV_FILE ?= $(CURDIR)/.env

.PHONY: gateway-test gateway-run gateway-record llm-spend

gateway-test: ## Gateway tests in replay mode (no key, no network)
	LLM_MODE=replay uv run pytest tests/unit/gateway -q

gateway-run: ## Run the LLM gateway in replay mode on GATEWAY_PORT
	$(SGW) gateway --port $(GATEWAY_PORT)

gateway-record: ## Run the gateway in record mode with the key from ENV_FILE (absolute path)
	uv run --env-file $(ENV_FILE) sgw gateway --mode record --port $(GATEWAY_PORT)

llm-spend: ## Summarise var/llm_spend.csv by spend bucket, purpose and node
	$(SGW) llm-spend
