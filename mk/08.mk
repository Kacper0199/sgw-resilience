# API targets: thin wrappers around `uv run sgw api ...` (K20).
SGW ?= uv run sgw
API_DB ?=
API_PORT ?= 8200

.PHONY: api api-seed-users test-sse

api: ## Run the API on the host (API_DB=<database> API_PORT=8200)
	$(SGW) api serve --port $(API_PORT) $(if $(API_DB),--database $(API_DB))

api-seed-users: ## Seed the K18 demo users with DEMO_PASSWORD (API_DB=<database>)
	$(SGW) api seed-users $(if $(API_DB),--database $(API_DB))

test-sse: ## SSE through Caddy on a real socket: reconnect replay and p95 latency (needs SGW_TEST_DATABASE_URL, Docker)
	uv run pytest tests/integration/sse_api -m slow -q -s
