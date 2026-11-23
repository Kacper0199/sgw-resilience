# Clocks, fusion and ranking: thin wrappers around `uv run sgw clocks` (K20).
SGW ?= uv run sgw
CLOCK_INPUT ?= data/artefacts/water_twin/ps17_clock_members.json
ADVISORY ?= N
CLOCK_DB ?=

.PHONY: clocks clocks-waterfall test-clocks

clocks: ## Decide-by queue for one advisory (CLOCK_INPUT=<member table>, ADVISORY=N, CLOCK_DB=<db> to store)
	$(SGW) clocks compute --input $(CLOCK_INPUT) --advisory '$(ADVISORY)' $(if $(CLOCK_DB),--database $(CLOCK_DB))

clocks-waterfall: ## Basis waterfall of the PS-17 generator case (ADVISORY=N)
	$(SGW) clocks waterfall --input $(CLOCK_INPUT) --advisory '$(ADVISORY)' --case DC-D3-PS17-POWER

test-clocks: ## Fusion, clock, critical-path and ranking tests (property and golden)
	uv run pytest tests/unit/models/fusion tests/unit/models/clocks tests/unit/models/ranking -q
