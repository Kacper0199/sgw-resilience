# Crew pre-positioning (A5 SAA): thin wrappers around `uv run sgw optimise` (K20).
SGW ?= uv run sgw
ADVISORY ?= N
OPT_DB ?= sgw_wp16

.PHONY: optimise-plan optimise-report optimise-enqueue optimise-work test-optimise

optimise-plan: ## Courses of action, baselines, VSS/EVPI for one advisory (ADVISORY=N)
	$(SGW) optimise plan --advisory '$(ADVISORY)'

optimise-report: ## Write evals/reports/saa.json (K17)
	$(SGW) optimise report --advisory '$(ADVISORY)'

optimise-enqueue: ## Queue an async SAA job in OPT_DB
	$(SGW) optimise enqueue --database $(OPT_DB) --advisory '$(ADVISORY)'

optimise-work: ## Run queued SAA jobs in OPT_DB until the queue is empty
	$(SGW) optimise work --database $(OPT_DB) --drain

test-optimise: ## Crew pre-positioning tests
	uv run pytest tests/unit/models/optimise -q
