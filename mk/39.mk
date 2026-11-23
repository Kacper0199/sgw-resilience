# Obs profile targets: thin wrappers around `uv run sgw obs ...` (K20). Not part of `make demo`.
SGW ?= uv run sgw

.PHONY: obs-up obs-down obs-check

obs-up: ## Start Prometheus + Grafana (profile obs) next to a running core stack
	$(SGW) obs up

obs-down: ## Stop and remove only the obs services
	$(SGW) obs down

obs-check: ## Prove the provisioned dashboards load and list scrape target health
	$(SGW) obs check
