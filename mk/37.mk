# Integration API targets: thin wrappers around `uv run sgw integrations ...` (K20).
SGW ?= uv run sgw
INT_DB ?=

.PHONY: integrations-worker integrations-openapi test-integrations

integrations-worker: ## Webhook fan-out and delivery worker (INT_DB=<database>)
	$(SGW) integrations worker $(if $(INT_DB),--database $(INT_DB))

integrations-openapi: ## Regenerate contracts/openapi-v1.json
	$(SGW) integrations openapi

test-integrations: ## Integration API tests incl. the HTTPS example consumer end to end (needs SGW_TEST_DATABASE_URL)
	uv run pytest tests/unit/integrations tests/integration/integrations_webhooks -q
