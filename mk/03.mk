# Stack targets: thin wrappers around `uv run sgw <cmd>` (K20). The CLI is the user path.
SGW ?= uv run sgw

.PHONY: bootstrap doctor up up-full down reset stats db-smoke migrate

bootstrap: ## Generate local stack credentials into var/ (never touches .env)
	$(SGW) bootstrap

doctor: ## Check this machine for docker, compose, uv, node/pnpm, ports and memory
	$(SGW) doctor

up: ## Start the core stack and wait until healthy
	$(SGW) up

up-full: ## Start the core + full profile
	$(SGW) up --profile full

down: ## Stop the stack (volumes kept)
	$(SGW) down

reset: ## Delete stack volumes, start again, migrate
	$(SGW) reset --yes

stats: ## Memory and CPU per container, plus host memory and swap
	$(SGW) stats

db-smoke: ## Prove extensions, PostGIS, H3, routing, vectors, LangGraph checkpointer
	$(SGW) db-smoke

migrate: ## Apply db/migrations in order (ledger: public.schema_migrations)
	$(SGW) migrate
